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
from urllib.parse import unquote
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict
from functools import wraps
from werkzeug.utils import secure_filename
import pdfplumber
from collections import defaultdict
from datetime import timedelta

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
import os
from flask_mail import Mail

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


# =========================
# Helpers debug mappe file
# =========================

# --- ASSICURATI DI AVERE QUESTI IMPORT IN ALTO ---
from datetime import datetime, date, timedelta
import pandas as pd

# --- AGGIUNGI QUESTA FUNZIONE HELPER (fuori dalle rotte) ---
def to_date_db(val):
    """
    Converte val in datetime.date (per DB).
    Gestisce: datetime/date, pandas Timestamp, numeri Excel (seriali), stringhe.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val) or val == '':
        return None

    # pandas Timestamp / datetime / date
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    # Excel serial date (es. 45234)
    if isinstance(val, (int, float)):
        try:
            # Excel origin: 1899-12-30
            return (datetime(1899, 12, 30) + timedelta(days=int(val))).date()
        except Exception:
            return None

    # Stringa
    s = str(val).strip()
    if not s:
        return None

    # Tentativi di parsing formati comuni
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    # Ultima spiaggia: pandas to_datetime
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if not pd.isna(dt):
            return dt.date()
    except Exception:
        pass
        
    return None

def _file_digest(p: Path) -> str:
    """MD5 del file (per capire se su Render stai usando davvero la versione corretta)."""
    try:
        data = p.read_bytes()
        return hashlib.md5(data).hexdigest()
    except Exception:
        return "N/A"


app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))

app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'

app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

mail = Mail(app)

# ========================================================
# 2. CONFIGURAZIONE PATH E FILES
# ========================================================
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = APP_DIR / "static"

# --- GESTIONE DISCO PERSISTENTE (Percorso Forzato) ---
persistent_path = "/var/data/app"

if os.path.exists(persistent_path):
    # Se la cartella del disco esiste fisicamente, usala!
    MEDIA_DIR = Path(persistent_path)
    print(f"✅ USO DISCO PERSISTENTE RENDER: {MEDIA_DIR}")
else:
    # Altrimenti usa cartella locale
    MEDIA_DIR = APP_DIR / "media"
    print(f"⚠️ USO DISCO LOCALE (Temporaneo): {MEDIA_DIR}")

DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"

# --- CONFIGURAZIONE FILE MAPPE EXCEL ---
# Definiamo qui i percorsi esatti per evitare confusione
MAPPE_FILE_PERSISTENT = MEDIA_DIR / "mappe_excel.json"        # File modificabile (nel disco dati)
MAPPE_FILE_ORIGINAL = APP_DIR / "config" / "mappe_excel.json" # File originale (da GitHub)

# Crea le cartelle se non esistono
for d in (STATIC_DIR, MEDIA_DIR, DOCS_DIR, PHOTOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

def _discover_logo_path():
    # Lista aggiornata con il nome corretto del tuo file
    possible_names = [
        "logo camar.jpg",  # <--- Questo è quello che hai su GitHub
        "logo.png", 
        "logo.jpg", 
        "logo.jpeg", 
        "logo_camar.png"
    ]
    
    print(f"DEBUG: Cerco logo in {STATIC_DIR}")
    
    for name in possible_names:
        p = STATIC_DIR / name
        if p.exists(): 
            print(f"DEBUG: Logo TROVATO: {p}")
            return str(p)
            
    print("DEBUG: NESSUN logo trovato.")
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
    lotto = Column(Text) # <--- AGGIUNGI QUESTA

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, Identity(start=1), primary_key=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo", ondelete='CASCADE'), nullable=False)
    kind = Column(String(10)); filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)




# --- NUOVI MODELLI PER TRASPORTI E LAVORAZIONI ---

class Trasporto(Base):
    __tablename__ = 'trasporti'
    id = Column(Integer, primary_key=True)
    data = Column(Text)          # Salviamo come Text per uniformità
    cliente = Column(Text)
    trasportatore = Column(Text)
    tipo_mezzo = Column(Text)
    ddt_uscita = Column(Text)
    costo = Column(Float)
    consolidato = Column(Text)   # Si/No o altro

class Lavorazione(Base):
    __tablename__ = 'lavorazioni'
    id = Column(Integer, primary_key=True)
    data = Column(Text)
    cliente = Column(Text)
    descrizione = Column(Text)
    ore_white_collar = Column(Float)
    ore_blue_collar = Column(Float)
    pallet_forniti = Column(Integer)
    note = Column(Text)

# ========================================================
# 5. GESTIONE UTENTI (Definizione PRIMA dell'uso)
# ========================================================
DEFAULT_USERS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'MARINE INTERIORS': 'Struppa09', 'GALLVANO': 'Struppa10','OPS': '271214',
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


# --- HELPER ESTRAZIONE PDF (Necessario per Import PDF) ---
def extract_data_from_ddt_pdf(path):
    import pdfplumber
    extracted_rows = []
    meta = {'cliente': '', 'commessa': '', 'n_ddt': '', 'data_ingresso': date.today().strftime("%Y-%m-%d"), 'fornitore': ''}
    
    try:
        with pdfplumber.open(path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"
                lines = text.split('\n')
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) < 2: continue
                    
                    qty = 1
                    desc = line.strip()
                    code = ""
                    found_q = False
                    
                    # Cerca quantità (numeri isolati piccoli)
                    for i, p in enumerate(parts):
                        if p.isdigit() and len(p) < 4:
                            qty = int(p)
                            desc = line.replace(p, "", 1).strip()
                            found_q = True
                            break
                    
                    # Cerca codice (parola lunga all'inizio)
                    if len(parts[0]) > 3 and not parts[0].isdigit():
                        code = parts[0]
                        desc = desc.replace(code, "", 1).strip()
                    
                    if found_q or code:
                        extracted_rows.append({'codice': code, 'descrizione': desc, 'qta': qty})
    except Exception as e:
        print(f"Errore lettura PDF: {e}")
        
    return meta, extracted_rows
    
def is_blank(v):
    try:
        if pd.isna(v): return True
    except Exception: pass
    return (v is None) or (isinstance(v, str) and not v.strip())

def to_float_eu(val):
    """Converte stringa '1,2' in float 1.2. Se vuoto o errore, restituisce 0.0"""
    if not val:
        return 0.0
    if isinstance(val, (float, int)):
        return float(val)
    try:
        # Sostituisce virgola con punto e rimuove spazi
        return float(str(val).replace(',', '.').strip())
    except:
        return 0.0

def to_int_eu(val):
    """Converte stringa in intero sicuro."""
    if not val:
        return 0
    try:
        return int(float(str(val).replace(',', '.')))
    except:
        return 0
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

def calc_m2_m3(L, P, H, colli=1):
    """Calcola M2 e M3 basandosi su metri o centimetri."""
    # Convertiamo tutto in float
    l = to_float_eu(L)
    p = to_float_eu(P)
    h = to_float_eu(H)
    c = max(1, to_int_eu(colli))

    # Logica intelligente: se le misure sono grandi (>10), assumiamo siano CM e convertiamo in METRI
    # Esempio: 120 -> 1.20
    if l > 10: l /= 100.0
    if p > 10: p /= 100.0
    if h > 10: h /= 100.0

    m3 = l * p * h * c
    # M2: Spesso si intende l'ingombro a terra (L x P) oppure la superficie. 
    # Qui calcoliamo L * P * Colli (Floor space)
    m2 = l * p * c
    
    return round(m2, 4), round(m3, 4)

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
IMPORT_PDF_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-file-earmark-pdf"></i> Importa Articoli da PDF (DDT/Bolla)</h3>
    
    {% if not rows %}
    <div class="alert alert-info">
        Carica un DDT in formato PDF digitale. Il sistema tenterà di leggere codici e quantità.<br>
        <b>Nota:</b> Funziona meglio con PDF generati da computer, non scansioni.
    </div>
    <form method="post" enctype="multipart/form-data" class="mt-4">
        <div class="mb-3">
            <label class="form-label">Seleziona File PDF</label>
            <input type="file" name="file" class="form-control" accept=".pdf" required>
        </div>
        <button type="submit" class="btn btn-primary">Analizza PDF</button>
        <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
    </form>
    {% endif %}

    {% if rows %}
    <form action="{{ url_for('save_pdf_import') }}" method="post">
        <div class="row g-3 mb-3 bg-light p-3 rounded border">
            <h5 class="mb-3">Dati Testata (Rilevati o da compilare)</h5>
            <div class="col-md-3">
                <label>Cliente</label>
                <input name="cliente" class="form-control" value="{{ meta.cliente }}">
            </div>
            <div class="col-md-3">
                <label>Fornitore</label>
                <input name="fornitore" class="form-control" value="{{ meta.fornitore }}">
            </div>
            <div class="col-md-2">
                <label>Commessa</label>
                <input name="commessa" class="form-control" value="{{ meta.commessa }}">
            </div>
            <div class="col-md-2">
                <label>N. DDT</label>
                <input name="n_ddt" class="form-control" value="{{ meta.n_ddt }}">
            </div>
            <div class="col-md-2">
                <label>Data Ingresso</label>
                <input type="date" name="data_ingresso" class="form-control" value="{{ meta.data_ingresso }}">
            </div>
        </div>

        <div class="table-responsive">
            <table class="table table-striped table-sm align-middle">
                <thead class="table-dark">
                    <tr>
                        <th>Rimuovi</th>
                        <th>Codice Articolo</th>
                        <th>Descrizione</th>
                        <th style="width:100px">Q.tà (Colli)</th>
                    </tr>
                </thead>
                <tbody id="rowsBody">
                    {% for r in rows %}
                    <tr>
                        <td class="text-center"><button type="button" class="btn btn-danger btn-sm py-0" onclick="this.closest('tr').remove()">X</button></td>
                        <td><input name="codice[]" class="form-control form-control-sm" value="{{ r.codice }}"></td>
                        <td><input name="descrizione[]" class="form-control form-control-sm" value="{{ r.descrizione }}"></td>
                        <td><input name="qta[]" type="number" class="form-control form-control-sm" value="{{ r.qta }}"></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="d-flex justify-content-between mt-3">
            <button type="button" class="btn btn-secondary btn-sm" onclick="addRow()">+ Aggiungi Riga Vuota</button>
            <div>
                <a href="{{ url_for('import_pdf') }}" class="btn btn-outline-secondary">Ricomincia</a>
                <button type="submit" class="btn btn-success fw-bold px-4">CONFERMA E IMPORTA</button>
            </div>
        </div>
    </form>

    <script>
    function addRow() {
        const tbody = document.getElementById('rowsBody');
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="text-center"><button type="button" class="btn btn-danger btn-sm py-0" onclick="this.closest('tr').remove()">X</button></td>
            <td><input name="codice[]" class="form-control form-control-sm"></td>
            <td><input name="descrizione[]" class="form-control form-control-sm"></td>
            <td><input name="qta[]" type="number" class="form-control form-control-sm" value="1"></td>
        `;
        tbody.appendChild(tr);
    }
    </script>
    {% endif %}
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
    .table-compact td, .table-compact th { font-size: 0.8rem; padding: 4px 5px; vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px; }
    .table-compact th { background-color: #f0f0f0; font-weight: 600; text-align: center; }
    .fw-buono { font-weight: bold; color: #000; }
    .att-link { text-decoration: none; font-size: 1.3em; cursor: pointer; margin: 0 3px; }
    .att-link:hover { transform: scale(1.2); display:inline-block; }
</style>

<div class="d-flex justify-content-between align-items-center mb-2">
    <h4>Magazzino</h4>
    <div class="d-flex gap-2">
       <a href="{{ url_for('nuovo_articolo') }}" class="btn btn-sm btn-success">Nuovo</a>
       <a href="{{ url_for('import_pdf') }}" class="btn btn-sm btn-dark">Import PDF</a>
       <a href="{{ url_for('labels_form') }}" class="btn btn-sm btn-info text-white">Etichette</a>
       <a href="{{ url_for('calcola_costi') }}" class="btn btn-sm btn-warning">Calcoli</a>
    </div>
</div>

<div class="card mb-2 bg-light">
    <div class="card-header py-1" data-bs-toggle="collapse" data-bs-target="#filterBody" style="cursor:pointer">
        <small><i class="bi bi-funnel"></i> <b>Filtri Avanzati</b></small>
    </div>
    <div id="filterBody" class="collapse {% if request.args %}show{% endif %}">
        <div class="card-body py-2">
            <form method="get">
                <div class="row g-1 mb-1">
                    <div class="col-md-2"><input name="fornitore" class="form-control form-control-sm" placeholder="Fornitore" value="{{ request.args.get('fornitore','') }}"></div>
                    <div class="col-md-2"><input name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ request.args.get('cliente','') }}"></div>
                    <div class="col-md-1"><input name="id" class="form-control form-control-sm" placeholder="ID" value="{{ request.args.get('id','') }}"></div>
                    <div class="col-md-2"><input name="n_ddt_ingresso" class="form-control form-control-sm" placeholder="N. DDT Ing" value="{{ request.args.get('n_ddt_ingresso','') }}"></div>
                    <div class="col-md-2"><input name="protocollo" class="form-control form-control-sm" placeholder="Protocollo" value="{{ request.args.get('protocollo','') }}"></div>
                    <div class="col-md-2"><input name="ordine" class="form-control form-control-sm" placeholder="Ordine" value="{{ request.args.get('ordine','') }}"></div>
                    <div class="col-md-1"><button type="submit" class="btn btn-primary btn-sm w-100">Cerca</button></div>
                </div>
                <div class="row g-1 mb-1">
                    <div class="col-md-2"><input name="commessa" class="form-control form-control-sm" placeholder="Commessa" value="{{ request.args.get('commessa','') }}"></div>
                    <div class="col-md-2"><input name="n_arrivo" class="form-control form-control-sm" placeholder="N. Arrivo" value="{{ request.args.get('n_arrivo','') }}"></div>
                    <div class="col-md-2"><input name="magazzino" class="form-control form-control-sm" placeholder="Magazzino" value="{{ request.args.get('magazzino','') }}"></div>
                    <div class="col-md-2"><input name="serial_number" class="form-control form-control-sm" placeholder="Serial No" value="{{ request.args.get('serial_number','') }}"></div>
                    <div class="col-md-2"><input name="codice_articolo" class="form-control form-control-sm" placeholder="Codice Art" value="{{ request.args.get('codice_articolo','') }}"></div>
                    <div class="col-md-2"><input name="stato" class="form-control form-control-sm" placeholder="Stato" value="{{ request.args.get('stato','') }}"></div>
                </div>
                <div class="row g-1 align-items-center">
                    <div class="col-md-5">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Ingresso</span>
                            <input name="data_ing_da" type="date" class="form-control" value="{{ request.args.get('data_ing_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_ing_a" type="date" class="form-control" value="{{ request.args.get('data_ing_a','') }}">
                        </div>
                    </div>
                    <div class="col-md-5">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Uscita</span>
                            <input name="data_usc_da" type="date" class="form-control" value="{{ request.args.get('data_usc_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_usc_a" type="date" class="form-control" value="{{ request.args.get('data_usc_a','') }}">
                        </div>
                    </div>
                    <div class="col-md-2 text-end">
                        <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm w-100" onclick="localStorage.removeItem('camar_selected_articles');">Reset</a>
                    </div>
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
        <button type="submit" formaction="{{ url_for('labels_pdf') }}" class="btn btn-warning btn-sm"><i class="bi bi-download"></i> Scarica Etichette</button>
        <button type="submit" formaction="{{ url_for('delete_rows') }}" class="btn btn-danger btn-sm" onclick="return confirm('Eliminare?')">Elimina</button>
    </div>

    <div class="table-responsive" style="max-height: 70vh;">
        <table class="table table-striped table-bordered table-hover table-compact mb-0">
            <thead class="sticky-top" style="top:0; z-index:5;">
                <tr>
                    <th><input type="checkbox" onclick="toggleAll(this)"></th>
                    <th>ID</th> <th>Doc</th> <th>Foto</th> <th>Codice</th> <th>Descrizione</th>
                    <th>Cliente</th> <th>Fornitore</th> <th>Commessa</th> <th>Ordine</th> <th>Protocollo</th>
                    <th>Buono</th> <th>N.Arr</th> <th>Data Ing</th> <th>DDT Ing</th> <th>Pos</th> <th>Stato</th>
                    <th>Pz</th> <th>Colli</th> <th>Kg</th> <th>LxPxH</th> 
                    <th>Lotto</th> <th>M2</th> <th>M3</th> <th>Act</th>
                </tr>
            </thead>
            <tbody>
                {% for r in rows %}
                <tr>
                    <td class="text-center"><input type="checkbox" name="ids" value="{{ r.id_articolo }}" class="row-checkbox"></td>
                    <td>{{ r.id_articolo }}</td>
                    
                    <td class="text-center">
                        {% for a in r.attachments if a.kind=='doc' %}
                        <a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank" class="att-link" title="{{ a.filename }}">📄</a>
                        {% endfor %}
                    </td>
                    <td class="text-center">
                        {% for a in r.attachments if a.kind=='photo' %}
                        <a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank" class="att-link" title="{{ a.filename }}">📷</a>
                        {% endfor %}
                    </td>

                    <td title="{{ r.codice_articolo }}">{{ r.codice_articolo or '' }}</td>
                    <td title="{{ r.descrizione }}">{{ r.descrizione or '' }}</td>
                    <td>{{ r.cliente or '' }}</td>
                    <td>{{ r.fornitore or '' }}</td>
                    <td>{{ r.commessa or '' }}</td>
                    <td>{{ r.ordine or '' }}</td>
                    <td>{{ r.protocollo or '' }}</td>
                    <td class="fw-buono">{{ r.buono_n or '' }}</td>
                    <td>{{ r.n_arrivo or '' }}</td>
                    <td>{{ r.data_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_ingresso or '' }}</td>
                    <td>{{ r.posizione or '' }}</td>
                    <td>{{ r.stato or '' }}</td>
                    <td>{{ r.pezzo or '' }}</td>
                    <td>{{ r.n_colli or '' }}</td>
                    <td>{{ r.peso or '' }}</td>
                    <td>{{ r.lunghezza|int }}x{{ r.larghezza|int }}x{{ r.altezza|int }}</td>
                    
                    <td>{{ r.lotto or '' }}</td> <td>{{ r.m2|round(3) if r.m2 else '' }}</td>
                    <td>{{ r.m3|round(3) if r.m3 else '' }}</td>
                    
                    <td class="text-center">
                        <a href="{{ url_for('edit_record', id_articolo=r.id_articolo) }}" title="Modifica" class="text-decoration-none me-1">✏️</a>
                        <a href="{{ url_for('duplica_articolo', id=r.id_articolo) }}" title="Duplica" class="text-decoration-none">📄</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot class="sticky-bottom bg-white fw-bold">
                <tr><td colspan="25">Totali: Colli {{ total_colli }} | M2 {{ total_m2|round(2) }} | Peso {{ total_peso }}</td></tr>
            </tfoot>
        </table>
    </div>
</form>

<script>
    function toggleAll(source) {
        document.getElementsByName('ids').forEach(c => {
            c.checked = source.checked;
            // Scatena l'evento change per aggiornare il localStorage
            c.dispatchEvent(new Event('change'));
        });
    }

    // SCRIPT PER MANTENERE LA SELEZIONE DOPO IL REFRESH
    document.addEventListener("DOMContentLoaded", function() {
        const STORAGE_KEY = 'camar_selected_articles';
        
        // 1. Ripristina selezioni
        let savedIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        const checkboxes = document.querySelectorAll('input[name="ids"]');
        
        checkboxes.forEach(cb => {
            if (savedIds.includes(cb.value)) {
                cb.checked = true;
            }
            
            // 2. Salva su cambio stato
            cb.addEventListener('change', function() {
                let currentIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
                if (this.checked) {
                    if (!currentIds.includes(this.value)) currentIds.push(this.value);
                } else {
                    currentIds = currentIds.filter(id => id !== this.value);
                }
                localStorage.setItem(STORAGE_KEY, JSON.stringify(currentIds));
            });
        });
    });
</script>
{% endblock %}
"""

EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3>
        <i class="bi bi-pencil-square"></i> 
        {% if row.id_articolo %}Modifica Articolo #{{ row.id_articolo }}{% else %}Nuovo Articolo{% endif %}
    </h3>
    <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Torna alla Lista</a>
</div>

<form method="post" enctype="multipart/form-data" class="card p-4 shadow-sm mb-4">
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
            <input class="form-control" list="statoList" name="stato" value="{{ row.stato or '' }}" placeholder="Seleziona...">
            <datalist id="statoList">
                <option value="NAZIONALE">
                <option value="DOGANALE">
                <option value="ESTERO">
                <option value="USCITO">
                <option value="FINCANTIERI SCOPERTO">
                <option value="AGGIUNTO A MANO">
            </datalist>
        </div>

        <div class="col-md-2"><label class="form-label">Commessa</label><input type="text" name="commessa" class="form-control" value="{{ row.commessa or '' }}"></div>
        <div class="col-md-4"><label class="form-label">Cliente</label><input type="text" name="cliente" class="form-control" value="{{ row.cliente or '' }}"></div>
        <div class="col-md-4"><label class="form-label">Fornitore</label><input type="text" name="fornitore" class="form-control" value="{{ row.fornitore or '' }}"></div>
        <div class="col-md-4"><label class="form-label">Protocollo</label><input type="text" name="protocollo" class="form-control" value="{{ row.protocollo or '' }}"></div>
        
        <div class="col-md-3"><label class="form-label">N. Buono</label><input type="text" name="buono_n" class="form-control" value="{{ row.buono_n or '' }}"></div>
        <div class="col-md-3"><label class="form-label">Magazzino</label><input type="text" name="magazzino" class="form-control" value="{{ row.magazzino or 'STRUPPA' }}"></div>
        <div class="col-md-3"><label class="form-label">Posizione</label><input type="text" name="posizione" class="form-control" value="{{ row.posizione or '' }}"></div>
        <div class="col-md-3"><label class="form-label">Ordine</label><input type="text" name="ordine" class="form-control" value="{{ row.ordine or '' }}"></div>
        
        <div class="col-md-3"><label class="form-label">Data Ingresso</label><input type="date" name="data_ingresso" class="form-control" value="{{ row.data_ingresso or '' }}"></div>
        <div class="col-md-3"><label class="form-label">DDT Ingresso</label><input type="text" name="n_ddt_ingresso" class="form-control" value="{{ row.n_ddt_ingresso or '' }}"></div>
        <div class="col-md-3"><label class="form-label">Data Uscita</label><input type="date" name="data_uscita" class="form-control" value="{{ row.data_uscita or '' }}"></div>
        <div class="col-md-3"><label class="form-label">DDT Uscita</label><input type="text" name="n_ddt_uscita" class="form-control" value="{{ row.n_ddt_uscita or '' }}"></div>
        
        <div class="col-md-2"><label class="form-label">Pezzi</label><input type="number" name="pezzo" class="form-control" value="{{ row.pezzo or '' }}"></div>
        <div class="col-md-2 bg-warning bg-opacity-10 rounded">
            <label class="form-label fw-bold">Colli</label>
            <input type="number" name="n_colli" class="form-control fw-bold" value="{{ row.n_colli or '' }}">
            <small style="font-size:10px">Se >1 crea copie</small>
        </div>
        <div class="col-md-2"><label class="form-label">Peso (Kg)</label><input type="number" step="0.01" name="peso" class="form-control" value="{{ row.peso or '' }}"></div>
        <div class="col-md-2"><label class="form-label">M³</label><input type="number" step="0.001" name="m3" class="form-control" value="{{ row.m3 or '' }}"></div>
        <div class="col-md-2"><label class="form-label">N. Arrivo</label><input type="text" name="n_arrivo" class="form-control" value="{{ row.n_arrivo or '' }}"></div>
        
        <div class="col-md-4">
            <label class="form-label">Dimensioni (LxPxH)</label>
            <div class="input-group">
                <input type="number" step="0.01" name="lunghezza" class="form-control" placeholder="L" value="{{ row.lunghezza or '' }}">
                <span class="input-group-text">x</span>
                <input type="number" step="0.01" name="larghezza" class="form-control" placeholder="P" value="{{ row.larghezza or '' }}">
                <span class="input-group-text">x</span>
                <input type="number" step="0.01" name="altezza" class="form-control" placeholder="H" value="{{ row.altezza or '' }}">
            </div>
        </div>
        
        <div class="col-md-4"><label class="form-label">Serial Number</label><input type="text" name="serial_number" class="form-control" value="{{ row.serial_number or '' }}"></div>
        <div class="col-md-4"><label class="form-label">Mezzi in Uscita</label><input type="text" name="mezzi_in_uscita" class="form-control" value="{{ row.mezzi_in_uscita or '' }}"></div>
        <div class="col-12"><label class="form-label">Note</label><textarea name="note" class="form-control" rows="3">{{ row.note or '' }}</textarea></div>

        {% if not row.id_articolo %}
        <div class="col-12 mt-3">
            <div class="card bg-light border-dashed p-3">
                 <label class="form-label fw-bold text-primary"><i class="bi bi-paperclip"></i> Carica Allegati (Subito)</label>
                 <input type="file" name="new_files" class="form-control" multiple>
                 <small class="text-muted">Seleziona i file da caricare insieme alla creazione dell'articolo.</small>
            </div>
        </div>
        {% endif %}
    </div>

    <div class="mt-4 text-end">
        <button type="submit" class="btn btn-primary px-5 btn-lg"><i class="bi bi-save"></i> {% if row.id_articolo %}Salva Modifiche{% else %}Crea Articolo{% endif %}</button>
    </div>
