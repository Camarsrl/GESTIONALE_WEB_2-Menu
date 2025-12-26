# -*- coding: utf-8 -*-
"""
Camar • Gestionale Web – build aggiornata (Ottobre 2025)
© Copyright Alessia Moncalvo
Tutti i diritti riservati.
"""
import os
import io
import re
import uuid
import json
import logging
import calendar
import pandas as pd
from pathlib import Path
from datetime import datetime, date

# Importazioni Flask e Login
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Importazioni Database (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, ForeignKey, or_, Identity, Boolean
# AGGIUNTO scoped_session QUI SOTTO:
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session
from sqlalchemy.sql import func

# --- IMPORTAZIONI PDF (ReportLab) ---
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

# --- IMPORTAZIONI EMAIL ---
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Jinja loader for in-memory templates
from jinja2 import DictLoader

# --- AUTH ---
from functools import wraps

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            flash("Effettua il login per accedere", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# --- PATH / LOGO (Robust configuration for Render) ---
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
APP_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

MEDIA_DIR = APP_DIR / "media"
DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"
for d in (DOCS_DIR, PHOTOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

def _discover_logo_path():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo camar.jpg", "logo_camar.png"):
        p = STATIC_DIR / name
        if p.exists():
            return str(p)
    p = os.environ.get("LOGO_PATH")
    return p if p and Path(p).exists() else None

LOGO_PATH = _discover_logo_path()

# --- DATABASE ---
os.environ["DATABASE_URL"] = "postgresql://magazzino_1pgq_user:SrXIOLyspVI2RUSx51r7ZMq8usa0K8WD@dpg-d348i73uibrs73fagoa0-a/magazzino_1pgq"

DB_URL = (os.environ.get("DATABASE_URL") or "").strip()

def _normalize_db_url(u: str) -> str:
    if not u: return u
    if u.startswith("mysql://"):
        u = "mysql+pymysql://" + u[len("mysql://"):]
    if re.search(r"<[^>]+>", u):
        raise ValueError("DATABASE_URL contiene segnaposto non sostituiti.")
    return u

if DB_URL:
    DB_URL = _normalize_db_url(DB_URL)
    engine = create_engine(DB_URL, future=True, pool_pre_ping=True)
else:
    sqlite_path = APP_DIR / "magazzino.db"
    engine = create_engine(f"sqlite:///{sqlite_path}", future=True)

SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

from sqlalchemy import text
import logging

def ensure_articoli_columns():
    """Aggiunge colonne mancanti su Postgres (senza Alembic)."""
    try:
        db = SessionLocal()
        try:
            db.execute(text('ALTER TABLE articoli ADD COLUMN IF NOT EXISTS ordine VARCHAR(255);'))
            db.commit()
            logging.info("[DB] ensure_articoli_columns OK (ordine)")
        finally:
            db.close()
    except Exception:
        logging.exception("[DB] ensure_articoli_columns FAILED")


# --- MODELLI ---
class Articolo(Base):
    __tablename__ = "articoli"
    id_articolo = Column(Integer, Identity(start=1), primary_key=True)
    
    # Dati identificativi (Usa Text per evitare limiti di lunghezza)
    codice_articolo = Column(Text) 
    descrizione = Column(Text)
    cliente = Column(Text)
    fornitore = Column(Text)
    magazzino = Column(String(255))
    
    # Riferimenti documenti
    protocollo = Column(Text)
    ordine = Column(Text)
    commessa = Column(Text)
    buono_n = Column(Text)
    n_arrivo = Column(Text)
    ns_rif = Column(String(255))
    serial_number = Column(String(255))
    
    # Dati dimensionali e quantità
    pezzo = Column(String(255))
    n_colli = Column(Integer)
    peso = Column(Float)
    larghezza = Column(Float)
    lunghezza = Column(Float)
    altezza = Column(Float)
    m2 = Column(Float)
    m3 = Column(Float)
    
    # Logistica e Stato
    posizione = Column(String(255))
    stato = Column(String(255))
    note = Column(Text)
    mezzi_in_uscita = Column(String(255))
    
    # Date e DDT
    data_ingresso = Column(String(32))
    n_ddt_ingresso = Column(Text)
    data_uscita = Column(String(32))
    n_ddt_uscita = Column(Text)

    attachments = relationship("Attachment", back_populates="articolo", cascade="all, delete-orphan", passive_deletes=True)

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, Identity(start=1), primary_key=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo", ondelete='CASCADE'), nullable=False)
    kind = Column(String(10))
    filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)

# --- UTENTI ---
DEFAULT_USERS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'MARINE INTERIORS': 'Struppa09', 'OPS': '271214',
    'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02', 'DIEGO': 'Balleydier03', 'ADMIN': 'admin123',
}
ADMIN_USERS = {'ADMIN', 'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO'}

def get_users():
    fp = APP_DIR / "password Utenti Gestionale.txt"
    if fp.exists():
        try:
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(r"'([^']+)'\s*:\s*'([^']+)'", raw)
            m = {k.strip().upper(): v.strip() for k, v in pairs}
            if m: return m
        except Exception: pass
    return DEFAULT_USERS

# --- UTILS ---
def is_blank(v):
    try:
        if pd.isna(v): return True
    except Exception: pass
    return (v is None) or (isinstance(v, str) and not v.strip())

def to_float_eu(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(",", ".")
    if not s: return None
    try: return float(s)
    except Exception: return None

def to_int_eu(v):
    f = to_float_eu(v)
    return None if f is None else int(round(f))

def parse_date_ui(d):
    if not d: return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(d).split(" ")[0], fmt).strftime("%Y-%m-%d")
        except Exception: pass
    return d

def fmt_date(d):
    if not d: return ""
    try:
        if isinstance(d, (datetime, date)):
            return d.strftime("%d/%m/%Y")
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception: return d

def calc_m2_m3(l, w, h, colli):
    l = to_float_eu(l) or 0.0
    w = to_float_eu(w) or 0.0
    h = to_float_eu(h) or 0.0
    c = to_int_eu(colli) or 1
    return round(c * l * w, 3), round(c * l * w * h, 3)

def load_destinatari():
    DESTINATARI_JSON = APP_DIR / "destinatari_saved.json"
    data = {}
    if DESTINATARI_JSON.exists():
        try:
            content = DESTINATARI_JSON.read_text(encoding="utf-8")
            raw_data = json.loads(content)
            
            # Se il JSON è una lista (vecchio formato), lo convertiamo in dizionario
            if isinstance(raw_data, list):
                for item in raw_data:
                    # Usa il campo 'Cliente' come chiave, o genera un nome se manca
                    key = item.get("Cliente") or item.get("ragione_sociale") or "Destinatario Sconosciuto"
                    data[key] = {
                        "ragione_sociale": item.get("ragione_sociale") or item.get("Cliente", ""),
                        "indirizzo": item.get("indirizzo", ""),
                        "piva": item.get("piva", "")
                    }
            else:
                data = raw_data
        except Exception:
            data = {}
            
    if not data:
        # Dati di default se il file è vuoto o corrotto
        data = {
            "Sede Cliente": {
                "ragione_sociale": "Cliente S.p.A.", 
                "indirizzo": "Via Esempio 1, 16100 Genova", 
                "piva": "IT00000000000"
            }
        }
    return data
def next_ddt_number():
    PROG_FILE = APP_DIR / "progressivi_ddt.json"
    y = str(date.today().year)[-2:]
    prog = {}
    if PROG_FILE.exists():
        try:
            prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
        except Exception: prog = {}
    n = int(prog.get(y, 0)) + 1
    prog[y] = n
    PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{n:02d}/{y}"

# --- SEZIONE TEMPLATES HTML ---
BASE_HTML = """
<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "Camar • Gestionale Web" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        body { background: #f8f9fa; font-size: 14px; }
        .card { border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.08); border: none; }
        .table-container { overflow: auto; max-height: 65vh; }
        .table thead th { position: sticky; top: 0; background: #f0f2f5; z-index: 2; }
        .dropzone { border: 2px dashed #0d6efd; background: #eef4ff; padding: 20px; border-radius: 12px; text-align: center; color: #0d6efd; cursor: pointer; }
        .logo { height: 40px; }
        .table-compact th, .table-compact td { font-size: 11px; padding: 4px 5px; white-space: normal; word-wrap: break-word; vertical-align: middle; }
        .table-striped tbody tr:nth-of-type(odd) { background-color: rgba(0,0,0,.03); }
        @media print { .no-print { display: none !important; } }
    </style>
</head>
<body>
<nav class="navbar bg-white shadow-sm no-print">
    <div class="container-fluid">
        <div class="d-flex align-items-center gap-2">
            {% if logo_url %}<img src="{{ logo_url }}" class="logo" alt="logo">{% endif %}
            <a class="navbar-brand" href="{{ url_for('home') }}">Camar • Gestionale</a>
        </div>
        <div class="ms-auto">
            {% if session.get('user') %}
                <span class="me-3">Utente: <b>{{ session['user'] }}</b></span>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a>
            {% endif %}
        </div>
    </div>
</nav>
<main class="container-fluid my-4">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show no-print" role="alert">
                    {{ message|safe }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
</main>
<footer class="text-center text-muted py-3 small no-print">
    © Alessia Moncalvo – Gestionale Camar Web Edition • Tutti i diritti riservati.
</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% block extra_js %}{% endblock %}
</body>
</html>
"""

LOGIN_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-5 col-lg-4">
        <div class="card p-4 text-center">
            {% if logo_url %}<img src="{{ logo_url }}" class="mb-3 mx-auto" style="height:56px; width: auto;">{% endif %}
            <h4 class="mb-3">Login al gestionale</h4>
            <form method="post" class="text-start">
                <div class="mb-3">
                    <label class="form-label">Utente</label>
                    <input name="user" class="form-control" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Password</label>
                    <input type="password" name="pwd" class="form-control" required>
                </div>
                <button class="btn btn-primary w-100">Accedi</button>
            </form>
        </div>
    </div>
</div>
{% endblock %}
"""

HOME_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row g-3">
    <div class="col-lg-3">
        <div class="card p-3">
            <h6 class="mb-3">Menu Principale</h6>
            <div class="d-grid gap-2">
                <a class="btn btn-primary" href="{{ url_for('giacenze') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Visualizza Giacenze</a>
                <a class="btn btn-success" href="{{ url_for('new_row') }}"><i class="bi bi-plus-circle"></i> Nuovo Articolo</a>
                <a class="btn btn-outline-secondary" href="{{ url_for('labels_form') }}"><i class="bi bi-tag"></i> Stampa Etichette</a>
                <hr>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('import_excel') }}"><i class="bi bi-file-earmark-arrow-up"></i> Import Excel</a>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('export_excel') }}"><i class="bi bi-file-earmark-arrow-down"></i> Export Excel Totale</a>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('export_client') }}"><i class="bi bi-people"></i> Export per Cliente</a>
                <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('calcola_costi') }}"><i class="bi bi-calculator"></i> Calcola Giacenze Mensili</a>
            </div>
        </div>
    </div>
    <div class="col-lg-9">
        <div class="card p-4">
            <div class="d-flex align-items-center gap-3">
                {% if logo_url %}<img src="{{ logo_url }}" style="height:48px">{% endif %}
                <div>
                    <h4 class="m-0">Benvenuto nel Gestionale Camar</h4>
                    <p class="text-muted m-0">Gestione completa di giacenze, DDT, buoni di prelievo e stampa PDF.</p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

GIACENZE_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex align-items-center justify-content-between mb-3 no-print">
    <h4 class="m-0">📦 Visualizza Giacenze</h4>
    <a href="{{ url_for('new_row') }}" class="btn btn-success"><i class="bi bi-plus-circle"></i> Aggiungi Articolo</a>
</div>
<div class="accordion mb-3 no-print" id="accordionFiltri">
    <div class="accordion-item">
        <h2 class="accordion-header">
            <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapseOne" aria-expanded="false" aria-controls="collapseOne">
                Mostra/Nascondi Filtri di Ricerca
            </button>
        </h2>
        <div id="collapseOne" class="accordion-collapse collapse" data-bs-parent="#accordionFiltri">
            <div class="accordion-body">
                <form class="row g-2 align-items-end" method="get">
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Cliente</label><input name="cliente" value="{{ request.args.get('cliente', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Fornitore</label><input name="fornitore" value="{{ request.args.get('fornitore', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Commessa</label><input name="commessa" value="{{ request.args.get('commessa', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Descrizione</label><input name="descrizione" value="{{ request.args.get('descrizione', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Posizione</label><input name="posizione" value="{{ request.args.get('posizione', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Stato</label><input name="stato" value="{{ request.args.get('stato', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Protocollo</label><input name="protocollo" value="{{ request.args.get('protocollo', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">N. DDT Ingresso</label><input name="n_ddt_ingresso" value="{{ request.args.get('n_ddt_ingresso', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">N. DDT Uscita</label><input name="n_ddt_uscita" value="{{ request.args.get('n_ddt_uscita', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">N. Arrivo</label><input name="n_arrivo" value="{{ request.args.get('n_arrivo', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">N. Buono</label><input name="buono_n" value="{{ request.args.get('buono_n', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">NS Rif.</label><input name="ns_rif" value="{{ request.args.get('ns_rif', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Serial Number</label><input name="serial_number" value="{{ request.args.get('serial_number', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Mezzo Uscito</label><input name="mezzi_in_uscita" value="{{ request.args.get('mezzi_in_uscita', '') }}" class="form-control form-control-sm"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Ingresso Da</label><input name="data_ingresso_da" value="{{ request.args.get('data_ingresso_da', '') }}" class="form-control form-control-sm" placeholder="gg/mm/aaaa"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Ingresso A</label><input name="data_ingresso_a" value="{{ request.args.get('data_ingresso_a', '') }}" class="form-control form-control-sm" placeholder="gg/mm/aaaa"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Uscita Da</label><input name="data_uscita_da" value="{{ request.args.get('data_uscita_da', '') }}" class="form-control form-control-sm" placeholder="gg/mm/aaaa"></div>
                    <div class="col-lg-2 col-md-4"><label class="form-label small">Uscita A</label><input name="data_uscita_a" value="{{ request.args.get('data_uscita_a', '') }}" class="form-control form-control-sm" placeholder="gg/mm/aaaa"></div>
                    <div class="col-lg-2 col-md-4 d-grid"><button class="btn btn-primary btn-sm mt-3">Filtra</button></div>
                    <div class="col-lg-2 col-md-4 d-grid"><a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm mt-3">Pulisci Filtri</a></div>
                </form>
            </div>
        </div>
    </div>
</div>
<div class="card p-3">
    <div class="d-flex flex-wrap gap-2 mb-3 no-print border-bottom pb-3">
        <button class="btn btn-outline-secondary btn-sm" onclick="return submitForm('{{ url_for('buono_preview') }}', 'post')"><i class="bi bi-receipt"></i> Crea Buono</button>
        <button class="btn btn-outline-secondary btn-sm" onclick="return submitForm('{{ url_for('ddt_preview') }}', 'post')"><i class="bi bi-truck"></i> Crea DDT</button>
        {% if session.get('role') == 'admin' %}
        <button class="btn btn-outline-primary btn-sm" onclick="return submitForm('{{ url_for('bulk_duplicate') }}', 'post')"><i class="bi bi-copy"></i> Duplica Selezionati</button>
        <button class="btn btn-info btn-sm text-white" onclick="return submitForm('{{ url_for('bulk_edit') }}', 'get')"><i class="bi bi-pencil-square"></i> Modifica Multipla</button>
        <button class="btn btn-danger btn-sm" onclick="return submitDeleteForm()"><i class="bi bi-trash"></i> Elimina Selezionati</button>
        {% endif %}
    </div>
    <form id="selection-form" method="post">
        <div class="table-container">
            <table class="table table-sm table-hover table-compact table-bordered table-striped align-middle">
                <thead class="table-light">
                    <tr>
                        <th class="no-print" style="width:28px"><input type="checkbox" id="checkall"></th>
                        {% for c in cols %}<th>{{ c.replace('_', ' ') | title }}</th>{% endfor %}
                        <th>Allegati</th>
                        <th class="no-print">Azione</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr class="{% if r.data_uscita %}text-muted{% endif %}">
                        <td class="no-print"><input type="checkbox" name="ids" class="sel" value="{{ r.id_articolo }}"></td>
                        {% for c in cols %}
                            {% set v = getattr(r, c) %}
                            <td>{% if c in ['data_ingresso','data_uscita'] %}{{ v|fmt_date }}{% else %}{{ v or '' }}{% endif %}</td>
                        {% endfor %}
                        <td>
                            {% for a in r.attachments %}
                            <a class="badge text-bg-secondary text-decoration-none" href="{{ url_for('media', att_id=a.id) }}" target="_blank">
                                <i class="bi {% if a.kind == 'doc' %}bi-file-pdf{% else %}bi-image{% endif %}"></i>
                            </a>
                            {% endfor %}
                        </td>
                        <td class="no-print"><a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_row', id=r.id_articolo) }}">Modifica</a></td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="{{ cols|length + 3 }}" class="text-center text-muted">Nessun articolo trovato con i filtri attuali.</td>
                    </tr>
                    {% endfor %}
                </tbody>
                <tfoot class="no-print">
                    <tr class="table-light fw-bold">
                        <td colspan="10" class="text-end">Totali Merce in Giacenza (filtrata):</td>
                        <td colspan="2">Colli: {{ total_colli }}</td>
                        <td colspan="2">M²: {{ "%.3f"|format(total_m2) }}</td>
                        <td colspan="4"></td>
                    </tr>
                </tfoot>
            </table>
        </div>
    </form>
</div>
{% endblock %}
{% block extra_js %}
<script>
    document.getElementById('checkall').addEventListener('change', e => {
        document.querySelectorAll('.sel').forEach(cb => cb.checked = e.target.checked);
    });
    function getSelectedIds() {
        return [...document.querySelectorAll('.sel:checked')].map(x => x.value);
    }
    function submitForm(actionUrl, method) {
        const ids = getSelectedIds();
        if (ids.length === 0) {
            alert('Seleziona almeno una riga');
            return false;
        }
        const form = document.getElementById('selection-form');
        form.action = actionUrl;
        form.method = method;
        if (method.toLowerCase() === 'get') {
            form.querySelectorAll('input.get-param').forEach(el => el.remove());
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'ids';
            hiddenInput.value = ids.join(',');
            hiddenInput.className = 'get-param';
            form.appendChild(hiddenInput);
        }
        form.submit();
        return true;
    }
    function submitDeleteForm() {
        const ids = getSelectedIds();
        if (ids.length === 0) {
            alert('Seleziona almeno una riga');
            return;
        }
        if (confirm(`Sei sicuro di voler eliminare definitivamente ${ids.length} articoli selezionati? L'azione è irreversibile.`)) {
            submitForm('{{ url_for("bulk_delete") }}', 'post');
        }
    }
</script>
{% endblock %}
"""

EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h5><i class="bi bi-pencil"></i> {{ 'Modifica' if row.id_articolo else 'Nuovo' }} Articolo {% if row.id_articolo %}#{{ row.id_articolo }}{% endif %}</h5>
    <hr>
    <form method="post" enctype="multipart/form-data">
        <div class="row g-3">
            {% for label, name in fields %}
            <div class="col-md-4">
                <label class="form-label">{{ label }}</label>
                <input name="{{ name }}" value="{{ getattr(row, name, '') or '' }}" class="form-control">
            </div>
            {% endfor %}
        </div>
        <div class="mt-4 d-flex gap-2">
            <button class="btn btn-primary"><i class="bi bi-save"></i> Salva Modifiche</button>
            <a class="btn btn-secondary" href="{{ url_for('giacenze') }}">Annulla</a>
        </div>
    </form>
</div>
{% if row.id_articolo %}
<div class="card p-4 mt-4">
    <h6><i class="bi bi-paperclip"></i> Allegati</h6>
    <form method="post" enctype="multipart/form-data" class="my-3">
         <div class="mb-3">
            <label class="form-label">Carica nuovi file (PDF/Immagini)</label>
            <div class="dropzone" id="dz">Trascina qui i file o clicca per selezionare</div>
            <input type="file" id="fi" name="files" multiple class="form-control mt-2" style="display:none" accept="application/pdf,image/*">
         </div>
         <button class="btn btn-success btn-sm">Carica Allegati</button>
    </form>
    <ul class="list-group">
        {% for a in row.attachments %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
            <div>
                <span class="badge text-bg-light me-2">{{ a.kind }}</span>
                <a href="{{ url_for('media', att_id=a.id) }}" target="_blank">{{ a.filename }}</a>
            </div>
            <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_attachment', att_id=a.id) }}"><i class="bi bi-trash"></i></a>
        </li>
        {% else %}
        <li class="list-group-item text-muted">Nessun allegato presente</li>
        {% endfor %}
    </ul>
</div>
{% endif %}
{% endblock %}
{% block extra_js %}
<script>
const dz = document.getElementById('dz'), fi = document.getElementById('fi');
if(dz && fi) {
    dz.addEventListener('click', () => fi.click());
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.style.backgroundColor = '#dbeafe'; });
    dz.addEventListener('dragleave', () => dz.style.backgroundColor = '#eef4ff');
    dz.addEventListener('drop', e => {
        e.preventDefault();
        fi.files = e.dataTransfer.files;
        dz.textContent = `${e.dataTransfer.files.length} file selezionati`;
        dz.style.backgroundColor = '#eef4ff';
    });
    fi.addEventListener('change', () => {
        if(fi.files.length > 0) {
            dz.textContent = `${fi.files.length} file selezionati`;
        }
    });
}
</script>
{% endblock %}
"""

BULK_EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h5><i class="bi bi-pencil-square"></i> Modifica Multipla</h5>
    <p class="text-muted">Stai modificando {{ rows|length }} articoli selezionati. Lascia un campo vuoto per non modificarlo.</p>
    <hr>
    <form method="post">
        <input type="hidden" name="ids" value="{{ ids_csv }}">
        <div class="row g-3">
            {% for label, name in fields %}
            <div class="col-md-4">
                <label class="form-label">{{ label }}</label>
                <input name="{{ name }}" class="form-control form-control-sm" placeholder="Nuovo valore per tutti...">
            </div>
            {% endfor %}
        </div>
        <div class="mt-4 d-flex gap-2">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Applica Modifiche</button>
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
        </div>
    </form>
    <hr>
    <h6>Articoli Selezionati</h6>
    <ul class="list-group list-group-flush">
    {% for row in rows %}
        <li class="list-group-item"><b>ID {{ row.id_articolo }}</b>: {{ row.codice_articolo or 'N/D' }} - {{ row.descrizione or 'N/D' }}</li>
    {% endfor %}
    </ul>
</div>
{% endblock %}
"""
BUONO_PREVIEW_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-3">
    <div class="d-flex align-items-center gap-3 mb-3">
        {% if logo_url %}<img src="{{ logo_url }}" style="height:40px">{% endif %}
        <h5 class="flex-grow-1 text-center m-0">BUONO DI PRELIEVO</h5>
        
        <div class="btn-group">
            <button type="button" class="btn btn-outline-primary" onclick="submitBuono('preview')">
                <i class="bi bi-eye"></i> Anteprima PDF
            </button>
            <button type="button" class="btn btn-success" onclick="submitBuono('save')">
                <i class="bi bi-file-earmark-check"></i> Genera e Salva
            </button>
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
        </div>
    </div>

    <form id="buono-form" method="POST" action="{{ url_for('buono_finalize_and_get_pdf') }}">
        <input type="hidden" name="ids" value="{{ ids }}">
        <input type="hidden" name="action" id="form-action" value="preview">

        <div class="row g-3">
            <div class="col-md-3"><label class="form-label">N. Buono</label><input name="buono_n" class="form-control" value="{{ meta.buono_n }}"></div>
            <div class="col-md-3"><label class="form-label">Data Emissione</label><input name="data_em" class="form-control" value="{{ meta.data_em }}" readonly></div>
            <div class="col-md-3"><label class="form-label">Commessa</label><input name="commessa" class="form-control" value="{{ meta.commessa }}"></div>
            <div class="col-md-3"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control" value="{{ meta.fornitore }}"></div>
            <div class="col-md-3"><label class="form-label">Protocollo</label><input name="protocollo" class="form-control" value="{{ meta.protocollo }}"></div>
        </div>
        <hr>
        <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Ordine</th>
                        <th>Codice Articolo</th>
                        <th>Descrizione</th>
                        <th style="width: 250px;">Note (Editabili)</th>
                        <th style="width: 80px;">Quantità</th>
                        <th>N.Arrivo</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.ordine or '' }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
                        <td><textarea class="form-control form-control-sm" name="note_{{ r.id_articolo }}" rows="1">{{ r.note or '' }}</textarea></td>
                        <td><input name="q_{{ r.id_articolo }}" class="form-control form-control-sm" value="{{ r.n_colli or 1 }}"></td>
                        <td>{{ r.n_arrivo or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </form>
</div>
{% endblock %}
{% block extra_js %}
<script>
function submitBuono(actionType) {
    const form = document.getElementById('buono-form');
    document.getElementById('form-action').value = actionType;

    if (actionType === 'preview') {
        // ANTEPRIMA: Apre nuova scheda inviando i dati via POST (evita errori URL troppo lunghi)
        form.target = '_blank';
        form.submit();
    } else {
        // SALVA: Usa fetch per scaricare e poi reindirizzare
        // Reset target per non aprire nuove schede
        form.target = '_self'; 
        const formData = new FormData(form);

        fetch(form.action, { method: 'POST', body: formData })
        .then(resp => {
            if (resp.ok) return resp.blob();
            throw new Error('Errore nel salvataggio');
        })
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'Buono_Prelievo.pdf';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            
            // Redirect dopo il download
            setTimeout(() => { window.location.href = '{{ url_for("giacenze") }}'; }, 1000);
        })
        .catch(err => alert("Errore: " + err));
    }
}
</script>
{% endblock %}
"""

DDT_PREVIEW_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-3">
    <div class="d-flex align-items-center gap-3 mb-3">
        {% if logo_url %}<img src="{{ logo_url }}" style="height:40px">{% endif %}
        <h5 class="flex-grow-1 text-center m-0">DOCUMENTO DI TRASPORTO</h5>
        
        <div class="btn-group">
            <button type="button" class="btn btn-outline-primary" onclick="submitDdt('preview')">
                <i class="bi bi-eye"></i> Anteprima PDF
            </button>
            <button type="button" class="btn btn-success" onclick="submitDdt('finalize')">
                <i class="bi bi-check-circle-fill"></i> Finalizza e Scarica
            </button>
        </div>
    </div>

    <form id="ddt-form">
        <input type="hidden" name="ids" value="{{ ids }}">
        <input type="hidden" name="action" id="action_type" value="preview">
        
        <div class="row g-3">
            <div class="col-md-4">
                <label class="form-label">Destinatario</label>
                <div class="input-group">
                    <select class="form-select" name="dest_key">
                        {% for k, v in destinatari.items() %}
                        <option value="{{ k }}">{{ k }} - {{ v.ragione_sociale }}</option>
                        {% endfor %}
                    </select>
                    <a href="{{ url_for('manage_destinatari') }}" class="btn btn-outline-secondary" target="_blank"><i class="bi bi-pencil"></i></a>
                </div>
            </div>
            <div class="col-md-3">
                 <label class="form-label">N. DDT</label>
                 <div class="input-group">
                    <input name="n_ddt" id="n_ddt_input" class="form-control" value="{{ n_ddt }}">
                    <button class="btn btn-outline-secondary" type="button" id="get-next-ddt" title="Genera Nuovo Numero">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </div>
            <div class="col-md-2"><label class="form-label">Data DDT</label><input name="data_ddt" type="date" class="form-control" value="{{ oggi }}"></div>
            <div class="col-md-3"><label class="form-label">Targa</label><input name="targa" class="form-control"></div>
            
            <div class="col-md-4"><label class="form-label">Causale</label><input name="causale" class="form-control" value="TRASFERIMENTO"></div>
            <div class="col-md-4"><label class="form-label">Porto</label><input name="porto" class="form-control" value="FRANCO"></div>
            <div class="col-md-4"><label class="form-label">Aspetto</label><input name="aspetto" class="form-control" value="A VISTA"></div>
        </div>
        <hr>
        <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle">
                <thead class="table-light">
                    <tr>
                        <th style="width: 50px;">ID</th>
                        <th>Cod.Art.</th>
                        <th>Descrizione</th>
                        <th style="width: 250px;">Note (Editabili)</th>
                        <th style="width: 70px;">Pezzi</th>
                        <th style="width: 70px;">Colli</th>
                        <th style="width: 80px;">Peso</th>
                        <th>N.Arrivo</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.id_articolo }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
                        
                        <td>
                            <textarea class="form-control form-control-sm" name="note_{{ r.id_articolo }}" rows="1" style="resize:vertical">{{ r.note or '' }}</textarea>
                        </td>
                        
                        <td><input class="form-control form-control-sm" name="pezzi_{{ r.id_articolo }}" value="{{ r.pezzo or 1 }}"></td>
                        <td><input class="form-control form-control-sm" name="colli_{{ r.id_articolo }}" value="{{ r.n_colli or 1 }}"></td>
                        <td><input class="form-control form-control-sm" name="peso_{{ r.id_articolo }}" value="{{ r.peso or '' }}"></td>
                        <td>{{ r.n_arrivo or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </form>
</div>
{% endblock %}
{% block extra_js %}
<script>
// Aggiorna numero DDT
document.getElementById('get-next-ddt').addEventListener('click', function() {
    fetch('{{ url_for('get_next_ddt_number') }}')
        .then(response => response.json())
        .then(data => { document.getElementById('n_ddt_input').value = data.next_ddt; });
});

function submitDdt(action) {
    const form = document.getElementById('ddt-form');
    document.getElementById('action_type').value = action; // Imposta azione (preview/finalize)
    const formData = new FormData(form);

    if (action === 'preview') {
        // ANTEPRIMA: Apre in nuova scheda (Blob URL)
        fetch('{{ url_for("ddt_finalize") }}', {
            method: 'POST',
            body: formData
        })
        .then(resp => resp.blob())
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            window.open(url, '_blank'); // Apre il PDF in una nuova tab
        })
        .catch(err => alert("Errore generazione anteprima: " + err));
    
    } else {
        // FINALIZZA: Scarica il file e poi reindirizza
        fetch('{{ url_for("ddt_finalize") }}', {
            method: 'POST',
            body: formData
        })
        .then(resp => {
            if (resp.ok) {
                return resp.blob().then(blob => {
                    // 1. Scarica il file automaticamente
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'DDT_Finale.pdf'; // Nome temporaneo, il server ne manda uno migliore ma questo è fallback
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                    
                    // 2. Torna alla Home (Giacenze) dopo breve attesa
                    setTimeout(() => {
                        window.location.href = '{{ url_for("giacenze") }}';
                    }, 1500);
                });
            } else {
                alert("Errore durante la finalizzazione.");
            }
        })
        .catch(err => alert("Errore di rete: " + err));
    }
}
</script>
{% endblock %}
"""

