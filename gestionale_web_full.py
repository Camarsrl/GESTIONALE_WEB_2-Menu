# -*- coding: utf-8 -*-
"""
Camar • Gestionale Web – build aggiornata (Ottobre 2025)
© Copyright Alessia Moncalvo
Tutti i diritti riservati.
"""

import os, io, re, json, uuid, smtplib
from email.message import EmailMessage
from datetime import datetime, date
from pathlib import Path

import pandas as pd
from flask import (
    Flask, request, render_template, redirect, url_for,
    send_file, session, flash, abort, jsonify
)
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet

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

# --- PATH / LOGO ---
APP_DIR = Path(os.environ.get("APP_DIR", "."))
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
    if not u:
        return u
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
    id_articolo = Column(Integer, primary_key=True, autoincrement=True)
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
    attachments = relationship("Attachment", back_populates="articolo", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo"))
    kind = Column(String(10))  # doc/foto
    filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)

# --- UTENTI ---
DEFAULT_USERS = {
    # Clienti
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'MARINE INTERIORS': 'Struppa09',
    # Interni
    'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123',
}
ADMIN_USERS = {'ADMIN', 'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO'}

def get_users():
    fp = APP_DIR / "password Utenti Gestionale.txt"
    if fp.exists():
        try:
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(r"'([^']+)'\s*:\s*'([^']+)'", raw)
            m = {k.strip().upper(): v.strip() for k, v in pairs}
            if m:
                return m
        except Exception:
            pass
    return DEFAULT_USERS

# --- UTILS ---
def is_blank(v):
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return (v is None) or (isinstance(v, str) and not v.strip())

