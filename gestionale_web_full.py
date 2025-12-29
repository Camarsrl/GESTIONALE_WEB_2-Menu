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
import smtplib
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict
from functools import wraps

# Importazioni Flask e Login
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify, render_template_string, abort
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Importazioni Database (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, ForeignKey, or_, Identity, Boolean, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session, selectinload
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError

# --- IMPORTAZIONI PDF (ReportLab) ---
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

# --- IMPORTAZIONI EMAIL ---
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Jinja loader
from jinja2 import DictLoader

# ========================================================
# 1. INIZIALIZZAZIONE APP E LOGIN MANAGER (ORDINE CORRETTO)
# ========================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chiave_segreta_super_sicura")

# Inizializza LoginManager SUBITO
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ========================================================
# 2. CONFIGURAZIONE PATH E FILES
# ========================================================
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = APP_DIR / "static"
MEDIA_DIR = APP_DIR / "media"
DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"

# Crea cartelle se non esistono
for d in (STATIC_DIR, MEDIA_DIR, DOCS_DIR, PHOTOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

def _discover_logo_path():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo camar.jpg", "logo_camar.png"):
        p = STATIC_DIR / name
        if p.exists(): return str(p)
    return None

LOGO_PATH = _discover_logo_path()

# ========================================================
# 3. CONFIGURAZIONE DATABASE
# ========================================================
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    DB_URL = f"sqlite:///{APP_DIR / 'magazzino.db'}"
else:
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

def _normalize_db_url(u: str) -> str:
    if u.startswith("mysql://"): u = "mysql+pymysql://" + u[len("mysql://"):]
    return u

engine = create_engine(_normalize_db_url(DB_URL), future=True, echo=False)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

# ========================================================
# 4. DEFINIZIONE MODELLI
# ========================================================
class Articolo(Base):
    __tablename__ = "articoli"
    id_articolo = Column(Integer, Identity(start=1), primary_key=True)
    codice_articolo = Column(Text); descrizione = Column(Text)
    cliente = Column(Text); fornitore = Column(Text); magazzino = Column(String(255))
    protocollo = Column(Text); ordine = Column(Text); commessa = Column(Text)
    buono_n = Column(Text); n_arrivo = Column(Text); ns_rif = Column(String(255))
    serial_number = Column(String(255)); pezzo = Column(String(255))
    n_colli = Column(Integer); peso = Column(Float)
    larghezza = Column(Float); lunghezza = Column(Float); altezza = Column(Float)
    m2 = Column(Float); m3 = Column(Float); posizione = Column(String(255))
    stato = Column(String(255)); note = Column(Text); mezzi_in_uscita = Column(String(255))
    data_ingresso = Column(String(32)); n_ddt_ingresso = Column(Text)
    data_uscita = Column(String(32)); n_ddt_uscita = Column(Text)
    attachments = relationship("Attachment", back_populates="articolo", cascade="all, delete-orphan", passive_deletes=True)

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, Identity(start=1), primary_key=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo", ondelete='CASCADE'), nullable=False)
    kind = Column(String(10)); filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)

# ========================================================
# 5. GESTIONE UTENTI (Definizione PRIMA dell'uso)
# ========================================================
DEFAULT_USERS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'MARINE INTERIORS': 'Struppa09', 'OPS': '271214',
    'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02', 'DIEGO': 'Balleydier03', 'ADMIN': 'admin123'
}
ADMIN_USERS = {'ADMIN', 'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO'}

def get_users():
    """Legge utenti dal file txt o usa i default."""
    try:
        fp = APP_DIR / "password Utenti Gestionale.txt"
        if fp.exists():
            content = fp.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(r"'([^']+)'\s*[:=]\s*'?([^']+)'?", content)
            if pairs:
                return {k.strip().upper(): v.strip().replace("'", "") for k, v in pairs}
    except Exception as e:
        print(f"Errore lettura file utenti: {e}")
    return DEFAULT_USERS

# ORA possiamo chiamarla, perché è stata definita sopra
USERS_DB = get_users()

class User(UserMixin):
    def __init__(self, id, role):
        self.id = id; self.role = role

@login_manager.user_loader
def load_user(user_id):
    users_db = get_users() 
    if user_id in users_db:
        role = 'admin' if user_id in ADMIN_USERS else 'client'
        return User(user_id, role)
    return None

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
                <a class="btn btn-success" href="{{ url_for('nuovo_articolo') }}"><i class="bi bi-plus-circle"></i> Nuovo Articolo</a>
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
CALCOLI_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container-fluid">
    <h3><i class="bi bi-calculator"></i> Report Costi Magazzino (M² per cliente)</h3>
    
    <div class="card mb-4" style="background-color: #f0f0f0; border: 1px solid #ccc;">
        <div class="card-body py-3">
            <form method="POST">
                <div class="row g-3 align-items-center">
                    
                    <div class="col-auto">
                        <label class="fw-bold">Data da:</label>
                    </div>
                    <div class="col-auto">
                        <input type="date" name="data_da" class="form-control form-control-sm" required value="{{ data_da }}">
                    </div>
                    
                    <div class="col-auto">
                        <label class="fw-bold">Data a:</label>
                    </div>
                    <div class="col-auto">
                        <input type="date" name="data_a" class="form-control form-control-sm" required value="{{ data_a }}">
                    </div>

                    <div class="col-auto ms-4">
                        <label class="fw-bold">Cliente (contiene):</label>
                    </div>
                    <div class="col-auto">
                        <input type="text" name="cliente" class="form-control form-control-sm" value="{{ cliente_filtro }}">
                    </div>

                    <div class="col-auto ms-4">
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="raggruppamento" value="mese" id="rmese" {% if raggruppamento=='mese' %}checked{% endif %}>
                            <label class="form-check-label" for="rmese">Per mese</label>
                        </div>
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="raggruppamento" value="giorno" id="rgiorno" {% if raggruppamento=='giorno' %}checked{% endif %}>
                            <label class="form-check-label" for="rgiorno">Per giorno</label>
                        </div>
                    </div>

                    <div class="col-auto ms-auto">
                        <button type="submit" class="btn btn-secondary border-dark px-4" style="background-color: #e0e0e0; color: black;">Calcola</button>
                    </div>
                </div>
            </form>
        </div>
    </div>

    {% if risultati %}
    <div class="table-responsive bg-white border">
        <table class="table table-bordered table-striped table-hover table-sm mb-0">
            <thead class="table-light">
                <tr class="text-center align-middle">
                    <th>Mese/Giorno</th>
                    <th>Cliente</th>
                    <th>M² * giorni</th>
                    <th>M² medio</th>
                    <th>Giorni</th>
                </tr>
            </thead>
            <tbody>
                {% for row in risultati %}
                <tr>
                    <td class="text-center">{{ row.periodo }}</td>
                    <td>{{ row.cliente }}</td>
                    <td class="text-end">{{ row.m2_tot }}</td>
                    <td class="text-end fw-bold">{{ row.m2_medio }}</td>
                    <td class="text-center">{{ row.giorni }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% elif request.method == 'POST' %}
    <div class="alert alert-warning">Nessun dato trovato per i criteri selezionati.</div>
    {% endif %}