LABELS_FORM_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-tag"></i> Nuova Etichetta</h3>
    <hr>
    <form method="post" action="{{ url_for('labels_pdf') }}" target="_blank">
        <div class="row g-3">
            <div class="col-md-4">
                <label class="form-label">Cliente</label>
                <input class="form-control" list="clienti-datalist" name="cliente" placeholder="Digita o seleziona un cliente...">
                <datalist id="clienti-datalist">
                    {% for c in clienti %}
                    <option value="{{ c }}">
                    {% endfor %}
                </datalist>
            </div>
            <div class="col-md-4"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Ordine</label><input name="ordine" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Commessa</label><input name="commessa" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">DDT Ingresso</label><input name="ddt_ingresso" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Data Ingresso</label><input name="data_ingresso" class="form-control" placeholder="gg/mm/aaaa"></div>
            <div class="col-md-4"><label class="form-label">Arrivo (es. 01/25)</label><input name="arrivo" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">N. Colli</label><input name="n_colli" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Posizione</label><input name="posizione" class="form-control"></div>
        </div>
        <div class="mt-4 d-flex gap-2">
            <button type="submit" class="btn btn-primary"><i class="bi bi-printer"></i> Genera PDF Etichetta</button>
        </div>
    </form>
</div>
{% endblock %}
"""

LABELS_PREVIEW_HTML = " " # Non più utilizzato

IMPORT_EXCEL_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8 col-lg-6">
        <div class="card p-4">
            <h3><i class="bi bi-file-earmark-arrow-up"></i> Importa Articoli da Excel</h3>
            <hr>
            
            {% if not profiles %}
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle"></i> <strong>Attenzione:</strong> Nessun profilo di importazione trovato. 
                <br>Carica prima il file <code>mappe_excel.json</code> nella sezione <a href="{{ url_for('manage_mappe') }}">Gestisci Mappe</a>.
            </div>
            {% else %}
            <p class="text-muted">Seleziona il profilo di mappatura corretto per il tuo file.</p>
            <form method="post" enctype="multipart/form-data">
                <div class="mb-3">
                    <label class="form-label fw-bold">1. Seleziona Profilo Mappa</label>
                    <select name="profile" class="form-select" required>
                        <option value="" disabled selected>-- Scegli dalla lista --</option>
                        {% for p in profiles %}
                        <option value="{{ p }}">{{ p }}</option>
                        {% endfor %}
                    </select>
                    <div class="form-text">Profili caricati: {{ profiles|length }}</div>
                </div>
                
                <div class="mb-3">
                    <label for="excel_file" class="form-label fw-bold">2. Carica File Excel</label>
                    <input class="form-control" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls,.xlsm" required>
                </div>
                
                <div class="d-grid gap-2">
                    <button type="submit" class="btn btn-primary btn-lg">Avvia Importazione</button>
                    <a href="{{ url_for('home') }}" class="btn btn-outline-secondary">Annulla</a>
                </div>
            </form>
            {% endif %}
            
            <div class="mt-4 text-center">
                <a href="{{ url_for('manage_mappe') }}" class="small text-decoration-none"><i class="bi bi-gear"></i> Gestisci file mappe_excel.json</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""
MAPPE_EXCEL_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container">
    <div class="card p-4">
        <h3><i class="bi bi-gear"></i> Gestione Mappe Excel (JSON)</h3>
        <hr>
        <p>Qui puoi visualizzare o aggiornare il file <code>mappe_excel.json</code> che definisce come leggere i file Excel.</p>
        
        <form method="post">
            <div class="mb-3">
                <label class="form-label">Contenuto JSON corrente:</label>
                <textarea name="json_content" class="form-control" rows="15" style="font-family: monospace; font-size: 12px;">{{ content }}</textarea>
            </div>
            <button type="submit" class="btn btn-success">Salva Modifiche</button>
            <a href="{{ url_for('import_excel') }}" class="btn btn-secondary">Torna all'Import</a>
        </form>

        <hr class="my-4">
        <h5>Oppure carica un nuovo file .json</h5>
        <form method="post" enctype="multipart/form-data" action="{{ url_for('upload_mappe_json') }}">
             <div class="input-group mb-3">
                <input type="file" class="form-control" name="json_file" accept=".json" required>
                <button class="btn btn-outline-primary" type="submit">Carica File</button>
             </div>
        </form>
    </div>
</div>
{% endblock %}
"""
EXPORT_CLIENT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8 col-lg-6">
        <div class="card p-4">
            <h3><i class="bi bi-people"></i> Export Excel per Cliente</h3>
            <hr>
            <p>Seleziona un cliente dall'elenco per scaricare il file Excel con solo le sue giacenze.</p>
            <form method="post">
                <div class="mb-3">
                    <label for="cliente" class="form-label">Cliente</label>
                    <select class="form-select" id="cliente" name="cliente" required>
                        <option value="" disabled selected>-- Seleziona un cliente --</option>
                        {% for c in clienti %}
                        <option value="{{ c }}">{{ c }}</option>
                        {% endfor %}
                    </select>
                </div>
                <button type="submit" class="btn btn-primary">Scarica Excel</button>
                <a href="{{ url_for('home') }}" class="btn btn-secondary">Annulla</a>
            </form>
        </div>
    </div>