</form>

{% if row and row.id_articolo %}
<div class="card p-4 shadow-sm">
    <div class="d-flex justify-content-between">
        <h5><i class="bi bi-paperclip"></i> Allegati Salvati</h5>
        <form action="{{ url_for('upload_file', id_articolo=row.id_articolo) }}" method="post" enctype="multipart/form-data" class="d-flex gap-2">
            <input type="file" name="file" class="form-control form-control-sm" required>
            <button type="submit" class="btn btn-success btn-sm">Carica</button>
        </form>
    </div>
    <hr>
    
    <div class="row g-3">
        {% for att in row.attachments %}
        <div class="col-md-2 col-6">
            <div class="card h-100 text-center p-2 border bg-light">
                <div class="mb-2" style="font-size:2em;">
                    {% if att.kind == 'photo' %}📷{% else %}📄{% endif %}
                </div>
                <div class="text-truncate small fw-bold mb-2" title="{{ att.filename }}">{{ att.filename }}</div>
                
                <div class="btn-group btn-group-sm w-100">
                    <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank" class="btn btn-outline-primary">Apri</a>
                    <a href="{{ url_for('delete_attachment', id_attachment=att.id) }}" class="btn btn-outline-danger" onclick="return confirm('Sicuro di eliminare questo file?')">X</a>
                </div>
            </div>
        </div>
        {% else %}
        <div class="col-12 text-muted fst-italic">Nessun allegato caricato.</div>
        {% endfor %}
    </div>