</div>
{% endblock %}
"""

GIACENZE_HTML = """
{% extends 'base.html' %}
{% block content %}
<style>
    /* Stile Tabella Compatto e Leggibile */
    .table-compact td, .table-compact th { 
        font-size: 0.8rem !important; 
        padding: 4px 5px !important; 
        vertical-align: middle; 
        white-space: nowrap; /* Testo su una riga */
        overflow: hidden; 
        text-overflow: ellipsis; /* Puntini se troppo lungo */
        max-width: 150px; /* Larghezza massima celle */
    }
    .table-compact th { 
        font-weight: 600 !important; 
        background-color: #f0f0f0; 
        text-align: center;
    }
    .fw-buono { font-weight: bold !important; color: #000000; }
    /* Hover per leggere tutto il testo */
    .table-compact td:hover { 
        white-space: normal; 
        overflow: visible; 
        position: relative; 
        background-color: #fff; 
        z-index: 10;
    }
</style>

<div class="d-flex justify-content-between align-items-center mb-2">
    <h4>Magazzino</h4>
    <div class="d-flex gap-2">
       <a href="{{ url_for('nuovo_articolo') }}" class="btn btn-sm btn-success"><i class="bi bi-plus-lg"></i> Nuovo</a>
       <a href="{{ url_for('labels_form') }}" class="btn btn-sm btn-info text-white"><i class="bi bi-tags"></i> Etichette</a>
       <a href="{{ url_for('calcola_costi') }}" class="btn btn-sm btn-warning"><i class="bi bi-calculator"></i> Calcoli</a>
    </div>
</div>

<div class="card mb-2">
    <div class="card-header py-1 bg-light" data-bs-toggle="collapse" data-bs-target="#filterBody" style="cursor:pointer">
        <small><i class="bi bi-funnel"></i> <b>Filtri Avanzati</b></small>
    </div>
    <div id="filterBody" class="collapse {% if request.args %}show{% endif %}">
        <div class="card-body py-2 bg-white">
            <form method="get">
                <div class="row g-2 mb-2">
                    <div class="col-md-2"><input name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ request.args.get('cliente','') }}"></div>
                    <div class="col-md-2"><input name="commessa" class="form-control form-control-sm" placeholder="Commessa" value="{{ request.args.get('commessa','') }}"></div>
                    <div class="col-md-2"><input name="buono_n" class="form-control form-control-sm" placeholder="Buono N" value="{{ request.args.get('buono_n','') }}"></div>
                    <div class="col-md-2"><input name="descrizione" class="form-control form-control-sm" placeholder="Descrizione" value="{{ request.args.get('descrizione','') }}"></div>
                    <div class="col-md-2"><button type="submit" class="btn btn-primary btn-sm w-100">Cerca</button></div>
                    <div class="col-md-1"><a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm w-100">Reset</a></div>
                </div>
            </form>
        </div>
    </div>
</div>

<form method="POST">
    <div class="btn-toolbar mb-2 gap-1">
        <button type="submit" formaction="{{ url_for('buono_preview') }}" class="btn btn-outline-dark btn-sm">Buono</button>
        <button type="submit" formaction="{{ url_for('ddt_preview') }}" class="btn btn-outline-dark btn-sm">DDT</button>
        <button type="submit" formaction="{{ url_for('bulk_edit') }}" class="btn btn-info btn-sm text-white">Mod. Multipla</button>
        <button type="submit" formaction="{{ url_for('bulk_duplicate') }}" class="btn btn-outline-secondary btn-sm">Duplica</button>
        <button type="submit" formaction="{{ url_for('delete_rows') }}" class="btn btn-danger btn-sm" onclick="return confirm('Eliminare?')">Elimina</button>
    </div>

    <div class="table-responsive" style="max-height: 70vh;">
        <table class="table table-striped table-bordered table-hover table-compact mb-0">
            <thead class="sticky-top" style="top: 0; z-index: 5;">
                <tr>
                    <th><input type="checkbox" onclick="toggleAll(this)"></th>
                    <th>ID</th>
                    <th>Codice</th>
                    <th>Descrizione</th>
                    <th>Cliente</th>
                    <th>Fornitore</th>
                    <th>Commessa</th>
                    <th>Ordine</th>
                    <th>Protocollo</th>
                    <th>Buono</th>
                    <th>N.Arr</th>
                    <th>Data Ing.</th>
                    <th>DDT Ing.</th>
                    <th>Pos</th>
                    <th>Stato</th>
                    <th>Pz</th>
                    <th>Colli</th>
                    <th>Kg</th>
                    <th>LxPxH</th>
                    <th>M²</th>
                    <th>M³</th>
                    <th>Note</th>
                    <th>Azioni</th>
                </tr>
            </thead>
            <tbody>
                {% for r in rows %}
                <tr>
                    <td class="text-center"><input type="checkbox" name="ids" value="{{ r.id_articolo }}"></td>
                    <td>{{ r.id_articolo }}</td>
                    <td title="{{ r.codice_articolo }}">{{ r.codice_articolo or '' }}</td>
                    <td title="{{ r.descrizione }}">{{ r.descrizione or '' }}</td>
                    <td title="{{ r.cliente }}">{{ r.cliente or '' }}</td>
                    <td title="{{ r.fornitore }}">{{ r.fornitore or '' }}</td>
                    <td>{{ r.commessa or '' }}</td>
                    <td>{{ r.ordine or '' }}</td>
                    <td>{{ r.protocollo or '' }}</td>
                    <td class="fw-buono">{{ r.buono_n or '' }}</td>
                    <td>{{ r.n_arrivo or '' }}</td>
                    <td>{{ r.data_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_ingresso or '' }}</td>
                    <td>{{ r.posizione or '' }}</td>
                    <td>{{ r.stato or '' }}</td>
                    <td class="text-end">{{ r.pezzo or '' }}</td>
                    <td class="text-end">{{ r.n_colli or '' }}</td>
                    <td class="text-end">{{ r.peso or '' }}</td>
                    <td>{{ r.lunghezza|int }}x{{ r.larghezza|int }}x{{ r.altezza|int }}</td>
                    <td class="text-end">{{ r.m2 or '' }}</td>
                    <td class="text-end">{{ r.m3 or '' }}</td>
                    <td title="{{ r.note }}">{{ r.note or '' }}</td>
                    <td class="text-center">
                        <a href="{{ url_for('edit_record', id_articolo=r.id_articolo) }}" class="btn btn-sm btn-link p-0 text-decoration-none">✏️</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot class="sticky-bottom bg-white fw-bold">
                <tr>
                    <td colspan="23" class="py-2 px-3">
                        Totali: Colli {{ total_colli }} | M² {{ total_m2 }} | Peso {{ total_peso }}
                    </td>
                </tr>
            </tfoot>
        </table>
    </div>