</div>
{% endblock %}
"""

DESTINATARI_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-10 col-lg-8">
        <div class="card p-4">
            <h3><i class="bi bi-person-rolodex"></i> Gestione Destinatari</h3>
            <hr>
            <h5>Aggiungi Nuovo Destinatario</h5>
            <form method="post" class="mb-4">
                <div class="row g-3">
                    <div class="col-md-6"><label class="form-label">Nome Chiave (es. Sede Cliente)</label><input name="key_name" class="form-control" required></div>
                    <div class="col-md-6"><label class="form-label">Ragione Sociale</label><input name="ragione_sociale" class="form-control" required></div>
                    <div class="col-md-6"><label class="form-label">Indirizzo Completo</label><input name="indirizzo" class="form-control"></div>
                    <div class="col-md-6"><label class="form-label">Partita IVA</label><input name="piva" class="form-control"></div>
                </div>
                <button type="submit" class="btn btn-primary mt-3">Aggiungi</button>
            </form>
            <hr>
            <h5>Destinatari Esistenti</h5>
            <ul class="list-group">
                {% for key, details in destinatari.items() %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{{ key }}</strong><br>
                        <small class="text-muted">{{ details.ragione_sociale }} - {{ details.indirizzo }}</small>
                    </div>
                    <a href="{{ url_for('delete_destinatario', key=key) }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Sei sicuro di voler eliminare questo destinatario?')"><i class="bi bi-trash"></i></a>
                </li>
                {% else %}
                <li class="list-group-item">Nessun destinatario salvato.</li>
                {% endfor %}
            </ul>
             <a href="{{ request.referrer or url_for('home') }}" class="btn btn-secondary mt-4">Indietro</a>
        </div>
    </div>
</div>
{% endblock %}
"""