def to_float_eu(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def to_int_eu(v):
    f = to_float_eu(v)
    return None if f is None else int(round(f))

def parse_date_ui(d):
    if not d:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return d

def fmt_date(d):
    if not d:
        return ""
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return d

def calc_m2_m3(l, w, h, colli):
    l = to_float_eu(l) or 0.0
    w = to_float_eu(w) or 0.0
    h = to_float_eu(h) or 0.0
    c = to_int_eu(colli) or 1
    return round(c * l * w, 3), round(c * l * w * h, 3)

def load_destinatari():
    DESTINATARI_JSON = APP_DIR / "destinatari_saved.json"
    if DESTINATARI_JSON.exists():
        try:
            data = json.loads(DESTINATARI_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = {f"Destinatario {i+1}": v for i, v in enumerate(data)}
            return data
        except Exception:
            pass
    data = {
        "Sede Cliente": {
            "ragione_sociale": "Cliente S.p.A.",
            "indirizzo": "Via Esempio 1, 16100 Genova",
            "piva": "IT00000000000"
        }
    }
    DESTINATARI_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def next_ddt_number():
    PROG_FILE = APP_DIR / "progressivi_ddt.json"
    y = str(date.today().year)[-2:] # Usa solo le ultime due cifre dell'anno (es. 25 per 2025)
    prog = {}
    if PROG_FILE.exists():
        try:
            prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
    n = int(prog.get(y, 0)) + 1
    prog[y] = n
    PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{n:02d}/{y}"

# --- SEZIONE TEMPLATES HTML ---
# Tutto l'HTML è definito qui come stringhe per avere un file unico.

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
        body { background: #f7f9fc; }
        .card { border-radius: 16px; box-shadow: 0 6px 18px rgba(0,0,0,.06); border: none; }
        .table thead th { position: sticky; top: 0; background: #fff; z-index: 2; }
        .dropzone { border: 2px dashed #7aa2ff; background: #eef4ff; padding: 20px; border-radius: 12px; text-align: center; color: #2c4a9a; cursor: pointer; }
        .logo { height: 40px; }
        .table-compact th, .table-compact td { font-size: 0.85rem; padding: 0.3rem 0.4rem; }
        @media print { .no-print { display: none !important; } }
    </style>
</head>
<body>

<nav class="navbar bg-white shadow-sm">
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
                <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    
    {% block content %}{% endblock %}
</main>

<footer class="text-center text-muted py-3 small">
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
<div class="d-flex align-items-center justify-content-between mb-3">
    <h4 class="m-0">📦 Visualizza Giacenze</h4>
    <a href="{{ url_for('new_row') }}" class="btn btn-success no-print"><i class="bi bi-plus-circle"></i> Aggiungi Articolo</a>
</div>

<div class="card p-3 mb-3 no-print">
    <form class="row g-2 align-items-end" method="get">
        <div class="col-md-1"><label class="form-label small">ID</label><input name="id" value="{{ request.args.get('id', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2"><label class="form-label small">Cod.Art.</label><input name="codice_articolo" value="{{ request.args.get('codice_articolo', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2"><label class="form-label small">Cliente</label><input name="cliente" value="{{ request.args.get('cliente', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2"><label class="form-label small">Commessa</label><input name="commessa" value="{{ request.args.get('commessa', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2"><label class="form-label small">Posizione</label><input name="posizione" value="{{ request.args.get('posizione', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2"><label class="form-label small">Stato</label><input name="stato" value="{{ request.args.get('stato', '') }}" class="form-control form-control-sm"></div>
        <div class="col-md-2 d-grid"><button class="btn btn-primary btn-sm mt-3">Filtra</button></div>
        <div class="col-md-2 d-grid"><a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm mt-3">Pulisci Filtri</a></div>
    </form>
</div>

<div class="card p-3">
    <div class="d-flex flex-wrap gap-2 mb-3 no-print border-bottom pb-3">
        <button class="btn btn-outline-secondary btn-sm" onclick="submitForm('{{ url_for('buono_preview') }}', 'post')"><i class="bi bi-receipt"></i> Crea Buono</button>
        <button class="btn btn-outline-secondary btn-sm" onclick="submitForm('{{ url_for('ddt_preview') }}', 'post')"><i class="bi bi-truck"></i> Crea DDT</button>
        {% if session.get('role') == 'admin' %}
        <button class="btn btn-info btn-sm text-white" onclick="submitForm('{{ url_for('bulk_edit') }}', 'get')"><i class="bi bi-pencil-square"></i> Modifica Multipla</button>
        <button class="btn btn-danger btn-sm" onclick="submitDeleteForm()"><i class="bi bi-trash"></i> Elimina Selezionati</button>
        {% endif %}
    </div>

    <form id="selection-form" method="post">
        <div class="table-responsive" style="max-height:70vh">
            <table class="table table-sm table-hover table-compact align-middle">
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
                    <tr>
                        <td class="no-print"><input type="checkbox" name="ids" class="sel" value="{{ r.id_articolo }}"></td>
                        {% for c in cols %}
                            {% set v = getattr(r, c) %}
                            <td>{% if c in ['data_ingresso','data_uscita'] %}{{ v|fmt_date }}{% else %}{{ v or '' }}{% endif %}</td>
                        {% endfor %}
                        <td>
                            {% for a in r.attachments %}
                            <a class="badge text-bg-secondary text-decoration-none" href="{{ url_for('media', att_id=a.id) }}" target="_blank">
                                <i class="bi {% if a.kind == 'doc' %}bi-file-pdf{% else %}bi-image{% endif %}"></i> {{ a.kind }}
                            </a>
                            {% endfor %}
                        </td>
                        <td class="no-print"><a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_row', id=r.id_articolo) }}">Modifica</a></td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="{{ cols|length + 3 }}" class="text-center text-muted">Nessun articolo trovato.</td>
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
            return;
        }
        const form = document.getElementById('selection-form');
        form.action = actionUrl;
        form.method = method;
        form.submit();
    }
    
    function submitDeleteForm() {
        const ids = getSelectedIds();
        if (ids.length === 0) {
            alert('Seleziona almeno una riga');
            return;
        }
        if (confirm(`Sei sicuro di voler eliminare definitivamente ${ids.length} articoli selezionati? L'azione è irreversibile.`)) {
            submitForm('{{ url_for('bulk_delete') }}', 'post');
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
    <p class="text-muted">Stai modificando {{ rows|length }} articoli selezionati. I campi lasciati vuoti non verranno modificati.</p>
    <hr>
    <form method="post">
        <input type="hidden" name="ids" value="{{ ids_csv }}">
        <div class="row g-3">
            <div class="col-md-6">
                <label class="form-label">Nuova Posizione</label>
                <input name="posizione" class="form-control" placeholder="es. A-01-01">
            </div>
            <div class="col-md-6">
                <label class="form-label">Nuovo Stato</label>
                <input name="stato" class="form-control" placeholder="es. IN TRANSITO">
            </div>
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
                <button type="button" class="btn btn-primary" onclick="document.getElementById('ddt-form').action='{{ url_for('pdf_ddt') }}'; document.getElementById('ddt-form').target='_blank'; document.getElementById('ddt-form').submit();">
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
        </div>
        <hr>
        <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle">
                <thead><tr><th>ID</th><th>Cod.Art.</th><th>Descrizione</th><th style="width:110px">Colli</th><th style="width:110px">Peso</th><th>N.Arrivo</th></tr></thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td>{{ r.id_articolo }}</td>
                        <td>{{ r.codice_articolo or '' }}</td>
                        <td>{{ r.descrizione or '' }}</td>
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
document.getElementById('get-next-ddt').addEventListener('click', function() {
    fetch('{{ url_for('get_next_ddt_number') }}')
        .then(response => response.json())
        .then(data => {
            document.getElementById('n_ddt_input').value = data.next_ddt;
        })
        .catch(error => console.error('Error fetching next DDT number:', error));
});
</script>
{% endblock %}
"""

LABELS_FORM_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-tag"></i> Nuova Etichetta (99,82×61,98 mm)</h3>
    <hr>
    <form method="post" action="{{ url_for('labels_preview') }}">
        <div class="row g-3">
            <div class="col-md-4"><label class="form-label">Cliente</label><input name="cliente" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Ordine</label><input name="ordine" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Commessa</label><input name="commessa" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">DDT Ingresso</label><input name="ddt_ingresso" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Data Ingresso</label><input name="data_ingresso" class="form-control" placeholder="gg/mm/aaaa"></div>
            <div class="col-md-4"><label class="form-label">Arrivo (es. 01/24)</label><input name="arrivo" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">N. Colli</label><input name="n_colli" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Posizione</label><input name="posizione" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Protocollo</label><input name="protocollo" class="form-control"></div>
        </div>
        <div class="mt-4 d-flex gap-2">
            <button class="btn btn-primary"><i class="bi bi-eye"></i> Anteprima / Stampa</button>
            <button type="submit" formaction="{{ url_for('labels_pdf') }}" class="btn btn-outline-primary" target="_blank"><i class="bi bi-file-pdf"></i> Apri solo PDF</button>
        </div>
    </form>
</div>
{% endblock %}
"""

LABELS_PREVIEW_HTML = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        @media print { .no-print { display: none } body { margin: 0 } }
        .logo { height: 26px; margin-right: 10px; }
        .wrap { 
            width: 99.82mm; 
            height: 61.98mm; 
            padding: 4mm; 
            border: 1px solid #ccc; 
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            font-family: 'Helvetica', sans-serif;
        }
        .row-line { font-size: 11pt; line-height: 1.35; margin: 0; }
        .key { font-weight: bold; }
    </style>
</head>
<body class="p-4 bg-light">
    <div class="no-print mb-3 d-flex gap-2">
        <button class="btn btn-primary" onclick="window.print()"><i class="bi bi-printer"></i> Stampa</button>
        <a class="btn btn-outline-secondary" href="{{ url_for('labels_form') }}">Indietro</a>
    </div>
    <div class="wrap bg-white">
        <div class="d-flex align-items-center mb-2">
            {% if logo_url %}<img src="{{ logo_url }}" class="logo" alt="logo">{% endif %}
            <h5 class="m-0" style="font-size: 12pt;">Camar S.r.l.</h5>
        </div>
        <p class="row-line"><span class="key">CLIENTE:</span> {{ d.cliente }}</p>
        <p class="row-line"><span class="key">FORNITORE:</span> {{ d.fornitore }}</p>
        <p class="row-line"><span class="key">ORDINE:</span> {{ d.ordine }}</p>
        <p class="row-line"><span class="key">COMMESSA:</span> {{ d.commessa }}</p>
        <p class="row-line"><span class="key">DDT:</span> {{ d.ddt_ingresso }}</p>
        <p class="row-line"><span class="key">DATA ING.:</span> {{ d.data_ingresso }}</p>
        <p class="row-line"><span class="key">ARRIVO:</span> {{ d.arrivo }}</p>
        <p class="row-line"><span class="key">POSIZIONE:</span> {{ d.posizione }}</p>
        <p class="row-line"><span class="key">COLLI:</span> {{ d.n_colli }}</p>
    </div>
</body>
</html>
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
}

# --- APP FLASK ---
app = Flask(__name__)
# Configura il loader per usare i template definiti sopra nel dizionario
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

# Rende la funzione logo_url disponibile a tutti i template automaticamente
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

# --- FUNZIONI PLACEHOLDER ---
@app.route('/import_excel')
@login_required
def import_excel():
    flash("Funzione di import Excel non ancora attiva.", "info")
    return redirect(url_for('home'))

# --- GESTIONE ARTICOLI (CRUD) ---
@app.get('/new')
@login_required
def new_row():
    db = SessionLocal()
    a = Articolo(data_ingresso=datetime.today().strftime("%Y-%m-%d"))
    db.add(a)
    db.commit()
    flash('Articolo vuoto creato. Ora puoi compilare i campi.', 'info')
    return redirect(url_for('edit_row', id=a.id_articolo))

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db = SessionLocal()
    row = db.get(Articolo, id)
    if not row:
        abort(404)

    if request.method == 'POST':
        fields_to_update = [
            'codice_articolo','pezzo','larghezza','lunghezza','altezza','protocollo','ordine','commessa',
            'magazzino','fornitore','data_ingresso','n_ddt_ingresso','cliente','descrizione','peso','n_colli',
            'posizione','n_arrivo','buono_n','note','serial_number','data_uscita','n_ddt_uscita','ns_rif',
            'stato','mezzi_in_uscita'
        ]
        numeric_float = {'larghezza','lunghezza','altezza','peso','m2','m3'}
        numeric_int   = {'n_colli'}

        for f in fields_to_update:
            v = request.form.get(f) or None
            if f in ('data_ingresso','data_uscita'):
                v = parse_date_ui(v) if v else None
            elif f in numeric_float:
                v = to_float_eu(v)
            elif f in numeric_int:
                v = to_int_eu(v)
            setattr(row, f, v)

        row.m2, row.m3 = calc_m2_m3(row.lunghezza, row.larghezza, row.altezza, row.n_colli)

        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if not f or not f.filename:
                    continue
                safe_name = f"{id}_{uuid.uuid4().hex}_{f.filename.replace(' ','_')}"
                ext = os.path.splitext(safe_name)[1].lower()
                kind = 'doc' if ext == '.pdf' else 'foto'
                folder = DOCS_DIR if kind == 'doc' else PHOTOS_DIR
                f.save(str(folder / safe_name))
                db.add(Attachment(articolo_id=id, kind=kind, filename=safe_name))

        db.commit()
        flash('Riga salvata', 'success')
        return redirect(url_for('giacenze'))

    fields_labels = [
        ('Codice Articolo','codice_articolo'),('Descrizione','descrizione'),('Cliente','cliente'),
        ('Protocollo','protocollo'),('Ordine','ordine'),('Peso (Kg)','peso'),('N° Colli','n_colli'),
        ('Posizione','posizione'),('Stato','stato'),('N° Arrivo','n_arrivo'),('Buono N°','buono_n'),
        ('Fornitore','fornitore'),('Magazzino','magazzino'),
        ('Data Ingresso (GG/MM/AAAA)','data_ingresso'),('Data Uscita (GG/MM/AAAA)','data_uscita'),
        ('N° DDT Ingresso','n_ddt_ingresso'),('N° DDT Uscita','n_ddt_uscita'),
        ('Larghezza (m)','larghezza'),('Lunghezza (m)','lunghezza'),('Altezza (m)','altezza'),
        ('Serial Number','serial_number'),('NS Rif','ns_rif'),('Mezzi in Uscita','mezzi_in_uscita'),('Note','note')
    ]
    return render_template('edit.html', row=row, fields=fields_labels)

# --- MEDIA & ALLEGATI ---
@app.get('/attachment/<int:att_id>/delete')
@login_required
def delete_attachment(att_id):
    db = SessionLocal()
    att = db.get(Attachment, att_id)
    if att:
        path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
        articolo_id = att.articolo_id
        db.delete(att)
        db.commit()
        flash('Allegato eliminato', 'success')
        return redirect(url_for('edit_row', id=articolo_id))
    return redirect(url_for('giacenze'))

@app.get('/media/<int:att_id>')
@login_required
def media(att_id):
    db = SessionLocal()
    att = db.get(Attachment, att_id)
    if not att:
        abort(404)
    path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=False)

# --- VISUALIZZA GIACENZE E AZIONI MULTIPLE ---
@app.get('/giacenze')
@login_required
def giacenze():
    db = SessionLocal()
    qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())
    if session.get('role') == 'client':
        qs = qs.filter(Articolo.cliente == session['user'])
    
    # Filtri di ricerca
    like_cols = ['codice_articolo','cliente','fornitore','commessa','posizione', 'stato']
    if request.args.get('id'):
        try:
            qs = qs.filter(Articolo.id_articolo == int(request.args.get('id')))
        except ValueError:
            pass
    for col in like_cols:
        v = request.args.get(col)
        if v:
            qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))

    rows = qs.all()
    cols = ["id_articolo","codice_articolo","descrizione","cliente","fornitore","protocollo","ordine",
            "commessa","magazzino","posizione","stato","peso","n_colli","data_ingresso","data_uscita",
            "n_ddt_uscita", "mezzi_in_uscita"]

    return render_template('giacenze.html', rows=rows, cols=cols)