</div>
{% endif %}
{% endblock %}
"""
BULK_EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h3><i class="bi bi-ui-checks"></i> Modifica Multipla ({{ rows|length }} articoli)</h3>
        <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
    </div>

    <div class="alert alert-warning shadow-sm">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <strong>Attenzione:</strong> Attiva la spunta accanto ai campi che vuoi modificare. 
        Il valore inserito verrà applicato a <b>TUTTI</b> gli articoli selezionati.
    </div>

    <form method="POST" enctype="multipart/form-data">
        <input type="hidden" name="save_bulk" value="true">
        {% for id in ids_csv.split(',') %}
        <input type="hidden" name="ids" value="{{ id }}">
        {% endfor %}

        <div class="card p-4 mb-4 bg-light border-dashed shadow-sm">
            <h5 class="text-primary"><i class="bi bi-cloud-upload"></i> Caricamento Allegati Massivo</h5>
            <div class="d-flex gap-2">
                <input type="file" name="bulk_file" class="form-control" multiple>
            </div>
            <small class="text-muted">I file selezionati verranno allegati a ciascuno degli articoli.</small>
        </div>

        <div class="row g-3">
            {% for label, field_name in fields %}
            <div class="col-md-3 col-sm-6">
                <div class="card h-100 shadow-sm border-0">
                    <div class="card-header py-2 bg-white border-bottom-0 d-flex align-items-center gap-2">
                        <div class="form-check form-switch m-0">
                            <input class="form-check-input" type="checkbox" name="chk_{{ field_name }}" id="chk_{{ field_name }}" 
                                   onchange="document.getElementById('in_{{ field_name }}').disabled = !this.checked; 
                                             document.getElementById('in_{{ field_name }}').focus();">
                        </div>
                        <label for="chk_{{ field_name }}" class="m-0 fw-bold text-dark w-100" style="cursor:pointer; font-size:0.9rem;">
                            {{ label }}
                        </label>
                    </div>
                    <div class="card-body p-2 bg-light rounded-bottom">
                        
                        {% if field_name == 'stato' %}
                            <input list="statoOptions" name="{{ field_name }}" id="in_{{ field_name }}" class="form-control form-control-sm" disabled placeholder="Seleziona...">
                            <datalist id="statoOptions">
                                <option value="NAZIONALE">
                                <option value="DOGANALE">
                                <option value="ESTERO">
                                <option value="USCITO">
                                <option value="FINCANTIERI SCOPERTO">
                                <option value="AGGIUNTO A MANO">
                            </datalist>
                        
                        {% elif 'data' in field_name %}
                            <input type="date" name="{{ field_name }}" id="in_{{ field_name }}" class="form-control form-control-sm" disabled>
                        
                        {% elif field_name in ['pezzo','n_colli','lunghezza','larghezza','altezza'] %}
                            <input type="number" step="0.01" name="{{ field_name }}" id="in_{{ field_name }}" class="form-control form-control-sm" disabled>

                        {% else %}
                            <input type="text" name="{{ field_name }}" id="in_{{ field_name }}" class="form-control form-control-sm" disabled>
                        {% endif %}
                        
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="mt-5 text-center mb-5">
            <button type="submit" class="btn btn-warning btn-lg px-5 fw-bold shadow">
                <i class="bi bi-check-circle-fill"></i> Applica Modifiche a Tutti
            </button>
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
<div class="card p-4" style="max-width: 800px; margin: auto;">
    <h3><i class="bi bi-tags"></i> Crea Etichette (PDF)</h3>
    
    <form action="{{ url_for('labels_pdf') }}" method="post">
        
        <div class="row g-3">
            <div class="col-md-6">
                <label class="form-label">Cliente</label>
                <input name="cliente" class="form-control" list="clist">
                <datalist id="clist">{% for c in clienti %}<option value="{{ c }}">{% endfor %}</datalist>
            </div>
            <div class="col-md-6"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Ordine</label><input name="ordine" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Commessa</label><input name="commessa" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Posizione</label><input name="posizione" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">DDT Ingresso</label><input name="n_ddt_ingresso" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Data Ingresso</label><input type="date" name="data_ingresso" class="form-control" value="{{ today }}"></div>
            <div class="col-md-4"><label class="form-label">N. Arrivo</label><input name="n_arrivo" class="form-control"></div>
            <div class="col-md-4"><label class="form-label fw-bold">Numero Colli</label><input name="n_colli" type="number" class="form-control" value="1" required></div>
        </div>

        <div class="mt-4">
            <button type="submit" class="btn btn-warning btn-lg"><i class="bi bi-download"></i> Scarica PDF</button>
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary btn-lg">Indietro</a>
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
    'import_pdf.html': IMPORT_PDF_HTML,      # <--- NUOVO
    

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
                next_page = url_for('home')
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

# ========================================================
# GESTIONE MAPPE EXCEL (CORRETTA + LOG DEBUG)
# ========================================================

def load_mappe():
    """Carica mappe_excel.json: prima da config. (con punto), poi fallback su root."""
    config_path = APP_DIR / "config." / "mappe_excel.json"   # <-- cartella con il punto
    root_path = APP_DIR / "mappe_excel.json"

    json_path = config_path if config_path.exists() else root_path
    print(f"DEBUG scelto json_path: {json_path}")

    if not json_path.exists():
        print("DEBUG NESSUN mappe_excel.json trovato -> {}")
        print("=== FINE DEBUG load_mappe() ===\n")
        return {}

    try:
        raw = json_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        print(f"DEBUG size={len(raw)} bytes | profili={len(data) if isinstance(data, dict) else 'N/A'}")
        print("=== FINE DEBUG load_mappe() ===\n")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"DEBUG ERRORE parsing mappe: {e}")
        print("=== FINE DEBUG load_mappe() ===\n")
        return {}


@app.route('/manage_mappe', methods=['GET', 'POST'])
@login_required
def manage_mappe():
    json_path = APP_DIR / "mappe_excel.json"

    print("\n=== DEBUG manage_mappe() ===")
    print(f"DEBUG manage_mappe: json_path={json_path}")

    if request.method == 'POST':
        content = request.form.get('json_content', '')
        try:
            json.loads(content)  # Validazione
            print(f"DEBUG manage_mappe: scrivo su {json_path}")

            json_path.write_text(content, encoding='utf-8')

            try:
                size = json_path.stat().st_size
            except Exception:
                size = "N/A"
            print(f"DEBUG manage_mappe: scritto OK. md5={_file_digest(json_path)} size={size}")

            flash("Mappa aggiornata con successo.", "success")
        except json.JSONDecodeError as e:
            print(f"DEBUG manage_mappe: JSON NON valido: {e}")
            flash(f"Errore nel formato JSON: {e}", "danger")
        except Exception as e:
            print(f"DEBUG manage_mappe: ERRORE scrittura file: {e}")
            flash(f"Errore scrittura mappa: {e}", "danger")

        print("=== FINE DEBUG manage_mappe() ===\n")
        return redirect(url_for('manage_mappe'))

    # GET
    content = ""
    if json_path.exists():
        try:
            content = json_path.read_text(encoding='utf-8')
            print(f"DEBUG manage_mappe GET: file esiste, md5={_file_digest(json_path)} size={len(content)}")
        except Exception as e:
            print(f"DEBUG manage_mappe GET: errore lettura file: {e}")
    else:
        print("DEBUG manage_mappe GET: file NON esiste")

    print("=== FINE DEBUG manage_mappe() ===\n")
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

    target = APP_DIR / "mappe_excel.json"

    print("\n=== DEBUG upload_mappe_json() ===")
    print(f"DEBUG upload_mappe_json: filename={f.filename}")
    print(f"DEBUG upload_mappe_json: target={target}")

    try:
        content = f.read().decode('utf-8')
        json.loads(content)  # Validazione

        target.write_text(content, encoding='utf-8')

        try:
            size = target.stat().st_size
        except Exception:
            size = "N/A"
        print(f"DEBUG upload_mappe_json: scritto OK. md5={_file_digest(target)} size={size}")

        flash("File mappe_excel.json caricato correttamente.", "success")
    except Exception as e:
        print(f"DEBUG upload_mappe_json: ERRORE: {e}")
        flash(f"Errore nel file caricato: {e}", "danger")

    print("=== FINE DEBUG upload_mappe_json() ===\n")
    return redirect(url_for('manage_mappe'))


# --- GESTIONE TRASPORTI (ADMIN) ---
@app.route('/trasporti', methods=['GET', 'POST'])
@login_required
def trasporti():
    if session.get('role') != 'admin':
        flash("Accesso non autorizzato", "danger")
        return redirect(url_for('home'))

    db = SessionLocal()
    query = db.query(Trasporto)

    # Filtri
    f_consolidato = request.args.get('consolidato', '')
    f_trasportatore = request.args.get('trasportatore', '')
    f_mezzo = request.args.get('tipo_mezzo', '')
    f_cliente = request.args.get('cliente', '')
    f_data = request.args.get('data', '')

    if f_consolidato: query = query.filter(Trasporto.consolidato.ilike(f"%{f_consolidato}%"))
    if f_trasportatore: query = query.filter(Trasporto.trasportatore.ilike(f"%{f_trasportatore}%"))
    if f_mezzo: query = query.filter(Trasporto.tipo_mezzo.ilike(f"%{f_mezzo}%"))
    if f_cliente: query = query.filter(Trasporto.cliente.ilike(f"%{f_cliente}%"))
    if f_data: query = query.filter(Trasporto.data.ilike(f"%{f_data}%"))

    dati = query.all()
    db.close()
    return render_template('trasporti.html', trasporti=dati)

@app.route('/report_trasporti', methods=['POST'])
@login_required
def report_trasporti():
    if session.get('role') != 'admin': return "No Access", 403
    
    # Prendi i dati filtrati dal form
    mese = request.form.get('mese') # Es. '2025-01'
    mezzo = request.form.get('tipo_mezzo')
    cliente = request.form.get('cliente')
    
    db = SessionLocal()
    query = db.query(Trasporto)
    
    if mese: query = query.filter(Trasporto.data.like(f"{mese}%")) # Filtra per YYYY-MM
    if mezzo: query = query.filter(Trasporto.tipo_mezzo == mezzo)
    if cliente: query = query.filter(Trasporto.cliente == cliente)
    
    dati = query.all()
    
    # Calcolo totali
    totale_costo = sum(t.costo for t in dati if t.costo)
    
    db.close()
    
    # Renderizza un template pulito per la stampa
    return render_template('report_trasporti_print.html', dati=dati, totale=totale_costo, mese=mese, cliente=cliente)


# --- GESTIONE LAVORAZIONI (ADMIN) ---
@app.route('/lavorazioni', methods=['GET'])
@login_required
def lavorazioni():
    if session.get('role') != 'admin':
        flash("Accesso non autorizzato", "danger")
        return redirect(url_for('home'))

    db = SessionLocal()
    query = db.query(Lavorazione)

    # Filtri
    f_cliente = request.args.get('cliente', '')
    f_desc = request.args.get('descrizione', '')
    
    if f_cliente: query = query.filter(Lavorazione.cliente.ilike(f"%{f_cliente}%"))
    if f_desc: query = query.filter(Lavorazione.descrizione.ilike(f"%{f_desc}%"))

    dati = query.all()
    db.close()
    return render_template('lavorazioni.html', lavorazioni=dati)



# --- REPORT INVENTARIO PER CLIENTE/DATA ---
@app.route('/report_inventario', methods=['POST'])
@login_required
def report_inventario():
    data_rif = request.form.get('data_inventario') # Data scelta
    
    db = SessionLocal()
    
    # Logica Inventario Storico:
    # Cerchiamo articoli che erano DENTRO in quella data (Ingresso <= Data)
    # E che NON erano ancora usciti (Uscita IS NULL oppure Uscita > Data)
    
    # Nota: Poiché le date sono TEXT nel DB, usiamo il confronto stringhe ISO YYYY-MM-DD
    # Assicurati che data_rif sia YYYY-MM-DD
    
    query = db.query(Articolo).filter(Articolo.data_ingresso <= data_rif)
    
    # Filtro uscita: O è NULL, O è successiva alla data rif
    from sqlalchemy import or_
    query = query.filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == '', Articolo.data_uscita > data_rif))
    
    articoli = query.all()
    
    # Raggruppa per Cliente
    inventario = {}
    for art in articoli:
        cli = art.cliente or "NESSUN CLIENTE"
        if cli not in inventario: inventario[cli] = []
        inventario[cli].append(art)
        
    db.close()
    
    return render_template('report_inventario_print.html', inventario=inventario, data_rif=data_rif)



# =========================
# IMPORT EXCEL (con log)
# =========================

@app.route('/import_excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    mappe = load_mappe()
    profiles = list(mappe.keys()) if mappe else []

    if request.method == 'GET':
        return render_template('import_excel.html', profiles=profiles)

    # POST
    profile_name = request.form.get('profile')
    if not profile_name or profile_name not in mappe:
        flash("Seleziona un profilo valido.", "warning")
        return redirect(request.url)

    if 'excel_file' not in request.files:
        flash('Nessun file selezionato', 'warning')
        return redirect(request.url)

    file = request.files['excel_file']
    if file.filename == '':
        flash('Nessun file selezionato', 'warning')
        return redirect(request.url)

    if not file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm')):
        flash('Formato file non supportato.', 'warning')
        return redirect(request.url)

    db = SessionLocal()
    try:
        config = mappe[profile_name]
        # Excel 1-based -> Pandas 0-based
        header_row_idx = int(config.get('header_row', 1)) - 1  
        column_map = config.get('column_map', {}) or {}

        # Ispezione e Lettura Excel
        xls = pd.ExcelFile(file, engine="openpyxl")
        
        # Lettura con header indicato
        df = xls.parse(0, header=header_row_idx)

        # Normalizzazione colonne (rimuove spazi e mette tutto in maiuscolo per il match)
        df_cols_upper = {str(c).strip().upper(): c for c in df.columns}

        # Import
        imported_count = 0

        for row_idx, row in df.iterrows():
            # salta righe completamente vuote
            if row.isnull().all():
                continue

            new_art = Articolo()
            has_data = False

            for excel_header, db_field in column_map.items():
                # Match colonna in Excel (usando la chiave normalizzata)
                key = str(excel_header).strip().upper()
                col_name_in_df = df_cols_upper.get(key)

                if col_name_in_df is None:
                    continue

                val = row[col_name_in_df]
                if pd.isna(val) or str(val).strip() == "":
                    continue

                # Conversioni
                try:
                    if db_field in ['larghezza', 'lunghezza', 'altezza', 'peso', 'm2', 'm3']:
                        val = to_float_eu(val)
                    elif db_field in ['n_colli', 'pezzo']:
                        val = to_int_eu(val)
                    elif db_field in ['data_ingresso', 'data_uscita']:
                        # Usa to_date_db se presente per salvare oggetti data corretti nel DB
                        # Se non hai to_date_db, usa fmt_date/parse_date_ui
                        if 'to_date_db' in globals():
                             val = to_date_db(val)
                        else:
                             val = fmt_date(val) if isinstance(val, (datetime, date)) else parse_date_ui(str(val))
                    else:
                        val = str(val).strip()
                except Exception:
                    continue

                # Set attributo
                try:
                    setattr(new_art, db_field, val)
                    has_data = True
                except Exception:
                    pass

            if has_data:
                # Calcolo automatico M2/M3 se non presenti
                try:
                    if not getattr(new_art, "m2", None) or getattr(new_art, "m2", 0) == 0:
                        new_art.m2, new_art.m3 = calc_m2_m3(
                            getattr(new_art, "lunghezza", None),
                            getattr(new_art, "larghezza", None),
                            getattr(new_art, "altezza", None),
                            getattr(new_art, "n_colli", None)
                        )
                except Exception:
                    pass

                db.add(new_art)
                imported_count += 1

        db.commit()

        # Feedback utente
        if imported_count == 0:
            flash(f"0 articoli importati con la mappa '{profile_name}'. Controlla il file o la mappatura.", "warning")
        else:
            flash(f"{imported_count} articoli importati con successo con la mappa '{profile_name}'.", "success")

        return redirect(url_for('giacenze', v=uuid.uuid4().hex[:6]))

    except Exception as e:
        db.rollback()
        flash(f"Errore durante l'importazione: {e}", 'danger')
        return redirect(request.url)

    finally:
        db.close()

def get_all_fields_map():
    return {
        'codice_articolo': 'Codice Articolo', 'pezzo': 'Pezzi','lotto':'Lotto',
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

# --- ROUTE IMPORT PDF (PROTETTA ADMIN) ---
@app.route('/import_pdf', methods=['GET', 'POST'])
@login_required
def import_pdf():
    # PROTEZIONE ADMIN
    if session.get('role') != 'admin':
        flash("Accesso negato: Funzione riservata agli amministratori.", "danger")
        return redirect(url_for('giacenze'))

    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        f = request.files['file']
        if f.filename:
            temp_path = os.path.join(DOCS_DIR, f"temp_{uuid.uuid4().hex}.pdf")
            f.save(temp_path)
            try:
                meta, rows = extract_data_from_ddt_pdf(temp_path)
                # Pulisce file temp
                if os.path.exists(temp_path): os.remove(temp_path)
                return render_template('import_pdf.html', meta=meta, rows=rows)
            except Exception as e:
                flash(f"Errore PDF: {e}", "danger")
                return redirect(url_for('giacenze'))
                
    return render_template('import_pdf.html', meta={}, rows=[])

@app.route('/save_pdf_import', methods=['POST'])
@login_required
def save_pdf_import():
    # PROTEZIONE ADMIN
    if session.get('role') != 'admin':
        return "Accesso Negato", 403

    db = SessionLocal()
    try:
        codici = request.form.getlist('codice[]')
        descrizioni = request.form.getlist('descrizione[]')
        qtas = request.form.getlist('qta[]')
        
        c = 0
        for i in range(len(codici)):
            if codici[i].strip() or descrizioni[i].strip():
                art = Articolo()
                art.cliente = request.form.get('cliente')
                art.commessa = request.form.get('commessa')
                art.n_ddt_ingresso = request.form.get('n_ddt')
                art.data_ingresso = parse_date_ui(request.form.get('data_ingresso'))
                art.fornitore = request.form.get('fornitore')
                art.stato = "DOGANALE"
                art.codice_articolo = codici[i]
                art.descrizione = descrizioni[i]
                art.n_colli = to_int_eu(qtas[i])
                db.add(art); c += 1
        db.commit()
        flash(f"Importati {c} articoli.", "success")
        return redirect(url_for('giacenze'))
    finally: db.close()



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
    allegati_extra = request.files.getlist('allegati_extra')

    ids_list = [int(i) for i in selected_ids.split(',') if i.isdigit()]
    
    # --- CORREZIONE VARIABILI E LOG DEBUG ---
    # Cerchiamo le variabili con i nomi usati su Render (MAIL_...)
    SMTP_SERVER = os.environ.get("MAIL_SERVER") or os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("MAIL_PORT") or os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("MAIL_USERNAME") or os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("MAIL_PASSWORD") or os.environ.get("SMTP_PASS", "")

    # STAMPA NEI LOG (Visibili nella Dashboard di Render)
    print(f"DEBUG EMAIL - Server: {SMTP_SERVER}, Port: {SMTP_PORT}, User: {SMTP_USER}")
    if not SMTP_PASS:
        print("DEBUG EMAIL - ERRORE: Password non trovata nelle variabili d'ambiente!")

    if not SMTP_USER or not SMTP_PASS:
        flash(f"Configurazione email mancante (User: {SMTP_USER}). Controlla le variabili su Render.", "warning")
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
                # Usa dati fittizi per l'header del riepilogo
                dest_data = {"ragione_sociale": "RIEPILOGO", "indirizzo": "", "citta": ""}
                # Genera un DDT temporaneo in memoria
                pdf_bio = io.BytesIO()
                # Chiamiamo la funzione di generazione PDF
                _genera_pdf_ddt_file(
                    {'n_ddt': 'RIEP', 'data_uscita': date.today().strftime('%d/%m/%Y'), 
                     'destinatario': 'RIEPILOGO', 'dest_indirizzo': '', 'dest_citta': ''}, 
                    [{
                        'id_articolo': r.id_articolo, 'codice_articolo': r.codice_articolo, 
                        'descrizione': r.descrizione, 'pezzo': r.pezzo, 'n_colli': r.n_colli, 
                        'peso': r.peso, 'n_arrivo': r.n_arrivo, 'note': r.note
                    } for r in rows], 
                    pdf_bio
                )
                
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
                    # Cerca file (decodifica spazi se necessario)
                    fname = att.filename
                    path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / fname
                    if not path.exists():
                         # Prova con unquote se il file su disco ha spazi
                         from urllib.parse import unquote
                         path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / unquote(fname)
                    
                    if path.exists():
                        with open(path, "rb") as f:
                            part = MIMEBase('application', "octet-stream")
                            part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                        msg.attach(part)
            db.close()

        # 3. Allegati Extra
        for file in allegati_extra:
            if file and file.filename:
                part = MIMEBase('application', "octet-stream")
                part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{secure_filename(file.filename)}"')
                msg.attach(part)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()

        flash(f"Email inviata correttamente a {destinatario}", "success")
    except Exception as e:
        print(f"DEBUG EMAIL EXCEPTION: {e}")
        flash(f"Errore invio: {e}", "danger")

    return redirect(url_for('giacenze'))
# --- ROUTE ALLEGATI (MANCANTI - DA AGGIUNGERE) ---
from urllib.parse import unquote # <--- Assicurati di importare questo in alto o dentro la funzione

# --- AGGIUNGI QUESTO IMPORT IN ALTO NEL FILE SE NON C'È ---
from urllib.parse import unquote 
# ----------------------------------------------------------

# --- FUNZIONE PER CARICARE NUOVI FILE (Dalla pagina Modifica) ---

# --- FUNZIONE UPLOAD FILE SINGOLO (CORRETTA) ---
@app.route('/upload/<int:id_articolo>', methods=['POST'])
@login_required
def upload_file(id_articolo):
    if session.get('role') != 'admin':
        flash("Solo Admin può caricare file", "danger")
        return redirect(url_for('edit_record', id_articolo=id_articolo))

    file = request.files.get('file')
    # Controllo base
    if not file or not file.filename:
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('edit_record', id_articolo=id_articolo))

    db = SessionLocal()
    try:
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            kind = 'photo'
            save_path = PHOTOS_DIR / filename
        else:
            kind = 'doc'
            save_path = DOCS_DIR / filename
            
        file.save(str(save_path))

        # --- CORREZIONE QUI: articolo_id INVECE DI id_articolo ---
        att = Attachment(
            articolo_id=id_articolo,  # <--- QUESTA ERA LA CAUSA DELL'ERRORE ROSSO
            filename=filename,
            kind=kind
        )
        db.add(att)
        db.commit()
        flash("File caricato correttamente!", "success")
        
    except Exception as e:
        db.rollback()
        # Stampa l'errore nei log per capire meglio
        print(f"ERRORE UPLOAD: {e}") 
        flash(f"Errore caricamento: {e}", "danger")
    finally:
        db.close()

    return redirect(url_for('edit_record', id_articolo=id_articolo))

    
    

@app.route('/delete_file/<int:id_file>')
@login_required
def delete_file(id_file):
    db = SessionLocal()
    att = db.query(Attachment).get(id_file)
    if att:
        id_art = att.articolo_id
        path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
        try:
            if path.exists(): os.remove(path)
        except: pass
        db.delete(att)
        db.commit()
        db.close()
        return redirect(url_for('edit_record', id_articolo=id_art))
    db.close()
    return redirect(url_for('giacenze'))



# --- FIX VISUALIZZAZIONE ALLEGATI ---
from urllib.parse import unquote
import os

@app.route('/serve_file/<path:filename>')
@login_required
def serve_uploaded_file(filename):
    # 1. Decodifica standard (es. %20 -> spazio)
    decoded_name = unquote(filename)
    
    # 2. Lista di possibili nomi da cercare (Originale, Decodificato, Con Underscore)
    candidates = [
        filename,                   
        decoded_name,               
        filename.replace(' ', '_'), 
        decoded_name.replace(' ', '_'),
        secure_filename(decoded_name) # Prova anche la versione "sicura"
    ]
    
    # 3. Cerca in entrambe le cartelle (Foto e Documenti)
    # Usa os.walk o listdir se necessario, ma qui proviamo i path diretti
    for folder in [PHOTOS_DIR, DOCS_DIR]:
        for name in candidates:
            p = folder / name
            if p.exists():
                return send_file(p)
            
            # Tentativo case-insensitive (per sistemi Linux sensibili alle maiuscole)
            try:
                for existing_file in os.listdir(folder):
                    if existing_file.lower() == name.lower():
                        return send_file(folder / existing_file)
            except: pass

    # Se arriviamo qui, il file non c'è. Stampa debug nei log di Render.
    print(f"DEBUG: File '{filename}' non trovato. Cercato candidati: {candidates}")
    return f"File '{decoded_name}' non trovato sul server (potrebbe essere stato cancellato dal riavvio di Render).", 404
    
# --- GESTIONE ARTICOLI (CRUD) ---
# ========================================================
# 8. CRUD (NUOVO / MODIFICA)
# ========================================================

@app.route('/new', methods=['GET', 'POST'])
@login_required
def nuovo_articolo():
    # 1. Controllo permessi
    if session.get('role') != 'admin':
        flash("Accesso negato: Solo Admin.", "danger")
        return redirect(url_for('giacenze'))

    if request.method == 'POST':
        db = SessionLocal()
        try:
            # --- A. CREAZIONE ARTICOLO ---
            art = Articolo()
            # Popola i dati dal form
            art.codice_articolo = request.form.get('codice_articolo')
            art.descrizione = request.form.get('descrizione')
            art.cliente = request.form.get('cliente')
            art.fornitore = request.form.get('fornitore')
            art.commessa = request.form.get('commessa')
            art.ordine = request.form.get('ordine')
            art.protocollo = request.form.get('protocollo')
            art.buono_n = request.form.get('buono_n')
            art.n_arrivo = request.form.get('n_arrivo')
            art.magazzino = request.form.get('magazzino')
            art.posizione = request.form.get('posizione')
            art.stato = request.form.get('stato')
            art.note = request.form.get('note')
            art.serial_number = request.form.get('serial_number')
            art.mezzi_in_uscita = request.form.get('mezzi_in_uscita')
            
            # Date
            art.data_ingresso = parse_date_ui(request.form.get('data_ingresso'))
            art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')
            
            # Numeri
            art.pezzo = request.form.get('pezzo')
            art.n_colli = to_int_eu(request.form.get('n_colli')) or 1
            art.peso = to_float_eu(request.form.get('peso'))
            art.lunghezza = to_float_eu(request.form.get('lunghezza'))
            art.larghezza = to_float_eu(request.form.get('larghezza'))
            art.altezza = to_float_eu(request.form.get('altezza'))
            
            # Calcolo M2/M3
            art.m2, art.m3 = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, 1)

            # Salvataggio iniziale per ottenere l'ID
            db.add(art)
            db.commit() 
            
            # --- B. SALVATAGGIO ALLEGATI (Se presenti) ---
            # Recupera i file dal campo input 'new_files'
            files = request.files.getlist('new_files')
            count_files = 0
            
            if files:
                from werkzeug.utils import secure_filename
                for file in files:
                    if file and file.filename:
                        # Pulisce il nome file
                        fname = secure_filename(file.filename)
                        # Crea nome univoco: ID_NomeOriginale
                        final_name = f"{art.id_articolo}_{fname}"
                        
                        # Decide se è foto o doc
                        ext = fname.rsplit('.', 1)[-1].lower()
                        kind = 'photo' if ext in ['jpg', 'jpeg', 'png', 'webp'] else 'doc'
                        folder = PHOTOS_DIR if kind == 'photo' else DOCS_DIR
                        
                        # Salva su disco
                        file.save(str(folder / final_name))
                        
                        # Salva collegamento nel DB
                        att = Attachment(articolo_id=art.id_articolo, filename=final_name, kind=kind)
                        db.add(att)
                        count_files += 1
                
                # Se abbiamo aggiunto file, facciamo un secondo commit
                if count_files > 0:
                    db.commit()

            flash(f"Articolo creato (ID: {art.id_articolo}) con {count_files} allegati.", "success")
            # Rimanda alla pagina di modifica per vedere subito il risultato
            return redirect(url_for('edit_record', id_articolo=art.id_articolo))
            
        except Exception as e:
            db.rollback()
            flash(f"Errore creazione: {e}", "danger")
            return redirect(url_for('giacenze'))
        finally:
            db.close()

    # GET: Mostra form vuoto
    dummy_art = Articolo() 
    dummy_art.data_ingresso = date.today().strftime("%d/%m/%Y") # Data di default
    return render_template('edit.html', row=dummy_art)

@app.route('/edit/<int:id_articolo>', methods=['GET', 'POST'])
@login_required
def edit_record(id_articolo):
    db = SessionLocal()
    try:
        art = db.query(Articolo).filter(Articolo.id_articolo == id_articolo).first()
        if not art:
            flash("Articolo non trovato", "danger")
            return redirect(url_for('giacenze'))

        if request.method == 'POST':
            # --- SALVATAGGIO MODIFICHE ---
            colli_input = to_int_eu(request.form.get('n_colli'))
            if colli_input < 1: colli_input = 1

            # Aggiornamento campi
            art.codice_articolo = request.form.get('codice_articolo')
            art.descrizione = request.form.get('descrizione')
            art.cliente = request.form.get('cliente')
            art.fornitore = request.form.get('fornitore')
            art.commessa = request.form.get('commessa')
            art.ordine = request.form.get('ordine')
            art.protocollo = request.form.get('protocollo')
            art.buono_n = request.form.get('buono_n')
            art.n_arrivo = request.form.get('n_arrivo')
            art.magazzino = request.form.get('magazzino')
            art.posizione = request.form.get('posizione')
            art.stato = request.form.get('stato')
            art.note = request.form.get('note')
            art.serial_number = request.form.get('serial_number')
            art.mezzi_in_uscita = request.form.get('mezzi_in_uscita')
            
            art.data_ingresso = parse_date_ui(request.form.get('data_ingresso'))
            art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')
            
            art.pezzo = request.form.get('pezzo')
            # Nella modifica singola, n_colli resta 1 per coerenza, se split gestito sotto
            art.n_colli = 1 
            art.peso = to_float_eu(request.form.get('peso'))
            art.lunghezza = to_float_eu(request.form.get('lunghezza'))
            art.larghezza = to_float_eu(request.form.get('larghezza'))
            art.altezza = to_float_eu(request.form.get('altezza'))
            
            # Calcoli
            m2_calc, m3_calc = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, 1)
            art.m2 = m2_calc
            m3_man = request.form.get('m3')
            art.m3 = to_float_eu(m3_man) if m3_man and to_float_eu(m3_man) > 0 else m3_calc

            # --- DUPLICAZIONE SE COLLI > 1 ---
            if colli_input > 1:
                for _ in range(colli_input - 1):
                    clone = Articolo()
                    for c in Articolo.__table__.columns:
                        if c.name not in ['id_articolo', 'attachments']:
                            setattr(clone, c.name, getattr(art, c.name))
                    db.add(clone)
                flash(f"Salvataggio OK. Generate {colli_input - 1} copie aggiuntive.", "success")
            else:
                flash("Modifiche salvate.", "success")

            db.commit()
            return redirect(url_for('giacenze'))

        return render_template('edit.html', row=art)
    except Exception as e:
        db.rollback()
        flash(f"Errore: {e}", "danger")
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

# --- ROUTE PER ELIMINARE UN ALLEGATO ---
@app.route('/delete_attachment/<int:id_attachment>')
@login_required
def delete_attachment(id_attachment):
    # Protezione Ruolo
    if session.get('role') != 'admin':
        flash("Solo gli admin possono eliminare file.", "danger")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        att = db.query(Attachment).filter(Attachment.id == id_attachment).first()
        
        if att:
            article_id = att.articolo_id # Salva ID per il redirect
            
            # Percorsi possibili
            folder = PHOTOS_DIR if att.kind == 'photo' else DOCS_DIR
            file_path = folder / att.filename
            
            # Prova a cancellare il file fisico
            if file_path.exists():
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Avviso: Errore rimozione file fisico {e}")
            
            # ELIMINA SEMPRE DAL DATABASE (Pulizia)
            db.delete(att)
            db.commit()
            
            flash("Allegato eliminato.", "success")
            return redirect(url_for('edit_record', id_articolo=article_id))
        else:
            flash("Allegato non trovato nel database.", "warning")
            return redirect(url_for('giacenze'))
            
    except Exception as e:
        db.rollback()
        flash(f"Errore eliminazione: {e}", "danger")
        return redirect(url_for('giacenze'))
    finally:
        db.close()
@app.route('/giacenze', methods=['GET', 'POST'])
@login_required
def giacenze():
    import logging
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload

    db = SessionLocal()
    try:
        # Query base ottimizzata
        qs = db.query(Articolo).options(selectinload(Articolo.attachments)).order_by(Articolo.id_articolo.desc())

        args = request.args

        # 1. Filtro Cliente (Sicurezza)
        if session.get('role') == 'client':
            qs = qs.filter(Articolo.cliente.ilike(f"%{current_user.id}%"))
        elif args.get('cliente'):
            qs = qs.filter(Articolo.cliente.ilike(f"%{args.get('cliente')}%"))

        # 2. Filtro ID univoco
        if args.get('id'):
            try:
                qs = qs.filter(Articolo.id_articolo == int(args.get('id')))
            except ValueError:
                pass

        # 3. Filtri Testuali (incluso 'stato' che ora è libero)
        text_filters = [
            'commessa', 'descrizione', 'posizione', 'buono_n', 'protocollo', 
            'fornitore', 'ordine', 'magazzino', 'mezzi_in_uscita', 'stato',
            'n_ddt_ingresso', 'n_ddt_uscita', 'codice_articolo', 'serial_number',
            'n_arrivo'
        ]
        
        for field in text_filters:
            val = args.get(field)
            if val and val.strip():
                # Usa ilike per ricerca case-insensitive parziale
                qs = qs.filter(getattr(Articolo, field).ilike(f"%{val.strip()}%"))

        # Esecuzione query DB
        rows_raw = qs.all()
        
        # 4. Filtri DATE (Post-processing in Python per sicurezza)
        rows = []
        
        def get_date(k): 
            v = args.get(k)
            try: return datetime.strptime(v, "%Y-%m-%d").date() if v else None
            except: return None

        d_ing_da = get_date('data_ing_da')
        d_ing_a = get_date('data_ing_a')
        d_usc_da = get_date('data_usc_da')
        d_usc_a = get_date('data_usc_a')

        for r in rows_raw:
            keep = True
            
            # Filtro Data Ingresso
            if d_ing_da or d_ing_a:
                r_dt = None
                if r.data_ingresso:
                    try: r_dt = datetime.strptime(r.data_ingresso, "%Y-%m-%d").date()
                    except: 
                        try: r_dt = datetime.strptime(r.data_ingresso, "%d/%m/%Y").date()
                        except: pass
                
                if not r_dt: keep = False # Se filtro data attivo ma record senza data -> nascondi
                else:
                    if d_ing_da and r_dt < d_ing_da: keep = False
                    if d_ing_a and r_dt > d_ing_a: keep = False
            
            # Filtro Data Uscita
            if keep and (d_usc_da or d_usc_a):
                r_dt = None
                if r.data_uscita:
                    try: r_dt = datetime.strptime(r.data_uscita, "%Y-%m-%d").date()
                    except:
                        try: r_dt = datetime.strptime(r.data_uscita, "%d/%m/%Y").date()
                        except: pass
                
                if not r_dt: keep = False
                else:
                    if d_usc_da and r_dt < d_usc_da: keep = False
                    if d_usc_a and r_dt > d_usc_a: keep = False

            if keep:
                rows.append(r)

        # Totali (Calcolati su ciò che si vede)
        # Nota: totale peso/m2 calcolato solo su merce NON uscita (opzionale, qui su tutto il filtrato)
        total_colli = sum((r.n_colli or 0) for r in rows)
        total_m2 = sum((r.m2 or 0) for r in rows)
        total_peso = sum((r.peso or 0) for r in rows)

        return render_template(
            'giacenze.html',
            rows=rows,
            total_colli=total_colli,
            total_m2=f"{total_m2:.2f}",
            total_peso=f"{total_peso:.2f}"
        )
    except Exception as e:
        logging.error(f"Errore giacenze: {e}")
        return render_template('giacenze.html', rows=[], total_colli=0, total_m2="0", total_peso="0")
    finally:
        db.close()
# --- MODIFICA MULTIPLA COMPLETA CON CALCOLI ---
@app.route('/bulk_edit', methods=['GET', 'POST'])
@login_required
def bulk_edit():
    db = SessionLocal()
    try:
        ids = request.form.getlist('ids') or request.args.getlist('ids')
        if not ids:
            flash("Nessun articolo selezionato.", "warning")
            return redirect(url_for('giacenze'))

        ids = [int(i) for i in ids if str(i).isdigit()]
        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

        # LISTA DI TUTTI I CAMPI RICHIESTI
        editable_fields = [
            ('Cliente', 'cliente'), ('Fornitore', 'fornitore'),
            ('N. DDT Ingresso', 'n_ddt_ingresso'), ('Data Ingresso', 'data_ingresso'),
            ('Data Uscita', 'data_uscita'), ('N. DDT Uscita', 'n_ddt_uscita'),
            ('Protocollo', 'protocollo'), ('N. Buono', 'buono_n'),
            ('Magazzino', 'magazzino'), ('Commessa', 'commessa'),
            ('Ordine', 'ordine'), ('Stato', 'stato'),
            ('Codice Articolo', 'codice_articolo'), ('Serial Number', 'serial_number'),
            ('Colli', 'n_colli'), ('Pezzi', 'pezzo'),
            ('Lunghezza', 'lunghezza'), ('Larghezza', 'larghezza'), ('Altezza', 'altezza')
        ]

        if request.method == 'POST' and request.form.get('save_bulk') == 'true':
            updates = {}
            recalc_dims = False # Flag per ricalcolare M2/M3
            
            # 1. Aggiornamento Campi
            for key in request.form:
                if key.startswith('chk_'):
                    field_name = key.replace('chk_', '') 
                    if any(f[1] == field_name for f in editable_fields):
                        val = request.form.get(field_name)
                        
                        # Conversioni Numeriche
                        if field_name in ['n_colli', 'pezzo']:
                            val = to_int_eu(val)
                        elif field_name in ['lunghezza', 'larghezza', 'altezza']:
                            val = to_float_eu(val)
                        elif 'data' in field_name and val:
                            val = parse_date_ui(val)
                        
                        updates[field_name] = val
                        
                        # Se cambiano le dimensioni o i colli, attiviamo il ricalcolo
                        if field_name in ['lunghezza', 'larghezza', 'altezza', 'n_colli']:
                            recalc_dims = True

            if updates:
                for art in articoli:
                    # Applica le modifiche
                    for k, v in updates.items():
                        if hasattr(art, k):
                            setattr(art, k, v)
                    
                    # CALCOLO AUTOMATICO M2 / M3
                    if recalc_dims:
                        # Se un valore non è stato modificato in massa, usa quello attuale dell'articolo
                        L = updates.get('lunghezza', art.lunghezza)
                        W = updates.get('larghezza', art.larghezza)
                        H = updates.get('altezza', art.altezza)
                        C = updates.get('n_colli', art.n_colli)
                        art.m2, art.m3 = calc_m2_m3(L, W, H, C)

            # 2. Upload Massivo (senza uploaded_at)
            files = request.files.getlist('bulk_file')
            count_files = 0
            from werkzeug.utils import secure_filename
            
            for file in files:
                if file and file.filename:
                    raw_name = secure_filename(file.filename)
                    content = file.read()
                    file.seek(0)
                    ext = raw_name.rsplit('.', 1)[-1].lower()
                    kind = 'photo' if ext in ['jpg','jpeg','png','webp'] else 'doc'
                    dest_dir = PHOTOS_DIR if kind == 'photo' else DOCS_DIR
                    
                    for art in articoli:
                        new_name = f"{art.id_articolo}_{raw_name}"
                        save_path = dest_dir / new_name
                        with open(save_path, 'wb') as f:
                            f.write(content)
                        
                        att = Attachment(articolo_id=art.id_articolo, filename=new_name, kind=kind)
                        db.add(att)
                    count_files += 1

            db.commit()
            flash(f"Aggiornati {len(articoli)} articoli.", "success")
            return redirect(url_for('giacenze'))

        return render_template('bulk_edit.html', rows=articoli, ids_csv=",".join(map(str, ids)), fields=editable_fields)
    
    except Exception as e:
        db.rollback()
        print(f"ERRORE BULK: {e}")
        flash(f"Errore: {e}", "danger")
        return redirect(url_for('giacenze'))
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

# --- GENERAZIONE PDF DDT (LAYOUT RICHIESTO) ---

def _genera_pdf_ddt_file(ddt_data, righe, filename_out):
    import io
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from pathlib import Path

    bio = filename_out
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=5*mm, bottomMargin=5*mm)
    story = []
    
    styles = getSampleStyleSheet()
    s_norm = styles['Normal']
    s_small = ParagraphStyle('s', parent=s_norm, fontSize=9, leading=11)
    s_bold = ParagraphStyle('b', parent=s_small, fontName='Helvetica-Bold')
    s_white = ParagraphStyle('w', parent=s_bold, textColor=colors.white, alignment=TA_CENTER, fontSize=14)

    def clean(val):
        if val is None: return ""
        s = str(val).strip()
        if s.lower() == 'none': return ""
        return s

    # 1. Logo
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=50*mm, height=16*mm, hAlign='CENTER'))
    story.append(Spacer(1, 2*mm))

    # 2. Titolo
    t_title = Table([[Paragraph("DOCUMENTO DI TRASPORTO (DDT)", s_white)]], colWidths=[190*mm])
    t_title.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#4682B4")), 
        ('PADDING', (0,0), (-1,-1), 6)
    ]))
    story.append(t_title)
    story.append(Spacer(1, 2*mm))

    # 3. Testata
    dest_ragione = clean(ddt_data.get('destinatario'))
    dest_ind = clean(ddt_data.get('dest_indirizzo')).replace('\n', '<br/>')
    dest_citta = clean(ddt_data.get('dest_citta'))
    
    mittente_html = "<b>Mittente</b><br/>Camar srl<br/>Via Luigi Canepa 2<br/>16165 Genova Struppa (GE)"
    dest_html = f"<b>Destinatario</b><br/>{dest_ragione}<br/>{dest_ind}<br/>{dest_citta}"
    
    t_md = Table([[Paragraph(mittente_html, s_small), Paragraph(dest_html, s_small)]], colWidths=[95*mm, 95*mm])
    t_md.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 5)
    ]))
    story.append(t_md)
    story.append(Spacer(1, 2*mm))

    # 4. Dati Aggiuntivi
    t_bar = Table([[Paragraph("Dati Aggiuntivi", ParagraphStyle('wb', parent=s_white, fontSize=10, alignment=TA_LEFT))]], colWidths=[190*mm])
    t_bar.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#4682B4")), ('PADDING', (0,0), (-1,-1), 2)]))
    story.append(t_bar)

    first = righe[0] if righe else {}
    commessa = clean(first.get('commessa', ''))
    ordine = clean(first.get('ordine', ''))
    buono = clean(first.get('buono', ''))
    protocollo = clean(first.get('protocollo', ''))
    n_ddt = clean(ddt_data.get('n_ddt'))
    data_ddt = clean(ddt_data.get('data_uscita'))
    targa = clean(ddt_data.get('vettore')) 
    causale = clean(ddt_data.get('causale'))

    dati_agg = [
        [Paragraph("<b>Commessa</b>", s_bold), Paragraph(commessa, s_small), Paragraph("<b>N. DDT</b>", s_bold), Paragraph(n_ddt, s_small)],
        [Paragraph("<b>Ordine</b>", s_bold), Paragraph(ordine, s_small), Paragraph("<b>Data Uscita</b>", s_bold), Paragraph(data_ddt, s_small)],
        [Paragraph("<b>Buono</b>", s_bold), Paragraph(buono, s_small), Paragraph("<b>Targa</b>", s_bold), Paragraph(targa, s_small)],
        [Paragraph("<b>Protocollo</b>", s_bold), Paragraph(protocollo, s_small), Paragraph("<b>Causale</b>", s_bold), Paragraph(causale, s_small)]
    ]
    t_agg = Table(dati_agg, colWidths=[25*mm, 70*mm, 25*mm, 70*mm])
    t_agg.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(t_agg)
    story.append(Spacer(1, 5*mm))

    # 5. Articoli
    story.append(Paragraph("<b>Articoli nel DDT</b>", ParagraphStyle('h', parent=s_bold, fontSize=10)))
    
    header = [Paragraph(x, s_bold) for x in ['ID', 'Cod.Art.', 'Descrizione', 'Pezzi', 'Colli', 'Peso', 'N.Arrivo']]
    data = [header]
    
    tot_pezzi = 0; tot_colli = 0; tot_peso = 0.0
    note_da_stampare = []

    for r in righe:
        pz = int(r.get('pezzo') or 0)
        cl = int(r.get('n_colli') or 0)
        we = float(r.get('peso') or 0.0)
        tot_pezzi += pz; tot_colli += cl; tot_peso += we
        
        # Note fuori (MODIFICATO: Solo il testo della nota, senza codice articolo)
        nota = r.get('note')
        if nota and str(nota).strip():
            # Prima era: f"NOTE ARTICOLO ({r.get('codice_articolo')}): {nota}"
            # Ora è solo: f"NOTE: {nota}"
            note_da_stampare.append(f"NOTE: {nota}")

        data.append([
            Paragraph(str(r.get('id_articolo','')), s_small),
            Paragraph(clean(r.get('codice_articolo')), s_small),
            Paragraph(clean(r.get('descrizione')), s_small),
            str(pz),
            str(cl),
            f"{we:.0f}",
            Paragraph(clean(r.get('n_arrivo')), s_small)
        ])

    t_items = Table(data, colWidths=[15*mm, 35*mm, 80*mm, 15*mm, 15*mm, 15*mm, 15*mm], repeatRows=1)
    t_items.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4)
    ]))
    story.append(t_items)
    story.append(Spacer(1, 3*mm))

    # Note
    if note_da_stampare:
        story.append(Spacer(1, 2*mm))
        for n in note_da_stampare:
            story.append(Paragraph(f"<i>{n}</i>", s_small))
        story.append(Spacer(1, 3*mm))

    # 6. Footer
    porto = clean(ddt_data.get('porto'))
    aspetto = clean(ddt_data.get('aspetto'))

    footer_data = [
        [
            Paragraph(f"<b>Porto:</b> {porto}", s_small),
            Paragraph(f"<b>Aspetto:</b> {aspetto}", s_small)
        ],
        [
            Paragraph(f"<b>TOTALE:</b> Pezzi {tot_pezzi} - Colli {tot_colli} - Peso {tot_peso:.0f} Kg", s_bold),
            Paragraph("Firma Vettore: _______________________", s_small)
        ]
    ]
    
    t_foot = Table(footer_data, colWidths=[95*mm, 95*mm])
    t_foot.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,1), (0,1), colors.whitesmoke),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_foot)

    doc.build(story)

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
        

@app.route('/ddt/finalize', methods=['POST'])
@login_required
def ddt_finalize():
    import io
    db = SessionLocal()
    try:
        # 1. Recupera ID e Azione
        ids_str = request.form.get('ids', '')
        ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
        action = request.form.get('action', 'preview') 
        
        # 2. Dati Testata
        n_ddt = request.form.get('n_ddt', '').strip()
        data_ddt_str = request.form.get('data_ddt')
        
        try:
            data_ddt_obj = datetime.strptime(data_ddt_str, "%Y-%m-%d").date()
            data_formatted = data_ddt_obj.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            data_ddt_obj = date.today()
            data_formatted = date.today().strftime("%d/%m/%Y")
            data_ddt_str = date.today().strftime("%Y-%m-%d")

        # 3. Recupera Destinatario
        dest_ragione = request.form.get('dest_ragione', '')
        dest_indirizzo = request.form.get('dest_indirizzo', '')
        dest_citta = request.form.get('dest_citta', '')
        
        # Sovrascrittura da eventuale rubrica
        dest_key = request.form.get('dest_key')
        if dest_key:
             try:
                 dest_info = load_destinatari().get(dest_key, {})
                 if dest_info:
                     dest_ragione = dest_info.get('ragione_sociale', '')
                     dest_indirizzo = dest_info.get('indirizzo', '')
                     dest_citta = dest_info.get('citta', '')
             except: pass
        
        # 4. Recupera Articoli
        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
        righe_per_pdf = []

        # 5. Loop Articoli
        for art in articoli:
            # Recupera modifiche dal form
            raw_pezzi = request.form.get(f"pezzi_{art.id_articolo}")
            raw_colli = request.form.get(f"colli_{art.id_articolo}")
            raw_peso = request.form.get(f"peso_{art.id_articolo}")
            # Recupera la nota (eventualmente modificata)
            nuove_note = request.form.get(f"note_{art.id_articolo}", art.note)
            
            nuovi_pezzi = to_int_eu(raw_pezzi) if raw_pezzi is not None else art.pezzo
            nuovi_colli = to_int_eu(raw_colli) if raw_colli is not None else art.n_colli
            nuovo_peso = to_float_eu(raw_peso) if raw_peso is not None else art.peso
            
            # Se Finalizza -> Salva su DB
            if action == 'finalize':
                art.data_uscita = data_ddt_obj
                art.n_ddt_uscita = n_ddt
                if nuove_note: art.note = nuove_note
            
            # Prepara riga PDF (AGGIUNTI I CAMPI MANCANTI)
            righe_per_pdf.append({
                'codice_articolo': art.codice_articolo or '',
                'descrizione': art.descrizione or '',
                'pezzo': nuovi_pezzi,
                'n_colli': nuovi_colli,
                'peso': nuovo_peso,
                'n_arrivo': art.n_arrivo or '',
                'note': nuove_note,           
                'commessa': art.commessa,     # <--- AGGIUNTO
                'ordine': art.ordine,         # <--- AGGIUNTO
                'buono': art.buono_n,         # <--- AGGIUNTO
                'protocollo': art.protocollo  # <--- AGGIUNTO
            })

        # 6. Salvataggio DB
        if action == 'finalize':
            db.commit()
            flash(f"DDT N.{n_ddt} del {data_formatted} salvato con successo.", "success")

        # 7. Dati Generali PDF
        ddt_data = {
            'n_ddt': n_ddt,
            'data_uscita': data_formatted,
            'destinatario': dest_ragione,
            'dest_indirizzo': dest_indirizzo,
            'dest_citta': dest_citta,
            'causale': request.form.get('causale', ''),
            'vettore': request.form.get('targa', ''),
            'porto': request.form.get('porto', 'FRANCO'),
            'aspetto': request.form.get('aspetto', 'A VISTA')
        }

        # 8. Genera PDF
        pdf_bio = io.BytesIO()
        _genera_pdf_ddt_file(ddt_data, righe_per_pdf, pdf_bio)
        pdf_bio.seek(0)
        
        safe_n = n_ddt.replace('/', '-').replace('\\', '-')
        filename = f"DDT_{safe_n}_{data_ddt_str}.pdf"

        return send_file(
            pdf_bio,
            as_attachment=(action == 'finalize'),
            download_name=filename,
            mimetype='application/pdf'
        )

    except Exception as e:
        db.rollback()
        print(f"Errore DDT Finalize: {e}")
        return f"Errore durante la creazione del DDT: {e}", 500
    finally:
        db.close()

@app.get('/labels')
@login_required
def labels_form():
    # --- PROTEZIONE ADMIN ---
    if session.get('role') != 'admin':
        flash("Accesso negato.", "danger")
        return redirect(url_for('giacenze'))
    # ------------------------

    db = SessionLocal()
    try:
        clienti_query = db.query(Articolo.cliente).distinct().filter(Articolo.cliente != None, Articolo.cliente != '').order_by(Articolo.cliente).all()
        clienti = [c[0] for c in clienti_query]
        return render_template('labels_form.html', clienti=clienti)
    finally:
        db.close()


@app.route('/labels_pdf', methods=['POST'])
@login_required
def labels_pdf():
    # PROTEZIONE ADMIN
    if session.get('role') != 'admin':
        flash("Funzione riservata agli amministratori.", "danger")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    ids = request.form.getlist('ids')
    articoli_da_stampare = []

    try:
        if ids:
            # CASO A: Selezione Multipla dalla Tabella
            records = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            articoli_da_stampare = records
        else:
            # CASO B: Inserimento Manuale (Pagina "Crea Etichette")
            a = Articolo()
            a.cliente = request.form.get('cliente')
            a.fornitore = request.form.get('fornitore')
            a.ordine = request.form.get('ordine')
            a.commessa = request.form.get('commessa')
            a.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            
            d_ing = request.form.get('data_ingresso')
            a.data_ingresso = parse_date_ui(d_ing) if d_ing else date.today().strftime("%Y-%m-%d")
            
            a.n_arrivo = request.form.get('n_arrivo')
            a.posizione = request.form.get('posizione')
            # N. Colli manuale
            a.n_colli = to_int_eu(request.form.get('n_colli')) or 1
            
            articoli_da_stampare = [a]
        
        if not articoli_da_stampare:
            flash("Nessun dato per la stampa.", "warning")
            return redirect(url_for('giacenze'))

        # Genera il PDF (Passiamo '62x100' come richiesto)
        pdf_file = _genera_pdf_etichetta(articoli_da_stampare, '62x100')
        
        # Scarica il file
        return send_file(
            pdf_file, 
            as_attachment=True, 
            download_name='Etichette_Camar.pdf', 
            mimetype='application/pdf'
        )
    
    except Exception as e:
        flash(f"Errore generazione PDF: {e}", "danger")
        return redirect(url_for('giacenze'))
    finally:
        db.close()

# --- FUNZIONE ETICHETTE COMPATTA (100x62) ---
def _genera_pdf_etichetta(articoli, formato='62x100', anteprima=False):
    import io
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from pathlib import Path

    bio = io.BytesIO()
    
    # Formato Etichetta Orizzontale
    pagesize = (100*mm, 62*mm) 
    # Margini ridotti al minimo per sfruttare lo spazio
    margin_top = 1*mm
    margin_side = 2*mm

    doc = SimpleDocTemplate(
        bio, 
        pagesize=pagesize, 
        leftMargin=margin_side, 
        rightMargin=margin_side, 
        topMargin=margin_top, 
        bottomMargin=margin_top
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # --- STILI PERSONALIZZATI PER RIDURRE SPAZIO ---
    # leading = spazio tra le righe. Lo teniamo basso.
    
    # Etichetta (es. "CLIENTE:") - Font 9
    s_lbl = ParagraphStyle('L', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=9)
    # Valore (es. "WINGECO") - Font 10
    s_val = ParagraphStyle('V', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=10)
    
    # Stile GRANDE per Arrivo e Collo - Font 14, Bold
    s_big = ParagraphStyle('B', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, leading=16, alignment=1) # Centrato

    for art in articoli:
        tot = int(art.n_colli) if (art.n_colli and str(art.n_colli).isdigit()) else 1
        if tot < 1: tot = 1

        for i in range(1, tot + 1):
            # 1. LOGO
            if LOGO_PATH and Path(LOGO_PATH).exists():
                story.append(Image(LOGO_PATH, width=35*mm, height=9*mm, hAlign='LEFT'))
                # Pochissimo spazio dopo il logo
                story.append(Spacer(1, 1*mm))
            
            # 2. STRINGHE COMPOSTE
            # Combina: ARRIVO: 01/24 N.1
            arr_base = art.n_arrivo or ''
            txt_arrivo_combined = f"ARRIVO: {arr_base}  N.{i}"
            
            txt_collo = f"COLLO: {i} / {tot}"

            # 3. TABELLA DATI (Compatta)
            dati = [
                [Paragraph("CLIENTE:", s_lbl), Paragraph(str(art.cliente or '')[:25], s_val)],
                [Paragraph("FORNITORE:", s_lbl), Paragraph(str(art.fornitore or '')[:25], s_val)],
                [Paragraph("ORDINE:", s_lbl), Paragraph(str(art.ordine or ''), s_val)],
                [Paragraph("COMMESSA:", s_lbl), Paragraph(str(art.commessa or ''), s_val)],
                [Paragraph("DDT ING.:", s_lbl), Paragraph(str(art.n_ddt_ingresso or ''), s_val)],
                [Paragraph("DATA ING.:", s_lbl), Paragraph(fmt_date(art.data_ingresso), s_val)],
                
                # Riga separatoria invisibile (spazio minimo)
                ['', ''],
                
                # Arrivo Combinato (es. ARRIVO: 01/24 N.1) su tutta la larghezza
                [Paragraph(txt_arrivo_combined, s_big), ''], 
                # Collo su tutta la larghezza
                [Paragraph(txt_collo, s_big), '']
            ]
            
            t = Table(dati, colWidths=[23*mm, 72*mm])
            t.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                # Riduciamo il padding interno celle a zero per compattare
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                # Unisci le celle delle ultime due righe (Arrivo e Collo) per centrarle meglio
                ('SPAN', (0,6), (1,6)), # Riga Arrivo
                ('SPAN', (0,7), (1,7)), # Riga Collo
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
    


    
# --- FIX DATABASE SCHEMA (Esegui all'avvio per correggere tipi colonne) ---
# ========================================================
# 🚑 PULSANTE DI EMERGENZA PER FIX DATABASE
# ========================================================
@app.route('/fix_db_types')
@login_required
def fix_db_types():
    if session.get('role') != 'admin':
        return "Accesso Negato", 403
    
    db = SessionLocal()
    try:
        from sqlalchemy import text
        # ELENCO DI TUTTE LE COLONNE DA SBLOCCARE (Convertire in TEXT)
        colonne_da_sbloccare = [
            'codice_articolo', 
            'descrizione', 
            'commessa', 
            'ordine', 
            'n_ddt_ingresso', 
            'n_ddt_uscita', 
            'n_arrivo',
            'buono_n',
            'protocollo',
            'cliente',
            'fornitore',
            # AGGIUNTO ORA: Convertiamo anche le date per evitare errori Timestamp!
            'data_ingresso', 
            'data_uscita',
            'serial_number',
            'magazzino',
            'posizione',
            'stato'
        ]
        
        log_msg = "<h3>Operazioni Database (Fix Tipi):</h3><ul>"
        
        for col in colonne_da_sbloccare:
            try:
                # Comando SQL per convertire forzatamente in TEXT
                sql = text(f"ALTER TABLE articoli ALTER COLUMN {col} TYPE TEXT USING {col}::text")
                db.execute(sql)
                log_msg += f"<li>✅ Colonna <b>{col}</b> convertita in TEXT.</li>"
            except Exception as e:
                log_msg += f"<li>⚠️ Colonna <b>{col}</b>: {str(e)}</li>"
        
        db.commit()
        log_msg += "</ul><br><h3 style='color:green'>DATABASE SBLOCCATO! Ora riprova l'importazione.</h3>"
        log_msg += f'<br><a href="{url_for("home")}">Torna alla Home</a>'
        return log_msg
        
    except Exception as e:
        db.rollback()
        return f"<h1>ERRORE CRITICO:</h1> {e}"
    finally:
        db.close()



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
    # --- PROTEZIONE ADMIN ---
    if session.get('role') != 'admin':
        flash("Accesso negato: Funzione riservata agli amministratori.", "danger")
        return redirect(url_for('giacenze'))
    # ------------------------

    # Defaults per il form
    oggi = date.today()
    data_da_val = (oggi.replace(day=1)).strftime("%Y-%m-%d")
    data_a_val = oggi.strftime("%Y-%m-%d")
    cliente_val = ""
    raggruppamento = "mese"
    risultati = []

    if request.method == 'POST':
        data_da_str = request.form.get('data_da')
        data_a_str = request.form.get('data_a')
        cliente_val = request.form.get('cliente', '').strip()
        raggruppamento = request.form.get('raggruppamento', 'mese')
        
        try:
            d_da = datetime.strptime(data_da_str, "%Y-%m-%d").date()
            d_a = datetime.strptime(data_a_str, "%Y-%m-%d").date()
            
            db = SessionLocal()
            query = db.query(Articolo).filter(Articolo.data_ingresso.isnot(None), Articolo.data_ingresso != '')
            
            if cliente_val:
                query = query.filter(Articolo.cliente.ilike(f"%{cliente_val}%"))
                
            articoli = query.all()
            db.close()
            
            # Esegui calcolo logico (assicurati di avere la funzione _calcola_logica_costi nel file)
            risultati = _calcola_logica_costi(articoli, d_da, d_a, raggruppamento)
            
            data_da_val = data_da_str
            data_a_val = data_a_str

        except Exception as e:
            flash(f"Errore nel calcolo: {e}", "danger")

    return render_template('calcoli.html', risultati=risultati, data_da=data_da_val, data_a=data_a_val, cliente_filtro=cliente_val, raggruppamento=raggruppamento)


# --- AVVIO FLASK APP ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