CALCOLA_COSTI_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-calculator"></i> Calcolo Giacenze Mensili</h3>
    <hr>
    <form method="post" class="mb-4">
        <div class="row g-3 align-items-end">
            <div class="col-md-5">
                <label for="cliente" class="form-label">Cliente</label>
                <select class="form-select" id="cliente" name="cliente" required>
                    <option value="" disabled selected>-- Seleziona un cliente --</option>
                    {% for c in clienti %}
                    <option value="{{ c }}" {% if cliente_selezionato == c %}selected{% endif %}>{{ c }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-5">
                <label for="mese_anno" class="form-label">Mese e Anno</label>
                <input type="month" class="form-control" id="mese_anno" name="mese_anno" value="{{ mese_selezionato }}" required>
            </div>
            <div class="col-md-2 d-grid">
                <button type="submit" class="btn btn-primary">Calcola</button>
            </div>
        </div>
    </form>
    {% if risultato %}
    <hr>
    <div class="alert alert-success">
        <h5>Risultato Calcolo</h5>
        <p>Per il cliente <strong>{{ risultato.cliente }}</strong> alla fine del periodo <strong>{{ risultato.periodo }}</strong>, la giacenza totale era di:</p>
        <h3 class="display-6">{{ "%.3f"|format(risultato.total_m2) }} m²</h3>
        <p class="mb-0 text-muted">(calcolato su {{ risultato.count }} articoli in giacenza in quel periodo)</p>
    </div>
    {% endif %}
     <a href="{{ url_for('home') }}" class="btn btn-secondary mt-3">Torna alla Home</a>
</div>
{% endblock %}
"""

INVIA_EMAIL_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8">
        <div class="card p-4">
            <h4 class="mb-3"><i class="bi bi-envelope"></i> Invia Email con Allegati</h4>
            
            {% if selected_ids %}
            <div class="alert alert-info">
                <i class="bi bi-info-circle"></i> Hai selezionato <strong>{{ selected_ids.split(',')|length }}</strong> articoli. 
                Verrà generato e allegato un PDF di riepilogo/DDT e gli eventuali allegati presenti (foto/documenti).
            </div>
            {% endif %}

            <form method="post" enctype="multipart/form-data">
                <input type="hidden" name="selected_ids" value="{{ selected_ids }}">
                
                <div class="mb-3">
                    <label class="form-label">Destinatario (Email)</label>
                    <input type="email" name="destinatario" class="form-control" required placeholder="cliente@esempio.com">
                </div>
                
                <div class="mb-3">
                    <label class="form-label">Oggetto</label>
                    <input type="text" name="oggetto" class="form-control" value="Documentazione Merce - Camar S.r.l." required>
                </div>
                
                <div class="mb-3">
                    <label class="form-label">Messaggio</label>
                    <textarea name="messaggio" rows="5" class="form-control">Buongiorno,

In allegato inviamo la documentazione relativa alla merce in oggetto.

Cordiali saluti,
Camar S.r.l.</textarea>
                </div>

                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" name="genera_ddt" id="genera_ddt" checked>
                        <label class="form-check-label" for="genera_ddt">
                            Genera e allega PDF Riepilogo/DDT
                        </label>
                    </div>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" name="allega_file" id="allega_file" checked>
                        <label class="form-check-label" for="allega_file">
                            Includi allegati esistenti (Foto/PDF caricati sugli articoli)
                        </label>
                    </div>
                </div>

                <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                    <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
                    <button type="submit" class="btn btn-primary"><i class="bi bi-send"></i> Invia Email</button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
"""




templates = {
    'base.html': BASE_HTML,
    'login.html': LOGIN_HTML,
    'home.html': HOME_HTML,
    'giacenze.html': GIACENZE_HTML,
    'edit.html': EDIT_HTML,
    'bulk_edit.html': BULK_EDIT_HTML,
    'buono_preview.html': BUONO_PREVIEW_HTML,
    'ddt_preview.html': DDT_PREVIEW_HTML,
    'labels_form.html': LABELS_FORM_HTML,
    'labels_preview.html': LABELS_PREVIEW_HTML,
    'import_excel.html': IMPORT_EXCEL_HTML,

    # ✅ AGGIUNGI QUESTA RIGA
    'mappe_excel.html': MAPPE_EXCEL_HTML,
    'invia_email.html': INVIA_EMAIL_HTML,
 

    'export_client.html': EXPORT_CLIENT_HTML,
    'destinatari.html': DESTINATARI_HTML,
    'calcola_costi.html': CALCOLA_COSTI_HTML
}

# --- APP FLASK ---
app = Flask(__name__)
app.jinja_loader = DictLoader(templates)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.jinja_env.globals['getattr'] = getattr
app.jinja_env.filters['fmt_date'] = fmt_date


def logo_url():
    if not LOGO_PATH:
        return None
    p = Path(LOGO_PATH)
    if p.exists() and p.parent == STATIC_DIR:
        return url_for('static', filename=p.name)
    try:
        target = STATIC_DIR / Path(LOGO_PATH).name
        if not target.exists():
            target.write_bytes(p.read_bytes())
        return url_for('static', filename=target.name)
    except Exception:
        return None

@app.context_processor
def inject_globals():
    return dict(logo_url=logo_url())

# --- ROUTE PRINCIPALI E AUTH ---
@app.route('/')
def index():
    if not session.get('user'):
        return redirect(url_for('login'))
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = (request.form.get('user') or '').strip().upper()
        pwd = request.form.get('pwd') or ''
        users = get_users()
        if user in users and users[user] == pwd:
            session['user'] = user
            session['role'] = 'admin' if user in ADMIN_USERS else 'client'
            flash(f"Benvenuto {user}", "success")
            return redirect(url_for('home'))
        else:
            flash("Credenziali non valide", "danger")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logout effettuato con successo", "success")
    return redirect(url_for('login'))

@app.route('/home')
@login_required
def home():
    return render_template('home.html')


# --- GESTIONE MAPPE E IMPORTAZIONE RIGIDA ---

def load_mappe():
    """Carica il file mappe_excel.json"""
    json_path = APP_DIR / "mappe_excel.json"
    if not json_path.exists():
        # Crea un default vuoto se non esiste
        return {}
    try:
        return json.loads(json_path.read_text(encoding='utf-8'))
    except Exception as e:
        return {}

@app.route('/manage_mappe', methods=['GET', 'POST'])
@login_required
def manage_mappe():
    json_path = APP_DIR / "mappe_excel.json"
    
    if request.method == 'POST':
        content = request.form.get('json_content')
        try:
            # Verifica che sia un JSON valido
            json.loads(content)
            json_path.write_text(content, encoding='utf-8')
            flash("Mappa aggiornata con successo.", "success")
        except json.JSONDecodeError as e:
            flash(f"Errore nel formato JSON: {e}", "danger")
        return redirect(url_for('manage_mappe'))

    content = ""
    if json_path.exists():
        content = json_path.read_text(encoding='utf-8')
    
    return render_template('mappe_excel.html', content=content)

@app.post('/upload_mappe_json')
@login_required
def upload_mappe_json():
    if 'json_file' not in request.files:
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('manage_mappe'))
    f = request.files['json_file']
    if f.filename == '':
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('manage_mappe'))
    
    try:
        content = f.read().decode('utf-8')
        json.loads(content) # Validazione
        (APP_DIR / "mappe_excel.json").write_text(content, encoding='utf-8')
        flash("File mappe_excel.json caricato correttamente.", "success")
    except Exception as e:
        flash(f"Errore nel file caricato: {e}", "danger")
    
    return redirect(url_for('manage_mappe'))