@app.route('/bulk/edit', methods=['GET', 'POST'])
@login_required
def bulk_edit():
    db = SessionLocal()
    if request.method == 'POST':
        ids = [int(i) for i in request.form.getlist('ids')]
        new_posizione = request.form.get('posizione', '').strip()
        new_stato = request.form.get('stato', '').strip()
        
        if not new_posizione and not new_stato:
            flash("Nessuna modifica inserita. Specificare almeno un nuovo valore.", "warning")
            return redirect(url_for('giacenze'))

        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        for art in articoli:
            if new_posizione:
                art.posizione = new_posizione
            if new_stato:
                art.stato = new_stato
        db.commit()
        flash(f"{len(articoli)} articoli aggiornati con successo.", "success")
        return redirect(url_for('giacenze'))

    # Metodo GET
    ids_csv = request.args.get('ids', '')
    ids = [int(i) for i in ids_csv.split(',') if i.isdigit()]
    if not ids:
        flash("Nessun articolo selezionato per la modifica.", "warning")
        return redirect(url_for('giacenze'))
    
    rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
    return render_template('bulk_edit.html', rows=rows, ids_csv=ids_csv)

@app.post('/bulk/delete')
@login_required
def bulk_delete():
    ids = [int(i) for i in request.form.getlist('ids')]
    if not ids:
        flash("Nessun articolo selezionato per l'eliminazione.", "warning")
        return redirect(url_for('giacenze'))
    
    db = SessionLocal()
    db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).delete(synchronize_session=False)
    db.commit()
    flash(f"{len(ids)} articoli eliminati con successo.", "success")
    return redirect(url_for('giacenze'))

