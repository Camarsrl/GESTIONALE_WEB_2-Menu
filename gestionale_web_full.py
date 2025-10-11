# -*- coding: utf-8 -*-
"""
Camar • Gestionale Web – build aggiornata (Ottobre 2025)
© Copyright Alessia Moncalvo
Tutti i diritti riservati.
"""

import os, io, re, json, uuid
from datetime import datetime, date
from pathlib import Path

import pandas as pd
from flask import (
    Flask, request, render_template, redirect, url_for,
    send_file, session, flash, abort, jsonify
)
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey, Identity
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect

# ReportLab (PDF)
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Jinja loader per gestire i template in memoria
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

# --- PATH / LOGO (Configurazione robusta per Render) ---
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
if not os.environ.get("DATABASE_URL"):
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

# --- MODELLI ---
class Articolo(Base):
    __tablename__ = "articoli"
    id_articolo = Column(Integer, Identity(start=1), primary_key=True)
    codice_articolo = Column(String(255))
    pezzo = Column(String(255))
    larghezza = Column(Float); lunghezza = Column(Float); altezza = Column(Float)
    m2 = Column(Float); m3 = Column(Float)
    protocollo = Column(String(255)); ordine = Column(String(255)); commessa = Column(String(255))
    magazzino = Column(String(255)); fornitore = Column(String(255))
    data_ingresso = Column(String(32)); n_ddt_ingresso = Column(String(255))
    cliente = Column(String(255)); descrizione = Column(Text); peso = Column(Float); n_colli = Column(Integer)
    posizione = Column(String(255)); n_arrivo = Column(String(255)); buono_n = Column(String(255)); note = Column(Text)
    serial_number = Column(String(255))
    data_uscita = Column(String(32)); n_ddt_uscita = Column(String(255)); ns_rif = Column(String(255))
    stato = Column(String(255)); mezzi_in_uscita = Column(String(255))
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
            data = json.loads(DESTINATARI_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = {f"Destinatario {i+1}": v for i, v in enumerate(data)}
        except Exception: pass
    if not data:
        data = {"Sede Cliente": {"ragione_sociale": "Cliente S.p.A.", "indirizzo": "Via Esempio 1, 16100 Genova", "piva": "IT00000000000"}}
        DESTINATARI_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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
        .table-compact th, .table-compact td { font-size: 11px; padding: 4px 5px; white-space: nowrap; vertical-align: middle; }
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
            return false;
        }
        if (confirm(`Sei sicuro di voler eliminare definitivamente ${ids.length} articoli selezionati? L'azione è irreversibile.`)) {
            submitForm('{{ url_for("bulk_delete") }}', 'post');
        }
        return false;
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
<form method="post" id="buono-form">
    <input type="hidden" name="ids" value="{{ ids }}">
    <div class="card p-3">
        <div class="d-flex align-items-center gap-3 mb-3">
            {% if logo_url %}<img src="{{ logo_url }}" style="height:40px">{% endif %}
            <h5 class="flex-grow-1 text-center m-0">BUONO DI PRELIEVO</h5>
            <div class="btn-group">
                <button type="submit" class="btn btn-primary"><i class="bi bi-file-earmark-check"></i> Genera e Salva Buono</button>
                <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
            </div>
        </div>
        <div class="row g-3">
            <div class="col-md-3"><label class="form-label">N. Buono</label><input name="buono_n" class="form-control" value="{{ meta.buono_n }}"></div>
            <div class="col-md-3"><label class="form-label">Data Emissione</label><input name="data_em" class="form-control" value="{{ meta.data_em }}" readonly></div>
            <div class="col-md-3"><label class="form-label">Commessa</label><input name="commessa" class="form-control" value="{{ meta.commessa }}"></div>
            <div class="col-md-3"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control" value="{{ meta.fornitore }}"></div>
            <div class="col-md-3"><label class="form-label">Protocollo</label><input name="protocollo" class="form-control" value="{{ meta.protocollo }}"></div>
        </div>
        <hr>
        <div class="table-responsive">
            <table class="table table-sm table-bordered">
                <thead><tr><th>Ordine</th><th>Codice Articolo</th><th>Descrizione</th><th>Quantità</th><th>N.Arrivo</th></tr></thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.ordine or '' }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
                        <td><input name="q_{{ r.id_articolo }}" class="form-control form-control-sm" value="{{ r.n_colli or 1 }}"></td>
                        <td>{{ r.n_arrivo or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</form>
{% endblock %}
{% block extra_js %}
<script>
document.getElementById('buono-form').addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = new FormData(this);
    fetch('{{ url_for('buono_finalize_and_get_pdf') }}', {
        method: 'POST',
        body: formData
    })
    .then(resp => {
        if (resp.ok) {
            const contentDisposition = resp.headers.get('content-disposition');
            let filename = "buono.pdf";
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="(.+)"/);
                if (filenameMatch.length > 1) {
                    filename = filenameMatch[1];
                }
            }
            resp.blob().then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.target = '_blank'; // Apri in una nuova scheda
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                // Reindirizza la pagina corrente
                window.location.href = '{{ url_for('giacenze') }}';
            });
        } else {
            alert("Si è verificato un errore durante la generazione del buono.");
        }
    }).catch(err => {
        console.error('Error:', err);
        alert("Errore di rete o del server.");
    });
});
</script>
{% endblock %}
"""

DDT_PREVIEW_HTML = """
{% extends 'base.html' %}
{% block content %}
<form method="post" id="ddt-form">
    <input type="hidden" name="ids" value="{{ ids }}">
    <div class="card p-3">
        <div class="d-flex align-items-center gap-3 mb-3">
            {% if logo_url %}<img src="{{ logo_url }}" style="height:40px">{% endif %}
            <h5 class="flex-grow-1 text-center m-0">DOCUMENTO DI TRASPORTO</h5>
            <div class="btn-group">
                <button type="button" class="btn btn-primary" onclick="submitDdtPreview()">
                    <i class="bi bi-printer"></i> Genera PDF (Anteprima)
                </button>
                <button type="submit" class="btn btn-success" formaction="{{ url_for('ddt_finalize') }}">
                    <i class="bi bi-check-circle-fill"></i> Finalizza e Scarica DDT
                </button>
            </div>
        </div>
        <div class="row g-3">
            <div class="col-md-4">
                <label class="form-label">Destinatario</label>
                <select class="form-select" name="dest_key">
                    {% for k, v in destinatari.items() %}
                    <option value="{{ k }}">{{ k }} — {{ v.ragione_sociale }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-3">
                 <label class="form-label">N. DDT</label>
                 <div class="input-group">
                    <input name="n_ddt" id="n_ddt_input" class="form-control" value="{{ n_ddt }}">
                    <button class="btn btn-outline-secondary" type="button" id="get-next-ddt" title="Ottieni prossimo numero">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </div>
            <div class="col-md-2"><label class="form-label">Data DDT</label><input name="data_ddt" type="date" class="form-control" value="{{ oggi }}"></div>
            <div class="col-md-3"><label class="form-label">Targa</label><input name="targa" class="form-control"></div>
            <div class="col-md-3"><label class="form-label">Causale</label><input name="causale" class="form-control" value="TRASFERIMENTO"></div>
            <div class="col-md-3"><label class="form-label">Porto</label><input name="porto" class="form-control" value="FRANCO"></div>
            <div class="col-md-3"><label class="form-label">Aspetto</label><input name="aspetto" class="form-control" value="A VISTA"></div>
        </div>
        <hr>
        <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle">
                <thead><tr><th>ID</th><th>Cod.Art.</th><th>Descrizione</th><th style="width:90px">Pezzi</th><th style="width:90px">Colli</th><th style="width:90px">Peso</th><th>N.Arrivo</th></tr></thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.id_articolo }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
                        <td><input class="form-control form-control-sm" name="pezzi_{{ r.id_articolo }}" value="{{ r.pezzo or 1 }}"></td>
                        <td><input class="form-control form-control-sm" name="colli_{{ r.id_articolo }}" value="{{ r.n_colli or 1 }}"></td>
                        <td><input class="form-control form-control-sm" name="peso_{{ r.id_articolo }}" value="{{ r.peso or '' }}"></td>
                        <td>{{ r.n_arrivo or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</form>
{% endblock %}
{% block extra_js %}
<script>
function submitDdtPreview() {
    const form = document.getElementById('ddt-form');
    form.action = '{{ url_for('pdf_ddt') }}';
    form.target = '_blank';
    form.submit();
}

document.getElementById('get-next-ddt').addEventListener('click', function() {
    fetch('{{ url_for('get_next_ddt_number') }}')
        .then(response => response.json())
        .then(data => {
            document.getElementById('n_ddt_input').value = data.next_ddt;
        })
        .catch(error => console.error('Error fetching next DDT number:', error));
});

document.getElementById('ddt-form').addEventListener('submit', function(e) {
    if (this.action.endsWith('{{ url_for('ddt_finalize') }}')) {
        e.preventDefault();
        const formData = new FormData(this);
        fetch(this.action, {
            method: 'POST',
            body: formData
        })
        .then(resp => {
            if (resp.ok) {
                const redirectUrl = resp.headers.get('X-Redirect');
                const contentDisposition = resp.headers.get('content-disposition');
                let filename = "download.pdf";
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="(.+)"/);
                    if (filenameMatch && filenameMatch.length > 1) {
                        filename = filenameMatch[1];
                    }
                }
                resp.blob().then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    if (redirectUrl) {
                        window.location.href = redirectUrl;
                    }
                });
            } else {
                alert("Si è verificato un errore durante la finalizzazione del DDT.");
            }
        }).catch(err => {
            console.error('Error:', err);
            alert("Errore di rete o del server.");
        });
    }
});
</script>
{% endblock %}
"""

LABELS_FORM_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-tag"></i> Nuova Etichetta Stampa Multipla</h3>
    <hr>
    <form method="post" action="{{ url_for('labels_pdf') }}" target="_blank">
        <div class="row g-3">
            <div class="col-md-4"><label class="form-label">Cliente</label><input name="cliente" class="form-control"></div>
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
            <button type="submit" class="btn btn-primary"><i class="bi bi-printer"></i> Genera e Stampa PDF</button>
        </div>
    </form>
</div>
{% endblock %}
"""