# --- IMPORTAZIONE EXCEL (Versione Super-Robusta) ---
@app.route('/import_excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    import logging, re
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    logger = logging.getLogger("IMPORT")

    mappe = load_mappe()
    profiles = list(mappe.keys()) if mappe else []

    if request.method == 'GET':
        return render_template('import_excel.html', profiles=profiles)

    profile_name = request.form.get('profile')
    if not profile_name or profile_name not in mappe:
        flash("Seleziona un profilo valido.", "warning")
        return redirect(request.url)
    
    if 'excel_file' not in request.files:
        flash('Nessun file selezionato', 'warning')
        return redirect(request.url)
    
    file = request.files['excel_file']
    if not file or file.filename == '':
        flash('Nessun file selezionato', 'warning')
        return redirect(request.url)

    if not file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm')):
        flash('Formato file non supportato.', 'warning')
        return redirect(request.url)

    config = mappe[profile_name]
    column_map = config.get('column_map', {}) or {}
    
    # Definisci i campi che DEVONO essere numerici
    numeric_fields = ['larghezza', 'lunghezza', 'altezza', 'peso', 'm2', 'm3', 'n_colli', 'pezzo']

    # Auto-detect header (semplificato)
    try:
        df_scan = pd.read_excel(file, engine='openpyxl', header=None, nrows=30)
        expected = [str(k).strip().upper() for k in column_map.keys()]
        best_header = 0
        max_matches = 0
        for i, row in df_scan.iterrows():
            row_vals = [str(v).strip().upper() for v in row if pd.notna(v)]
            matches = sum(1 for e in expected if e in row_vals)
            if matches > max_matches:
                max_matches = matches
                best_header = i
        
        if max_matches < 2:
            best_header = int(config.get('header_row', 1)) - 1
            logger.warning("Auto-detect header fallito, uso config JSON.")
        
        file.seek(0)
        df = pd.read_excel(file, engine='openpyxl', header=best_header)
        
    except Exception as e:
        flash(f"Errore lettura file: {e}", "danger")
        return redirect(request.url)

    # Normalizzazione colonne DF
    df_cols_norm = {str(c).strip().upper(): c for c in df.columns}
    
    db = SessionLocal()
    try:
        imported_count = 0
        for _, row in df.iterrows():
            if row.isnull().all(): continue
            
            new_art = Articolo()
            has_data = False
            
            for excel_header, db_field in column_map.items():
                if excel_header.upper() == "ID": continue # Salta ID excel

                col_name = df_cols_norm.get(str(excel_header).strip().upper())
                if col_name:
                    val = row[col_name]
                    if pd.isna(val) or str(val).strip() == "": continue
                    
                    try:
                        # Gestione Tipi Rigorosa
                        if db_field in numeric_fields:
                            # Pulisci stringhe tipo "1.200,00" -> 1200.00
                            if isinstance(val, str):
                                val = val.replace('.', '').replace(',', '.')
                            val = float(val)
                            if db_field in ['n_colli', 'pezzo']:
                                val = int(round(val))
                        elif db_field in ['data_ingresso', 'data_uscita']:
                             val = fmt_date(val) if isinstance(val, (datetime, date)) else parse_date_ui(str(val))
                        else:
                            # Tutto il resto è stringa
                            val = str(val).strip()
                            
                        setattr(new_art, db_field, val)
                        has_data = True
                    except Exception:
                        continue # Salta valore se conversione fallisce

            if has_data:
                 # Calcolo m2/m3
                if not new_art.m2:
                    new_art.m2, new_art.m3 = calc_m2_m3(
                        new_art.lunghezza, new_art.larghezza, new_art.altezza, new_art.n_colli
                    )
                db.add(new_art)
                imported_count += 1
        
        db.commit()
        flash(f"{imported_count} articoli importati correttamente.", "success")
        return redirect(url_for('giacenze', v=uuid.uuid4().hex[:6]))

    except Exception as e:
        db.rollback()
        logger.error(f"DB ERROR: {e}")
        # Messaggio user-friendly
        msg = str(e)
        if "invalid input syntax for type integer" in msg:
            msg = "Errore nei dati: una colonna di testo contiene numeri o viceversa. Controlla il file Excel."
        flash(f"Errore importazione: {msg}", "danger")
        return redirect(request.url)
    finally:
        db.close()

def get_all_fields_map():
    return {
        'codice_articolo': 'Codice Articolo', 'pezzo': 'Pezzi',
        'descrizione': 'Descrizione', 'cliente': 'Cliente','ordine':'Ordine',
        'protocollo': 'Protocollo', 'peso': 'Peso (Kg)',
        'n_colli': 'N° Colli', 'posizione': 'Posizione', 'stato': 'Stato',
        'n_arrivo': 'N° Arrivo', 'buono_n': 'Buono N°',
        'fornitore': 'Fornitore', 'magazzino': 'Magazzino',
        'data_ingresso': 'Data Ingresso', 'data_uscita': 'Data Uscita',
        'n_ddt_ingresso': 'N° DDT Ingresso', 'n_ddt_uscita': 'N° DDT Uscita',
        'larghezza': 'Larghezza (m)', 'lunghezza': 'Lunghezza (m)',
        'altezza': 'Altezza (m)', 'serial_number': 'Serial Number',
        'ns_rif': 'NS Rif', 'mezzi_in_uscita': 'Mezzi in Uscita', 'note': 'Note'
    }

# --- EXPORTAZIONE EXCEL ---
@app.get('/export_excel')
@login_required
def export_excel():
    db = SessionLocal()
    df = pd.read_sql(db.query(Articolo).statement, db.bind)
    bio = io.BytesIO()
    df.to_excel(bio, index=False, engine='openpyxl')
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name='Giacenze_Totali.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export_client', methods=['GET', 'POST'])
@login_required
def export_client():
    db = SessionLocal()
    clienti = [c[0] for c in db.query(Articolo.cliente).distinct().filter(Articolo.cliente != None, Articolo.cliente != '').order_by(Articolo.cliente).all()]
    
    if request.method == 'POST':
        cliente = request.form.get('cliente')
        if not cliente:
            flash("Seleziona un cliente.", "warning")
            return redirect(request.url)
        
        rows = db.query(Articolo).filter(Articolo.cliente == cliente).all()
        if not rows:
            flash(f"Nessun articolo trovato per il cliente {cliente}.", "info")
            return redirect(request.url)
        
        df = pd.DataFrame([vars(r) for r in rows])
        bio = io.BytesIO()
        df.to_excel(bio, index=False, engine='openpyxl')
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name=f"Giacenze_{cliente}.xlsx",
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return render_template('export_client.html', clienti=clienti)

# --- CALCOLO GIACENZE MENSILI (Corretto per date gg/mm/aaaa) ---
@app.route('/calcola_costi', methods=['GET', 'POST'])
@login_required
def calcola_costi():
    db = SessionLocal()
    try:
        # Prendi la lista clienti
        clienti = [c[0] for c in db.query(Articolo.cliente)
                   .distinct()
                   .filter(Articolo.cliente != None, Articolo.cliente != '')
                   .order_by(Articolo.cliente)
                   .all()]

        risultato = None
        cliente_selezionato = None
        mese_selezionato = None

        if request.method == 'POST':
            cliente = request.form.get('cliente')
            mese_anno = request.form.get('mese_anno')
            cliente_selezionato = cliente
            mese_selezionato = mese_anno

            if not cliente or not mese_anno:
                flash("Seleziona sia il cliente che il mese.", "warning")
                return redirect(request.url)

            try:
                # 1. Definisci l'intervallo del mese selezionato
                anno, mese = map(int, mese_anno.split('-'))
                data_inizio_mese = date(anno, mese, 1)
                ultimo_giorno = calendar.monthrange(anno, mese)[1]
                data_fine_mese = date(anno, mese, ultimo_giorno)

                # 2. Scarica TUTTI gli articoli di quel cliente (il filtro data lo facciamo in Python per sicurezza)
                articoli_grezzi = db.query(Articolo).filter(Articolo.cliente == cliente).all()
                
                articoli_validi = []
                
                for art in articoli_grezzi:
                    # Parsing Data Ingresso
                    d_in = None
                    if art.data_ingresso:
                        d_in = parse_date_ui(art.data_ingresso) # Restituisce stringa YYYY-MM-DD o None
                        if d_in:
                            try: d_in = datetime.strptime(d_in, "%Y-%m-%d").date()
                            except: d_in = None
                    
                    # Parsing Data Uscita
                    d_out = None
                    if art.data_uscita:
                        d_out = parse_date_ui(art.data_uscita)
                        if d_out:
                            try: d_out = datetime.strptime(d_out, "%Y-%m-%d").date()
                            except: d_out = None

                    # LOGICA DI GIACENZA:
                    # L'articolo deve essere entrato PRIMA o DURANTE il mese selezionato
                    # E deve essere uscito DOPO l'inizio del mese (o essere ancora dentro)
                    
                    if d_in and d_in <= data_fine_mese:
                        # Se non è mai uscito OPPURE è uscito dopo l'inizio del mese corrente
                        if d_out is None or d_out >= data_inizio_mese:
                            articoli_validi.append(art)

                total_m2 = sum(float(a.m2) for a in articoli_validi if a.m2 is not None)
                
                risultato = {
                    "cliente": cliente,
                    "periodo": f"{mese}/{anno}",
                    "total_m2": total_m2,
                    "count": len(articoli_validi)
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                flash(f"Errore nel calcolo: {e}", "danger")
    finally:
        db.close()

    return render_template(
        'calcola_costi.html',
        clienti=clienti,
        risultato=risultato,
        cliente_selezionato=cliente_selezionato,
        mese_selezionato=mese_selezionato
    )

@app.route('/invia_email', methods=['GET', 'POST'])
@login_required
def invia_email():
    if request.method == 'GET':
        selected_ids = request.args.get('ids', '')
        return render_template('invia_email.html', selected_ids=selected_ids)

    # POST: Invio Email
    selected_ids = request.form.get('selected_ids', '')
    destinatario = request.form.get('destinatario')
    oggetto = request.form.get('oggetto')
    messaggio = request.form.get('messaggio')
    genera_ddt = 'genera_ddt' in request.form
    allega_file = 'allega_file' in request.form

    ids_list = [int(i) for i in selected_ids.split(',') if i.isdigit()]
    if not ids_list:
        flash("Nessun articolo selezionato.", "warning")
        return redirect(url_for('giacenze'))

    # Configurazione SMTP (Defaults o Variabili d'ambiente)
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "") # Metti qui la tua email se testi in locale
    SMTP_PASS = os.environ.get("SMTP_PASS", "")

    if not SMTP_USER or not SMTP_PASS:
        flash("Configurazione email mancante (SMTP_USER/PASS). Controlla le impostazioni del server.", "warning")
        # Per test, simuliamo il successo
        return redirect(url_for('giacenze'))

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = destinatario
        msg['Subject'] = oggetto
        msg.attach(MIMEText(messaggio, 'plain'))

        db = SessionLocal()
        rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()

        # 1. Genera DDT al volo e allegalo
        if genera_ddt and rows:
            # Dati fittizi per il DDT volante
            dest_data = {"ragione_sociale": rows[0].cliente or "Cliente", "indirizzo": ""}
            pdf_bio = _generate_ddt_pdf("RIEPILOGO", date.today(), "", dest_data, rows, {})
            part = MIMEBase('application', "octet-stream")
            part.set_payload(pdf_bio.getvalue())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="Riepilogo_Merce.pdf"')
            msg.attach(part)

        # 2. Allega file caricati (foto/doc)
        if allega_file:
            for r in rows:
                for att in r.attachments:
                    path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
                    if path.exists():
                        with open(path, "rb") as f:
                            part = MIMEBase('application', "octet-stream")
                            part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename="{att.filename}"')
                        msg.attach(part)
        db.close()

        # Connessione al Server e Invio
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()

        flash(f"Email inviata correttamente a {destinatario}", "success")
    except Exception as e:
        flash(f"Errore durante l'invio: {e}", "danger")

    return redirect(url_for('giacenze'))