</form>
<script>function toggleAll(s){ document.getElementsByName('ids').forEach(c => c.checked = s.checked); }</script>
{% endblock %}
"""
EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3><i class="bi bi-pencil-square"></i> {% if row %}Modifica Articolo #{{ row.id_articolo }}{% else %}Nuovo Articolo{% endif %}</h3>
    <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Torna alla Lista</a>
</div>

<form method="post" class="card p-4 shadow-sm">
    <div class="row g-3">
        <div class="col-md-3">
            <label class="form-label fw-bold">Codice Articolo</label>
            <input type="text" name="codice_articolo" class="form-control" value="{{ row.codice_articolo or '' }}">
        </div>
        <div class="col-md-5">
            <label class="form-label fw-bold">Descrizione</label>
            <input type="text" name="descrizione" class="form-control" value="{{ row.descrizione or '' }}">
        </div>
        <div class="col-md-2">
            <label class="form-label">Stato</label>
            <select name="stato" class="form-select">
                <option value="DOGANALE" {% if row.stato == 'DOGANALE' %}selected{% endif %}>DOGANALE</option>
                <option value="NAZIONALE" {% if row.stato == 'NAZIONALE' %}selected{% endif %}>NAZIONALE</option>
                <option value="USCITO" {% if row.stato == 'USCITO' %}selected{% endif %}>USCITO</option>
            </select>
        </div>
        <div class="col-md-2">
            <label class="form-label">Commessa</label>
            <input type="text" name="commessa" class="form-control" value="{{ row.commessa or '' }}">
        </div>

        <div class="col-md-4">
            <label class="form-label">Cliente</label>
            <input type="text" name="cliente" class="form-control" value="{{ row.cliente or '' }}">
        </div>
        <div class="col-md-4">
            <label class="form-label">Fornitore</label>
            <input type="text" name="fornitore" class="form-control" value="{{ row.fornitore or '' }}">
        </div>
        <div class="col-md-4">
            <label class="form-label">Protocollo</label>
            <input type="text" name="protocollo" class="form-control" value="{{ row.protocollo or '' }}">
        </div>

        <div class="col-md-3">
            <label class="form-label">N. Buono</label>
            <input type="text" name="buono_n" class="form-control" value="{{ row.buono_n or '' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Magazzino</label>
            <input type="text" name="magazzino" class="form-control" value="{{ row.magazzino or 'STRUPPA' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Posizione</label>
            <input type="text" name="posizione" class="form-control" value="{{ row.posizione or '' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Ordine</label>
            <input type="text" name="ordine" class="form-control" value="{{ row.ordine or '' }}">
        </div>

        <div class="col-md-3">
            <label class="form-label">Data Ingresso</label>
            <input type="date" name="data_ingresso" class="form-control" value="{{ row.data_ingresso or '' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">DDT Ingresso</label>
            <input type="text" name="n_ddt_ingresso" class="form-control" value="{{ row.n_ddt_ingresso or '' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">Data Uscita</label>
            <input type="date" name="data_uscita" class="form-control" value="{{ row.data_uscita or '' }}">
        </div>
        <div class="col-md-3">
            <label class="form-label">DDT Uscita</label>
            <input type="text" name="n_ddt_uscita" class="form-control" value="{{ row.n_ddt_uscita or '' }}">
        </div>

        <div class="col-md-2">
            <label class="form-label">Pezzi</label>
            <input type="number" name="pezzo" class="form-control" value="{{ row.pezzo or 0 }}">
        </div>
        <div class="col-md-2">
            <label class="form-label">Colli</label>
            <input type="number" name="n_colli" class="form-control" value="{{ row.n_colli or 0 }}">
        </div>
        <div class="col-md-2">
            <label class="form-label">Peso (Kg)</label>
            <input type="number" step="0.01" name="peso" class="form-control" value="{{ row.peso or 0 }}">
        </div>
        <div class="col-md-2">
            <label class="form-label">M³</label>
            <input type="number" step="0.001" name="m3" class="form-control" value="{{ row.m3 or 0 }}">
        </div>
        <div class="col-md-2">
            <label class="form-label">N. Arrivo</label>
            <input type="text" name="n_arrivo" class="form-control" value="{{ row.n_arrivo or '' }}">
        </div>
        
        <div class="col-md-4">
            <label class="form-label">Dimensioni (LxWxH)</label>
            <div class="input-group">
                <input type="number" step="0.01" name="lunghezza" class="form-control" placeholder="L" value="{{ row.lunghezza or '' }}">
                <span class="input-group-text">x</span>
                <input type="number" step="0.01" name="larghezza" class="form-control" placeholder="W" value="{{ row.larghezza or '' }}">
                <span class="input-group-text">x</span>
                <input type="number" step="0.01" name="altezza" class="form-control" placeholder="H" value="{{ row.altezza or '' }}">
            </div>
        </div>
        <div class="col-md-4">
            <label class="form-label">Serial Number</label>
            <input type="text" name="serial_number" class="form-control" value="{{ row.serial_number or '' }}">
        </div>
        <div class="col-md-4">
            <label class="form-label">Mezzi in Uscita</label>
            <input type="text" name="mezzi_in_uscita" class="form-control" value="{{ row.mezzi_in_uscita or '' }}">
        </div>

        <div class="col-12">
            <label class="form-label">Note</label>
            <textarea name="note" class="form-control" rows="3">{{ row.note or '' }}</textarea>
        </div>
    </div>

    <div class="mt-4 text-end">
        <button type="submit" class="btn btn-primary px-5"><i class="bi bi-save"></i> Salva Modifiche</button>
    </div>
</form>

{% if row and row.id_articolo %}
<div class="card mt-4 p-4 shadow-sm">
    <h5><i class="bi bi-paperclip"></i> Allegati</h5>
    <hr>
    <form action="{{ url_for('upload_file', id_articolo=row.id_articolo) }}" method="post" enctype="multipart/form-data" class="mb-3">
        <div class="input-group">
            <input type="file" name="file" class="form-control" required>
            <button type="submit" class="btn btn-outline-primary">Carica</button>
        </div>
    </form>
    <div class="row">
        {% for att in row.attachments %}
        <div class="col-md-3 mb-3">
            <div class="card h-100">
                <div class="card-body text-center p-2">
                    <p class="small text-truncate mb-2" title="{{ att.filename }}">{{ att.filename }}</p>
                    <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank" class="btn btn-sm btn-primary">Apri</a>
                    <a href="{{ url_for('delete_file', id_file=att.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Eliminare?')">Elimina</a>
                </div>
            </div>
        </div>
        {% else %}
        <p class="text-muted small">Nessun allegato.</p>
        {% endfor %}
    </div>
</div>
{% endif %}
{% endblock %}
"""
BULK_EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h5>Modifica Multipla</h5>
    <form method="post">
        <input type="hidden" name="ids" value="{{ ids_csv }}">
        <input type="hidden" name="save_bulk" value="true">
        <div class="row g-2">
            {% for label, name in fields %}
            <div class="col-md-3">
                <div class="input-group input-group-sm">
                    <div class="input-group-text">
                        <input class="form-check-input mt-0" type="checkbox" name="chk_{{ name }}" 
                               onclick="document.getElementById('in_{{ name }}').disabled = !this.checked">
                    </div>
                    <input type="text" id="in_{{ name }}" name="{{ name }}" class="form-control" 
                           placeholder="{{ label }}" disabled>
                </div>
            </div>
            {% endfor %}
        </div>
        <div class="mt-3 text-end">
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary btn-sm">Annulla</a>
            <button type="submit" class="btn btn-primary btn-sm">Applica Modifiche</button>
        </div>
    </form>
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
        <input type="hidden" name="action" id="action_field" value="preview">

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
    // Imposta il valore nel campo hidden
    document.getElementById('action_field').value = actionType;

    if (actionType === 'preview') {
        form.target = '_blank';
        form.submit();
    } else {
        form.target = '_self';
        const formData = new FormData(form);
        // FIX: Usa getAttribute per evitare il conflitto con l'input name="action"
        const url = form.getAttribute('action'); 
        
        fetch(url, { method: 'POST', body: formData })
        .then(resp => {
            if (resp.ok) return resp.blob();
            throw new Error('Errore salvataggio');
        })
        .then(blob => {
            const urlBlob = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = urlBlob;
            a.download = 'Buono_Prelievo.pdf';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(urlBlob);
            // Redirect dopo 1 secondo
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
                <i class="bi bi-printer"></i> Anteprima PDF
            </button>
            <button type="button" class="btn btn-success" onclick="submitDdt('finalize')">
                <i class="bi bi-check-circle-fill"></i> Finalizza e Scarica
            </button>
            <a href="{{ url_for('invia_email', ids=ids) }}" class="btn btn-warning">
                <i class="bi bi-envelope"></i> Invia Email
            </a>
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
        </div>
    </div>

    <form id="ddt-form" method="POST" action="{{ url_for('ddt_finalize') }}">
        <input type="hidden" name="ids" value="{{ ids }}">
        <input type="hidden" name="action" id="action_field" value="preview">
        
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
                    <button class="btn btn-outline-secondary" type="button" id="get-next-ddt" title="Nuovo Numero"><i class="bi bi-arrow-clockwise"></i></button>
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
                        <th>ID</th> <th>Cod.Art.</th> <th>Descrizione</th>
                        <th style="width: 250px;">Note (Editabili)</th>
                        <th style="width: 70px;">Pezzi</th> <th style="width: 70px;">Colli</th> <th style="width: 80px;">Peso</th>
                        <th>N.Arrivo</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.id_articolo }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
                        <td><textarea class="form-control form-control-sm" name="note_{{ r.id_articolo }}" rows="1">{{ r.note or '' }}</textarea></td>
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
document.getElementById('get-next-ddt').addEventListener('click', function() {
    fetch('{{ url_for('get_next_ddt_number') }}').then(r => r.json()).then(d => { document.getElementById('n_ddt_input').value = d.next_ddt; });
});

function submitDdt(actionType) {
    const form = document.getElementById('ddt-form');
    document.getElementById('action_field').value = actionType;

    if (actionType === 'preview') {
        form.target = '_blank';
        form.submit();
    } else {
        form.target = '_self';
        const formData = new FormData(form);
        const url = form.getAttribute('action'); // FIX JS
        
        fetch(url, { method: 'POST', body: formData })
        .then(resp => {
            if (resp.ok) return resp.blob();
            throw new Error('Errore finalizzazione');
        })
        .then(blob => {
            const urlBlob = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = urlBlob;
            a.download = 'DDT_Finale.pdf';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(urlBlob);
            setTimeout(() => { window.location.href = '{{ url_for("giacenze") }}'; }, 1500);
        })
        .catch(err => alert("Errore: " + err));
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
        <div class="card p-4 shadow">
            <h4 class="mb-3"><i class="bi bi-envelope"></i> Invia Email con Allegati</h4>
            
            {% if selected_ids %}
            <div class="alert alert-info py-2">
                <i class="bi bi-info-circle"></i> Hai selezionato <strong>{{ selected_ids.split(',')|length }}</strong> articoli. 
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

                <div class="card bg-light mb-3">
                    <div class="card-body">
                        <h6 class="card-title">Opzioni Allegati</h6>
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" name="genera_ddt" id="genera_ddt" checked>
                            <label class="form-check-label" for="genera_ddt">Genera e allega Riepilogo/DDT PDF</label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" name="allega_file" id="allega_file" checked>
                            <label class="form-check-label" for="allega_file">Includi allegati esistenti (Foto/PDF degli articoli)</label>
                        </div>
                        
                        <label class="form-label mt-2"><strong>Aggiungi altro allegato (dal PC):</strong></label>
                        <input type="file" name="allegati_extra" class="form-control" multiple>
                    </div>
                </div>

                <div class="d-flex justify-content-between">
                    <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
                    <button type="submit" class="btn btn-primary px-4"><i class="bi bi-send"></i> Invia Email</button>
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
    'calcoli.html': CALCOLI_HTML  
}

# ========================================================
# CONFIGURAZIONE FINALE (SENZA RICREARE L'APP)
# ========================================================
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
        # Supporta sia 'username' che 'user' come nomi campo nel form
        username = (request.form.get('username') or request.form.get('user') or '').strip().upper()
        password = (request.form.get('password') or request.form.get('pwd') or '').strip()
        
        users_db = get_users()
        
        if username in users_db and users_db[username] == password:
            # 1. Crea l'oggetto utente
            role = 'admin' if username in ADMIN_USERS else 'client'
            user = User(username, role)
            
            # 2. PUNTO FONDAMENTALE: Effettua il login formale con Flask-Login
            login_user(user)
            
            # 3. Imposta variabili di sessione accessorie
            session['role'] = role
            session['user_name'] = username
            
            flash(f"Benvenuto {username}", "success")
            
            # 4. Reindirizza alla pagina richiesta o alle giacenze
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('giacenze')
            return redirect(next_page)
        else:
            flash("Credenziali non valide", "danger")
            
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


@app.route('/invia_email', methods=['GET', 'POST'])
@login_required
def invia_email():
    if request.method == 'GET':
        selected_ids = request.args.getlist('ids')
        ids_str = ",".join(selected_ids)
        return render_template('invia_email.html', selected_ids=ids_str)

    # POST: Invio
    selected_ids = request.form.get('selected_ids', '')
    destinatario = request.form.get('destinatario')
    oggetto = request.form.get('oggetto')
    messaggio = request.form.get('messaggio')
    genera_ddt = 'genera_ddt' in request.form
    allega_file = 'allega_file' in request.form
    
    # Allegati dal PC
    allegati_extra = request.files.getlist('allegati_extra')

    ids_list = [int(i) for i in selected_ids.split(',') if i.isdigit()]
    
    # SMTP
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")

    if not SMTP_USER or not SMTP_PASS:
        flash("Configurazione email mancante.", "warning")
        return redirect(url_for('giacenze'))

    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = destinatario
        msg['Subject'] = oggetto
        msg.attach(MIMEText(messaggio, 'plain'))

        # 1. PDF DDT
        if genera_ddt and ids_list:
            db = SessionLocal()
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
            if rows:
                dest_data = {"ragione_sociale": rows[0].cliente or "Cliente", "indirizzo": ""}
                pdf_bio = _generate_ddt_pdf("RIEPILOGO", date.today(), "", dest_data, rows, {})
                part = MIMEBase('application', "octet-stream")
                part.set_payload(pdf_bio.getvalue())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment; filename="Riepilogo_Merce.pdf"')
                msg.attach(part)
            db.close()

        # 2. Allegati DB
        if allega_file and ids_list:
            db = SessionLocal()
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
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

        # 3. Allegati Extra (Dal PC)
        for file in allegati_extra:
            if file and file.filename:
                part = MIMEBase('application', "octet-stream")
                part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{file.filename}"')
                msg.attach(part)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()

        flash(f"Email inviata a {destinatario}", "success")
    except Exception as e:
        flash(f"Errore invio: {e}", "danger")

    return redirect(url_for('giacenze'))
    
# --- GESTIONE ARTICOLI (CRUD) ---
# ========================================================
# 8. CRUD (NUOVO / MODIFICA)
# ========================================================

@app.route('/new', methods=['GET', 'POST'])
@login_required
def nuovo_articolo():
    db = SessionLocal()
    try:
        art = Articolo()
        art.data_ingresso = date.today().strftime("%d/%m/%Y")
        art.stato = "DOGANALE"
        
        db.add(art)
        db.commit()
        db.refresh(art) # Importante: ottiene l'ID dal DB
        
        new_id = art.id_articolo
        db.close()
        
        # Redirect esplicito alla pagina di modifica
        return redirect(url_for('edit_record', id_articolo=new_id))
    except Exception as e:
        db.rollback()
        flash(f"Errore creazione riga: {e}", "danger")
        return redirect(url_for('giacenze'))
        
@app.route('/edit/<int:id_articolo>', methods=['GET', 'POST'])
@login_required
def edit_record(id_articolo):
    """Pagina per modificare un singolo articolo."""
    db = SessionLocal()
    try:
        art = db.query(Articolo).filter(Articolo.id_articolo == id_articolo).first()
        if not art:
            flash("Articolo non trovato", "danger")
            return redirect(url_for('giacenze'))

        if request.method == 'POST':
            # Controllo permessi cliente
            if session.get('role') == 'client':
                flash("Accesso negato: i clienti non possono modificare.", "danger")
                return redirect(url_for('giacenze'))

            # Aggiornamento campi testuali
            art.codice_articolo = request.form.get('codice_articolo')
            art.descrizione = request.form.get('descrizione')
            art.cliente = request.form.get('cliente')
            art.fornitore = request.form.get('fornitore')
            art.commessa = request.form.get('commessa')
            art.protocollo = request.form.get('protocollo')
            art.buono_n = request.form.get('buono_n')
            art.note = request.form.get('note')
            art.stato = request.form.get('stato')
            art.magazzino = request.form.get('magazzino')
            art.posizione = request.form.get('posizione')
            art.ordine = request.form.get('ordine')
            art.n_arrivo = request.form.get('n_arrivo')
            art.serial_number = request.form.get('serial_number')
            art.ns_rif = request.form.get('ns_rif')
            art.mezzi_in_uscita = request.form.get('mezzi_in_uscita')
            
            # Gestione Date (se vuote mette None)
            d_in = request.form.get('data_ingresso')
            art.data_ingresso = parse_date_ui(d_in) if d_in else None
            
            d_out = request.form.get('data_uscita')
            art.data_uscita = parse_date_ui(d_out) if d_out else None
            
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')
            
            # Gestione Numerici
            art.pezzo = request.form.get('pezzo')
            art.n_colli = to_int_eu(request.form.get('n_colli'))
            art.peso = to_float_eu(request.form.get('peso'))
            art.lunghezza = to_float_eu(request.form.get('lunghezza'))
            art.larghezza = to_float_eu(request.form.get('larghezza'))
            art.altezza = to_float_eu(request.form.get('altezza'))
            
            # Ricalcolo automatico M2/M3
            m2, m3 = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, art.n_colli)
            art.m2 = m2
            art.m3 = m3

            db.commit()
            flash("Modifiche salvate con successo.", "success")
            return redirect(url_for('giacenze'))

        return render_template('edit.html', row=art)
    except Exception as e:
        db.rollback()
        flash(f"Errore salvataggio: {e}", "danger")
        return redirect(url_for('giacenze'))
    finally:
        db.close()
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


@app.route('/giacenze', methods=['GET', 'POST'])
@login_required
def giacenze():
    db = SessionLocal()
    try:
        q = db.query(Articolo).options(selectinload(Articolo.attachments)).order_by(Articolo.id_articolo.desc())
        
        # Filtro Ruolo Cliente
        if session.get('role') == 'client':
            q = q.filter(Articolo.cliente.ilike(f"%{current_user.id}%"))
        
        args = request.args
        
        # Filtro ID specifico
        if args.get('id'):
            try: q = q.filter(Articolo.id_articolo == int(args.get('id')))
            except: pass

        # Lista completa dei campi di testo da filtrare
        text_filters = [
            'cliente', 'fornitore', 'commessa', 'ordine', 'protocollo', 
            'serial_number', 'codice_articolo', 'magazzino', 'stato', 
            'buono_n', 'descrizione', 'mezzi_in_uscita', 
            'n_ddt_ingresso', 'n_ddt_uscita'
        ]
        
        for f in text_filters:
            val = args.get(f)
            if val: q = q.filter(getattr(Articolo, f).ilike(f"%{val}%"))

        # Recupero dati per filtro date in memoria (sicurezza formati misti)
        all_rows = q.all()
        rows = []
        
        # Parsing date dai filtri
        d_ing_da = parse_date_ui(args.get('data_ing_da'))
        d_ing_a = parse_date_ui(args.get('data_ing_a'))
        d_usc_da = parse_date_ui(args.get('data_usc_da'))
        d_usc_a = parse_date_ui(args.get('data_usc_a'))

        for r in all_rows:
            keep = True
            
            # Filtro Data Ingresso
            if d_ing_da or d_ing_a:
                ri = parse_date_ui(r.data_ingresso)
                if not ri: keep = False # Se filtro per data ma data manca, escludo
                elif d_ing_da and ri < d_ing_da: keep = False
                elif d_ing_a and ri > d_ing_a: keep = False
            
            # Filtro Data Uscita
            if keep and (d_usc_da or d_usc_a):
                ru = parse_date_ui(r.data_uscita)
                if not ru: keep = False
                elif d_usc_da and ru < d_usc_da: keep = False
                elif d_usc_a and ru > d_usc_a: keep = False
            
            if keep: rows.append(r)

        # Calcolo Totali
        stock = [r for r in rows if not r.data_uscita]
        tc = sum((r.n_colli or 0) for r in stock)
        tm = sum((r.m2 or 0) for r in stock)
        tp = sum((r.peso or 0) for r in stock)

        return render_template('giacenze.html', rows=rows, total_colli=tc, total_m2=f"{tm:.2f}", total_peso=f"{tp:.2f}")
    finally:
        db.close()

@app.route('/bulk/edit', methods=['GET', 'POST'])
@login_required
def bulk_edit():
    db = SessionLocal()
    try:
        # Recupera IDs da POST o GET
        ids = request.form.getlist('ids') or request.args.getlist('ids')
        if not ids:
            flash("Nessun articolo selezionato.", "warning")
            return redirect(url_for('giacenze'))

        # Pulisci IDs
        ids = [int(i) for i in ids if str(i).isdigit()]
        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

        # Tutti i campi possibili
        editable_fields = [
            ('Cliente', 'cliente'), ('Fornitore', 'fornitore'),
            ('Codice Articolo', 'codice_articolo'), ('Descrizione', 'descrizione'),
            ('Commessa', 'commessa'), ('Ordine', 'ordine'), ('Protocollo', 'protocollo'),
            ('Magazzino', 'magazzino'), ('Posizione', 'posizione'), ('Stato', 'stato'),
            ('Pezzi', 'pezzo'), ('N. Colli', 'n_colli'),
            ('Lunghezza', 'lunghezza'), ('Larghezza', 'larghezza'), ('Altezza', 'altezza'),
            ('Buono N.', 'buono_n'), ('Data Uscita', 'data_uscita'), ('DDT Uscita', 'n_ddt_uscita'),
            ('N. Arrivo', 'n_arrivo'), ('Serial Number', 'serial_number')
        ]

        if request.method == 'POST' and request.form.get('save_bulk') == 'true':
            updates = {}
            
            # Itera su TUTTI i campi del form per trovare le checkbox attive
            for key in request.form:
                if key.startswith('chk_'):
                    field_name = key.replace('chk_', '') # es. 'cliente'
                    # Cerca se questo campo è nella lista dei modificabili
                    if any(f[1] == field_name for f in editable_fields):
                        val = request.form.get(field_name)
                        
                        # Gestione conversioni
                        if field_name in ['n_colli', 'pezzo']:
                            val = to_int_eu(val)
                        elif field_name in ['lunghezza', 'larghezza', 'altezza']:
                            val = to_float_eu(val)
                        elif field_name == 'data_uscita' and val:
                            val = parse_date_ui(val)
                        
                        updates[field_name] = val

            if updates:
                c = 0
                for art in articoli:
                    for k, v in updates.items():
                        if hasattr(art, k):
                            setattr(art, k, v)
                    
                    # Ricalcolo
                    if any(x in updates for x in ['lunghezza','larghezza','altezza','n_colli']):
                        art.m2, art.m3 = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, art.n_colli)
                    c += 1
                
                db.commit()
                flash(f"{c} articoli aggiornati correttamente.", "success")
            else:
                flash("Nessun campo selezionato per la modifica.", "info")
            
            return redirect(url_for('giacenze'))

        # GET request: Mostra form
        return render_template('bulk_edit.html', rows=articoli, ids_csv=",".join(map(str, ids)), fields=editable_fields)
    finally:
        db.close()

@app.post('/delete_rows')
@login_required
def delete_rows():
    # Controllo Permessi: Solo Admin può cancellare
    if session.get('role') != 'admin':
        flash("Non hai i permessi per eliminare le righe.", "danger")
        return redirect(url_for('giacenze'))

    ids = request.form.getlist('ids')
    if not ids:
        flash("Nessuna riga selezionata per l'eliminazione.", "warning")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        # Filtra solo ID numerici validi
        clean_ids = [int(x) for x in ids if x.isdigit()]
        
        # Esegue la cancellazione
        affected = db.query(Articolo).filter(Articolo.id_articolo.in_(clean_ids)).delete(synchronize_session=False)
        db.commit()
        
        flash(f"Eliminati {affected} articoli.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Errore durante l'eliminazione: {e}", "danger")
    finally:
        db.close()
        
    return redirect(url_for('giacenze'))
        
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
    # Controllo Permessi
    if session.get('role') != 'admin':
        flash("Non hai i permessi per duplicare.", "danger")
        return redirect(url_for('giacenze'))

    ids = request.form.getlist('ids')
    if not ids:
        flash("Nessun articolo selezionato.", "warning")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        count = 0
        for id_str in ids:
            if not id_str.isdigit(): continue
            original = db.query(Articolo).get(int(id_str))
            if original:
                # Clona tutti i campi tranne ID
                new_art = Articolo(
                    codice_articolo=original.codice_articolo,
                    descrizione=original.descrizione,
                    cliente=original.cliente,
                    fornitore=original.fornitore,
                    commessa=original.commessa,
                    protocollo=original.protocollo,
                    buono_n=original.buono_n,
                    ordine=original.ordine,
                    data_ingresso=original.data_ingresso,
                    n_ddt_ingresso=original.n_ddt_ingresso,
                    data_uscita=original.data_uscita,
                    n_ddt_uscita=original.n_ddt_uscita,
                    pezzo=original.pezzo,
                    n_colli=original.n_colli,
                    peso=original.peso,
                    m2=original.m2,
                    m3=original.m3,
                    n_arrivo=original.n_arrivo,
                    stato=original.stato,
                    magazzino=original.magazzino,
                    posizione=original.posizione,
                    note=original.note
                )
                db.add(new_art)
                count += 1
        db.commit()
        flash(f"{count} articoli duplicati.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Errore duplicazione: {e}", "danger")
    finally:
        db.close()
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

def _generate_buono_pdf(form_data, rows):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    story = []
    
    styles = getSampleStyleSheet()
    s_norm = ParagraphStyle('Norm', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.black)
    s_bold = ParagraphStyle('Bold', parent=s_norm, fontName='Helvetica-Bold')
    s_title = ParagraphStyle('Title', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=16, spaceAfter=10, textColor=colors.black)

    # 1. Logo
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=50*mm, height=16*mm, hAlign='CENTER'))
    else:
        story.append(Paragraph("<b>Ca.mar. srl</b>", s_title))
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("BUONO DI PRELIEVO", s_title))
    story.append(Spacer(1, 5*mm))
    
    # 2. Tabella Dati Testata (Simile al tuo PDF)
    meta_data = [
        [Paragraph("<b>Data Emissione:</b>", s_bold), Paragraph(form_data.get('data_em',''), s_norm)],
        [Paragraph("<b>Commessa:</b>", s_bold), Paragraph(form_data.get('commessa',''), s_norm)],
        [Paragraph("<b>Fornitore:</b>", s_bold), Paragraph(form_data.get('fornitore',''), s_norm)],
        [Paragraph("<b>Protocollo:</b>", s_bold), Paragraph(form_data.get('protocollo',''), s_norm)],
        [Paragraph("<b>N. Buono:</b>", s_bold), Paragraph(form_data.get('buono_n',''), s_norm)]
    ]
    
    t_meta = Table(meta_data, colWidths=[40*mm, 140*mm])
    t_meta.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke), # Sfondo grigio colonna sx
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 8*mm))
    
    # Cliente
    cliente = rows[0].cliente if rows else ""
    story.append(Paragraph(f"<b>Cliente:</b> {cliente}", ParagraphStyle('C', parent=s_norm, fontSize=11)))
    story.append(Spacer(1, 5*mm))
    
    # 3. Tabella Articoli (COLONNE CORRETTE: Ordine, Codice, Descrizione, Qta, Arrivo)
    header = [
        Paragraph('<b>Ordine</b>', s_bold),
        Paragraph('<b>Codice Articolo</b>', s_bold), 
        Paragraph('<b>Descrizione / Note</b>', s_bold), 
        Paragraph('<b>Q.tà</b>', s_bold),
        Paragraph('<b>N.Arrivo</b>', s_bold)
    ]
    data = [header]
    
    for r in rows:
        q = form_data.get(f"q_{r.id_articolo}") or r.n_colli
        # Combina Descrizione e Note utente
        desc = r.descrizione or ''
        note_user = form_data.get(f"note_{r.id_articolo}") or r.note
        if note_user: desc += f"<br/><i>Note: {note_user}</i>"
        
        data.append([
            Paragraph(r.ordine or '', s_norm),
            Paragraph(r.codice_articolo or '', s_norm), 
            Paragraph(desc, s_norm), 
            str(q), 
            Paragraph(r.n_arrivo or '', s_norm)
        ])
        
    t = Table(data, colWidths=[30*mm, 35*mm, 85*mm, 15*mm, 25*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), 
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4)
    ]))
    story.append(t)
    
    # 4. Firme
    story.append(Spacer(1, 20*mm))
    sig_data = [[Paragraph("Firma Magazzino:<br/><br/>__________________", s_norm),
                 Paragraph("Firma Cliente:<br/><br/>__________________", s_norm)]]
    t_sig = Table(sig_data, colWidths=[90*mm, 90*mm])
    story.append(t_sig)
    
    doc.build(story)
    bio.seek(0)
    return bio