# --- ANTEPRIME HTML (BUONO / DDT) ---
def _get_rows_from_ids(ids_list):
    if not ids_list: return []
    db=SessionLocal()
    return db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()

@app.post('/buono/preview')
@login_required
def buono_preview():
    ids = [int(i) for i in request.form.getlist('ids')]
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
    ids = [int(i) for i in request.form.getlist('ids')]
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
PRIMARY_COLOR = colors.HexColor("#1f6fb2")

def _pdf_table(data, col_widths=None, header=True, hAlign='LEFT'):
    t = Table(data, colWidths=col_widths, hAlign=hAlign)
    style = [
        ('FONT', (0,0), (-1,-1), 'Helvetica', 9), ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]
    if header and data:
        style.extend([
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke), ('FONT', (0,0), (-1,0), 'Helvetica-Bold', 9)
        ])
    t.setStyle(TableStyle(style))
    return t

def _copyright_para():
    tiny_style = _styles['Normal'].clone('copyright')
    tiny_style.fontSize = 7; tiny_style.textColor = colors.grey; tiny_style.alignment = 1
    return Paragraph("© Alessia Moncalvo — Gestionale Camar Web Edition", tiny_style)

def _doc_with_header(title, pagesize=A4):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=pagesize, leftMargin=15*mm, rightMargin=15*mm, topMargin=12*mm, bottomMargin=12*mm)
    story = []
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=40*mm, height=15*mm))
        story.append(Spacer(1, 4))
    title_style = _styles['Heading2'].clone('title_bar')
    title_style.textColor = colors.white; title_style.alignment = 1
    title_tbl = Table([[Paragraph(title, title_style)]], colWidths=[doc.width],
        style=[('BACKGROUND',(0,0),(-1,-1),PRIMARY_COLOR), ('PADDING',(0,0),(-1,-1),6)])
    story.extend([title_tbl, Spacer(1, 8)])
    return doc, story, bio