# --- GESTIONE ARTICOLI (CRUD) ---
@app.get('/new')
@login_required
def new_row():
    db = SessionLocal()
    try:
        a = Articolo(data_ingresso=date.today().strftime("%Y-%m-%d"))
        db.add(a)
        db.commit()
        flash('Articolo vuoto creato. Ora puoi compilare i campi.', 'success')
        return redirect(url_for('edit_row', id=a.id_articolo))
    except IntegrityError as e:
        db.rollback()
        flash(f'<b>Errore del database!</b> Potrebbe essere necessario resettare il contatore degli ID. Dettagli: {e.orig}', 'danger')
    except Exception as e:
        db.rollback()
        flash(f'Errore imprevisto: {e}', 'danger')
    return redirect(url_for('giacenze'))

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db = SessionLocal()
    row = db.get(Articolo, id)
    if not row:
        abort(404)

    if request.method == 'POST':
        for f, label in get_all_fields_map().items():
            v = request.form.get(f)
            if v is not None:
                if f in ('data_ingresso','data_uscita'):
                    v = parse_date_ui(v) if v else None
                elif f in ('larghezza','lunghezza','altezza','peso'):
                    v = to_float_eu(v)
                elif f in ('n_colli', 'pezzo'):
                    v = to_int_eu(v)
                setattr(row, f, v if v != '' else None)
        row.m2, row.m3 = calc_m2_m3(row.lunghezza, row.larghezza, row.altezza, row.n_colli)
        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if not f or not f.filename: continue
                safe_name = f"{id}_{uuid.uuid4().hex}_{f.filename.replace(' ','_')}"
                ext = os.path.splitext(safe_name)[1].lower()
                kind = 'doc' if ext == '.pdf' else 'foto'
                folder = DOCS_DIR if kind == 'doc' else PHOTOS_DIR
                f.save(str(folder / safe_name))
                db.add(Attachment(articolo_id=id, kind=kind, filename=safe_name))
        db.commit()
        flash('Riga salvata', 'success')
        return redirect(url_for('giacenze'))

    return render_template('edit.html', row=row, fields=get_all_fields_map().items())

# --- MEDIA & ALLEGATI ---
@app.get('/media/<int:att_id>')
@login_required
def media(att_id):
    db = SessionLocal()
    att = db.get(Attachment, att_id)
    if not att: abort(404)
    path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
    if not path.exists():
        flash(f"File allegato non trovato sul server: {att.filename}", "danger")
        return redirect(request.referrer or url_for('giacenze'))
    return send_file(path, as_attachment=False)

@app.get('/attachment/<int:att_id>/delete')
@login_required
def delete_attachment(att_id):
    db = SessionLocal()
    att = db.get(Attachment, att_id)
    if att:
        path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
        try:
            if path.exists(): path.unlink()
        except Exception as e:
            flash(f"Impossibile eliminare il file fisico: {e}", "warning")
        articolo_id = att.articolo_id
        db.delete(att)
        db.commit()
        flash('Allegato eliminato', 'success')
        return redirect(url_for('edit_row', id=articolo_id))
    return redirect(url_for('giacenze'))


# --- VISUALIZZA GIACENZE E AZIONI MULTIPLE ---
@app.get('/giacenze')
@login_required
def giacenze():
    import logging
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload

    db = SessionLocal()
    try:
        logging.info("=== GIACENZE: INIZIO ===")
        logging.info(f"Args ricevuti: {dict(request.args)}")
        logging.info(f"Session user={session.get('user')} role={session.get('role')}")

        # Query base
        qs = db.query(Articolo).options(selectinload(Articolo.attachments)).order_by(Articolo.id_articolo.desc())

        # Conteggio totale DB (senza filtri)
        tot_db = db.query(func.count(Articolo.id_articolo)).scalar()
        logging.info(f"Totale articoli nel DB: {tot_db}")

        # Restrizione client (se attiva)
        if session.get('role') == 'client':
            qs = qs.filter(Articolo.cliente == session['user'])
            logging.info("Filtro CLIENT attivo: Articolo.cliente == session['user']")

        like_cols = [
            'codice_articolo', 'cliente', 'fornitore', 'commessa', 'descrizione', 'posizione', 'stato',
            'protocollo', 'n_ddt_ingresso', 'n_ddt_uscita', 'n_arrivo', 'buono_n', 'ns_rif','ordine',
            'serial_number', 'mezzi_in_uscita'
        ]

        # Filtro per ID
        if request.args.get('id'):
            try:
                qs = qs.filter(Articolo.id_articolo == int(request.args.get('id')))
                logging.info(f"Filtro ID: {request.args.get('id')}")
            except ValueError:
                logging.warning(f"Filtro ID ignorato (non numerico): {request.args.get('id')}")

        # Filtri LIKE
        applied_like = {}
        for col in like_cols:
            v = request.args.get(col)
            if v:
                qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))
                applied_like[col] = v

        if applied_like:
            logging.info(f"Filtri LIKE applicati: {applied_like}")

        # Filtri date
        date_filters = {
            'data_ingresso_da': (Articolo.data_ingresso, '>='), 'data_ingresso_a': (Articolo.data_ingresso, '<='),
            'data_uscita_da': (Articolo.data_uscita, '>='), 'data_uscita_a': (Articolo.data_uscita, '<=')
        }

        applied_dates = {}
        for arg, (col, op) in date_filters.items():
            val = request.args.get(arg)
            if val:
                date_sql = parse_date_ui(val)
                if date_sql:
                    if op == '>=':
                        qs = qs.filter(col >= date_sql)
                    else:
                        qs = qs.filter(col <= date_sql)
                    applied_dates[arg] = val
                else:
                    logging.warning(f"Filtro data ignorato (parse fallito): {arg}={val}")

        if applied_dates:
            logging.info(f"Filtri DATE applicati: {applied_dates}")
            tot_filtered = qs.order_by(None).with_entities(func.count(Articolo.id_articolo)).scalar()
            logging.info(f"Totale righe dopo filtri: {tot_filtered}")


        # Scarica righe
        rows = qs.all()
        logging.info(f"Rows caricate in memoria: {len(rows)}")

        # ✅ Diagnosi: quante righe hanno campi valorizzati (non vuoti)
        def count_non_empty(colname: str) -> int:
            col = getattr(Articolo, colname)
            return db.query(func.count(Articolo.id_articolo)).filter(
                col.isnot(None),
                func.length(func.trim(col)) > 0
            ).scalar()

        try:
            con_codice = count_non_empty("codice_articolo")
            con_descr = count_non_empty("descrizione")
            con_cliente = count_non_empty("cliente")
            logging.info(f"DB non-vuoti -> codice_articolo: {con_codice}, descrizione: {con_descr}, cliente: {con_cliente}")
        except Exception:
            logging.warning("Non riesco a contare campi non-vuoti (colonne non stringa o errore)", exc_info=True)

        # ✅ Sample ultime 5 righe per capire cosa c’è DAVVERO nel DB
        sample = (
            db.query(Articolo)
            .order_by(Articolo.id_articolo.desc())
            .limit(5)
            .all()
        )
        for a in sample:
            logging.info(
                "SAMPLE id=%s codice=%r descr=%r cliente=%r fornitore=%r",
                a.id_articolo,
                getattr(a, "codice_articolo", None),
                getattr(a, "descrizione", None),
                getattr(a, "cliente", None),
                getattr(a, "fornitore", None),
            )

        # Calcoli stock
        stock_rows = [r for r in rows if not r.data_uscita]
        total_colli = sum(r.n_colli for r in stock_rows if r.n_colli)
        total_m2 = sum(r.m2 for r in stock_rows if r.m2)

        logging.info(f"Totali stock -> colli={total_colli}, m2={total_m2}")
        logging.info("=== GIACENZE: FINE OK ===")

    except Exception as e:
        db.rollback()
        logging.error("ERRORE GIACENZE", exc_info=True)
        flash(f"Errore nel caricamento delle giacenze: {e}", "danger")
        rows, total_colli, total_m2 = [], 0, 0
    finally:
        db.close()

    cols = [
        "id_articolo","codice_articolo","descrizione","cliente","fornitore","protocollo","buono_n",
        "lunghezza","larghezza","altezza","commessa","magazzino","posizione","stato","peso","n_colli",
        "m2","m3","data_ingresso","data_uscita","n_arrivo","n_ddt_uscita","ordine","mezzi_in_uscita"
    ]

    return render_template(
        'giacenze.html',
        rows=rows,
        cols=cols,
        total_colli=total_colli,
        total_m2=total_m2
    )


@app.route('/bulk/edit', methods=['GET', 'POST'])
@login_required
def bulk_edit():
    db = SessionLocal()
    if request.method == 'POST':
        ids_csv = request.form.get('ids', '')
        ids = [int(i) for i in ids_csv.split(',') if i.isdigit()]
        
        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        updated_fields_count = 0
        for art in articoli:
            for f in get_all_fields_map().keys():
                v = request.form.get(f)
                if v:
                    updated_fields_count += 1
                    if f in ('data_ingresso','data_uscita'):
                        v = parse_date_ui(v)
                    elif f in ('larghezza','lunghezza','altezza','peso'):
                        v = to_float_eu(v)
                    elif f in ('n_colli', 'pezzo'):
                        v = to_int_eu(v)
                    setattr(art, f, v)
        
        if updated_fields_count > 0:
            db.commit()
            flash(f"{len(articoli)} articoli aggiornati con successo.", "success")
        else:
            flash("Nessun campo compilato, nessuna modifica applicata.", "info")
            
        return redirect(url_for('giacenze'))

    ids_csv = request.args.get('ids', '')
    ids = [int(i) for i in ids_csv.split(',') if i.isdigit()]
    if not ids:
        flash("Nessun articolo selezionato per la modifica.", "warning")
        return redirect(url_for('giacenze'))
    
    rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
    return render_template('bulk_edit.html', rows=rows, ids_csv=ids_csv, fields=get_all_fields_map().items())