def _generate_ddt_pdf(n_ddt, data_ddt, targa, dest, rows, form_data):
    bio = io.BytesIO()
    # Margini ottimizzati
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=5*mm, bottomMargin=5*mm)
    story = []
    
    styles = getSampleStyleSheet()
    s_small = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, leading=10)
    s_bold = ParagraphStyle('b', parent=s_small, fontName='Helvetica-Bold')
    s_white = ParagraphStyle('w', parent=s_bold, textColor=colors.white, alignment=TA_CENTER, fontSize=12)

    # 1. Logo
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=50*mm, height=16*mm, hAlign='CENTER'))
    story.append(Spacer(1, 4*mm))

    # 2. Titolo su Fascia Blu
    t_title = Table([[Paragraph("DOCUMENTO DI TRASPORTO (DDT)", s_white)]], colWidths=[190*mm])
    t_title.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#4F81BD")), ('PADDING', (0,0), (-1,-1), 6)]))
    story.append(t_title); story.append(Spacer(1, 2*mm))

    # 3. Mittente e Destinatario
    dest_r = dest.get('ragione_sociale') or "Destinatario"
    dest_i = dest.get('indirizzo', '').replace('\n', '<br/>')
    mitt = "<b>Mittente</b><br/>Camar srl<br/>Via Luigi Canepa 2<br/>16165 Genova"
    dst = f"<b>Destinatario</b><br/>{dest_r}<br/>{dest_i}"
    t_md = Table([[Paragraph(mitt, s_small), Paragraph(dst, s_small)]], colWidths=[95*mm, 95*mm])
    t_md.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 5)]))
    story.append(t_md); story.append(Spacer(1, 2*mm))

    # 4. Dati Aggiuntivi (Barra Blu)
    t_bar = Table([[Paragraph("Dati Aggiuntivi", ParagraphStyle('wb', parent=s_white, fontSize=9, alignment=TA_LEFT))]], colWidths=[190*mm])
    t_bar.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#4F81BD")), ('PADDING', (0,0), (-1,-1), 2)]))
    story.append(t_bar)

    first = rows[0] if rows else None
    d_agg = [
        [Paragraph("<b>Commessa</b>", s_small), Paragraph((first.commessa if first else "") or "-", s_small), Paragraph("<b>N. DDT</b>", s_small), Paragraph(n_ddt, s_small)],
        [Paragraph("<b>Ordine</b>", s_small), Paragraph((first.ordine if first else "") or "-", s_small), Paragraph("<b>Data Uscita</b>", s_small), Paragraph(fmt_date(data_ddt), s_small)],
        [Paragraph("<b>Buono</b>", s_small), Paragraph((first.buono_n if first else "") or "-", s_small), Paragraph("<b>Targa</b>", s_small), Paragraph(targa or "-", s_small)],
        [Paragraph("<b>Protocollo</b>", s_small), Paragraph((first.protocollo if first else "") or "-", s_small), "", ""]
    ]
    t_agg = Table(d_agg, colWidths=[25*mm, 70*mm, 25*mm, 70*mm])
    t_agg.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(t_agg); story.append(Spacer(1, 5*mm))

    # 5. Articoli
    story.append(Paragraph("<b>Articoli nel DDT</b>", ParagraphStyle('h', parent=s_bold, fontSize=10)))
    header = [Paragraph(x, s_bold) for x in ['ID', 'Cod.Art.', 'Descrizione', 'Pezzi', 'Colli', 'Peso', 'N.Arrivo']]
    data = [header]
    tot_p=0; tot_c=0; tot_w=0.0
    note_list = []

    for r in rows:
        pz = to_int_eu(form_data.get(f"pezzi_{r.id_articolo}", r.pezzo)) or 0
        cl = to_int_eu(form_data.get(f"colli_{r.id_articolo}", r.n_colli)) or 0
        we = to_float_eu(form_data.get(f"peso_{r.id_articolo}", r.peso)) or 0.0
        tot_p+=pz; tot_c+=cl; tot_w+=we
        
        # Raccogli note per dopo
        note = form_data.get(f"note_{r.id_articolo}") or r.note
        if note and note.strip(): note_list.append(f"ID {r.id_articolo}: {note}")
        
        data.append([
            Paragraph(str(r.id_articolo), s_small), Paragraph(r.codice_articolo or '', s_small),
            Paragraph(r.descrizione or '', s_small), str(pz), str(cl), f"{we:.0f}", Paragraph(r.n_arrivo or '', s_small)
        ])

    t_items = Table(data, colWidths=[15*mm, 35*mm, 75*mm, 15*mm, 15*mm, 15*mm, 20*mm], repeatRows=1)
    t_items.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 4)]))
    story.append(t_items); story.append(Spacer(1, 3*mm))

    # 6. Note (Fuori Tabella)
    if note_list:
        story.append(Paragraph("<b>Note:</b>", s_bold))
        for n in note_list: story.append(Paragraph(n, s_small))
        story.append(Spacer(1, 3*mm))

    # 7. Footer
    foot = [[Paragraph("<b>Causale</b>", s_bold), Paragraph(form_data.get('causale','TRASFERIMENTO'), s_small)],
            [Paragraph("<b>Porto</b>", s_bold), Paragraph(form_data.get('porto','FRANCO'), s_small)],
            [Paragraph("<b>Aspetto</b>", s_bold), Paragraph(form_data.get('aspetto','A VISTA'), s_small)]]
    story.append(Table(foot, colWidths=[30*mm, 160*mm], style=[('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(Spacer(1, 5*mm))

    fin = [[Paragraph(f"<b>Tot. Colli:</b> {tot_c}   <b>Tot. Peso:</b> {tot_w:.0f}", s_small), Paragraph("Firma Vettore: _______________________", s_small)]]
    story.append(Table(fin, colWidths=[95*mm, 95*mm]))
    
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
        rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        
        action = req_data.get('action')
        
        # AGGIORNAMENTO DATI (Sia per anteprima che per salvataggio)
        # È importante salvare le note temporaneamente o definitivamente
        # Qui le salviamo nel DB se l'azione è 'save'
        
        bn = req_data.get('buono_n')
        
        for r in rows:
            # Se stiamo salvando, aggiorna il numero buono
            if action == 'save' and bn:
                r.buono_n = bn
            
            # SALVA LE NOTE! (Così il DDT le troverà dopo)
            note_inserite = req_data.get(f"note_{r.id_articolo}")
            if note_inserite is not None:
                r.note = note_inserite

        # Commit delle note (importante per il passaggio al DDT)
        if action == 'save':
            db.commit()
            flash(f"Buono salvato. Note aggiornate.", "info")
        
        # Genera PDF
        pdf_bio = _generate_buono_pdf(req_data, rows)
        
        return send_file(
            pdf_bio, 
            as_attachment=(action == 'save'), 
            download_name=f'Buono_{bn}.pdf', 
            mimetype='application/pdf'
        )

    except Exception as e:
        db.rollback()
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

# --- FUNZIONE ETICHETTE AGGIORNATA (Arrivo 10/25 N.1) ---
def _genera_pdf_etichetta(articoli, formato, anteprima=False):
    bio = io.BytesIO()
    # Dimensioni fisse per stampante etichette
    W, H = 100*mm, 62*mm
    doc = SimpleDocTemplate(bio, pagesize=(W, H), leftMargin=2*mm, rightMargin=2*mm, topMargin=2*mm, bottomMargin=2*mm)
    story = []
    
    styles = getSampleStyleSheet()
    # Stili Font Aumentati
    s_k = ParagraphStyle('K', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=11)
    s_v = ParagraphStyle('V', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=12)
    s_big = ParagraphStyle('B', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, leading=16)

    for art in articoli:
        tot = int(art.n_colli or 1)
        if tot < 1: tot = 1
        for i in range(1, tot+1):
            # Logo Ingrandito
            if LOGO_PATH and Path(LOGO_PATH).exists():
                story.append(Image(LOGO_PATH, width=40*mm, height=10*mm, hAlign='LEFT'))
                story.append(Spacer(1, 1*mm))
            
            # Dati Etichetta
            # Recupera n_arrivo anche se l'oggetto è manuale
            arr_val = art.n_arrivo or getattr(art, 'arrivo', '') or ''
            arr_str = f"{arr_val} N.{i}"
            col_str = f"{i} / {tot}"
            
            dati = [
                [Paragraph("CLIENTE:", s_k), Paragraph(art.cliente or '', s_v)],
                [Paragraph("FORNITORE:", s_k), Paragraph(art.fornitore or '', s_v)],
                [Paragraph("ORDINE:", s_k), Paragraph(art.ordine or '', s_v)],
                [Paragraph("COMMESSA:", s_k), Paragraph(art.commessa or '', s_v)],
                [Paragraph("DDT ING.:", s_k), Paragraph(art.n_ddt_ingresso or '', s_v)],
                [Paragraph("DATA ING.:", s_k), Paragraph(fmt_date(art.data_ingresso), s_v)],
                # Righe Grandi
                [Paragraph("ARRIVO:", s_k), Paragraph(arr_str, s_big)],
                [Paragraph("N. COLLO:", s_k), Paragraph(col_str, s_big)],
                [Paragraph("POSIZIONE:", s_k), Paragraph(art.posizione or '', s_v)]
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
            story.append(PageBreak())
            
    doc.build(story)
    bio.seek(0)
    return bio
        
# --- CONFIGURAZIONE FINALE E AVVIO ---
app.jinja_loader = DictLoader(templates)
app.jinja_env.globals['getattr'] = getattr
app.jinja_env.filters['fmt_date'] = fmt_date
    

@app.route('/labels_pdf', methods=['POST'])
@login_required
def labels_pdf():
    # Se ci sono ID selezionati, prendi dal DB
    ids = request.form.getlist('ids')
    articoli = []
    
    if ids:
        db = SessionLocal()
        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        db.close()
    else:
        # Etichetta Manuale: Crea oggetto al volo con i dati del form
        a = Articolo()
        a.cliente = request.form.get('cliente')
        a.fornitore = request.form.get('fornitore')
        a.ordine = request.form.get('ordine')
        a.commessa = request.form.get('commessa')
        a.n_ddt_ingresso = request.form.get('ddt_ingresso') # Attenzione al nome campo HTML
        a.data_ingresso = request.form.get('data_ingresso')
        a.n_arrivo = request.form.get('arrivo') # QUI ERA IL PROBLEMA! (arrivo vs n_arrivo)
        a.n_colli = to_int_eu(request.form.get('n_colli'))
        a.posizione = request.form.get('posizione')
        articoli = [a]

    # Genera il PDF
    pdf_bio = _genera_pdf_etichetta(articoli, request.form.get('formato', '62x100'))
    return send_file(pdf_bio, as_attachment=False, mimetype='application/pdf')

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

from collections import defaultdict
from datetime import timedelta

def _parse_data_db_helper(data_str):
    """Converte stringa data DB in oggetto date (Gestisce formati misti)."""
    if not data_str: return None
    formati = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
    for fmt in formati:
        try:
            return datetime.strptime(str(data_str).strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None

def _calcola_logica_costi(articoli, data_da, data_a, raggruppamento):
    """
    Core logic: Calcola M2 per ogni giorno di occupazione.
    Materiale contato dal giorno ingresso fino al giorno PRIMA dell'uscita.
    """
    m2_per_giorno = defaultdict(float)

    for art in articoli:
        # Parsing sicuro dei dati
        try:
            m2 = float(str(art.m2).replace(',', '.')) if art.m2 else 0.0
        except: m2 = 0.0
        
        if m2 <= 0: continue

        d_ingr = _parse_data_db_helper(art.data_ingresso)
        if not d_ingr: continue

        d_usc = _parse_data_db_helper(art.data_uscita)

        # Periodo attivo dell'articolo
        inizio_attivo = max(d_ingr, data_da)
        
        if d_usc:
            # Conta fino al giorno prima dell'uscita
            fine_attivo = min(d_usc - timedelta(days=1), data_a)
        else:
            # Ancora dentro
            fine_attivo = data_a

        if fine_attivo < inizio_attivo:
            continue

        # Ciclo giorni
        curr = inizio_attivo
        cliente_key = (art.cliente or "SCONOSCIUTO").upper()
        
        while curr <= fine_attivo:
            m2_per_giorno[(cliente_key, curr)] += m2
            curr += timedelta(days=1)

    # Aggregazione Risultati
    risultati_finali = []
    
    if raggruppamento == 'giorno':
        # Ordina per Cliente, Data
        sorted_keys = sorted(m2_per_giorno.keys(), key=lambda k: (k[0], k[1]))
        for cliente, giorno in sorted_keys:
            val_m2 = m2_per_giorno[(cliente, giorno)]
            risultati_finali.append({
                'periodo': giorno.strftime("%d/%m/%Y"),
                'cliente': cliente,
                'm2_tot': f"{val_m2:.3f}",
                'm2_medio': f"{val_m2:.3f}",
                'giorni': 1
            })
    else:
        # Raggruppa per Mese
        agg_mese = defaultdict(lambda: {'m2_sum': 0.0, 'giorni_set': set()})
        
        for (cliente, giorno), val_m2 in m2_per_giorno.items():
            key_mese = (cliente, giorno.year, giorno.month)
            agg_mese[key_mese]['m2_sum'] += val_m2
            agg_mese[key_mese]['giorni_set'].add(giorno)
            
        # Ordina per Anno, Mese, Cliente
        sorted_keys = sorted(agg_mese.keys(), key=lambda k: (k[1], k[2], k[0]))
        
        for (cliente, anno, mese) in sorted_keys:
            dati = agg_mese[(cliente, anno, mese)]
            num_giorni = len(dati['giorni_set'])
            m2_tot = dati['m2_sum']
            m2_medio = m2_tot / num_giorni if num_giorni > 0 else 0.0
            
            risultati_finali.append({
                'periodo': f"{mese:02d}/{anno}",
                'cliente': cliente,
                'm2_tot': f"{m2_tot:.3f}",
                'm2_medio': f"{m2_medio:.3f}",
                'giorni': num_giorni
            })
            
    return risultati_finali

@app.route('/calcola_costi', methods=['GET', 'POST'])
@login_required
def calcola_costi():
    # Defaults per il form
    oggi = date.today()
    data_da_val = (oggi.replace(day=1)).strftime("%Y-%m-%d") # Primo del mese corrente
    data_a_val = today_iso = oggi.strftime("%Y-%m-%d")
    cliente_val = ""
    raggruppamento = "mese"
    risultati = []

    if request.method == 'POST':
        data_da_str = request.form.get('data_da')
        data_a_str = request.form.get('data_a')
        cliente_val = request.form.get('cliente', '').strip()
        raggruppamento = request.form.get('raggruppamento', 'mese')
        
        # Converti date form in oggetti date
        try:
            d_da = datetime.strptime(data_da_str, "%Y-%m-%d").date()
            d_a = datetime.strptime(data_a_str, "%Y-%m-%d").date()
            
            # Recupera dati dal DB
            db = SessionLocal()
            query = db.query(Articolo).filter(
                Articolo.data_ingresso.isnot(None),
                Articolo.data_ingresso != ''
            )
            
            # Pre-filtro cliente su SQL se possibile (opzionale, ma velocizza)
            if cliente_val:
                query = query.filter(Articolo.cliente.ilike(f"%{cliente_val}%"))
                
            articoli = query.all()
            db.close()
            
            # Esegui calcolo logico
            risultati = _calcola_logica_costi(articoli, d_da, d_a, raggruppamento)
            
            # Mantieni valori nel form
            data_da_val = data_da_str
            data_a_val = data_a_str

        except Exception as e:
            flash(f"Errore nel calcolo: {e}", "danger")

    return render_template('calcoli.html', # Usa la stringa CALCOLI_HTML se non usi file separati
                           risultati=risultati,
                           data_da=data_da_val,
                           data_a=data_a_val,
                           cliente_filtro=cliente_val,
                           raggruppamento=raggruppamento)

# --- AVVIO FLASK APP ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