def _generate_ddt_pdf(n_ddt, data_ddt, targa, note, dest, rows):
    doc, story, bio = _doc_with_header("DOCUMENTO DI TRASPORTO (DDT)")
    mitt_text = "<b>Camar S.r.l.</b><br/>Via Luigi Canepa 2<br/>16165 Genova Struppa (GE)<br/>P.IVA 024 Camar Srl"
    mitt_tbl = _pdf_table([["Mittente", Paragraph(mitt_text, _styles['Normal'])]], [25*mm, None], header=False)
    dest_text = f"<b>{dest.get('ragione_sociale','')}</b>"
    if dest.get('indirizzo'): dest_text += f"<br/>{dest['indirizzo']}"
    if dest.get('piva'): dest_text += f"<br/>P.IVA {dest['piva']}"
    dest_tbl = _pdf_table([["Destinatario", Paragraph(dest_text, _styles['Normal'])]], [25*mm, None], header=False)
    header_tbl = Table([[mitt_tbl, dest_tbl]], colWidths=[doc.width/2 - 1*mm, doc.width/2 - 1*mm], style=[('VALIGN',(0,0),(-1,-1),'TOP')])
    story.append(header_tbl)
    story.append(Spacer(1, 8))
    info = [["N. DDT", n_ddt], ["Data DDT", fmt_date(data_ddt)], ["Targa", targa]]
    story.append(_pdf_table(info, [25*mm, None], header=False))
    story.append(Spacer(1, 8))
    data = [['ID','Cod.Art.','Descrizione','Colli','Peso (Kg)','N.Arrivo']]
    tot_colli, tot_peso = 0, 0.0
    for r in rows:
        colli, peso = (r.n_colli or 1), (r.peso or 0)
        data.append([r.id_articolo, r.codice_articolo or '', r.descrizione or '', colli, peso, r.n_arrivo or ''])
        tot_colli += colli; tot_peso += float(peso)
    story.append(_pdf_table(data, col_widths=[16*mm, 38*mm, None, 20*mm, 20*mm, 22*mm]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Totale Colli:</b> {tot_colli} &nbsp;&nbsp;&nbsp; <b>Totale Peso:</b> {tot_peso:.2f} Kg", _styles['Normal']))
    story.extend([Spacer(1, 8), _copyright_para()])
    doc.build(story)
    bio.seek(0)
    return bio

@app.post('/pdf/ddt')
@login_required
def pdf_ddt():
    rows = _get_rows_from_ids([int(i) for i in request.form.get('ids','').split(',')])
    dest = load_destinatari().get(request.form.get('dest_key'), {})
    pdf_bio = _generate_ddt_pdf(
        n_ddt=request.form.get('n_ddt', ''), data_ddt=request.form.get('data_ddt'), targa=request.form.get('targa'),
        note=request.form.get('note'), dest=dest, rows=rows
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
    db.commit()
    
    dest = load_destinatari().get(request.form.get('dest_key'), {})
    pdf_bio = _generate_ddt_pdf(
        n_ddt=n_ddt, data_ddt=data_ddt, targa=request.form.get('targa'),
        note=request.form.get('note'), dest=dest, rows=articoli
    )
    
    flash(f"{len(articoli)} articoli scaricati con successo. DDT N.{n_ddt} generato.", "success")
    
    download_name = f"DDT_{n_ddt.replace('/', '-')}_{data_ddt}.pdf"
    response = send_file(pdf_bio, as_attachment=True, download_name=download_name, mimetype='application/pdf')
    
    # Questo è un trucco per reindirizzare dopo il download
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

@app.post('/labels/preview')
@login_required
def labels_preview():
    data = _labels_clean_data(request.form)
    return render_template('labels_preview.html', d=data)

@app.post('/labels/pdf')
@login_required
def labels_pdf():
    d = _labels_clean_data(request.form)
    pagesize = (99.82*mm, 61.98*mm)
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=pagesize, leftMargin=4*mm, rightMargin=4*mm, topMargin=3*mm, bottomMargin=3*mm)
    story = []
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=24*mm, height=8*mm))
        story.append(Spacer(1, 2))

    row_style = _styles['Normal'].clone('label_line')
    row_style.fontName = 'Helvetica-Bold'; row_style.fontSize = 11; row_style.leading = 13.5

    def P(label, value):
        return Paragraph(f"{label}: <b>{value or ''}</b>", row_style)

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
    # debug=True è utile in sviluppo, ma va impostato a False in produzione
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)