@app.post('/bulk/delete')
@login_required
def bulk_delete():
    ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()]
    if not ids:
        flash("Nessun articolo selezionato per l'eliminazione.", "warning")
        return redirect(url_for('giacenze'))
    
    db = SessionLocal()
    articoli_da_eliminare = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
    for art in articoli_da_eliminare:
        for att in art.attachments:
            path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
            try:
                if path.exists(): path.unlink()
            except Exception: pass

    db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).delete(synchronize_session=False)
    db.commit()
    flash(f"{len(ids)} articoli e i loro allegati sono stati eliminati.", "success")
    return redirect(url_for('giacenze'))

@app.post('/bulk/duplicate')
@login_required
def bulk_duplicate():
    if session.get('role') != 'admin':
        flash("Non hai i permessi per eseguire questa azione.", "danger")
        return redirect(url_for('giacenze'))
        
    ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()]
    if not ids:
        flash("Nessun articolo selezionato per la duplicazione.", "warning")
        return redirect(url_for('giacenze'))
    
    db = SessionLocal()
    articoli_da_duplicare = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
    
    nuovi_articoli = []
    mapper = inspect(Articolo)
    for originale in articoli_da_duplicare:
        nuovo = Articolo()
        for column in mapper.attrs:
            if column.key not in ['id_articolo', 'attachments']:
                setattr(nuovo, column.key, getattr(originale, column.key))
        nuovi_articoli.append(nuovo)

    db.add_all(nuovi_articoli)
    db.commit()
    flash(f"{len(nuovi_articoli)} articoli duplicati con successo.", "success")
    return redirect(url_for('giacenze'))

# --- ANTEPRIME HTML (BUONO / DDT) ---
def _get_rows_from_ids(ids_list):
    if not ids_list: return []
    db=SessionLocal()
    return db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()

@app.post('/buono/preview')
@login_required
def buono_preview():
    ids_str_list = request.form.getlist('ids')
    ids = [int(i) for i in ids_str_list if i.isdigit()]
    rows = _get_rows_from_ids(ids)
    first = rows[0] if rows else None
    meta = {
        "buono_n": first.buono_n if first else "", "data_em": datetime.today().strftime("%d/%m/%Y"),
        "commessa": (first.commessa or "") if first else "", "fornitore": (first.fornitore or "") if first else "",
        "protocollo": (first.protocollo or "") if first else "",
    }
    return render_template('buono_preview.html', rows=rows, meta=meta, ids=",".join(map(str, ids)))

@app.post('/ddt/preview')
@login_required
def ddt_preview():
    ids_str_list = request.form.getlist('ids')
    ids = [int(i) for i in ids_str_list if i.isdigit()]
    rows = _get_rows_from_ids(ids)
    return render_template('ddt_preview.html',
                           rows=rows, ids=",".join(map(str, ids)), destinatari=load_destinatari(),
                           n_ddt=next_ddt_number(), oggi=date.today().isoformat())

@app.get('/next_ddt_number')
@login_required
def get_next_ddt_number():
    return jsonify({'next_ddt': next_ddt_number()})

@app.route('/manage_destinatari', methods=['GET', 'POST'])
@login_required
def manage_destinatari():
    dest_file = APP_DIR / "destinatari_saved.json"
    destinatari = load_destinatari()
    
    if request.method == 'POST':
        # Se stiamo eliminando
        if 'delete_key' in request.form:
            key_to_delete = request.form.get('delete_key')
            if key_to_delete in destinatari:
                del destinatari[key_to_delete]
                try:
                    dest_file.write_text(json.dumps(destinatari, ensure_ascii=False, indent=4), encoding="utf-8")
                    flash(f"Destinatario '{key_to_delete}' eliminato.", "success")
                except Exception as e:
                    flash(f"Errore salvataggio file: {e}", "danger")
        
        # Se stiamo aggiungendo
        else:
            key_name = request.form.get('key_name')
            if not key_name:
                flash("Il Nome Chiave è obbligatorio.", "warning")
            else:
                destinatari[key_name] = {
                    "ragione_sociale": request.form.get('ragione_sociale', ''),
                    "indirizzo": request.form.get('indirizzo', ''),
                    "piva": request.form.get('piva', '')
                }
                try:
                    dest_file.write_text(json.dumps(destinatari, ensure_ascii=False, indent=4), encoding="utf-8")
                    flash(f"Destinatario '{key_name}' salvato.", "success")
                except Exception as e:
                    flash(f"Errore salvataggio file: {e}", "danger")

        return redirect(url_for('manage_destinatari'))
        
    return render_template('destinatari.html', destinatari=destinatari)

# --- PDF E FINALIZZAZIONE DDT ---
_styles = getSampleStyleSheet()
PRIMARY_COLOR = colors.HexColor("#3498db")

def _pdf_table(data, col_widths=None, header=True, hAlign='LEFT', style=None):
    t = Table(data, colWidths=col_widths, hAlign=hAlign)
    base_style = [
        ('FONT', (0,0), (-1,-1), 'Helvetica', 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]
    if style:
        base_style.extend(style)
    else:
        base_style.append(('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey))

    if header and data:
        base_style.extend([
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('FONT', (0,0), (-1,0), 'Helvetica-Bold', 8)
        ])
    t.setStyle(TableStyle(base_style))
    return t

def _copyright_para():
    tiny_style = _styles['Normal'].clone('copyright')
    tiny_style.fontSize = 7; tiny_style.textColor = colors.grey; tiny_style.alignment = TA_CENTER
    return Paragraph("Camar S.r.l. - Gestionale Web - © Alessia Moncalvo", tiny_style)

def _generate_ddt_pdf(n_ddt, data_ddt, targa, dest, rows, form_data):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    story = []
    styles = getSampleStyleSheet()
    s_small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)
    s_bold = ParagraphStyle('b', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9)
    s_note = ParagraphStyle('n', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Oblique', spaceBefore=2)

    # 1. Intestazione (Logo + Titolo)
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=50*mm, height=16*mm, hAlign='CENTER')); story.append(Spacer(1, 5*mm))
    story.append(Table([[Paragraph("DOCUMENTO DI TRASPORTO (DDT)", ParagraphStyle('T', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.white, fontSize=14))]], 
                  colWidths=[doc.width], style=[('BACKGROUND', (0,0), (-1,-1), PRIMARY_COLOR), ('PADDING', (0,0), (-1,-1), 6)]))
    story.append(Spacer(1, 5*mm))

    # 2. Mittente e Destinatario
    dest_str = f"<b>{dest.get('ragione_sociale','')}</b><br/>{dest.get('indirizzo','').replace(chr(10),'<br/>')}"
    t_head = Table([
        [Paragraph("<b>MITTENTE</b><br/>Camar S.r.l.<br/>Via Luigi Canepa 2<br/>16165 Genova", s_small),
         Paragraph(f"<b>DESTINATARIO</b><br/>{dest_str}", s_small)]
    ], colWidths=[doc.width/2, doc.width/2])
    t_head.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.25, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 6)]))
    story.append(t_head); story.append(Spacer(1, 4*mm))

    # 3. Dati
    first = rows[0] if rows else Articolo()
    t_data = Table([
        [Paragraph(f"<b>Cliente:</b> {first.cliente}<br/><b>Commessa:</b> {first.commessa}<br/><b>Ordine:</b> {first.ordine}<br/><b>Buono:</b> {first.buono_n}", s_small),
         Paragraph(f"<b>N. DDT:</b> {n_ddt}<br/><b>Data:</b> {fmt_date(data_ddt)}<br/><b>Targa:</b> {targa}<br/><b>Causale:</b> {form_data.get('causale','')}", s_small)]
    ], colWidths=[doc.width/2, doc.width/2])
    t_data.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.25, colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(t_data); story.append(Spacer(1, 6*mm))

    # 4. Tabella Articoli (SENZA NOTE dentro)
    header = [Paragraph(c, s_bold) for c in ['ID', 'Cod.Art.', 'Descrizione', 'Pz', 'Colli', 'Peso', 'N.Arr']]
    data = [header]
    tot_pezzi, tot_colli, tot_peso = 0, 0, 0.0
    note_list = [] # Raccoglitore per le note

    for r in rows:
        pezzi = to_int_eu(form_data.get(f"pezzi_{r.id_articolo}", r.pezzo)) or 0
        colli = to_int_eu(form_data.get(f"colli_{r.id_articolo}", r.n_colli)) or 0
        peso = to_float_eu(form_data.get(f"peso_{r.id_articolo}", r.peso)) or 0.0
        
        # Se ci sono note, le salviamo per dopo
        if r.note and r.note.strip():
            note_list.append(f"• {r.codice_articolo}: {r.note}")

        data.append([
            Paragraph(str(r.id_articolo), s_small), Paragraph(r.codice_articolo or '', s_small), Paragraph(r.descrizione or '', s_small),
            Paragraph(str(pezzi), s_small), Paragraph(str(colli), s_small), Paragraph(f"{peso:.2f}", s_small), Paragraph(r.n_arrivo or '', s_small)
        ])
        tot_pezzi += pezzi; tot_colli += colli; tot_peso += peso

    story.append(Table(data, colWidths=[12*mm, 35*mm, 80*mm, 10*mm, 12*mm, 18*mm, 23*mm], repeatRows=1, 
                       style=[('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 4)]))
    
    # 5. Sezione Note (FUORI DALLA TABELLA)
    if note_list:
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph("<b>NOTE:</b>", s_bold))
        for nota in note_list:
            story.append(Paragraph(nota, s_note))

    # 6. Totali
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"<b>Totale Pezzi:</b> {tot_pezzi} &nbsp; <b>Colli:</b> {tot_colli} &nbsp; <b>Peso:</b> {tot_peso:.2f} Kg", s_small))
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph("Firma Vettore: _______________________", s_small))

    doc.build(story)
    bio.seek(0)
    return bio
    
@app.route('/buono/finalize_and_get_pdf', methods=['POST'])
@login_required
def buono_finalize_and_get_pdf():
    db = SessionLocal()
    try:
        req_data = request.form
        ids = [int(i) for i in req_data.get('ids','').split(',') if i.isdigit()]
        
        # Ricarichiamo gli articoli dalla sessione attuale per poterli modificare
        rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        
        action = req_data.get('action', 'preview')
        
        raw_buono = req_data.get('buono_n')
        buono_n = raw_buono.strip() if raw_buono and raw_buono.lower() != 'none' else ""

        # AGGIORNA I DATI IN MEMORIA (Note e Buono)
        # Questo serve sia per l'anteprima (vedere le note scritte) che per il salvataggio
        for r in rows:
            # Aggiorna N. Buono
            if buono_n: 
                r.buono_n = buono_n
            
            # Aggiorna Note (dal form)
            note_val = req_data.get(f"note_{r.id_articolo}")
            if note_val is not None:
                r.note = note_val

        # SE AZIONE = SAVE -> SALVA NEL DB
        if action == 'save':
            db.commit()
            flash(f"Buono salvato.", "info")
        
        # Genera PDF usando gli oggetti 'rows' che ora contengono le note aggiornate
        form_data = dict(req_data)
        form_data['buono_n'] = buono_n
        
        pdf_bio = _generate_buono_pdf(form_data, rows)
        
        return send_file(
            pdf_bio, 
            as_attachment=(action == 'save'), 
            download_name=f'Buono_{buono_n}.pdf', 
            mimetype='application/pdf'
        )

    except Exception as e:
        db.rollback()
        # Log dell'errore per debugging
        print(f"ERRORE BUONO: {e}")
        return f"Errore server: {e}", 500
    finally:
        db.close()