# Il template LABELS_PREVIEW_HTML non è più necessario e può essere rimosso.
LABELS_PREVIEW_HTML = " " 

IMPORT_EXCEL_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8 col-lg-6">
        <div class="card p-4">
            <h3><i class="bi bi-file-earmark-arrow-up"></i> Importa Articoli da Excel</h3>
            <hr>
            <p class="text-muted">Carica un file Excel (.xlsx, .xls, .xlsm) per aggiungere nuovi articoli in blocco. Assicurati che il file abbia una riga di intestazione con i nomi delle colonne corretti.</p>
            <form method="post" enctype="multipart/form-data">
                <div class="mb-3">
                    <label for="excel_file" class="form-label">Seleziona il file Excel</label>
                    <input class="form-control" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls,.xlsm" required>
                </div>
                <button type="submit" class="btn btn-primary">Carica e Importa</button>
                <a href="{{ url_for('home') }}" class="btn btn-secondary">Annulla</a>
            </form>
            <div class="alert alert-info mt-4">
                <strong>Nomi colonne suggeriti:</strong><br>
                <small><code>Codice Articolo, Pezzo, Larghezza, Lunghezza, Altezza, Protocollo, Ordine, Commessa, Magazzino, Fornitore, Data Ingresso, N. DDT Ingresso, Cliente, Descrizione, Peso, N. Colli, Posizione, N. Arrivo, Buono N., Note, Serial Number, Stato, Mezzi in Uscita, NS Rif</code></small>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

