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
import smtplib
import hashlib  # <--- QUESTO MANCAVA E CAUSA ERRORI
import math
import mimetypes
from urllib.parse import unquote
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict
from functools import wraps

# Excel e PDF
import pandas as pd
import pdfplumber

# Email
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders

# Flask
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify, render_template_string, abort
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Database (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Date, ForeignKey, Boolean, or_, Identity, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session, selectinload
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak

# Jinja
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
MAPPE_FILE_ORIGINAL = APP_DIR / "config." / "mappe_excel.json" # File originale (da GitHub)

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


# --- MODELLO TABELLA TRASPORTI (Separata da Articoli) ---
class Trasporto(Base):
    __tablename__ = 'trasporti'
    id = Column(Integer, primary_key=True)
    data = Column(Date)
    tipo_mezzo = Column(Text)       # Es. Motrice, Bilico
    cliente = Column(Text)
    trasportatore = Column(Text)
    ddt_uscita = Column(Text)       # N. DDT
    magazzino = Column(Text)        # Nuovo
    consolidato = Column(Text)      # Nuovo
    costo = Column(Float)

# --- MODELLO TABELLA PICKING / LAVORAZIONI (Separata da Articoli) ---
class Lavorazione(Base):
    __tablename__ = 'lavorazioni'
    id = Column(Integer, primary_key=True)
    data = Column(Date)
    cliente = Column(Text)
    descrizione = Column(Text)
    richiesta_di = Column(Text)     # Nuovo
    seriali = Column(Text)          # Nuovo
    colli = Column(Integer)
    pallet_forniti = Column(Integer) # Pallet IN
    pallet_uscita = Column(Integer)  # Pallet OUT
    ore_blue_collar = Column(Float)  # Ore Blue
    ore_white_collar = Column(Float) # Ore White

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


def parse_date_ui(s):
    s = (s or "").strip()
    if not s:
        return None

    # supporta sia YYYY-MM-DD (input date) sia DD/MM/YYYY
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

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
        .navbar { background-color: #1f6fb2; } /* Blu Camar */
        .navbar-brand, .nav-link, .navbar-text { color: white !important; }
        .nav-link:hover { opacity: 0.8; }
        
        .card { border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.08); border: none; }
        .table-container { overflow: auto; max-height: 65vh; }
        .table thead th { position: sticky; top: 0; background: #f0f2f5; z-index: 2; }
        .dropzone { border: 2px dashed #0d6efd; background: #eef4ff; padding: 20px; border-radius: 12px; text-align: center; color: #0d6efd; cursor: pointer; }
        .logo { height: 32px; width: auto; }
        .table-compact th, .table-compact td { font-size: 11px; padding: 4px 5px; white-space: normal; word-wrap: break-word; vertical-align: middle; }
        .table-striped tbody tr:nth-of-type(odd) { background-color: rgba(0,0,0,.03); }
        
        /* Stile Bottoni Admin nel Menu */
        .btn-nav-admin { font-weight: bold; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
        
        @media print { .no-print { display: none !important; } }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark shadow-sm no-print">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center gap-2" href="{{ url_for('home') }}">
            {% if logo_url %}<img src="{{ logo_url }}" class="logo" alt="logo">{% endif %}
            Camar • Gestionale
        </a>

        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>

        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav ms-auto align-items-center gap-2">
                
                <li class="nav-item"><a class="nav-link" href="{{ url_for('giacenze') }}">📦 Magazzino</a></li>
                <li class="nav-item"><a class="nav-link" href="{{ url_for('import_excel') }}">📥 Import Excel</a></li>

                {% if session.get('role') == 'admin' %}
                    <li class="nav-item border-start border-light ps-2 ms-2 d-none d-lg-block"></li> <li class="nav-item">
                        <a class="nav-link btn btn-danger text-white px-3 ms-2 btn-nav-admin" href="{{ url_for('trasporti') }}">
                            <i class="bi bi-truck"></i> TRASPORTI
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link btn btn-success text-white px-3 ms-2 btn-nav-admin" href="{{ url_for('lavorazioni') }}">
                            <i class="bi bi-box-seam"></i> PICKING
                        </a>
                    </li>
                    <li class="nav-item">
                         <a class="nav-link text-white-50 ms-1" href="{{ url_for('manage_mappe') }}" title="Gestione Mappe"><i class="bi bi-gear"></i></a>
                    </li>
                {% endif %}

                {% if session.get('user') %}
                    <li class="nav-item ms-4 text-white-50 small d-none d-lg-block">Utente: <b>{{ session['user'] }}</b></li>
                    <li class="nav-item">
                        <a class="btn btn-outline-light btn-sm ms-2" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Esci</a>
                    </li>
                {% endif %}
            </ul>
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

<footer class="text-center text-white py-3 small no-print" style="background-color: #1f6fb2; margin-top: auto;">
    © Alessia Moncalvo – Gestionale Camar Web Edition • Tutti i diritti riservati.
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% block extra_js %}{% endblock %}
</body>
</html>
"""
REPORT_INVENTARIO_HTML = """
<!DOCTYPE html>
<html>
<head><title>Inventario al {{ data_rif }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body onload="window.print()">
    <div class="container mt-4">
        <h1 class="text-center">Inventario al {{ data_rif }}</h1>
        <hr>
        {% for cliente, articoli in inventario.items() %}
            <h3 class="mt-4 bg-light p-2">{{ cliente }}</h3>
            <table class="table table-sm table-bordered">
                <thead>
                    <tr>
                        <th>Codice</th>
                        <th>Descrizione</th>
                        <th>Lotto</th>
                        <th>Q.tà</th>
                        <th>Posizione</th>
                    </tr>
                </thead>
                <tbody>
                    {% for art in articoli %}
                    <tr>
                        <td>{{ art.codice_articolo or '' }}</td>
                        <td>{{ art.descrizione or '' }}</td>
                        <!-- ✅ se lotto è vuoto/None resta vuoto -->
                        <td>{{ art.lotto or '' }}</td>
                        <td>{{ art.n_colli or '' }}</td>
                        <td>{{ art.posizione or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <div style="page-break-after: always;"></div>
        {% endfor %}
    </div>
</body>
</html>
"""


REPORT_TRASPORTI_HTML = """
<!DOCTYPE html>
<html>
<head><title>Report Trasporti</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body onload="window.print()">
    <div class="container mt-5">
        <h1>Report Trasporti</h1>
        <p>Periodo: {{ mese }} | Cliente: {{ cliente or 'Tutti' }}</p>
        <table class="table table-bordered">
            <thead><tr><th>Data</th><th>Mezzo</th><th>Cliente</th><th>Trasportatore</th><th>Costo</th></tr></thead>
            <tbody>
                {% for t in dati %}
                <tr>
                    <td>{{ t.data }}</td><td>{{ t.tipo_mezzo }}</td>
                    <td>{{ t.cliente }}</td><td>{{ t.trasportatore }}</td><td>€ {{ t.costo }}</td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot>
                <tr class="table-dark">
                    <td colspan="4" class="text-end">TOTALE</td>
                    <td>€ {{ totale }}</td>
                </tr>
            </tfoot>
        </table>
    </div>
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
    .table-compact td, .table-compact th {
        font-size: 0.78rem;
        padding: 4px 6px;
        vertical-align: middle;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 160px;
    }
    .table-compact th { background-color: #f0f0f0; font-weight: 700; text-align: center; }
    .fw-buono { font-weight: bold; color: #000; }
    .att-link { text-decoration: none; font-size: 1.3em; cursor: pointer; margin: 0 3px; }
    .att-link:hover { transform: scale(1.2); display:inline-block; }
</style>

<div class="d-flex justify-content-between align-items-center mb-2">
    <h4 class="mb-0"><i class="bi bi-box-seam"></i> Magazzino</h4>
    <div class="d-flex gap-2 flex-wrap">
       <a href="{{ url_for('nuovo_articolo') }}" class="btn btn-sm btn-success"><i class="bi bi-plus-lg"></i> Nuovo</a>
       <a href="{{ url_for('import_pdf') }}" class="btn btn-sm btn-dark"><i class="bi bi-file-earmark-pdf"></i> Import PDF</a>

       <form action="{{ url_for('labels_pdf') }}" method="POST" target="_blank" class="d-inline">
           <button class="btn btn-sm btn-info text-white"><i class="bi bi-tag"></i> Etichette</button>
       </form>

       <a href="{{ url_for('calcola_costi') }}" class="btn btn-sm btn-warning"><i class="bi bi-calculator"></i> Calcoli</a>

       {% if session.get('role') == 'admin' %}
       <form action="{{ url_for('report_inventario') }}" method="POST" target="_blank" class="d-inline-block">
            <div class="input-group input-group-sm">
                <input type="date" name="data_inventario" class="form-control" required value="{{ today }}">
                <button class="btn btn-warning" type="submit" title="Stampa Inventario">📋</button>
            </div>
       </form>
       {% endif %}
    </div>
</div>

<div class="card mb-2 bg-light shadow-sm">
    <div class="card-header py-1" data-bs-toggle="collapse" data-bs-target="#filterBody" style="cursor:pointer">
        <small><i class="bi bi-funnel"></i> <b>Filtri Avanzati</b></small>
    </div>

    <div id="filterBody" class="collapse {% if request.args %}show{% endif %}">
        <div class="card-body py-2">
            <form method="get">
                <div class="row g-1 mb-1">
                    <div class="col-md-1"><input name="id" class="form-control form-control-sm" placeholder="ID" value="{{ request.args.get('id','') }}"></div>
                    <div class="col-md-2"><input name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ request.args.get('cliente','') }}"></div>
                    <div class="col-md-2"><input name="fornitore" class="form-control form-control-sm" placeholder="Fornitore" value="{{ request.args.get('fornitore','') }}"></div>
                    <div class="col-md-2"><input name="codice_articolo" class="form-control form-control-sm" placeholder="Codice Articolo" value="{{ request.args.get('codice_articolo','') }}"></div>
                    <div class="col-md-2"><input name="serial_number" class="form-control form-control-sm" placeholder="Serial Number" value="{{ request.args.get('serial_number','') }}"></div>
                    <div class="col-md-2"><input name="ordine" class="form-control form-control-sm" placeholder="Ordine" value="{{ request.args.get('ordine','') }}"></div>
                    <div class="col-md-1"><button type="submit" class="btn btn-primary btn-sm w-100">Cerca</button></div>
                </div>

                <div class="row g-1 mb-1">
                    <div class="col-md-2"><input name="protocollo" class="form-control form-control-sm" placeholder="Protocollo" value="{{ request.args.get('protocollo','') }}"></div>
                    <div class="col-md-2"><input name="descrizione" class="form-control form-control-sm" placeholder="Descrizione" value="{{ request.args.get('descrizione','') }}"></div>
                    <div class="col-md-2"><input name="buono_n" class="form-control form-control-sm" placeholder="N. Buono" value="{{ request.args.get('buono_n','') }}"></div>
                    <div class="col-md-2"><input name="n_arrivo" class="form-control form-control-sm" placeholder="N. Arrivo" value="{{ request.args.get('n_arrivo','') }}"></div>
                    <div class="col-md-2"><input name="mezzi_in_uscita" class="form-control form-control-sm" placeholder="Mezzo Uscita" value="{{ request.args.get('mezzi_in_uscita','') }}"></div>
                    <div class="col-md-2"><input name="stato" class="form-control form-control-sm" placeholder="Stato" value="{{ request.args.get('stato','') }}"></div>
                </div>

                <div class="row g-1 mb-1">
                    <div class="col-md-2"><input name="n_ddt_ingresso" class="form-control form-control-sm" placeholder="N. DDT Ingresso" value="{{ request.args.get('n_ddt_ingresso','') }}"></div>
                    <div class="col-md-2"><input name="n_ddt_uscita" class="form-control form-control-sm" placeholder="N. DDT Uscita" value="{{ request.args.get('n_ddt_uscita','') }}"></div>

                    <div class="col-md-4">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Ingresso</span>
                            <input name="data_ing_da" type="date" class="form-control" value="{{ request.args.get('data_ing_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_ing_a" type="date" class="form-control" value="{{ request.args.get('data_ing_a','') }}">
                        </div>
                    </div>

                    <div class="col-md-4">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Uscita</span>
                            <input name="data_usc_da" type="date" class="form-control" value="{{ request.args.get('data_usc_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_usc_a" type="date" class="form-control" value="{{ request.args.get('data_usc_a','') }}">
                        </div>
                    </div>
                </div>

                <div class="row g-1">
                    <div class="col-md-2 ms-auto">
                        <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm w-100" onclick="localStorage.removeItem('camar_selected_articles');">Reset</a>
                    </div>
                </div>
            </form>
        </div>
    </div>
</div>

<form method="POST">
    <div class="btn-toolbar mb-2 gap-1 flex-wrap">
        <button type="submit" formaction="{{ url_for('buono_preview') }}" class="btn btn-outline-dark btn-sm">Buono</button>
        <button type="submit" formaction="{{ url_for('ddt_preview') }}" class="btn btn-outline-dark btn-sm">DDT</button>

        <!-- ✅ INVIA EMAIL (GET verso /invia_email con ids selezionati) -->
        <button type="submit" formaction="{{ url_for('invia_email') }}" formmethod="get" class="btn btn-success btn-sm">
            <i class="bi bi-envelope"></i> Invia E-mail
        </button>

        <button type="submit" formaction="{{ url_for('bulk_edit') }}" class="btn btn-info btn-sm text-white">Mod. Multipla</button>
        <button type="submit" formaction="{{ url_for('labels_pdf') }}" formtarget="_blank" class="btn btn-warning btn-sm">
            <i class="bi bi-download"></i> Scarica Etichette
        </button>

        <button type="submit" formaction="{{ url_for('delete_rows') }}" class="btn btn-danger btn-sm" onclick="return confirm('Eliminare SELEZIONATI?')">
            Elimina Selezionati
        </button>

        <button type="submit" formaction="{{ url_for('bulk_duplicate') }}" class="btn btn-primary btn-sm" onclick="return confirm('Duplicare gli articoli selezionati?')">
            Duplica Selezionati
        </button>
    </div>

    <div class="table-responsive shadow-sm" style="max-height: 70vh;">
        <table class="table table-striped table-bordered table-hover table-compact mb-0">
            <thead class="sticky-top" style="top:0; z-index:5;">
                <tr>
                    <th><input type="checkbox" onclick="toggleAll(this)"></th>

                    <th>ID</th>
                    <th>Codice</th>
                    <th>Pz</th>
                    <th>Larg</th>
                    <th>Lung</th>
                    <th>Alt</th>
                    <th>M2</th>
                    <th>M3</th>

                    <th>Descrizione</th>
                    <th>Protocollo</th>
                    <th>Ordine</th>
                    <th>Colli</th>
                    <th>Fornitore</th>
                    <th>Magazzino</th>

                    <th>Data Ing</th>
                    <th>DDT Ing</th>
                    <th>DDT Usc</th>
                    <th>Data Usc</th>
                    <th>Mezzo Usc</th>

                    <th>Cliente</th>
                    <th>Kg</th>
                    <th>Posizione</th>
                    <th>N.Arr</th>
                    <th>N.Buono</th>
                    <th>Note</th>
                    <th>Lotto</th>
                    <th>Ns.Rif</th>
                    <th>Serial</th>
                    <th>Stato</th>

                    <th>Doc Arrivo</th>
                    <th>Foto Arrivo</th>

                    <th style="min-width: 70px;">Act</th>
                </tr>
            </thead>

            <tbody>
                {% for r in rows %}
                {% set desc = (r.descrizione or '') %}
                <tr>
                    <td class="text-center">
                        <input type="checkbox" name="ids" value="{{ r.id_articolo }}" class="row-checkbox">
                    </td>

                    <td>{{ r.id_articolo }}</td>
                    <td title="{{ r.codice_articolo }}">{{ r.codice_articolo or '' }}</td>
                    <td>{{ r.pezzo or '' }}</td>

                    <td>{{ r.larghezza|float|round(2) if r.larghezza is not none else '' }}</td>
                    <td>{{ r.lunghezza|float|round(2) if r.lunghezza is not none else '' }}</td>
                    <td>{{ r.altezza|float|round(2) if r.altezza is not none else '' }}</td>

                    <td>{{ r.m2|float|round(3) if r.m2 else '' }}</td>
                    <td>{{ r.m3|float|round(3) if r.m3 else '' }}</td>

                    <td title="{{ desc }}">{{ desc[:30] }}{% if desc|length > 30 %}...{% endif %}</td>
                    <td>{{ r.protocollo or '' }}</td>
                    <td>{{ r.ordine or '' }}</td>
                    <td>{{ r.n_colli or '' }}</td>
                    <td>{{ r.fornitore or '' }}</td>
                    <td>{{ r.magazzino or '' }}</td>

                    <td>{{ r.data_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_uscita or '' }}</td>
                    <td>{{ r.data_uscita or '' }}</td>
                    <td>{{ r.mezzi_in_uscita or '' }}</td>

                    <td>{{ r.cliente or '' }}</td>
                    <td>{{ r.peso or '' }}</td>
                    <td>{{ r.posizione or '' }}</td>
                    <td>{{ r.n_arrivo or '' }}</td>
                    <td class="fw-buono">{{ r.buono_n or '' }}</td>
                    <td title="{{ r.note or '' }}">{{ (r.note or '')[:20] }}{% if (r.note or '')|length > 20 %}...{% endif %}</td>
                    <td>{{ r.lotto or '' }}</td>
                    <td>{{ r.ns_rif or '' }}</td>
                    <td>{{ r.serial_number or '' }}</td>
                    <td>{{ r.stato or '' }}</td>

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

                    <td class="text-center">
                        <a href="{{ url_for('edit_articolo', id=r.id_articolo) }}" title="Modifica" class="text-decoration-none me-2">✏️</a>
                        <a href="{{ url_for('delete_articolo', id=r.id_articolo) }}" title="Elimina" class="text-decoration-none text-danger" onclick="return confirm('Eliminare articolo {{ r.id_articolo }}?');">🗑️</a>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="33" class="text-center p-3 text-muted">Nessun articolo trovato con questi filtri.</td></tr>
                {% endfor %}
            </tbody>

            <tfoot class="sticky-bottom bg-white fw-bold">
                <tr><td colspan="33">Totali: Colli {{ total_colli }} | M2 {{ total_m2 }} | Peso {{ total_peso }}</td></tr>
            </tfoot>
        </table>
    </div>
</form>

<script>
function toggleAll(source) {
    document.getElementsByName('ids').forEach(c => {
        c.checked = source.checked;
        c.dispatchEvent(new Event('change'));
    });
}

document.addEventListener("DOMContentLoaded", function() {
    const STORAGE_KEY = 'camar_selected_articles';

    let savedIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    const checkboxes = document.querySelectorAll('input[name="ids"]');

    checkboxes.forEach(cb => {
        if (savedIds.includes(cb.value)) cb.checked = true;

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
        <div class="col-md-2 bg-warning bg-opacity-10 rounded border border-warning">
            <label class="form-label fw-bold text-dark">N° Colli</label>
            <input type="number" name="n_colli" class="form-control fw-bold" value="{{ row.n_colli or 1 }}">
            <small class="text-muted" style="font-size:10px">Se > 1, crea N righe separate!</small>
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
        
        <div class="col-md-2"><label class="form-label">Serial Number</label><input type="text" name="serial_number" class="form-control" value="{{ row.serial_number or '' }}"></div>
        <div class="col-md-2"><label class="form-label">Lotto</label><input type="text" name="lotto" class="form-control" value="{{ row.lotto or '' }}"></div>
        <div class="col-md-2"><label class="form-label">Ns. Rif</label><input type="text" name="ns_rif" class="form-control" value="{{ row.ns_rif or '' }}"></div>
        <div class="col-md-2"><label class="form-label">Mezzi Uscita</label><input type="text" name="mezzi_in_uscita" class="form-control" value="{{ row.mezzi_in_uscita or '' }}"></div>
        
        <div class="col-12"><label class="form-label">Note</label><textarea name="note" class="form-control" rows="3">{{ row.note or '' }}</textarea></div>

        {% if not row.id_articolo %}
        <div class="col-12 mt-3">
            <div class="card bg-white border border-primary p-3 shadow-sm">
                 <label class="form-label fw-bold text-primary fs-5"><i class="bi bi-cloud-upload"></i> Carica Documenti e Foto</label>
                 
                 <input type="file" name="new_files" class="form-control form-control-lg" multiple>
                 
                 <div class="alert alert-info mt-2 mb-0 py-2 small">
                    <i class="bi bi-info-circle-fill"></i> 
                    Puoi selezionare <strong>più file contemporaneamente</strong> (es. il PDF del documento e la FOTO del pacco).<br>
                    Tieni premuto il tasto <b>CTRL</b> (o CMD su Mac) mentre clicchi sui file nella finestra di selezione.
                 </div>
            </div>
        </div>
        {% endif %}
    </div>

    <div class="mt-4 text-end">
        <button type="submit" class="btn btn-primary px-5 btn-lg"><i class="bi bi-save"></i> {% if row.id_articolo %}Salva Modifiche{% else %}Crea Articolo{% endif %}</button>
    </div>
</form>

{% if row and row.id_articolo %}
<div class="card p-4 shadow-sm mb-5 border-top border-4 border-primary">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h5 class="m-0"><i class="bi bi-paperclip"></i> Allegati Salvati</h5>
        
        <form action="{{ url_for('upload_file', id_articolo=row.id_articolo) }}" method="post" enctype="multipart/form-data" class="d-flex gap-2 align-items-center">
            <input type="file" name="file" class="form-control" multiple required>
            <button type="submit" class="btn btn-success fw-bold"><i class="bi bi-cloud-upload"></i> Aggiungi File</button>
        </form>
    </div>
    <div class="small text-muted mb-3">Puoi caricare foto e PDF aggiuntivi selezionandoli insieme (tieni premuto CTRL).</div>
    <hr>
    
    <div class="row g-3">
        {% for att in row.attachments %}
        <div class="col-md-2 col-6">
            <div class="card h-100 text-center p-2 border bg-light position-relative shadow-sm">
                <div class="mb-2 text-primary" style="font-size:2.5em;">
                    {% if att.kind == 'photo' %}
                    <i class="bi bi-file-earmark-image"></i>
                    {% else %}
                    <i class="bi bi-file-earmark-pdf text-danger"></i>
                    {% endif %}
                </div>
                <div class="text-truncate small fw-bold mb-2 text-dark" title="{{ att.filename }}">
                    {{ att.filename.split('_', 2)[-1] }} 
                </div>
                
                <div class="btn-group btn-group-sm w-100">
                    <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank" class="btn btn-outline-primary">Apri</a>
                    <a href="{{ url_for('delete_attachment', id_attachment=att.id) }}" class="btn btn-outline-danger" onclick="return confirm('Sicuro di eliminare questo file?')">Elimina</a>
                </div>
            </div>
        </div>
        {% else %}
        <div class="col-12 text-center text-muted py-4 border border-dashed rounded">
            <i class="bi bi-inbox fs-3 d-block mb-2"></i>
            Nessun allegato presente per questo articolo.
        </div>
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
<div class="card p-4" style="max-width: 720px; margin: auto;">
    <h3 class="mb-3"><i class="bi bi-tags"></i> Stampa Etichette Massiva</h3>

    <form action="{{ url_for('labels_pdf') }}" method="post" target="_blank">
        <div class="mb-3">
            <label class="form-label fw-bold">Seleziona Cliente:</label>
            <select class="form-select" name="filtro_cliente" required>
                <option value="" disabled selected>-- Seleziona --</option>
                {% for c in clienti %}
                  <option value="{{ c }}">{{ c }}</option>
                {% endfor %}
            </select>
            <small class="text-muted">Verranno generate le etichette per tutti gli articoli in magazzino di questo cliente.</small>
        </div>

        <button type="submit" class="btn btn-primary w-100 py-2">
            <i class="bi bi-printer"></i> Genera PDF Etichette
        </button>

        <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary w-100 mt-2">Annulla</a>
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

# --- TEMPLATE PAGINA PICKING / LAVORAZIONI (Senza Emoji, usa Icone Bootstrap) ---

LAVORAZIONI_HTML = """ 
{% extends "base.html" %}
{% block content %}
<div class="container-fluid mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="bi bi-gear"></i> Gestione Picking / Lavorazioni</h2>
        
        <form action="{{ url_for('stampa_picking_pdf') }}" method="POST" target="_blank">
            <button type="submit" class="btn btn-warning shadow-sm">
                <i class="bi bi-printer"></i> Stampa Report PDF
            </button>
        </form>
    </div>
    
    <div class="card p-3 mb-4 bg-light border shadow-sm">
        <h5 class="mb-3">Inserisci Nuovo Picking</h5>
        <form method="POST" class="row g-2">
            <input type="hidden" name="add_lavorazione" value="1">

            <div class="col-md-2">
                <label class="small">Data</label>
                <input type="date" name="data" class="form-control" required value="{{ today }}">
            </div>
            <div class="col-md-2">
                <label class="small">Cliente</label>
                <input type="text" name="cliente" class="form-control">
            </div>
            <div class="col-md-3">
                <label class="small">Descrizione</label>
                <input type="text" name="descrizione" class="form-control">
            </div>
            <div class="col-md-2">
                <label class="small">Richiesta Di</label>
                <input type="text" name="richiesta_di" class="form-control">
            </div>
            <div class="col-md-3">
                <label class="small">Seriali</label>
                <input type="text" name="seriali" class="form-control">
            </div>
            
            <div class="col-md-1">
                <label class="small">Colli</label>
                <input type="number" name="colli" class="form-control">
            </div>
            <div class="col-md-1">
                <label class="small">Pallet IN</label>
                <input type="number" name="pallet_forniti" class="form-control">
            </div>
            <div class="col-md-1">
                <label class="small">Pallet OUT</label>
                <input type="number" name="pallet_uscita" class="form-control">
            </div>
            <div class="col-md-1">
                <label class="small">Ore Blue</label>
                <input type="number" step="0.5" name="ore_blue_collar" class="form-control">
            </div>
            <div class="col-md-1">
                <label class="small">Ore White</label>
                <input type="number" step="0.5" name="ore_white_collar" class="form-control">
            </div>
            
            <div class="col-md-12 text-end mt-2">
                <button type="submit" class="btn btn-success">
                    <i class="bi bi-plus-lg"></i> Aggiungi
                </button>
            </div>
        </form>
    </div>

    <div class="card shadow-sm">
        <div class="table-responsive">
            <table class="table table-bordered table-hover mb-0 align-middle">
                <!-- ✅ intestazioni con testo nero -->
                <thead class="table-light" style="color:#000;">
                    <tr>
                        <th>Data</th><th>Cliente</th><th>Descrizione</th>
                        <th>Richiesta</th><th>Seriali</th><th>Colli</th>
                        <th>P. IN</th><th>P. OUT</th>
                        <th>Blue</th><th>White</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    {% for l in lavorazioni %}
                    <tr>
                        <td>{{ l.data or '' }}</td>
                        <td>{{ l.cliente or '' }}</td>
                        <td>{{ l.descrizione or '' }}</td>
                        <td>{{ l.richiesta_di or '' }}</td>
                        <td>{{ l.seriali or '' }}</td>
                        <td>{{ l.colli or '' }}</td>
                        <td>{{ l.pallet_forniti or '' }}</td>
                        <td>{{ l.pallet_uscita or '' }}</td>
                        <td>{{ l.ore_blue_collar or '' }}</td>
                        <td>{{ l.ore_white_collar or '' }}</td>
                        <td>
                            <a href="{{ url_for('elimina_record', table='lavorazioni', id=l.id) }}"
                               class="btn btn-sm btn-danger"
                               onclick="return confirm('Sei sicuro di voler eliminare?')">
                               <i class="bi bi-trash"></i>
                            </a>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="11" class="text-center text-muted">Nessuna attività registrata.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
"""
CALCOLA_COSTI_HTML = """
{% extends 'base.html' %}
{% block content %}

<div class="container-fluid mt-4">
  <h2><i class="bi bi-calculator"></i> Report Costi Magazzino (M² per cliente)</h2>

  <div class="card p-3 mb-3 bg-light border shadow-sm">
    <form method="post" class="row g-2 align-items-end">
      <div class="col-md-2">
        <label class="form-label fw-bold">Data da:</label>
        <input type="date" name="data_da" class="form-control" value="{{ data_da }}" required>
      </div>

      <div class="col-md-2">
        <label class="form-label fw-bold">Data a:</label>
        <input type="date" name="data_a" class="form-control" value="{{ data_a }}" required>
      </div>

      <div class="col-md-4">
        <label class="form-label fw-bold">Cliente (contiene):</label>
        <input type="text" name="cliente" class="form-control" value="{{ cliente_filtro or '' }}" placeholder="es. FINCANTIERI">
      </div>

      <div class="col-md-3">
        <label class="form-label fw-bold d-block">Raggruppa:</label>
        <div class="form-check form-check-inline">
          <input class="form-check-input" type="radio" name="raggruppamento" id="rg_mese" value="mese"
                 {% if raggruppamento != 'giorno' %}checked{% endif %}>
          <label class="form-check-label" for="rg_mese">Per mese</label>
        </div>

        <div class="form-check form-check-inline">
          <input class="form-check-input" type="radio" name="raggruppamento" id="rg_giorno" value="giorno"
                 {% if raggruppamento == 'giorno' %}checked{% endif %}>
          <label class="form-check-label" for="rg_giorno">Per giorno</label>
        </div>
      </div>

      <div class="col-md-1 d-grid">
        <button type="submit" class="btn btn-secondary">Calcola</button>
      </div>
    </form>
  </div>

  {% if risultati %}
    <div class="card shadow-sm">
      <div class="table-responsive">
        <table class="table table-striped table-hover mb-0 align-middle">
          <thead style="background:#f0f0f0;">
            <tr>
              <th class="text-center">Periodo</th>
              <th>Cliente</th>
              <th class="text-end">M² Tot</th>
              <th class="text-end">M² Medio</th>
              <th class="text-center">Giorni</th>
            </tr>
          </thead>
          <tbody>
            {% for r in risultati %}
            <tr>
              <td class="text-center">{{ r.periodo }}</td>
              <td>{{ r.cliente }}</td>
              <td class="text-end">{{ r.m2_tot }}</td>
              <td class="text-end">{{ r.m2_medio }}</td>
              <td class="text-center">{{ r.giorni }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  {% else %}
    {% if calcolato %}
      <div class="alert alert-warning">Nessun dato trovato per i criteri selezionati.</div>
    {% endif %}
  {% endif %}

  <a href="{{ url_for('home') }}" class="btn btn-outline-secondary mt-3">Torna alla Home</a>
</div>

{% endblock %}
"""


# --- TEMPLATE PAGINA TRASPORTI (Senza Emoji, usa Icone Bootstrap) ---
TRASPORTI_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="container-fluid mt-4">

    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2 class="m-0"><i class="bi bi-truck"></i> Gestione Trasporti</h2>

        <div class="d-flex gap-2">
            <!-- ✅ STAMPA REPORT -->
            <form method="POST" class="m-0">
                <input type="hidden" name="stampa_report" value="1">
                <button type="submit" class="btn btn-warning shadow-sm">
                    <i class="bi bi-printer"></i> Stampa
                </button>
            </form>

            <!-- ✅ ESCI (torna al menu principale) -->
            <a href="{{ url_for('home') }}" class="btn btn-secondary shadow-sm">
                <i class="bi bi-box-arrow-left"></i> Esci
            </a>
        </div>
    </div>
    
    <div class="card p-3 mb-4 bg-light border shadow-sm">
        <h5 class="mb-3">Inserisci Nuovo Trasporto</h5>
        <form method="POST" class="row g-2">
            <input type="hidden" name="add_trasporto" value="1">

            <div class="col-md-2"><label class="small">Data</label><input type="date" name="data" class="form-control" required value="{{ today }}"></div>
            <div class="col-md-2"><label class="small">Tipo Mezzo</label><input type="text" name="tipo_mezzo" class="form-control" placeholder="es. Bilico"></div>
            <div class="col-md-2"><label class="small">Cliente</label><input type="text" name="cliente" class="form-control"></div>
            <div class="col-md-2"><label class="small">Trasportatore</label><input type="text" name="trasportatore" class="form-control"></div>
            <div class="col-md-1"><label class="small">N. DDT</label><input type="text" name="ddt_uscita" class="form-control"></div>
            <div class="col-md-1"><label class="small">Magazzino</label><input type="text" name="magazzino" class="form-control"></div>
            <div class="col-md-1"><label class="small">Consolidato</label><input type="text" name="consolidato" class="form-control"></div>
            <div class="col-md-1"><label class="small">Costo €</label><input type="text" name="costo" class="form-control" placeholder="0,00"></div>

            <div class="col-md-12 text-end mt-2 d-flex justify-content-end gap-2">
                <!-- ✅ SALVA (stesso submit dell’aggiunta) -->
                <button type="submit" class="btn btn-success">
                    <i class="bi bi-save"></i> Salva
                </button>

                <!-- ✅ ESCI -->
                <a href="{{ url_for('home') }}" class="btn btn-outline-secondary">
                    <i class="bi bi-x-circle"></i> Esci
                </a>
            </div>
        </form>
    </div>

    <div class="card shadow-sm">
        <div class="table-responsive">
            <table class="table table-striped table-hover mb-0 align-middle">
                <!-- ✅ intestazioni con testo nero -->
                <thead class="table-light" style="color:#000;">
                    <tr>
                        <th>Data</th><th>Mezzo</th><th>Cliente</th>
                        <th>Trasportatore</th><th>DDT</th><th>Mag.</th>
                        <th>Consolidato</th><th>Costo</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    {% for t in trasporti %}
                    <tr>
                        <td>{{ t.data or '' }}</td>
                        <td>{{ t.tipo_mezzo or '' }}</td>
                        <td>{{ t.cliente or '' }}</td>
                        <td>{{ t.trasportatore or '' }}</td>
                        <td>{{ t.ddt_uscita or '' }}</td>
                        <td>{{ t.magazzino or '' }}</td>
                        <td>{{ t.consolidato or '' }}</td>
                        <td>€ {{ '%.2f'|format(t.costo) if t.costo is not none else '' }}</td>
                        <td>
                            <a href="{{ url_for('elimina_record', table='trasporti', id=t.id) }}" 
                               class="btn btn-sm btn-danger" 
                               onclick="return confirm('Sei sicuro di voler eliminare questo trasporto?')">
                               <i class="bi bi-trash"></i>
                            </a>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="9" class="text-center text-muted">Nessun trasporto inserito.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
"""


INVIA_EMAIL_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-9">
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
                    <label class="form-label fw-bold">Destinatario</label>
                    <input type="email" name="destinatario" class="form-control" required placeholder="cliente@esempio.com">
                </div>
                
                <div class="mb-3">
                    <label class="form-label fw-bold">Oggetto</label>
                    <input type="text" name="oggetto" class="form-control" value="Documentazione Merce - Camar S.r.l." required>
                </div>
                
                <div class="mb-3">
                    <label class="form-label fw-bold">Messaggio</label>
                    <textarea name="messaggio" rows="6" class="form-control" style="font-family: Arial, sans-serif;">Buongiorno,

In allegato inviamo la documentazione relativa alla merce in oggetto.

Cordiali saluti,</textarea>
                    <div class="form-text text-muted">
                        <i class="bi bi-info-circle"></i> Il logo e la firma legale verranno aggiunti automaticamente sotto questo testo.
                    </div>
                </div>

                <div class="card bg-light mb-3 border-0">
                    <div class="card-body opacity-75">
                        <small class="text-uppercase fw-bold text-muted mb-2 d-block">Anteprima piè di pagina automatico:</small>
                        <div class="d-flex align-items-center gap-3 mb-2">
                            <img src="{{ url_for('static', filename='logo camar.jpg') }}" alt="Logo" style="height:50px;">
                            <div>
                                <strong>Camar S.r.l.</strong><br>
                                <span class="text-muted" style="font-size: 0.8rem;">Via Balleydier 52r – 16149 GENOVA</span>
                            </div>
                        </div>
                        <div style="font-size: 0.7rem; color: #666; max-height: 60px; overflow: hidden; text-overflow: ellipsis;">
                            (Seguono disclaimer legale, contatti uffici, telefoni, ecc...)
                        </div>
                    </div>
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
        'import_pdf.html': IMPORT_PDF_HTML,
        'mappe_excel.html': MAPPE_EXCEL_HTML,
        
        # NUOVI MODULI (Trasporti e Picking)
        'trasporti.html': TRASPORTI_HTML,
        'lavorazioni.html': LAVORAZIONI_HTML,

        # ⚠️ MANCAVANO QUESTI DUE PER LE STAMPE:
        'report_trasporti_print.html': REPORT_TRASPORTI_HTML,
        'report_inventario_print.html': REPORT_INVENTARIO_HTML,

        # ALTRI MODULI (Se hai le variabili definite sopra, lasciali)
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


@app.route('/')
@app.route('/home')
@login_required
def home():
    try:
        # Recupera dati per la dashboard (con gestione errori se il DB è vuoto)
        tot_articoli = 0
        tot_m2 = 0.0
        
        try:
            db = SessionLocal()
            tot_articoli = db.query(Articolo).count()
            # Calcolo somma M2 sicuro
            result = db.query(func.sum(Articolo.m2)).scalar()
            if result:
                tot_m2 = float(result)
            db.close()
        except Exception as e_db:
            print(f"Errore Dashboard DB: {e_db}")
            # Non bloccare l'app, mostra 0
            tot_articoli = 0
            tot_m2 = 0

        return render_template('home.html', 
                               tot_articoli=tot_articoli, 
                               tot_m2=round(tot_m2, 2),
                               today=date.today())
                               
    except Exception as e:
        # Se c'è un errore grave nel template o altro
        print(f"CRITICAL ERROR HOME: {e}")
        import traceback
        traceback.print_exc()
        # Fallback estremo: pagina bianca con errore leggibile
        return f"<h1>Errore Caricamento Home</h1><p>{e}</p><a href='/logout'>Logout</a>"

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
    db = SessionLocal()
    try:
        # STAMPA REPORT
        if request.method == 'POST' and request.form.get('stampa_report'):
            dati = db.query(Trasporto).order_by(Trasporto.data.desc().nullslast(), Trasporto.id.desc()).all()
            return render_template('report_trasporti_print.html', trasporti=dati, today=date.today())

        # AGGIUNGI
        if request.method == 'POST' and request.form.get('add_trasporto'):
            try:
                data_str = (request.form.get('data') or '').strip()
                data_val = datetime.strptime(data_str, '%Y-%m-%d').date() if data_str else None

                costo_str = (request.form.get('costo') or '').strip()
                costo_val = float(costo_str.replace(',', '.')) if costo_str != '' else None

                nuovo = Trasporto(
                    data=data_val,
                    tipo_mezzo=(request.form.get('tipo_mezzo') or '').strip() or None,
                    cliente=(request.form.get('cliente') or '').strip() or None,
                    trasportatore=(request.form.get('trasportatore') or '').strip() or None,
                    ddt_uscita=(request.form.get('ddt_uscita') or '').strip() or None,
                    magazzino=(request.form.get('magazzino') or '').strip() or None,
                    consolidato=(request.form.get('consolidato') or '').strip() or None,
                    costo=costo_val
                )

                db.add(nuovo)
                db.commit()
                flash("Trasporto salvato!", "success")
            except Exception as e:
                db.rollback()
                flash(f"Errore salvataggio trasporto: {e}", "danger")

            return redirect(url_for('trasporti'))

        # LISTA
        dati = db.query(Trasporto).order_by(Trasporto.data.desc().nullslast(), Trasporto.id.desc()).all()
        return render_template('trasporti.html', trasporti=dati, today=date.today())

    finally:
        db.close()

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
@app.route('/lavorazioni', methods=['GET', 'POST'])
@login_required
def lavorazioni():
    db = SessionLocal()

    # GESTIONE INSERIMENTO NUOVO DATO
    if request.method == 'POST':
        # --- QUI C'È IL CONTROLLO ADMIN ---
        if session.get('role') != 'admin':
            flash("ACCESSO NEGATO: Solo l'Amministratore può aggiungere dati.", "danger")
            return redirect(url_for('lavorazioni'))
        # ----------------------------------

        try:
            nuovo = Lavorazione(
                data=datetime.strptime(request.form.get('data'), '%Y-%m-%d').date(),
                cliente=request.form.get('cliente'),
                descrizione=request.form.get('descrizione'),
                richiesta_di=request.form.get('richiesta_di'),
                seriali=request.form.get('seriali'),
                colli=int(request.form.get('colli') or 0),
                pallet_forniti=int(request.form.get('pallet_forniti') or 0),
                pallet_uscita=int(request.form.get('pallet_uscita') or 0),
                ore_blue_collar=float(request.form.get('ore_blue_collar') or 0),
                ore_white_collar=float(request.form.get('ore_white_collar') or 0)
            )
            db.add(nuovo)
            db.commit()
            flash("Picking aggiunto con successo!", "success")
        except Exception as e:
            db.rollback()
            flash(f"Errore inserimento: {e}", "danger")
        return redirect(url_for('lavorazioni'))

    # VISUALIZZAZIONE (Eseguita da TUTTI)
    query = db.query(Lavorazione)
    if request.args.get('cliente'):
        query = query.filter(Lavorazione.cliente.ilike(f"%{request.args.get('cliente')}%"))

    dati = query.order_by(Lavorazione.data.desc()).all()
    db.close()
    
    return render_template('lavorazioni.html', lavorazioni=dati, today=date.today())

# --- REPORT INVENTARIO PER CLIENTE/DATA ---

@app.route('/report_inventario', methods=['POST'])
@login_required
def report_inventario():
    data_rif_str = request.form.get('data_inventario')
    cliente_rif = request.form.get('cliente_inventario', '').strip()
    
    if not data_rif_str: return "Data mancante", 400

    db = SessionLocal()
    try:
        query = db.query(Articolo)
        if cliente_rif:
            query = query.filter(Articolo.cliente.ilike(f"%{cliente_rif}%"))
        
        all_arts = query.all()
        d_limit = datetime.strptime(data_rif_str, "%Y-%m-%d").date()
        
        in_stock = []
        for art in all_arts:
            def parse_d(v):
                if isinstance(v, date): return v
                try: return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
                except: return None
            
            d_ing = parse_d(art.data_ingresso)
            if not d_ing or d_ing > d_limit: continue
            
            is_present = True
            if art.data_uscita:
                d_usc = parse_d(art.data_uscita)
                if d_usc and d_usc <= d_limit:
                    is_present = False
            
            if is_present:
                in_stock.append(art)

        inventario = {}
        for art in in_stock:
            cli = art.cliente or "NESSUN CLIENTE"
            if cli not in inventario: inventario[cli] = []
            inventario[cli].append(art)
            
        return render_template('report_inventario_print.html', inventario=inventario, data_rif=data_rif_str)
    finally:
        db.close()
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

    # POST logic
    profile_name = request.form.get('profile')
    if not profile_name or profile_name not in mappe:
        flash("Seleziona un profilo valido.", "warning")
        return redirect(request.url)

    if 'excel_file' not in request.files: return redirect(request.url)
    file = request.files['excel_file']
    if not file or file.filename == '': return redirect(request.url)

    db = SessionLocal()
    try:
        config = mappe[profile_name]
        header_row_idx = int(config.get('header_row', 1)) - 1  
        column_map = config.get('column_map', {}) or {}

        import pandas as pd
        xls = pd.ExcelFile(file, engine="openpyxl")
        df = xls.parse(0, header=header_row_idx)
        df_cols_upper = {str(c).strip().upper(): c for c in df.columns}

        # HELPER DATA ROBUSTO
        def to_date_db(val):
            if pd.isna(val) or val == '': return None
            # Se è già datetime/timestamp di pandas
            if isinstance(val, (datetime, pd.Timestamp)):
                return val.strftime("%Y-%m-%d")
            # Se è stringa
            s = str(val).strip()
            # Tenta vari formati
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
                except: pass
            return None

        imported_count = 0
        for _, row in df.iterrows():
            if row.isnull().all(): continue

            new_art = Articolo()
            has_data = False

            for excel_header, db_field in column_map.items():
                key = str(excel_header).strip().upper()
                col_name = df_cols_upper.get(key)
                if col_name is None: continue

                val = row[col_name]
                if pd.isna(val) or str(val).strip() == "": continue

                # Conversioni
                if db_field in ['larghezza', 'lunghezza', 'altezza', 'peso', 'm2', 'm3']:
                    try: val = float(str(val).replace(',', '.'))
                    except: val = 0.0
                elif db_field in ['n_colli', 'pezzo']:
                    try: val = int(float(str(val).replace(',', '.')))
                    except: val = 1
                elif db_field in ['data_ingresso', 'data_uscita']:
                    val = to_date_db(val)
                else:
                    val = str(val).strip()

                if val is not None:
                    setattr(new_art, db_field, val)
                    has_data = True

            if has_data:
                # Calcoli automatici se mancano
                try:
                    if not new_art.m2 or new_art.m2 == 0:
                        l = new_art.lunghezza or 0
                        w = new_art.larghezza or 0
                        h = new_art.altezza or 0
                        c = new_art.n_colli or 1
                        # Logica m2/m3
                        if l>0 and w>0:
                            # Se altezza è trascurabile o non usata per m2
                            new_art.m2 = round(l * w * c, 3)
                            new_art.m3 = round(l * w * (h if h>0 else 0) * c, 3)
                except: pass

                db.add(new_art)
                imported_count += 1

        db.commit()
        flash(f"{imported_count} articoli importati con successo.", "success")
        return redirect(url_for('giacenze'))

    except Exception as e:
        db.rollback()
        flash(f"Errore import: {e}", "danger")
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
    # Import necessari per gestire correttamente la codifica e gli allegati
    from email.header import Header
    from email.mime.image import MIMEImage
    import mimetypes

    # GET: Mostra il form
    if request.method == 'GET':
        selected_ids = request.args.getlist('ids')
        ids_str = ",".join(selected_ids)
        return render_template('invia_email.html', selected_ids=ids_str)

    # POST: Elabora l'invio
    selected_ids = request.form.get('selected_ids', '')
    destinatario = request.form.get('destinatario')
    oggetto = request.form.get('oggetto')
    messaggio_utente = request.form.get('messaggio') or "" # Testo inserito dall'utente
    genera_ddt = 'genera_ddt' in request.form
    allega_file = 'allega_file' in request.form
    allegati_extra = request.files.getlist('allegati_extra')

    ids_list = [int(i) for i in selected_ids.split(',') if i.isdigit()]

    # Configurazione SMTP
    SMTP_SERVER = os.environ.get("MAIL_SERVER") or os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("MAIL_PORT") or os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("MAIL_USERNAME") or os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("MAIL_PASSWORD") or os.environ.get("SMTP_PASS", "")

    if not SMTP_USER or not SMTP_PASS:
        flash(f"Configurazione email mancante (User: {SMTP_USER}).", "warning")
        return redirect(url_for('giacenze'))

    try:
        # Creazione Messaggio
        msg_root = MIMEMultipart('related')
        msg_root['From'] = SMTP_USER
        msg_root['To'] = destinatario
        # FIX ENCODING: Header con utf-8 risolve l'errore ASCII sull'oggetto
        msg_root['Subject'] = Header(oggetto, 'utf-8')

        msg_alt = MIMEMultipart('alternative')
        msg_root.attach(msg_alt)

        # 1. Corpo Testo Semplice (UTF-8)
        # Nota: Qui mettiamo solo il testo base per i client che non supportano HTML
        msg_alt.attach(MIMEText(messaggio_utente, 'plain', 'utf-8'))

        # 2. Corpo HTML (UTF-8) con LOGO POSIZIONATO DOPO I SALUTI
        # Convertiamo i "a capo" in <br>
        messaggio_html = messaggio_utente.replace('\n', '<br>')
        
        # HTML Strutturato
        html_body = f"""
        <html>
          <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
          </head>
          <body style="font-family: Arial, sans-serif; font-size: 14px; color:#333;">
            
            <div style="margin-bottom: 20px;">
              {messaggio_html}
            </div>

            <div style="margin-bottom: 20px;">
              <img src="cid:logo_camar" alt="Camar S.r.l." style="height:60px; width:auto; display:block;">
            </div>
            
            </body>
        </html>
        """
        msg_alt.attach(MIMEText(html_body, 'html', 'utf-8'))

        # 3. ALLEGARE IL LOGO (cid:logo_camar)
        possible_logos = ["logo camar.jpg", "logo_camar.jpg", "logo.jpg"]
        logo_found = False
        
        for logo_name in possible_logos:
            logo_path = os.path.join(app.root_path, "static", logo_name)
            if os.path.exists(logo_path):
                with open(logo_path, "rb") as f:
                    img_data = f.read()
                
                img = MIMEImage(img_data)
                img.add_header('Content-ID', '<logo_camar>') 
                img.add_header('Content-Disposition', 'inline', filename='logo_camar.jpg')
                msg_root.attach(img)
                logo_found = True
                break
        
        if not logo_found:
            print("⚠️ ATTENZIONE: Logo non trovato nella cartella static!")

        # 4. DDT PDF (Se richiesto)
        if genera_ddt and ids_list:
            db = SessionLocal()
            try:
                rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
                if rows:
                    pdf_bio = io.BytesIO()
                    _genera_pdf_ddt_file(
                        {'n_ddt': 'RIEP', 'data_uscita': date.today().strftime('%d/%m/%Y'), 
                         'destinatario': 'RIEPILOGO', 'dest_indirizzo': '', 'dest_citta': ''}, 
                        [{
                            'id_articolo': r.id_articolo, 'codice_articolo': r.codice_articolo, 
                            'descrizione': r.descrizione, 'pezzo': r.pezzo, 'n_colli': r.n_colli, 
                            'peso': r.peso, 'n_arrivo': r.n_arrivo, 'note': r.note,
                            'commessa': r.commessa, 'ordine': r.ordine, 'buono': r.buono_n, 'protocollo': r.protocollo
                        } for r in rows], 
                        pdf_bio
                    )
                    pdf_bio.seek(0)
                    part = MIMEBase('application', "octet-stream")
                    part.set_payload(pdf_bio.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', 'attachment; filename="Riepilogo_Merce.pdf"')
                    msg_root.attach(part)
            finally:
                db.close()

        # 5. ALLEGATI ESISTENTI
        if allega_file and ids_list:
            db = SessionLocal()
            try:
                rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
                for r in rows:
                    for att in r.attachments:
                        fname = att.filename
                        path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / fname
                        if not path.exists():
                             from urllib.parse import unquote
                             path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / unquote(fname)
                        
                        if path.exists():
                            with open(path, "rb") as f:
                                part = MIMEBase('application', "octet-stream")
                                part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                            msg_root.attach(part)
            finally:
                db.close()

        # 6. ALLEGATI EXTRA
        for file in allegati_extra:
            if file and file.filename:
                part = MIMEBase('application', "octet-stream")
                part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{secure_filename(file.filename)}"')
                msg_root.attach(part)

        # INVIO
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        # Usa send_message per gestire meglio la codifica
        server.send_message(msg_root)
        server.quit()

        flash(f"Email inviata correttamente a {destinatario}", "success")

    except Exception as e:
        print(f"DEBUG EMAIL EXCEPTION: {e}")
        # Log dettagliato per capire quale carattere dà problemi
        import traceback
        traceback.print_exc()
        flash(f"Errore invio: {e}", "danger")

    return redirect(url_for('giacenze'))


# --- FUNZIONE UPLOAD FILE MULTIPLI (CORRETTA PER EDIT_RECORD) ---
@app.route('/upload/<int:id_articolo>', methods=['POST'])
@login_required
def upload_file(id_articolo):
    # 1. Controllo Permessi
    if session.get('role') != 'admin':
        flash("Solo Admin può caricare file", "danger")
        return redirect(url_for('edit_record', id_articolo=id_articolo))

    # 2. Recupera LISTA di file
    files = request.files.getlist('file')
    
    if not files or all(f.filename == '' for f in files):
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('edit_record', id_articolo=id_articolo))

    db = SessionLocal()
    count = 0
    try:
        from werkzeug.utils import secure_filename
        
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                
                # Crea nome univoco: ID_UUID_Nome
                unique_name = f"{id_articolo}_{uuid.uuid4().hex[:6]}_{filename}"
                
                ext = filename.rsplit('.', 1)[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    kind = 'photo'
                    save_path = PHOTOS_DIR / unique_name
                else:
                    kind = 'doc'
                    save_path = DOCS_DIR / unique_name
                    
                file.save(str(save_path))

                # Salva nel DB
                att = Attachment(
                    articolo_id=id_articolo,
                    filename=unique_name,
                    kind=kind
                )
                db.add(att)
                count += 1
        
        db.commit()
        if count > 0:
            flash(f"Caricati {count} file correttamente!", "success")
        else:
            flash("Nessun file valido caricato.", "warning")
        
    except Exception as e:
        db.rollback()
        print(f"ERRORE UPLOAD: {e}") 
        flash(f"Errore caricamento: {e}", "danger")
    finally:
        db.close()

    # --- MODIFICA QUI: RITORNA A EDIT_RECORD ---
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
            # --- RECUPERO DATI FORM ---
            # Determina quante righe creare in base al numero di colli
            n_colli_input = to_int_eu(request.form.get('n_colli'))
            if n_colli_input < 1: n_colli_input = 1
            
            created_articles = []

            # --- CICLO DI CREAZIONE (Crea N righe identiche) ---
            for _ in range(n_colli_input):
                art = Articolo()
                
                # Popola i campi testuali
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
                art.lotto = request.form.get('lotto')

                # Date
                art.data_ingresso = parse_date_ui(request.form.get('data_ingresso'))
                art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
                art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
                art.n_ddt_uscita = request.form.get('n_ddt_uscita')
                
                # Numeri
                art.pezzo = request.form.get('pezzo')
                art.n_colli = 1  # FORZA 1 COLLO PER OGNI RIGA CREATA
                art.peso = to_float_eu(request.form.get('peso'))
                art.lunghezza = to_float_eu(request.form.get('lunghezza'))
                art.larghezza = to_float_eu(request.form.get('larghezza'))
                art.altezza = to_float_eu(request.form.get('altezza'))
                
                # Calcolo M2/M3 (su 1 collo)
                art.m2, art.m3 = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, 1)

                db.add(art)
                created_articles.append(art)

            # Salva tutto per ottenere gli ID
            db.commit() 
            
            # --- GESTIONE ALLEGATI (Duplicazione su tutte le righe) ---
            # getlist permette di prendere PIÙ file selezionati
            files = request.files.getlist('new_files') 
            valid_files = [f for f in files if f and f.filename]
            
            if valid_files:
                import shutil
                from werkzeug.utils import secure_filename
                
                for file in valid_files:
                    fname = secure_filename(file.filename)
                    ext = fname.rsplit('.', 1)[-1].lower()
                    kind = 'photo' if ext in ['jpg', 'jpeg', 'png', 'webp'] else 'doc'
                    folder = PHOTOS_DIR if kind == 'photo' else DOCS_DIR
                    
                    # 1. Salva il file fisico per il PRIMO articolo
                    first_art = created_articles[0]
                    first_final_name = f"{first_art.id_articolo}_{fname}"
                    src_path = folder / first_final_name
                    
                    # Importante: seek(0) se il file è stato letto parzialmente
                    file.seek(0) 
                    file.save(str(src_path))
                    
                    # Collega al primo articolo nel DB
                    db.add(Attachment(articolo_id=first_art.id_articolo, filename=first_final_name, kind=kind))
                    
                    # 2. Copia il file fisico e il record DB per gli ALTRI articoli
                    for other_art in created_articles[1:]:
                        other_final_name = f"{other_art.id_articolo}_{fname}"
                        dst_path = folder / other_final_name
                        
                        try:
                            # Copia fisica del file
                            shutil.copy2(src_path, dst_path)
                            # Nuovo record nel DB
                            db.add(Attachment(articolo_id=other_art.id_articolo, filename=other_final_name, kind=kind))
                        except Exception as e:
                            print(f"Errore copia file per ID {other_art.id_articolo}: {e}")

                db.commit()

            flash(f"Operazione completata: Creati {len(created_articles)} articoli distinti con allegati.", "success")
            
            # Se ne abbiamo creato uno solo, vai alla modifica, altrimenti torna alla lista
            if len(created_articles) == 1:
                # Reindirizza alla funzione edit_articolo corretta
                return redirect(url_for('edit_articolo', id=created_articles[0].id_articolo))
            else:
                return redirect(url_for('giacenze'))
            
        except Exception as e:
            db.rollback()
            flash(f"Errore creazione: {e}", "danger")
            return redirect(url_for('giacenze'))
        finally:
            db.close()

    # GET: Mostra form vuoto
    dummy_art = Articolo() 
    dummy_art.data_ingresso = date.today().strftime("%d/%m/%Y")
    return render_template('edit.html', row=dummy_art)
    
# 1. ELIMINA ARTICOLO (Per la pagina Magazzino)
@app.route('/delete_articolo/<int:id>')
@login_required
def delete_articolo(id):
    if session.get('role') != 'admin':
        flash("Accesso Negato: Solo Admin può eliminare.", "danger")
        return redirect(url_for('giacenze'))
        
    db = SessionLocal()
    try:
        record = db.query(Articolo).get(id)
        if record:
            db.delete(record)
            db.commit()
            flash("Articolo eliminato.", "success")
        else:
            flash("Articolo non trovato.", "warning")
    except Exception as e:
        db.rollback()
        flash(f"Errore eliminazione: {e}", "danger")
    finally:
        db.close()
    return redirect(url_for('giacenze'))

# --- DUPLICAZIONE SINGOLA (Quella che mancava e dava errore) ---
@app.route('/duplica_articolo/<int:id_articolo>')
@login_required
def duplica_articolo(id_articolo):
    db = SessionLocal()
    originale = db.query(Articolo).filter_by(id_articolo=id_articolo).first()
    
    if not originale:
        flash("Articolo non trovato", "danger")
        return redirect(url_for('giacenze'))

    # Crea copia esatta (tranne ID)
    nuovo = Articolo(
        codice_articolo=originale.codice_articolo,
        descrizione=originale.descrizione,
        cliente=originale.cliente,
        fornitore=originale.fornitore,
        magazzino=originale.magazzino,
        posizione=originale.posizione,
        stato=originale.stato,
        n_colli=originale.n_colli,
        peso=originale.peso,
        larghezza=originale.larghezza,
        lunghezza=originale.lunghezza,
        altezza=originale.altezza,
        m2=originale.m2,
        m3=originale.m3,
        # Copiamo anche i campi nuovi se servono
        lotto=originale.lotto,
        note=f"Copia di ID {originale.id_articolo}",
        data_ingresso=date.today() # La data diventa oggi
    )
    
    try:
        db.add(nuovo)
        db.commit()
        flash("Articolo duplicato con successo!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Errore duplicazione: {e}", "danger")
    finally:
        db.close()
    
    return redirect(url_for('giacenze'))

# ==============================================================================
#  1. MODIFICA ARTICOLO (Solo per TABELLA GIACENZE)
# ==============================================================================
# --- MODIFICA ARTICOLO SINGOLO (UNICA FUNZIONE CORRETTA) ---
@app.route('/edit_articolo/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_articolo(id):
    db = SessionLocal()
    try:
        art = db.query(Articolo).get(id)
        if not art:
            flash("Articolo non trovato", "danger")
            return redirect(url_for('giacenze'))

        if request.method == 'POST':
            # 1. Recupera Colli (per eventuale split)
            colli_input = to_int_eu(request.form.get('n_colli'))
            if colli_input < 1: colli_input = 1

            # 2. Aggiorna tutti i campi
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
            art.lotto = request.form.get('lotto')
            art.ns_rif = request.form.get('ns_rif')

            # Date
            art.data_ingresso = parse_date_ui(request.form.get('data_ingresso'))
            art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')

            # Numeri
            art.pezzo = request.form.get('pezzo')
            # In modifica, l'articolo corrente resta sempre 1 collo (perché è una riga sola)
            # Se l'utente ha scritto 3, creiamo 2 copie e lasciamo questo a 1
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

            # 3. LOGICA SPLIT (Se colli > 1, crea copie)
            if colli_input > 1:
                import shutil
                # Recupera gli allegati attuali per copiarli sulle nuove righe
                current_attachments = db.query(Attachment).filter_by(articolo_id=art.id_articolo).all()
                
                for _ in range(colli_input - 1):
                    # Clona l'articolo
                    clone = Articolo()
                    for c in Articolo.__table__.columns:
                        if c.name not in ['id_articolo', 'attachments']:
                            setattr(clone, c.name, getattr(art, c.name))
                    
                    db.add(clone)
                    db.flush() # Ottieni ID del clone
                    
                    # Clona anche gli allegati
                    for att in current_attachments:
                        fname = att.filename
                        ext = fname.rsplit('.', 1)[-1].lower()
                        kind = att.kind
                        folder = PHOTOS_DIR if kind == 'photo' else DOCS_DIR
                        
                        src_path = folder / fname
                        if src_path.exists():
                            new_name = f"{clone.id_articolo}_{uuid.uuid4().hex[:6]}_{fname.split('_',1)[-1]}"
                            dst_path = folder / new_name
                            try:
                                shutil.copy2(src_path, dst_path)
                                db.add(Attachment(articolo_id=clone.id_articolo, filename=new_name, kind=kind))
                            except: pass

                flash(f"Articolo aggiornato e create {colli_input - 1} copie aggiuntive.", "success")
            else:
                flash("Articolo aggiornato con successo.", "success")

            db.commit()
            return redirect(url_for('giacenze'))

        # GET: Mostra template modifica
        return render_template('edit.html', row=art)

    except Exception as e:
        db.rollback()
        flash(f"Errore modifica: {e}", "danger")
        return redirect(url_for('giacenze'))
    finally:
        db.close()

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


    # Redirect back to the correct page
    if table == 'trasporti': return redirect(url_for('trasporti'))
    if table == 'lavorazioni': return redirect(url_for('lavorazioni'))
    return redirect(url_for('home'))

# ==============================================================================
#  1. FUNZIONE GIACENZE (Visualizzazione Magazzino)
# ==============================================================================
@app.route('/giacenze', methods=['GET', 'POST'])
@login_required
def giacenze():
    # Import interni per sicurezza e pulizia
    import logging
    from sqlalchemy.orm import selectinload
    from datetime import datetime, date

    db = SessionLocal()
    try:
        # 1. Query Base: Carica articoli e allegati, ordinati per ID decrescente
        qs = db.query(Articolo).options(selectinload(Articolo.attachments)).order_by(Articolo.id_articolo.desc())
        args = request.args

        # 2. Filtro Cliente (Sicurezza per utenti con ruolo 'client')
        if session.get('role') == 'client':
            qs = qs.filter(Articolo.cliente.ilike(f"%{current_user.id}%"))
        elif args.get('cliente'):
            qs = qs.filter(Articolo.cliente.ilike(f"%{args.get('cliente')}%"))

        # 3. Filtro ID univoco
        if args.get('id'):
            try: qs = qs.filter(Articolo.id_articolo == int(args.get('id')))
            except ValueError: pass

        # 4. Filtri Testuali (Itera su tutti i campi di ricerca)
        text_filters = [
            'commessa', 'descrizione', 'posizione', 'buono_n', 'protocollo', 'lotto',
            'fornitore', 'ordine', 'magazzino', 'mezzi_in_uscita', 'stato',
            'n_ddt_ingresso', 'n_ddt_uscita', 'codice_articolo', 'serial_number',
            'n_arrivo'
        ]
        for field in text_filters:
            val = args.get(field)
            if val and val.strip():
                qs = qs.filter(getattr(Articolo, field).ilike(f"%{val.strip()}%"))

        # Esecuzione query DB
        rows_raw = qs.all()
        rows = []

        # 5. Gestione Filtri DATE (Robustezza anti-crash)
        def get_date_arg(k):
            v = args.get(k)
            if not v: return None
            try: return datetime.strptime(v, "%Y-%m-%d").date()
            except: return None

        d_ing_da = get_date_arg('data_ing_da')
        d_ing_a = get_date_arg('data_ing_a')
        d_usc_da = get_date_arg('data_usc_da')
        d_usc_a = get_date_arg('data_usc_a')

        for r in rows_raw:
            keep = True
            
            # --- FILTRO DATA INGRESSO ---
            if d_ing_da or d_ing_a:
                r_dt = None
                # Se è già un oggetto date
                if isinstance(r.data_ingresso, date):
                    r_dt = r.data_ingresso
                # Se è una stringa, controlliamo PRIMA che non sia None o vuota
                elif r.data_ingresso and isinstance(r.data_ingresso, str):
                    try: r_dt = datetime.strptime(r.data_ingresso[:10], "%Y-%m-%d").date()
                    except: 
                        try: r_dt = datetime.strptime(r.data_ingresso[:10], "%d/%m/%Y").date()
                        except: pass
                
                if not r_dt: keep = False
                else:
                    if d_ing_da and r_dt < d_ing_da: keep = False
                    if d_ing_a and r_dt > d_ing_a: keep = False
            
            # --- FILTRO DATA USCITA ---
            if keep and (d_usc_da or d_usc_a):
                r_dt = None
                if isinstance(r.data_uscita, date):
                    r_dt = r.data_uscita
                elif r.data_uscita and isinstance(r.data_uscita, str):
                    try: r_dt = datetime.strptime(r.data_uscita[:10], "%Y-%m-%d").date()
                    except:
                        try: r_dt = datetime.strptime(r.data_uscita[:10], "%d/%m/%Y").date()
                        except: pass
                
                if not r_dt: keep = False
                else:
                    if d_usc_da and r_dt < d_usc_da: keep = False
                    if d_usc_a and r_dt > d_usc_a: keep = False

            if keep:
                rows.append(r)

        # 6. Calcolo Totali Sicuro
        total_colli = 0
        total_m2 = 0.0
        total_peso = 0.0

        for r in rows:
            try: total_colli += int(r.n_colli) if r.n_colli else 0
            except: pass
            
            try: total_m2 += float(r.m2) if r.m2 else 0
            except: pass
            
            try: total_peso += float(r.peso) if r.peso else 0
            except: pass

        return render_template(
            'giacenze.html',
            rows=rows,
            result=rows, # Per compatibilità
            total_colli=total_colli,
            total_m2=f"{total_m2:.2f}",
            total_peso=f"{total_peso:.2f}",
            today=date.today()
        )

    except Exception as e:
        # Log dell'errore per il debug e messaggio utente
        logging.error(f"ERRORE GIACENZE: {e}")
        return f"<h1>Errore caricamento magazzino:</h1><p>{e}</p>"
    finally:
        db.close()
# ==============================================================================
#  3. FUNZIONE ELIMINA (Risolve l'errore 'endpoint elimina_record')
# ==============================================================================
@app.route('/elimina_record/<table>/<int:id>')
@login_required
def elimina_record(table, id):
    # Solo Admin può eliminare
    if session.get('role') != 'admin':
        flash("Accesso Negato: Solo Admin può eliminare.", "danger")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        record = None
        redirect_url = 'home'

        if table == 'articoli':
            record = db.query(Articolo).get(id)
            redirect_url = 'giacenze'
        elif table == 'trasporti':
            record = db.query(Trasporto).get(id)
            redirect_url = 'trasporti'
        elif table == 'lavorazioni':
            record = db.query(Lavorazione).get(id)
            redirect_url = 'lavorazioni'
        
        if record:
            db.delete(record)
            db.commit()
            flash("Elemento eliminato.", "success")
        else:
            flash("Elemento non trovato.", "warning")

        return redirect(url_for(redirect_url))

    except Exception as e:
        db.rollback()
        flash(f"Errore eliminazione: {e}", "danger")
        return redirect(url_for('home'))
    finally:
        db.close()

# --- MODIFICA MULTIPLA COMPLETA CON CALCOLI ---
@app.route('/bulk_edit', methods=['GET', 'POST'])
@login_required
def bulk_edit():
    db = SessionLocal()
    try:
        # Recupera ID (da form POST o query string GET)
        ids = request.form.getlist('ids') or request.args.getlist('ids')

        # Filtra ID validi
        ids = [int(i) for i in ids if str(i).isdigit()]

        if not ids:
            flash("Nessun articolo selezionato.", "warning")
            return redirect(url_for('giacenze'))

        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

        # Configurazione Campi Modificabili
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
            recalc_dims = False

            # 1) Applica Modifiche Campi
            for key in request.form:
                if not key.startswith('chk_'):
                    continue

                field_name = key.replace('chk_', '')
                if not any(f[1] == field_name for f in editable_fields):
                    continue

                val = request.form.get(field_name)

                if field_name in ['n_colli', 'pezzo']:
                    val = to_int_eu(val)
                elif field_name in ['lunghezza', 'larghezza', 'altezza']:
                    val = to_float_eu(val)
                elif 'data' in field_name:
                    val = parse_date_ui(val) if val else None

                updates[field_name] = val

                if field_name in ['lunghezza', 'larghezza', 'altezza', 'n_colli']:
                    recalc_dims = True

            if updates:
                for art in articoli:
                    for k, v in updates.items():
                        if hasattr(art, k):
                            setattr(art, k, v)

                    if recalc_dims:
                        # Ricalcola M2/M3 usando i nuovi valori (o quelli esistenti se non cambiati)
                        L = updates.get('lunghezza', art.lunghezza)
                        W = updates.get('larghezza', art.larghezza)
                        H = updates.get('altezza', art.altezza)
                        C = updates.get('n_colli', art.n_colli)
                        art.m2, art.m3 = calc_m2_m3(L, W, H, C)

            # 2) UPLOAD MASSIVO MULTIPLO (più file)
            # NB: in HTML usa name="bulk_files" multiple
            files = request.files.getlist('bulk_files')
            count_uploaded = 0

            if files:
                from werkzeug.utils import secure_filename

                for file in files:
                    if not file or not file.filename:
                        continue

                    raw_name = secure_filename(file.filename)
                    content = file.read()  # leggo UNA volta

                    if not content:
                        continue

                    ext = os.path.splitext(raw_name)[1].lower()

                    # Coerenza: doc=PDF, photo=immagine
                    if ext == '.pdf':
                        kind = 'doc'
                        dest_dir = DOCS_DIR
                    elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                        kind = 'photo'
                        dest_dir = PHOTOS_DIR
                    else:
                        # fallback: documenti
                        kind = 'doc'
                        dest_dir = DOCS_DIR

                    # Salva una copia per ogni articolo selezionato
                    for art in articoli:
                        new_name = f"{art.id_articolo}_{uuid.uuid4().hex[:6]}_{raw_name}"
                        save_path = dest_dir / new_name

                        with open(save_path, 'wb') as f_out:
                            f_out.write(content)

                        db.add(Attachment(articolo_id=art.id_articolo, filename=new_name, kind=kind))

                    count_uploaded += 1

            db.commit()
            flash(
                f"Aggiornati {len(articoli)} articoli e caricati {count_uploaded} file (copiati su ciascun articolo).",
                "success"
            )
            return redirect(url_for('giacenze'))

        return render_template(
            'bulk_edit.html',
            rows=articoli,
            ids_csv=",".join(map(str, ids)),
            fields=editable_fields
        )

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


@app.route('/stampa_picking_pdf', methods=['POST'])
@login_required
def stampa_picking_pdf():
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    db = SessionLocal()
    try:
        # Prendi tutti i picking (o filtra per data se vuoi, qui stampiamo tutto)
        rows = db.query(Lavorazione).order_by(Lavorazione.data.desc()).all()
        
        bio = io.BytesIO()
        doc = SimpleDocTemplate(bio, pagesize=landscape(A4), topMargin=10*mm, bottomMargin=10*mm)
        elements = []
        styles = getSampleStyleSheet()

        # Titolo
        elements.append(Paragraph("<b>REPORT PICKING / LAVORAZIONI</b>", styles['Title']))
        elements.append(Spacer(1, 5*mm))

        # Intestazione Tabella
        data = [['DATA', 'CLIENTE', 'DESCRIZIONE', 'RICHIESTA DI', 'COLLI', 'PALLET', 'BLUE', 'WHITE']]
        
        # Righe Dati
        for r in rows:
            d_str = r.data.strftime('%d/%m/%Y') if r.data else ""
            p_str = f"IN:{r.pallet_forniti or 0} / OUT:{r.pallet_uscita or 0}"
            data.append([
                d_str,
                str(r.cliente or '')[:20],
                str(r.descrizione or '')[:30],
                str(r.richiesta_di or '')[:15],
                str(r.colli or 0),
                p_str,
                str(r.ore_blue_collar or 0),
                str(r.ore_white_collar or 0)
            ])

        # Creazione Tabella
        t = Table(data, colWidths=[25*mm, 40*mm, 60*mm, 35*mm, 15*mm, 35*mm, 15*mm, 15*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('fontName', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        elements.append(t)
        doc.build(elements)
        
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name=f"report_picking_{date.today()}.pdf", mimetype='application/pdf')

    except Exception as e:
        return f"Errore stampa: {e}"
    finally:
        db.close()

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
    # (facoltativo) protezione admin: togli se vuoi che anche user possa stampare etichette
    if session.get('role') != 'admin':
        flash("Accesso negato.", "danger")
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        clienti_query = (
            db.query(Articolo.cliente)
              .distinct()
              .filter(Articolo.cliente.isnot(None), Articolo.cliente != '')
              .order_by(Articolo.cliente)
              .all()
        )
        clienti = [c[0] for c in clienti_query]
        return render_template('labels_form.html', clienti=clienti)
    finally:
        db.close()

# ==============================================================================
#  GESTIONE ETICHETTE (PDF) - ROUTE E GENERAZIONE
# ==============================================================================
@app.route('/labels_pdf', methods=['POST'])
@login_required
def labels_pdf():
    ids = request.form.getlist('ids')
    filtro_cliente = (request.form.get('filtro_cliente') or '').strip()

    db = SessionLocal()
    try:
        articoli = []

        # ✅ CASO 1: ID specifici (dalla tabella giacenze)
        if ids:
            try:
                ids_int = [int(x) for x in ids if str(x).strip().isdigit()]
            except Exception:
                ids_int = []
            if ids_int:
                articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_int)).all()

        # ✅ CASO 2: filtro cliente (dalla pagina /labels)
        elif filtro_cliente:
            # solo articoli “in magazzino” (non usciti)
            articoli = (
                db.query(Articolo)
                  .filter(Articolo.cliente == filtro_cliente)
                  .filter((Articolo.data_uscita.is_(None)) | (Articolo.data_uscita == ''))
                  .all()
            )

        else:
            flash("Nessun articolo selezionato o filtro impostato.", "warning")
            return redirect(url_for('giacenze'))

        if not articoli:
            flash("Nessun articolo trovato per i criteri selezionati.", "warning")
            return redirect(url_for('giacenze'))

        pdf_file = _genera_pdf_etichetta(articoli)
        pdf_file.seek(0)

        filename = f"Etichette_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(pdf_file, as_attachment=True, download_name=filename, mimetype='application/pdf')

    finally:
        db.close()

# --- FUNZIONE GENERAZIONE PDF (REPORTLAB - Layout Grafico) ---
def _genera_pdf_etichetta(articoli):
    import io
    from pathlib import Path
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_LEFT

    bio = io.BytesIO()

    # ✅ Brother QL-800: 100mm x 62mm ORIZZONTALE
    W, H = 100 * mm, 62 * mm

    doc = SimpleDocTemplate(
        bio,
        pagesize=(W, H),
        leftMargin=2*mm, rightMargin=2*mm,
        topMargin=2*mm, bottomMargin=2*mm
    )

    # Stili "come foto": molto grandi
    s_big = ParagraphStyle(
        "BIG",
        fontName="Helvetica-Bold",
        fontSize=26,     # grande (simile alla foto)
        leading=28,
        alignment=TA_LEFT,
        spaceAfter=0
    )
    s_small = ParagraphStyle(
        "SMALL",
        fontName="Helvetica",
        fontSize=8,
        leading=9,
        alignment=TA_LEFT
    )

    def safe(v, maxlen=40):
        if v is None:
            return "-"
        v = str(v).strip()
        if not v:
            return "-"
        return v[:maxlen]

    def fmt_date(v):
        if not v:
            return "-"
        s = str(v).strip()
        # se arriva "YYYY-MM-DD ..." prendo i primi 10
        return s[:10]

    story = []
    logo_path = Path("static/logo camar.jpg")

    total_pages = 0
    # calcolo pagine totali per evitare PageBreak finale
    for art in articoli:
        try:
            tot_colli = int(art.n_colli) if art.n_colli else 1
        except Exception:
            tot_colli = 1
        tot_colli = max(1, tot_colli)
        total_pages += tot_colli

    page_counter = 0

    for art in articoli:
        try:
            tot_colli = int(art.n_colli) if art.n_colli else 1
        except Exception:
            tot_colli = 1
        tot_colli = max(1, tot_colli)

        for i in range(1, tot_colli + 1):
            page_counter += 1

            # --- LOGO (alto a sinistra)
            if logo_path.exists():
                try:
                    img = RLImage(str(logo_path), width=42*mm, height=12*mm)
                    img.hAlign = "LEFT"
                    story.append(img)
                    story.append(Spacer(1, 2*mm))
                except Exception:
                    pass

            # --- RIGHE GRANDI "come foto"
            cliente = safe(getattr(art, "cliente", None), 30)
            fornitore = safe(getattr(art, "fornitore", None), 30)
            ordine = safe(getattr(art, "ordine", None), 20)
            commessa = safe(getattr(art, "commessa", None), 20)
            n_ddt = safe(getattr(art, "n_ddt_ingresso", None), 20)
            data_ing = fmt_date(getattr(art, "data_ingresso", None))
            n_arrivo_base = safe(getattr(art, "n_arrivo", None), 20)

            # ✅ ARRIVO deve includere N.{collo}
            # es: "ARRIVO: 01/24 N.1"
            arrivo_full = f"{n_arrivo_base} N.{i}"

            # ✅ N. COLLO: 1/5
            n_collo = f"{i}/{tot_colli}"

            story.append(Paragraph(f"CLIENTE: {cliente}", s_big))
            story.append(Paragraph(f"FORNITORE: {fornitore}", s_big))
            story.append(Paragraph(f"ORDINE: {ordine}", s_big))
            story.append(Paragraph(f"COMMESSA: {commessa}", s_big))
            story.append(Paragraph(f"N. DDT: {n_ddt}", s_big))
            story.append(Paragraph(f"DATA INGRESSO: {data_ing}", s_big))
            story.append(Paragraph(f"ARRIVO: {arrivo_full}", s_big))
            story.append(Paragraph(f"N. COLLO: {n_collo}", s_big))
            story.append(Paragraph(f"COLLI: {tot_colli}", s_big))

            # (facoltativo) descrizione piccola in fondo
            descr = getattr(art, "descrizione", None)
            if descr:
                story.append(Spacer(1, 1*mm))
                story.append(Paragraph(safe(descr, 80), s_small))

            # ✅ NO pagina vuota finale
            if page_counter < total_pages:
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
@app.route('/fix_db_schema')
@login_required
def fix_db_schema():
    if session.get('role') != 'admin': return "Accesso Negato", 403
    db = SessionLocal()
    log = []
    try:
        from sqlalchemy import text
        # 1. Crea tabelle fisiche se mancano
        Base.metadata.create_all(bind=db.get_bind())
        log.append("Struttura base verificata.")

        # 2. COLONNE GIACENZE (Articoli)
        # Aggiungiamo tutte le colonne che potrebbero mancare
        cols_art = [
            ("lotto", "TEXT"), ("peso", "FLOAT"), ("m2", "FLOAT"), ("m3", "FLOAT"), 
            ("n_arrivo", "TEXT"), ("data_uscita", "DATE"), ("serial_number", "TEXT"),
            ("lunghezza", "FLOAT"), ("larghezza", "FLOAT"), ("altezza", "FLOAT")
        ]
        for c, t in cols_art:
            try: 
                db.execute(text(f"ALTER TABLE articoli ADD COLUMN {c} {t};"))
                db.commit()
                log.append(f"Aggiunto {c} ad Articoli")
            except: db.rollback()

        # 3. COLONNE TRASPORTI
        cols_tra = [
            ("magazzino", "TEXT"), ("consolidato", "TEXT"), 
            ("tipo_mezzo", "TEXT"), ("ddt_uscita", "TEXT"), ("costo", "FLOAT")
        ]
        for c, t in cols_tra:
            try: 
                db.execute(text(f"ALTER TABLE trasporti ADD COLUMN {c} {t};"))
                db.commit()
                log.append(f"Aggiunto {c} a Trasporti")
            except: db.rollback()

        # 4. COLONNE PICKING (Lavorazioni)
        cols_lav = [
            ("seriali", "TEXT"), ("colli", "INTEGER"), 
            ("pallet_forniti", "INTEGER"), ("pallet_uscita", "INTEGER"), 
            ("ore_blue_collar", "FLOAT"), ("ore_white_collar", "FLOAT"),
            ("richiesta_di", "TEXT")
        ]
        for c, t in cols_lav:
            try: 
                db.execute(text(f"ALTER TABLE lavorazioni ADD COLUMN {c} {t};"))
                db.commit()
                log.append(f"Aggiunto {c} a Picking")
            except: db.rollback()

        return f"<h1>Database Aggiornato!</h1><ul>{''.join(['<li>'+l+'</li>' for l in log])}</ul><a href='/home'>Torna alla Home</a>"
    except Exception as e:
        return f"Errore Fix: {e}"
    finally:
        db.close()

def _parse_data_db_helper(val):
    """
    Accetta:
    - date / datetime
    - stringa 'YYYY-MM-DD'
    - stringa 'DD/MM/YYYY'
    - stringa con orario 'YYYY-MM-DD HH:MM:SS'
    Ritorna date oppure None.
    """
    if val is None:
        return None

    if isinstance(val, datetime):
        return val.date()

    if isinstance(val, date):
        return val

    s = str(val).strip()
    if not s:
        return None

    # prova YYYY-MM-DD
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass

    # prova DD/MM/YYYY
    try:
        return datetime.strptime(s[:10], "%d/%m/%Y").date()
    except Exception:
        pass

    return None

@app.route('/calcola_costi', methods=['GET', 'POST'])
@login_required
def calcola_costi():
    from datetime import date

    # valori default
    today = date.today()
    data_da = request.form.get('data_da') or today.replace(day=1).isoformat()
    data_a = request.form.get('data_a') or today.isoformat()
    cliente_filtro = (request.form.get('cliente') or '').strip()
    raggruppamento = request.form.get('raggruppamento') or 'mese'

    risultati = []

    db = SessionLocal()
    try:
        q = db.query(Articolo)

        # filtro cliente (se inserito)
        if cliente_filtro:
            q = q.filter(Articolo.cliente.ilike(f"%{cliente_filtro}%"))

        articoli = q.all()

        # calcolo solo se POST (quando premi "Calcola")
        if request.method == 'POST':
            risultati = _calcola_logica_costi(articoli, data_da, data_a, raggruppamento)

        return render_template(
            'calcola_costi.html',
            risultati=risultati,
            data_da=data_da,
            data_a=data_a,
            cliente_filtro=cliente_filtro,
            raggruppamento=raggruppamento,
            today=today
        )

    finally:
        db.close()


def _calcola_logica_costi(articoli, data_da, data_a, raggruppamento):
    """
    Core logic: Calcola M2 per ogni giorno di occupazione.
    Output: lista di dict con periodo/cliente/m2_tot/m2_medio/giorni
    """
    from collections import defaultdict
    from datetime import timedelta, date, datetime

    m2_per_giorno = defaultdict(float)

    def to_date_obj(d):
        if not d:
            return None
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        s = str(d)[:10].strip()
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            try:
                return datetime.strptime(s, "%d/%m/%Y").date()
            except Exception:
                return None

    d_start = to_date_obj(data_da)
    d_end = to_date_obj(data_a)
    if not d_start or not d_end:
        return []

    # se l'utente mette date invertite, le scambiamo
    if d_end < d_start:
        d_start, d_end = d_end, d_start

    for art in articoli:
        # M2 sicuro
        try:
            m2 = float(str(getattr(art, "m2", "")).replace(",", ".")) if getattr(art, "m2", None) else 0.0
        except Exception:
            m2 = 0.0
        if m2 <= 0:
            continue

        d_ingr = to_date_obj(getattr(art, "data_ingresso", None))
        if not d_ingr:
            continue

        d_usc = to_date_obj(getattr(art, "data_uscita", None))

        inizio_attivo = max(d_ingr, d_start)

        # se esce, non conteggiamo il giorno di uscita (uscita - 1)
        if d_usc:
            fine_attivo = min(d_usc - timedelta(days=1), d_end)
        else:
            fine_attivo = d_end

        if fine_attivo < inizio_attivo:
            continue

        cliente_key = (getattr(art, "cliente", None) or "SCONOSCIUTO").upper()

        curr = inizio_attivo
        while curr <= fine_attivo:
            m2_per_giorno[(cliente_key, curr)] += m2
            curr += timedelta(days=1)

    risultati_finali = []

    if raggruppamento == "giorno":
        for (cliente, giorno) in sorted(m2_per_giorno.keys(), key=lambda k: (k[0], k[1])):
            val_m2 = m2_per_giorno[(cliente, giorno)]
            risultati_finali.append({
                "periodo": giorno.strftime("%d/%m/%Y"),
                "cliente": cliente,
                "m2_tot": f"{val_m2:.3f}",
                "m2_medio": f"{val_m2:.3f}",
                "giorni": 1
            })
    else:
        agg_mese = defaultdict(lambda: {"m2_sum": 0.0, "giorni_set": set()})
        for (cliente, giorno), val_m2 in m2_per_giorno.items():
            key = (cliente, giorno.year, giorno.month)
            agg_mese[key]["m2_sum"] += val_m2
            agg_mese[key]["giorni_set"].add(giorno)

        for (cliente, anno, mese) in sorted(agg_mese.keys(), key=lambda k: (k[1], k[2], k[0])):
            dati = agg_mese[(cliente, anno, mese)]
            num_giorni = len(dati["giorni_set"])
            m2_tot = dati["m2_sum"]
            m2_medio = (m2_tot / num_giorni) if num_giorni else 0.0

            risultati_finali.append({
                "periodo": f"{mese:02d}/{anno}",
                "cliente": cliente,
                "m2_tot": f"{m2_tot:.3f}",
                "m2_medio": f"{m2_medio:.3f}",
                "giorni": num_giorni
            })

    return risultati_finali


# --- AVVIO FLASK APP ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