@app.post('/pdf/ddt')
@login_required
def pdf_ddt():
    ids = [int(i) for i in request.form.get('ids','').split(',') if i.isdigit()]
    rows = _get_rows_from_ids(ids)
    dest = load_destinatari().get(request.form.get('dest_key'), {})
    pdf_bio = _generate_ddt_pdf(
        n_ddt=request.form.get('n_ddt', ''), data_ddt=request.form.get('data_ddt'), targa=request.form.get('targa'),
        dest=dest, rows=rows, form_data=request.form
    )
    return send_file(pdf_bio, as_attachment=False, download_name='DDT_Anteprima.pdf', mimetype='application/pdf')

@app.post('/ddt/finalize')
@login_required
def ddt_finalize():
    db = SessionLocal()
    try:
        # Recupera dati dal form
        ids = [int(i) for i in request.form.get('ids','').split(',') if i.isdigit()]
        action = request.form.get('action', 'preview')
        
        # Recupera dati testata DDT
        n_ddt = request.form.get('n_ddt', '').strip()
        data_ddt_str = request.form.get('data_ddt', date.today().isoformat())
        try:
            data_ddt = datetime.strptime(data_ddt_str, "%Y-%m-%d").date()
        except:
            data_ddt = date.today()

        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        
        # Aggiorna gli oggetti in memoria con i dati del form (per il PDF)
        # Se è 'finalize', salviamo anche nel DB.
        for art in articoli:
            # 1. Recupera valori modificati dall'utente (Input nel form)
            nuovi_pezzi = to_int_eu(request.form.get(f"pezzi_{art.id_articolo}", art.pezzo))
            nuovi_colli = to_int_eu(request.form.get(f"colli_{art.id_articolo}", art.n_colli))
            nuovo_peso = to_float_eu(request.form.get(f"peso_{art.id_articolo}", art.peso))
            nuove_note = request.form.get(f"note_{art.id_articolo}") # Note editate

            # Aggiorniamo l'oggetto in memoria per il PDF
            art.pezzo = nuovi_pezzi
            art.n_colli = nuovi_colli
            art.peso = nuovo_peso
            if nuove_note is not None:
                art.note = nuove_note

            # 2. SE FINALIZZA: Salviamo nel DB
            if action == 'finalize':
                art.data_uscita = data_ddt.strftime("%d/%m/%Y")
                art.n_ddt_uscita = n_ddt
                # art.stato = 'USCITO'  <-- RIMOSSO: Lo stato non cambia!
        
        if action == 'finalize':
            db.commit()
            flash(f"DDT N.{n_ddt} finalizzato per {len(articoli)} articoli.", "success")
        
        # Generazione PDF
        dest_key = request.form.get('dest_key')
        dest = load_destinatari().get(dest_key, {})
        
        pdf_bio = _generate_ddt_pdf(
            n_ddt=n_ddt, 
            data_ddt=data_ddt, 
            targa=request.form.get('targa'),
            dest=dest, 
            rows=articoli, 
            form_data=request.form
        )
        
        # Nome file
        safe_n_ddt = n_ddt.replace('/', '-')
        filename = f"DDT_{safe_n_ddt}_{data_ddt}.pdf"
        
        # Restituisce il PDF
        # Se anteprima -> inline (browser), Se finalize -> attachment (scarica)
        return send_file(
            pdf_bio, 
            as_attachment=(action == 'finalize'), 
            download_name=filename, 
            mimetype='application/pdf'
        )

    except Exception as e:
        db.rollback()
        # In caso di errore AJAX, Flask restituirà 500, gestito dal JS alert
        raise e
    finally:
        db.close()
@app.get('/labels')
@login_required
def labels_form():
    db = SessionLocal()
    try:
        # Ottieni la lista dei clienti per il menu a tendina
        clienti_query = db.query(Articolo.cliente).distinct().filter(Articolo.cliente != None, Articolo.cliente != '').order_by(Articolo.cliente).all()
        clienti = [c[0] for c in clienti_query]
        return render_template('labels_form.html', clienti=clienti)
    finally:
        db.close()

def _genera_pdf_etichetta(articoli, formato, anteprima=False):
    """Genera il PDF delle etichette."""
    bio = io.BytesIO()
    
    # Formato Etichetta (100x62mm orizzontale)
    if formato == '62x100':
        W, H = 100*mm, 62*mm 
        pagesize = (W, H)
        margin = 2*mm
    else:
        pagesize = A4
        margin = 10*mm

    doc = SimpleDocTemplate(bio, pagesize=pagesize, 
                            leftMargin=margin, rightMargin=margin, 
                            topMargin=margin, bottomMargin=margin)
    story = []
    
    styles = getSampleStyleSheet()
    s_label = ParagraphStyle(name='LabelKey', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=11)
    s_val = ParagraphStyle(name='LabelVal', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=11)

    for art in articoli:
        # Logo
        if LOGO_PATH and Path(LOGO_PATH).exists():
            img = Image(LOGO_PATH, width=35*mm, height=10*mm, hAlign='LEFT')
            story.append(img)
            story.append(Spacer(1, 2*mm))
        
        # Dati etichetta
        dati = [
            [Paragraph("CLIENTE:", s_label), Paragraph(art.cliente or '', s_val)],
            [Paragraph("FORNITORE:", s_label), Paragraph(art.fornitore or '', s_val)],
            [Paragraph("ORDINE:", s_label), Paragraph(art.ordine or '', s_val)],
            [Paragraph("COMMESSA:", s_label), Paragraph(art.commessa or '', s_val)],
            [Paragraph("DDT ING.:", s_label), Paragraph(art.n_ddt_ingresso or '', s_val)],
            [Paragraph("DATA ING.:", s_label), Paragraph(art.data_ingresso or '', s_val)],
            [Paragraph("ARRIVO:", s_label), Paragraph(art.n_arrivo or '', s_val)],
            [Paragraph("COLLI:", s_label), Paragraph(str(art.n_colli or ''), s_val)],
            [Paragraph("POSIZIONE:", s_label), Paragraph(art.posizione or '', s_val)],
        ]
        
        t = Table(dati, colWidths=[25*mm, 68*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(t)
        
        # Salto pagina: fondamentale per etichette singole
        story.append(PageBreak())

    doc.build(story)
    bio.seek(0)
    return bio

@app.route('/labels_pdf', methods=['POST'])
@login_required
def labels_pdf():
    # Recupera tutti i dati dal form
    form_data = request.form
    cliente = form_data.get('cliente')
    formato = form_data.get('formato', '62x100')
    anteprima = form_data.get('anteprima') == 'on'

    # Verifica se è una stampa manuale (controlliamo se ci sono dati specifici)
    # Se c'è almeno un campo compilato tra ordine, commessa o fornitore, è manuale.
    is_manual = any(form_data.get(k) for k in ['ordine', 'commessa', 'fornitore', 'n_ddt_ingresso', 'n_arrivo'])

    articoli = []
    
    if is_manual:
        # --- STAMPA MANUALE: Crea un oggetto Articolo "volante" con i dati del form ---
        # Non lo salviamo nel DB, serve solo per il PDF
        art_temp = Articolo()
        art_temp.cliente = cliente
        art_temp.fornitore = form_data.get('fornitore')
        art_temp.ordine = form_data.get('ordine')
        art_temp.commessa = form_data.get('commessa')
        art_temp.n_ddt_ingresso = form_data.get('n_ddt_ingresso') # O ddt_ingresso se il name html è diverso
        art_temp.data_ingresso = form_data.get('data_ingresso')
        art_temp.n_arrivo = form_data.get('n_arrivo') # O arrivo
        art_temp.n_colli = form_data.get('n_colli')
        art_temp.posizione = form_data.get('posizione')
        
        articoli = [art_temp]
    
    else:
        # --- STAMPA MASSIVA: Prendi dal DB ---
        db = SessionLocal()
        try:
            # Se ci sono ID selezionati (es. da check in giacenze)
            ids = request.form.getlist('ids')
            if ids:
                articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            elif cliente:
                articoli = db.query(Articolo).filter(Articolo.cliente == cliente).all()
        finally:
            db.close()

    if not articoli:
        flash("Nessun dato trovato per la stampa.", "warning")
        return redirect(request.referrer or url_for('home'))

    try:
        # Genera il PDF usando la funzione helper
        pdf_bio = _genera_pdf_etichetta(articoli, formato, anteprima)

        filename = f"Etichetta_{cliente or 'Manuale'}.pdf"
        
        # Se è manuale o anteprima, mostralo nel browser (inline), altrimenti scarica
        as_attachment = False if (anteprima or is_manual) else True

        return send_file(
            pdf_bio, 
            as_attachment=as_attachment, 
            download_name=filename, 
            mimetype='application/pdf'
        )
            
    except Exception as e:
        flash(f"Errore generazione etichette: {e}", "danger")
        return redirect(request.referrer or url_for('home'))

# --- FIX DATABASE SCHEMA (Esegui all'avvio per correggere tipi colonne) ---
def fix_db_schema():
    """
    Corregge i tipi di colonna nel database PostgreSQL per evitare errori di lunghezza.
    Converte le colonne critiche da VARCHAR(255) a TEXT.
    """
    try:
        from sqlalchemy import text
        db = SessionLocal()
        # Elenco delle colonne che potrebbero contenere testi lunghi
        cols_to_fix = [
            'codice_articolo', 'descrizione', 'note', 'commessa', 
            'ordine', 'protocollo', 'buono_n', 'n_arrivo', 
            'n_ddt_ingresso', 'n_ddt_uscita', 'cliente', 'fornitore'
        ]
        
        for col in cols_to_fix:
            try:
                # Comando SQL per convertire la colonna in TEXT (senza limiti)
                # "TYPE TEXT" è lo standard Postgres per stringhe di lunghezza arbitraria
                # "USING ...::text" serve per castare i dati esistenti
                query = text(f"ALTER TABLE articoli ALTER COLUMN {col} TYPE TEXT USING {col}::text;")
                db.execute(query)
            except Exception as e:
                # Se la colonna non esiste o c'è un altro errore, lo ignoriamo e passiamo alla prossima
                print(f"⚠️ Warning fix colonna {col}: {e}")
        
        db.commit()
        print("✅ SCHEMA DB AGGIORNATO: Colonne di testo convertite in TEXT (no limiti lunghezza).")
    except Exception as e:
        print(f"⚠️ Errore generale durante il fix dello schema: {e}")
    finally:
        db.close()

# Esegui il fix immediatamente quando il file viene importato/avviato
fix_db_schema()

# --- AVVIO FLASK APP ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