# Dizionario dei template per il loader di Jinja
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
    'import_excel.html': IMPORT_EXCEL_HTML
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

# --- IMPORTAZIONE EXCEL ---
@app.route('/import_excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('Nessun file selezionato', 'warning')
            return redirect(request.url)
        file = request.files['excel_file']
        if file.filename == '':
            flash('Nessun file selezionato', 'warning')
            return redirect(request.url)
        if file and file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm')):
            try:
                db = SessionLocal()
                df = pd.read_excel(file, engine='openpyxl')
                
                df.columns = [c.strip().lower().replace(' ', '_').replace('.', '').replace('°', '') for c in df.columns]

                column_map = {
                    'codice_articolo': 'codice_articolo', 'pezzo': 'pezzo', 'larghezza': 'larghezza', 'lunghezza': 'lunghezza',
                    'altezza': 'altezza', 'protocollo': 'protocollo', 'ordine': 'ordine', 'commessa': 'commessa', 'magazzino': 'magazzino',
                    'fornitore': 'fornitore', 'data_ingresso': 'data_ingresso', 'n_ddt_ingresso': 'n_ddt_ingresso', 'cliente': 'cliente',
                    'descrizione': 'descrizione', 'peso': 'peso', 'n_colli': 'n_colli', 'posizione': 'posizione', 'n_arrivo': 'n_arrivo',
                    'buono_n': 'buono_n', 'note': 'note', 'serial_number': 'serial_number', 'stato': 'stato',
                    'mezzi_in_uscita': 'mezzi_in_uscita', 'ns_rif': 'ns_rif'
                }

                imported_count = 0
                for _, row in df.iterrows():
                    new_art = Articolo()
                    for col_name, attr_name in column_map.items():
                        if col_name in row and not pd.isna(row[col_name]):
                            val = row[col_name]
                            if attr_name in ['larghezza', 'lunghezza', 'altezza', 'peso']:
                                val = to_float_eu(val)
                            elif attr_name in ['n_colli', 'pezzo']:
                                val = to_int_eu(val)
                            elif attr_name == 'data_ingresso':
                                val = fmt_date(val) if isinstance(val, (datetime, date)) else parse_date_ui(str(val))
                            setattr(new_art, attr_name, val)
                    
                    new_art.m2, new_art.m3 = calc_m2_m3(new_art.lunghezza, new_art.larghezza, new_art.altezza, new_art.n_colli)
                    db.add(new_art)
                    imported_count += 1
                
                db.commit()
                flash(f'{imported_count} articoli importati con successo dal file Excel.', 'success')
                return redirect(url_for('giacenze'))

            except Exception as e:
                db.rollback()
                flash(f"Errore durante l'importazione: {e}", 'danger')
                return redirect(request.url)
        else:
            flash('Formato file non supportato. Usare .xlsx, .xls o .xlsm', 'warning')
            return redirect(request.url)

    return render_template('import_excel.html')

def get_all_fields():
    return [
        'codice_articolo', 'pezzo', 'larghezza', 'lunghezza', 'altezza',
        'protocollo', 'ordine', 'commessa', 'magazzino', 'fornitore',
        'data_ingresso', 'n_ddt_ingresso', 'cliente', 'descrizione', 'peso',
        'n_colli', 'posizione', 'n_arrivo', 'buono_n', 'note',
        'serial_number', 'data_uscita', 'n_ddt_uscita', 'ns_rif', 'stato',
        'mezzi_in_uscita'
    ]

def get_field_labels():
    return [
        ('Codice Articolo', 'codice_articolo'), ('Pezzi', 'pezzo'),
        ('Descrizione', 'descrizione'), ('Cliente', 'cliente'),
        ('Protocollo', 'protocollo'), ('Ordine', 'ordine'), ('Peso (Kg)', 'peso'),
        ('N° Colli', 'n_colli'), ('Posizione', 'posizione'), ('Stato', 'stato'),
        ('N° Arrivo', 'n_arrivo'), ('Buono N°', 'buono_n'),
        ('Fornitore', 'fornitore'), ('Magazzino', 'magazzino'),
        ('Data Ingresso', 'data_ingresso'), ('Data Uscita', 'data_uscita'),
        ('N° DDT Ingresso', 'n_ddt_ingresso'), ('N° DDT Uscita', 'n_ddt_uscita'),
        ('Larghezza (m)', 'larghezza'), ('Lunghezza (m)', 'lunghezza'),
        ('Altezza (m)', 'altezza'), ('Serial Number', 'serial_number'),
        ('NS Rif', 'ns_rif'), ('Mezzi in Uscita', 'mezzi_in_uscita'), ('Note', 'note')
    ]

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
        for f in get_all_fields():
            v = request.form.get(f)
            if v is not None:
                if f in ('data_ingresso','data_uscita'):
                    v = parse_date_ui(v) if v else None
                elif f in ('larghezza','lunghezza','altezza','peso'):
                    v = to_float_eu(v)
                elif f in ('n_colli', 'pezzo'):
                    v = to_int_eu(v)
                setattr(row, f, v)
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

    return render_template('edit.html', row=row, fields=get_field_labels())

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
    db = SessionLocal()
    try:
        qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())
        if session.get('role') == 'client':
            qs = qs.filter(Articolo.cliente == session['user'])
        
        like_cols = [
            'codice_articolo', 'cliente', 'fornitore', 'commessa', 'descrizione', 'posizione', 'stato', 
            'protocollo', 'n_ddt_ingresso', 'n_ddt_uscita', 'n_arrivo', 'buono_n', 'ns_rif', 
            'serial_number', 'mezzi_in_uscita'
        ]
        if request.args.get('id'):
            try: qs = qs.filter(Articolo.id_articolo == int(request.args.get('id')))
            except ValueError: pass
        
        for col in like_cols:
            v = request.args.get(col)
            if v:
                qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))
                
        date_filters = {
            'data_ingresso_da': (Articolo.data_ingresso, '>='), 'data_ingresso_a': (Articolo.data_ingresso, '<='),
            'data_uscita_da': (Articolo.data_uscita, '>='), 'data_uscita_a': (Articolo.data_uscita, '<=')
        }
        for arg, (col, op) in date_filters.items():
            val = request.args.get(arg)
            if val:
                date_sql = parse_date_ui(val)
                if date_sql:
                    if op == '>=': qs = qs.filter(col >= date_sql)
                    else: qs = qs.filter(col <= date_sql)
        
        rows = qs.all()
        
        stock_rows = [r for r in rows if not r.data_uscita]
        total_colli = sum(r.n_colli for r in stock_rows if r.n_colli)
        total_m2 = sum(r.m2 for r in stock_rows if r.m2)

    except Exception as e:
        db.rollback()
        flash(f"Errore nel caricamento delle giacenze: {e}", "danger")
        rows, total_colli, total_m2 = [], 0, 0
    
    cols = ["id_articolo","codice_articolo","descrizione","cliente","fornitore","protocollo","ordine",
            "commessa","magazzino","posizione","stato","peso","n_colli","m2","data_ingresso","data_uscita",
            "n_ddt_uscita", "mezzi_in_uscita"]
    return render_template('giacenze.html', rows=rows, cols=cols, total_colli=total_colli, total_m2=total_m2)

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
            for f in get_all_fields():
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
    return render_template('bulk_edit.html', rows=rows, ids_csv=ids_csv, fields=get_field_labels())

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
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=10*mm, bottomMargin=15*mm)
    story = []
    
    s_small_bold = ParagraphStyle(name='small_bold', fontName='Helvetica-Bold', fontSize=8)
    s_small = ParagraphStyle(name='small', fontName='Helvetica', fontSize=8)
    
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=50*mm, height=16*mm, hAlign='LEFT'))
        story.append(Spacer(1, 5*mm))

    title_style = ParagraphStyle(name='TitleStyle', fontName='Helvetica-Bold', fontSize=16, alignment=TA_CENTER, textColor=colors.white)
    title_bar = Table([[Paragraph("DOCUMENTO DI TRASPORTO (DDT)", title_style)]], colWidths=[doc.width], style=[('BACKGROUND', (0,0), (-1,-1), PRIMARY_COLOR), ('PADDING', (0,0), (-1,-1), 6)])
    story.append(title_bar)
    story.append(Spacer(1, 8*mm))

    mitt_text = Paragraph("<b>Mittente</b><br/>Camar srl<br/>Via Luigi Canepa 2<br/>16165 Genova Struppa (GE)", s_small)
    dest_text = Paragraph(f"<b>Destinatario</b><br/>{dest.get('ragione_sociale','') or ''}<br/>{dest.get('indirizzo','') or ''}", s_small)
    
    first_row = rows[0] if rows else Articolo()
    add_data_content = [
        [Paragraph("<b>Commessa</b>", s_small_bold), Paragraph(first_row.commessa or '', s_small)],
        [Paragraph("<b>Ordine</b>", s_small_bold), Paragraph(first_row.ordine or '', s_small)],
        [Paragraph("<b>Buono</b>", s_small_bold), Paragraph(first_row.buono_n or '', s_small)],
        [Paragraph("<b>Protocollo</b>", s_small_bold), Paragraph(first_row.protocollo or '', s_small)],
    ]
    doc_data_content = [
        [Paragraph("<b>N. DDT</b>", s_small_bold), Paragraph(n_ddt, s_small)],
        [Paragraph("<b>Data Uscita</b>", s_small_bold), Paragraph(fmt_date(data_ddt), s_small)],
        [Paragraph("<b>Targa</b>", s_small_bold), Paragraph(targa, s_small)],
        [Paragraph("<b>Richiesta di:</b>", s_small_bold), Paragraph("", s_small)],
    ]

    header_table = Table(
        [[mitt_text, Paragraph("<b>Dati Aggiuntivi</b>", s_small_bold), Paragraph("<b>Dati Documento</b>", s_small_bold)],
         [dest_text, Table(add_data_content, colWidths=[25*mm, '35%'], style=[('VALIGN', (0,0), (-1,-1), 'TOP')]), 
                     Table(doc_data_content, colWidths=[25*mm, '35%'], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])]],
        colWidths=[doc.width/3, doc.width/3, doc.width/3],
        style=[('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0)]
    )
    story.append(header_table)
    story.append(Spacer(1, 8*mm))
    
    data = [['ID','Cod.Art.','Descrizione','Pezzi','Colli','Peso','N.Arrivo']]
    tot_colli, tot_peso, tot_pezzi = 0, 0.0, 0
    for r in rows:
        pezzi = to_int_eu(form_data.get(f"pezzi_{r.id_articolo}", r.pezzo)) or 0
        colli = to_int_eu(form_data.get(f"colli_{r.id_articolo}", r.n_colli)) or 0
        peso = to_float_eu(form_data.get(f"peso_{r.id_articolo}", r.peso)) or 0.0
        data.append([r.id_articolo, r.codice_articolo or '', r.descrizione or '', pezzi, colli, f"{peso:.2f}", r.n_arrivo or ''])
        tot_pezzi += pezzi; tot_colli += colli; tot_peso += float(peso)
    
    item_table = _pdf_table(data, col_widths=[15*mm, 35*mm, None, 15*mm, 15*mm, 18*mm, 22*mm])
    story.append(item_table)
    story.append(Spacer(1, 6*mm))
    
    causale_porto_aspetto = [
        [Paragraph("<b>Causale</b>", s_small), Paragraph(form_data.get('causale', 'TRASFERIMENTO'), s_small)],
        [Paragraph("<b>Porto</b>", s_small), Paragraph(form_data.get('porto', 'FRANCO'), s_small)],
        [Paragraph("<b>Aspetto</b>", s_small), Paragraph(form_data.get('aspetto', 'A VISTA'), s_small)],
    ]
    cpa_table = Table(causale_porto_aspetto, colWidths=[20*mm, None], style=[('GRID', (0,0), (-1,-1), 0.25, colors.lightgrey)])

    totals_text = f"<b>Totale Pezzi:</b> {tot_pezzi}<br/><b>Totale Colli:</b> {tot_colli}<br/><b>Totale Peso:</b> {tot_peso:.2f} Kg"
    firma_text = "<b>Firma Vettore:</b><br/><br/>________________________"
    
    footer_table = Table([[cpa_table, Paragraph(totals_text, s_bold), Paragraph(firma_text, s_bold)]], 
                         colWidths=[doc.width/3, doc.width/3, doc.width/3], 
                         style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(footer_table)
    
    story.append(Spacer(1, 15*mm))
    story.append(_copyright_para())
    
    doc.build(story)
    bio.seek(0)
    return bio

@app.post('/pdf/buono')
@login_required
def pdf_buono():
    ids = [int(i) for i in request.form.get('ids','').split(',') if i.isdigit()]
    rows = _get_rows_from_ids(ids)
    buono_n = (request.form.get('buono_n') or '').strip()
    db = SessionLocal()
    if buono_n:
        for r in rows:
            r.buono_n = buono_n
        db.commit()
        flash(f"Numero Buono '{buono_n}' salvato per gli articoli selezionati.", "info")
    
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=10*mm, bottomMargin=15*mm)
    story = []

    if LOGO_PATH and Path(LOGO_PATH).exists():
        logo = Image(LOGO_PATH, width=60*mm, height=20*mm, hAlign='CENTER')
        story.append(logo)
        story.append(Spacer(1, 5*mm))

    title_style = ParagraphStyle(name='TitleStyle', fontName='Helvetica-Bold', fontSize=16, alignment=TA_CENTER, textColor=colors.white)
    title_bar = Table([[Paragraph("BUONO DI PRELIEVO", title_style)]], colWidths=[doc.width], style=[('BACKGROUND', (0,0), (-1,-1), PRIMARY_COLOR), ('PADDING', (0,0), (-1,-1), 6)])
    story.append(title_bar)
    story.append(Spacer(1, 8*mm))

    d_row = rows[0] if rows else None
    meta = [
        ["Data Emissione", datetime.today().strftime("%d/%m/%Y")],
        ["Commessa", (d_row.commessa or "") if d_row else ""],
        ["Fornitore", (d_row.fornitore or "") if d_row else ""],
        ["Protocollo", (d_row.protocollo or "") if d_row else ""],
        ["N. Buono", (d_row.buono_n or "") if d_row else (buono_n or "")]
    ]
    story.append(_pdf_table(meta, [35*mm, None], header=False))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Cliente:</b> {(d_row.cliente or '').upper()}", getSampleStyleSheet()['Normal']))
    story.append(Spacer(1, 8))
    data = [['Ordine','Codice Articolo','Descrizione','Quantità','N.Arrivo']]
    for r in rows:
        q_val = request.form.get(f"q_{r.id_articolo}")
        quantita = to_int_eu(q_val) if q_val is not None else (r.n_colli or 1)
        data.append([r.ordine or '', r.codice_articolo or '', r.descrizione or '', quantita, r.n_arrivo or ''])
    story.append(_pdf_table(data, col_widths=[25*mm, 45*mm, None, 20*mm, 25*mm]))
    story.extend([
        Spacer(1, 25*mm),
        Table([["Firma Magazzino:\n\n___________________", "Firma Cliente:\n\n___________________"]],
              colWidths=[doc.width/2 - 4*mm, doc.width/2 - 4*mm], 
              style=[('GRID', (0,0), (-1,-1), 0, colors.white), ('VALIGN', (0,0), (-1,-1), 'TOP')]),
        Spacer(1, 25*mm), 
        _copyright_para()
    ])
    doc.build(story)
    bio.seek(0)
    return send_file(bio, as_attachment=False, download_name='buono.pdf', mimetype='application/pdf')

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
    ids = [int(i) for i in request.form.get('ids','').split(',') if i.isdigit()]
    n_ddt = request.form.get('n_ddt', '').strip()
    data_ddt = request.form.get('data_ddt', date.today().isoformat())
    
    articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
    for art in articoli:
        art.data_uscita = data_ddt
        art.n_ddt_uscita = n_ddt
        art.stato = 'USCITO'
        art.pezzo = to_int_eu(request.form.get(f"pezzi_{art.id_articolo}", art.pezzo))
        art.n_colli = to_int_eu(request.form.get(f"colli_{art.id_articolo}", art.n_colli))
        art.peso = to_float_eu(request.form.get(f"peso_{art.id_articolo}", art.peso))
    db.commit()
    
    dest = load_destinatari().get(request.form.get('dest_key'), {})
    pdf_bio = _generate_ddt_pdf(
        n_ddt=n_ddt, data_ddt=data_ddt, targa=request.form.get('targa'),
        dest=dest, rows=articoli, form_data=request.form
    )
    
    flash(f"{len(articoli)} articoli scaricati. DDT N.{n_ddt} generato.", "success")
    
    download_name = f"DDT_{n_ddt.replace('/', '-')}_{data_ddt}.pdf"
    response = send_file(pdf_bio, as_attachment=True, download_name=download_name, mimetype='application/pdf')
    
    response.headers['X-Redirect'] = url_for('giacenze')
    return response

# --- ETICHETTE ---
@app.get('/labels')
@login_required
def labels_form():
    return render_template('labels_form.html')

def _labels_clean_data(form):
    return {k: (form.get(k) or "").strip() for k in ("cliente","fornitore","ordine","commessa",
            "ddt_ingresso","data_ingresso","arrivo","n_colli","posizione","protocollo")}

@app.post('/labels/preview') # Questa route non è più usata dal form principale
@login_required
def labels_preview():
    data = _labels_clean_data(request.form)
    return render_template('labels_preview.html', d=data)

@app.post('/labels/pdf')
@login_required
def labels_pdf():
    d = _labels_clean_data(request.form)
    pagesize = (100*mm, 62*mm) # CORRETTO: 100x62 mm
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=pagesize, leftMargin=4*mm, rightMargin=4*mm, topMargin=3*mm, bottomMargin=3*mm)
    story = []
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=24*mm, height=8*mm))
        story.append(Spacer(1, 2))

    row_style = getSampleStyleSheet()['Normal']
    row_style.fontName = 'Helvetica-Bold'; row_style.fontSize = 9; row_style.leading = 11

    def P(label, value):
        return Paragraph(f"{label}: <b>{value or ''}</b>", row_style)

    story.extend([
        P("CLIENTE", d['cliente']), P("FORNITORE", d['fornitore']), P("ORDINE", d['ordine']),
        P("COMMESSA", d['commessa']), P("DDT", d['ddt_ingresso']), P("DATA ING.", d['data_ingresso']),
        P("ARRIVO", d['arrivo']), P("POSIZIONE", d['posizione']), P("COLLI", d['n_colli']),
    ])
    try:
        doc.build(story)
    except Exception:
        # Se il testo è troppo lungo, riduci il font e riprova
        bio.seek(0); bio.truncate(0)
        story = []
        if LOGO_PATH and Path(LOGO_PATH).exists():
            story.append(Image(LOGO_PATH, width=24*mm, height=8*mm))
            story.append(Spacer(1, 2))
        row_style.fontSize = 7; row_style.leading = 9
        story.extend([
            P("CLIENTE", d['cliente']), P("FORNITORE", d['fornitore']), P("ORDINE", d['ordine']),
            P("COMMESSA", d['commessa']), P("DDT", d['ddt_ingresso']), P("DATA ING.", d['data_ingresso']),
            P("ARRIVO", d['arrivo']), P("POSIZIONE", d['posizione']), P("COLLI", d['n_colli']),
        ])
        doc.build(story)

    bio.seek(0)
    return send_file(bio, as_attachment=False, download_name='etichetta.pdf', mimetype='application/pdf')


# --- AVVIO FLASK APP ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
