
# -*- coding: utf-8 -*-
"""
Camar - Gestionale Web – build aggiornata (Ottobre 2025)
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
import time
import mimetypes
from urllib.parse import unquote, quote
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
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify, render_template_string, abort, has_request_context
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Database (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Date, ForeignKey, Boolean, or_, Identity, text, Index, inspect, case
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
from jinja2 import DictLoader, ChoiceLoader, FileSystemLoader
# ========================================================
# 1. INIZIALIZZAZIONE APP E LOGIN MANAGER (ORDINE CORRETTO)
# ========================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chiave_segreta_super_sicura")

# Inizializza LoginManager SUBITO
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.after_request
def _force_utf8_html_response(response):
    """Evita caratteri strani tipo â€¢ su alcuni browser/mobile."""
    try:
        content_type = (response.headers.get('Content-Type') or '').lower()
        if content_type.startswith('text/html'):
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
    except Exception:
        pass
    return response

# =========================
# Formattazione numeri ITA
# =========================
def it_num(value, decimals=2):
    """Formatta un numero con la virgola come separatore decimale (stile IT)."""
    if value is None or value == "":
        return ""
    try:
        v = float(value)
    except Exception:
        return str(value)

    s = f"{v:.{int(decimals)}f}"
    return s.replace('.', ',')


# filtro Jinja: {{ value|it_num(2) }}
app.jinja_env.filters['it_num'] = it_num


def normalize_text_key(value):
    """Normalizza una stringa per confronti testuali esatti ma tolleranti."""
    s = (value or "").strip().upper()
    return re.sub(r'[^A-Z0-9]+', '', s)


app.jinja_env.filters['norm_key'] = normalize_text_key


def normalized_sql_text(column_expr):
    """Versione SQL normalizzata di un campo testuale (maiuscolo, senza spazi/punteggiatura)."""
    expr = func.upper(func.trim(column_expr))
    for char in [' ', '.', '-', '_', '/', '\\']:
        expr = func.replace(expr, char, '')
    return expr


def parse_float_filter(value):
    """Accetta valori tipo '1,25' oppure range '1,0-2,5' / '1,0:2,5'."""
    s = (value or "").strip()
    if not s:
        return None
    s = s.replace(' ', '')
    parts = re.split(r'\s*[-:]\s*', s, maxsplit=1)

    def _to_float(v):
        return float(str(v).replace('.', '').replace(',', '.')) if ',' in str(v) and str(v).count(',') == 1 and '.' in str(v) else float(str(v).replace(',', '.'))

    try:
        if len(parts) == 2 and parts[0] != '' and parts[1] != '':
            a = _to_float(parts[0])
            b = _to_float(parts[1])
            if a > b:
                a, b = b, a
            return ('range', a, b)
        return ('exact', _to_float(s))
    except Exception:
        return None


def match_numeric_filter(value, parsed_filter, tol=0.0005):
    if parsed_filter is None:
        return True
    try:
        num = float(value)
    except Exception:
        return False
    if parsed_filter[0] == 'range':
        return parsed_filter[1] <= num <= parsed_filter[2]
    return abs(num - parsed_filter[1]) <= tol


# ========================================================
#  BARCODE / QR ENTRATA
# ========================================================
def _norm_token(val):
    return re.sub(r'[^A-Z0-9]+', '', (val or '').upper())


def genera_codice_entrata(n_arrivo=None, n_ddt=None, data_ingresso=None, cliente=None):
    """Genera un codice entrata STABILE e separato per cliente.

    Regola importante:
    - stesso cliente + stessa data + stesso N. arrivo/DDT = stesso codice;
    - clienti diversi possono usare lo stesso N. arrivo senza sovrapporsi;
    - se manca tutto, usa un fallback casuale.
    """
    dt = to_date_db(data_ingresso) if 'to_date_db' in globals() else None
    if not dt:
        dt = date.today()

    cli = _norm_token(cliente)[:24]
    arr = _norm_token(n_arrivo)[:20]
    ddt = _norm_token(n_ddt)[:20]
    base = arr or ddt

    parts = ["ENT", dt.strftime("%Y%m%d")]
    if cli:
        parts.append(cli)
    if base:
        parts.append(base)
        return "-".join(parts)

    # fallback solo se non abbiamo riferimenti utili per rigenerare lo stesso codice
    parts.append(uuid.uuid4().hex[:6].upper())
    return "-".join(parts)


def ensure_codice_entrata(value=None, n_arrivo=None, n_ddt=None, data_ingresso=None, cliente=None):
    v = (value or '').strip()
    return v or genera_codice_entrata(n_arrivo=n_arrivo, n_ddt=n_ddt, data_ingresso=data_ingresso, cliente=cliente)


def cliente_from_form_or_current(form, current_value=None, allow_blank=False):
    """Legge il cliente dal form in modo robusto e lo normalizza sui clienti validi."""
    raw = ''
    for key in ('cliente', 'cliente_edit', 'cliente_form', 'cliente_hidden'):
        try:
            raw = (form.get(key) or '').strip()
        except Exception:
            raw = ''
        if raw:
            break
    if not raw:
        raw = (current_value or '').strip()
    return validate_cliente_or_raise(raw, allow_blank=allow_blank)


def strip_arrivo_progressivo(value):
    """Rimuove un eventuale progressivo finale tipo N.1 / N 1 / COLLO 1 / 1/3 dal n.arrivo."""
    s = (value or '').strip()
    if not s:
        return ''
    s = re.sub(r'\s+N\.?\s*\d+\s*$', '', s, flags=re.I)
    s = re.sub(r'\s+COLLO\s*\d+\s*$', '', s, flags=re.I)
    s = re.sub(r'\s+\d+\s*/\s*\d+\s*$', '', s, flags=re.I)
    return re.sub(r'\s{2,}', ' ', s).strip(' -')


def build_arrivo_progressivo(base_value, index):
    base = strip_arrivo_progressivo(base_value)
    idx = max(1, int(index or 1))
    return f"{base} N.{idx}" if base else f"N.{idx}"


def build_public_base_url():
    env_url = (os.environ.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
    if env_url:
        return env_url
    if has_request_context():
        return request.url_root.rstrip('/')
    return 'http://localhost:5000'


def build_entry_public_url(codice_entrata):
    codice_entrata = (codice_entrata or '').strip()
    if not codice_entrata:
        return ''
    from urllib.parse import quote
    return f"{build_public_base_url()}/entrata/{quote(codice_entrata, safe='')}"


def _codice_entrata_varianti(codice_entrata):
    """Restituisce le varianti compatibili del codice entrata.
    Serve per non perdere il collegamento tra barcode vecchi (senza cliente)
    e barcode nuovi (con cliente).
    Esempi:
    - ENT-20260511-71526
    - ENT-20260511-RFDEWAVE-71526
    """
    codice = (codice_entrata or '').strip()
    varianti = []
    if codice:
        varianti.append(codice)

    parts = codice.split('-') if codice else []
    if len(parts) >= 4 and parts[0].upper() == 'ENT':
        data_part = parts[1]
        cliente_part = parts[2]
        resto = '-'.join(parts[3:]).strip()
        # Variante vecchia senza cliente
        if resto:
            varianti.append(f"ENT-{data_part}-{resto}")
    elif len(parts) == 3 and parts[0].upper() == 'ENT':
        # Variante vecchia: aggiungo possibili versioni con cliente partendo dai clienti validi
        data_part = parts[1]
        resto = parts[2]
        try:
            for cli in get_clienti_utenti():
                cli_norm = _norm_token(cli)[:24]
                if cli_norm:
                    varianti.append(f"ENT-{data_part}-{cli_norm}-{resto}")
        except Exception:
            pass

    # de-dup preservando ordine
    out, seen = [], set()
    for v in varianti:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


app.jinja_env.globals['_codice_entrata_varianti'] = _codice_entrata_varianti


def _codice_entrata_preferito(codice_entrata, rows=None):
    """Calcola il codice entrata preferito usando il cliente quando possibile.
    Se il barcode richiesto è vecchio, lo aggiorna al nuovo formato stabile.
    """
    codice = (codice_entrata or '').strip()
    rows = rows or []
    if not rows:
        return codice
    first = rows[0]
    return ensure_codice_entrata(
        None,
        n_arrivo=strip_arrivo_progressivo(getattr(first, 'n_arrivo', None)),
        n_ddt=getattr(first, 'n_ddt_ingresso', None),
        data_ingresso=getattr(first, 'data_ingresso', None),
        cliente=getattr(first, 'cliente', None),
    ) or codice


def _normalizza_codice_entrata_rows(db, codice_entrata, rows):
    """Uniforma le righe trovate con barcode vecchio/nuovo allo stesso codice entrata.
    Non cambia QR/barcode se non serve; evita che il dettaglio entrata resti spezzato.
    """
    rows = rows or []
    if not rows:
        return 0, codice_entrata
    preferito = _codice_entrata_preferito(codice_entrata, rows)
    changed = 0
    for r in rows:
        if (getattr(r, 'codice_entrata', '') or '') != preferito:
            r.codice_entrata = preferito
            changed += 1
    if changed:
        try:
            db.commit()
        except Exception:
            db.rollback()
            changed = 0
    return changed, preferito


def _collect_entrata_attachments(rows):
    docs, photos = [], []
    seen_docs, seen_photos = set(), set()
    for r in rows or []:
        for a in getattr(r, 'attachments', []) or []:
            key = (a.kind or '', a.filename or '')
            if a.kind == 'doc' and a.filename and key not in seen_docs:
                docs.append(a)
                seen_docs.add(key)
            elif a.kind == 'photo' and a.filename and key not in seen_photos:
                photos.append(a)
                seen_photos.add(key)
    return docs, photos


def _row_att_counts(row):
    docs = 0
    photos = 0
    for a in getattr(row, 'attachments', []) or []:
        if a.kind == 'doc':
            docs += 1
        elif a.kind == 'photo':
            photos += 1
    return docs, photos


def analyze_entrata_rows(rows):
    """Analizza le righe di una stessa entrata e segnala eventuali anomalie leggere.
    Non modifica nulla: serve per mostrare Verifica/Correggi nel dettaglio entrata.
    """
    anomalies = []
    rows = rows or []
    if not rows:
        return {"has_anomalies": False, "anomalies": anomalies}

    clienti = {(getattr(r, 'cliente', '') or '').strip().upper() for r in rows if (getattr(r, 'cliente', '') or '').strip()}
    if len(clienti) > 1:
        for r in rows:
            anomalies.append({"row": r, "reason": "Cliente diverso dalle altre righe della stessa entrata"})

    seen_arrivi = {}
    for r in rows:
        arr = (getattr(r, 'n_arrivo', '') or '').strip().upper()
        desc = (getattr(r, 'descrizione', '') or '').strip().upper()
        code = (getattr(r, 'codice_articolo', '') or '').strip().upper()

        if arr:
            seen_arrivi.setdefault(arr, []).append(r)

        # Non segnaliamo più come errore le righe MERCE VARIA generate da etichetta/scansione:
        # sono righe provvisorie da completare, ma non devono rompere il collegamento barcode.
        # Segnaliamo solo vere righe vuote senza codice, descrizione e cliente.
        if len(rows) > 1 and not code and not desc and not (getattr(r, 'cliente', '') or '').strip():
            anomalies.append({"row": r, "reason": "Riga vuota o incompleta nell'entrata multipla"})

    for arr, group in seen_arrivi.items():
        if len(group) > 1:
            codici_entrata = {(getattr(r, 'codice_entrata', '') or '').strip() for r in group}
            # Se le righe appartengono alla stessa entrata/barcode, il N. arrivo uguale è ammesso.
            if len(codici_entrata) > 1:
                for r in group:
                    anomalies.append({"row": r, "reason": f"N. arrivo duplicato su entrate diverse: {arr}"})

    # dedup per id_articolo + motivo
    dedup = []
    seen = set()
    for a in anomalies:
        key = (getattr(a["row"], "id_articolo", None), a["reason"])
        if key not in seen:
            seen.add(key)
            dedup.append(a)

    return {"has_anomalies": bool(dedup), "anomalies": dedup}


# ========================================================
#  API INTEGRAZIONE CLIENTI
# ========================================================
# Le route API sono state spostate in routes/api.py
# Endpoint mantenuti:
# - /api/v1/health
# - /api/v1/giacenze
# - /api/v1/inventario
# - /api/v1/movimenti


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



def _safe_date_ymd(value):
    s = (value or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None


def _safe_int(value):
    s = str(value or '').strip()
    if not s:
        return None
    try:
        return int(float(s.replace(',', '.')))
    except Exception:
        return None


def _safe_float_it(value):
    s = str(value or '').strip()
    if not s:
        return None
    try:
        return float(s.replace(',', '.'))
    except Exception:
        return None


def _apply_ilike_filter(query, column, value):
    s = (value or '').strip()
    if not s:
        return query
    return query.filter(column.ilike(f"%{s}%"))

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


# ========================================================
# BACKUP
# Le funzioni backup e il backup automatico sono in routes/backup.py
# ========================================================

def _get_buono_carico_attivo_id():
    """Restituisce l'ID del buono QR attivo solo se valido ed esistente.

    Evita Internal Server Error quando in sessione resta salvato un buono eliminato
    oppure quando arriva un valore non numerico nella URL /giacenze.
    """
    raw = ""
    try:
        raw = (
            request.args.get("aggiungi_buono_carico")
            or session.get("aggiungi_buono_carico")
            or ""
        )
        raw = str(raw).strip()
        if not raw or not raw.isdigit():
            session.pop("aggiungi_buono_carico", None)
            return ""

        # A richiesta già avviata i modelli sono presenti nei globals().
        if "BuonoCarico" not in globals() or "SessionLocal" not in globals():
            return raw

        db = SessionLocal()
        try:
            exists = db.query(BuonoCarico.id).filter(BuonoCarico.id == int(raw)).first()
            if exists:
                return raw
            session.pop("aggiungi_buono_carico", None)
            return ""
        finally:
            db.close()
    except Exception:
        try:
            session.pop("aggiungi_buono_carico", None)
        except Exception:
            pass
        return ""


@app.before_request
def _remember_buono_carico_da_aggiungere():
    """Mantiene in sessione l'ID del buono quando si passa dal dettaglio buono al Magazzino."""
    try:
        val = (request.args.get("aggiungi_buono_carico") or "").strip()
        if val.isdigit():
            session["aggiungi_buono_carico"] = val
        elif "aggiungi_buono_carico" in request.args:
            session.pop("aggiungi_buono_carico", None)
    except Exception:
        pass


@app.context_processor
def _ctx_buono_carico_attivo():
    """ID buono carico attivo per template Magazzino."""
    return {"buono_carico_attivo": _get_buono_carico_attivo_id()}



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
# 3. CONFIGURAZIONE DATABASE (Render-safe)
# ========================================================
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base

DB_URL = os.environ.get("DATABASE_URL", "").strip()

# ✅ In produzione: MAI fallback silenzioso a sqlite
IS_RENDER = bool(os.environ.get("RENDER")) or bool(os.environ.get("RENDER_SERVICE_ID"))

if not DB_URL:
    if IS_RENDER:
        raise RuntimeError("DATABASE_URL non è impostata su Render! Controlla le Environment Variables del service.")
    DB_URL = f"sqlite:///{APP_DIR / 'magazzino.db'}"

# Render a volte usa postgres:// -> SQLAlchemy vuole postgresql://
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

def _normalize_db_url(u: str) -> str:
    # opzionale: mysql
    if u.startswith("mysql://"):
        u = "mysql+pymysql://" + u[len("mysql://"):]
    return u

DB_URL = _normalize_db_url(DB_URL)

# ✅ pool_pre_ping evita connessioni "morte" (tipico su hosting)
engine = create_engine(
    DB_URL,
    future=True,
    echo=False,
    pool_pre_ping=True
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
)

Base = declarative_base()

# ✅ IMPORTANTISSIMO: rimuove la sessione a fine request (evita problemi con più utenti/worker)
@app.teardown_appcontext
def remove_scoped_session(exception=None):
    SessionLocal.remove()

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
    codice_entrata = Column(String(255))
    created_by = Column(String(64))
    updated_by = Column(String(64))
    updated_at = Column(String(32))
    attachments = relationship("Attachment", back_populates="articolo", cascade="all, delete-orphan", passive_deletes=True)
    lotto = Column(Text) # <--- AGGIUNGI QUESTA

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, Identity(start=1), primary_key=True)
    articolo_id = Column(Integer, ForeignKey("articoli.id_articolo", ondelete='CASCADE'), nullable=False)
    kind = Column(String(10)); filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")


# --- MODELLO BUONI DI CARICO CON QR ---
class BuonoCarico(Base):
    __tablename__ = "buoni_carico"
    id = Column(Integer, Identity(start=1), primary_key=True)
    codice_buono = Column(String(64), unique=True)
    id_articolo_origine = Column(Integer)
    cliente = Column(Text)
    fornitore = Column(Text)
    codice_articolo = Column(Text)
    descrizione = Column(Text)
    n_arrivo = Column(Text)
    n_ddt_ingresso = Column(Text)
    data_ingresso = Column(String(32))
    codice_entrata = Column(String(255))
    pallet_previsti = Column(Integer)
    peso_previsto = Column(Float)
    stato = Column(String(32), default="DA CARICARE")
    note = Column(Text)
    created_at = Column(String(32))
    created_by = Column(String(64))

class BuonoCaricoScan(Base):
    __tablename__ = "buoni_carico_scansioni"
    id = Column(Integer, Identity(start=1), primary_key=True)
    buono_id = Column(Integer, ForeignKey("buoni_carico.id", ondelete="CASCADE"), nullable=False)
    codice_scansionato = Column(String(255))
    esito = Column(String(32))
    messaggio = Column(Text)
    scanned_at = Column(String(32))
    scanned_by = Column(String(64))


class BuonoCaricoRiga(Base):
    __tablename__ = "buoni_carico_righe"
    id = Column(Integer, Identity(start=1), primary_key=True)
    buono_id = Column(Integer, ForeignKey("buoni_carico.id", ondelete="CASCADE"), nullable=False)
    id_articolo = Column(Integer)
    cliente = Column(Text)
    fornitore = Column(Text)
    codice_articolo = Column(Text)
    descrizione = Column(Text)
    n_arrivo = Column(Text)
    n_ddt_ingresso = Column(Text)
    data_ingresso = Column(String(32))
    codice_entrata = Column(String(255))
    colli_previsti = Column(Integer)
    peso_previsto = Column(Float)

Base.metadata.create_all(engine)


def ensure_buoni_carico_extra_schema(engine):
    """Aggiunge campi extra ai buoni di carico se il DB è già esistente."""
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        if "buoni_carico" not in tables:
            Base.metadata.create_all(engine)
            return
        cols = {c.get("name") for c in insp.get_columns("buoni_carico")}
        extra_cols = {
            "id_articolo_origine": "INTEGER",
            "codice_articolo": "TEXT",
            "descrizione": "TEXT",
        }
        for col, typ in extra_cols.items():
            if col not in cols:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE buoni_carico ADD COLUMN {col} {typ}"))
                    print(f"[OK] aggiunta colonna buoni_carico.{col}")
                except Exception as e:
                    print(f"[WARN] impossibile aggiungere buoni_carico.{col}: {e}")
    except Exception as e:
        print(f"[WARN] ensure_buoni_carico_extra_schema fallita: {e}")

ensure_buoni_carico_extra_schema(engine)



def ensure_barcode_entry_schema(engine):
    try:
        insp = inspect(engine)
        cols = {c.get('name') for c in insp.get_columns('articoli')}
    except Exception as e:
        print(f"[WARN] impossibile ispezionare schema articoli: {e}")
        cols = set()

    if 'codice_entrata' not in cols:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE articoli ADD COLUMN codice_entrata TEXT"))
            print('[OK] aggiunta colonna codice_entrata ad articoli')
        except Exception as e:
            print(f"[WARN] impossibile aggiungere codice_entrata: {e}")


ensure_barcode_entry_schema(engine)


def ensure_audit_schema(engine):
    """Aggiunge colonne audit se il database è già esistente."""
    try:
        insp = inspect(engine)
        cols = {c.get('name') for c in insp.get_columns('articoli')}
    except Exception as e:
        print(f"[WARN] impossibile ispezionare schema audit articoli: {e}")
        cols = set()

    audit_cols = {
        'created_by': 'TEXT',
        'updated_by': 'TEXT',
        'updated_at': 'TEXT',
    }
    for col, typ in audit_cols.items():
        if col not in cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE articoli ADD COLUMN {col} {typ}"))
                print(f"[OK] aggiunta colonna audit {col} ad articoli")
            except Exception as e:
                print(f"[WARN] impossibile aggiungere colonna audit {col}: {e}")


ensure_audit_schema(engine)


def _current_username_for_audit():
    try:
        if has_request_context() and getattr(current_user, 'is_authenticated', False):
            return (getattr(current_user, 'id', '') or session.get('username') or '').strip().upper()
    except Exception:
        pass
    return ''


from sqlalchemy import event

@event.listens_for(SessionLocal.session_factory, 'before_flush')
def _audit_articoli_before_flush(session_db, flush_context, instances):
    """Compila automaticamente creato/modificato da per Articolo."""
    user = _current_username_for_audit()
    if not user:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for obj in list(session_db.new):
        if isinstance(obj, Articolo):
            if not getattr(obj, 'created_by', None):
                obj.created_by = user
            obj.updated_by = user
            obj.updated_at = now
    for obj in list(session_db.dirty):
        if isinstance(obj, Articolo) and session_db.is_modified(obj, include_collections=False):
            obj.updated_by = user
            obj.updated_at = now


# ========================================================
# 4b. INDICI DB (performance query) - SAFE (checkfirst)
# ========================================================

def ensure_db_indexes(engine):
    # Crea indici importanti se mancano (checkfirst).
    # Nota: su MySQL alcuni campi Text richiedono una lunghezza; la impostiamo solo su MySQL.
    try:
        dialect = engine.dialect.name
        mysql_len = 191 if dialect == 'mysql' else None

        idx_specs = []
        # Campi molto usati nei filtri/ricerche
        idx_specs.append(('ix_articoli_id_articolo', [Articolo.id_articolo], {}))
        idx_specs.append(('ix_articoli_magazzino', [Articolo.magazzino], {}))
        idx_specs.append(('ix_articoli_posizione', [Articolo.posizione], {}))
        idx_specs.append(('ix_articoli_serial_number', [Articolo.serial_number], {}))
        idx_specs.append(('ix_articoli_ns_rif', [Articolo.ns_rif], {}))
        idx_specs.append(('ix_articoli_codice_entrata', [Articolo.codice_entrata], {}))

        # Text: cliente/codice/protocollo/ordine spesso ricercati
        if mysql_len:
            idx_specs.append(('ix_articoli_cliente', [Articolo.cliente], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_codice_articolo', [Articolo.codice_articolo], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_protocollo', [Articolo.protocollo], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_ordine', [Articolo.ordine], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_buono_n', [Articolo.buono_n], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_n_arrivo', [Articolo.n_arrivo], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_ddt_ingresso', [Articolo.n_ddt_ingresso], {'mysql_length': mysql_len}))
            idx_specs.append(('ix_articoli_ddt_uscita', [Articolo.n_ddt_uscita], {'mysql_length': mysql_len}))
        else:
            idx_specs.append(('ix_articoli_cliente', [Articolo.cliente], {}))
            idx_specs.append(('ix_articoli_codice_articolo', [Articolo.codice_articolo], {}))
            idx_specs.append(('ix_articoli_protocollo', [Articolo.protocollo], {}))
            idx_specs.append(('ix_articoli_ordine', [Articolo.ordine], {}))
            idx_specs.append(('ix_articoli_buono_n', [Articolo.buono_n], {}))
            idx_specs.append(('ix_articoli_n_arrivo', [Articolo.n_arrivo], {}))
            idx_specs.append(('ix_articoli_ddt_ingresso', [Articolo.n_ddt_ingresso], {}))
            idx_specs.append(('ix_articoli_ddt_uscita', [Articolo.n_ddt_uscita], {}))

        # Date come stringa: indice comunque utile per ordinamenti/filtri grezzi
        idx_specs.append(('ix_articoli_data_ingresso', [Articolo.data_ingresso], {}))
        idx_specs.append(('ix_articoli_data_uscita', [Articolo.data_uscita], {}))

        for name, cols, kwargs in idx_specs:
            try:
                Index(name, *cols, **kwargs).create(bind=engine, checkfirst=True)
            except Exception as e:
                print(f"[WARN] indice non creato {name}: {e}")
    except Exception as e:
        print(f"[WARN] ensure_db_indexes fallita: {e}")

# Crea indici (se possibile) all'avvio
ensure_db_indexes(engine)


def ensure_buoni_carico_multi_schema(engine):
    """Crea tabella righe buono carico e aggiunge campi se il DB esiste già."""
    try:
        Base.metadata.create_all(engine)
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        if "buoni_carico" in tables:
            cols = {c.get("name") for c in insp.get_columns("buoni_carico")}
            extra_cols = {
                "id_articolo_origine": "INTEGER",
                "codice_articolo": "TEXT",
                "descrizione": "TEXT",
            }
            for col, typ in extra_cols.items():
                if col not in cols:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE buoni_carico ADD COLUMN {col} {typ}"))
                    except Exception as e:
                        print(f"[WARN] colonna buoni_carico.{col}: {e}")
    except Exception as e:
        print(f"[WARN] ensure_buoni_carico_multi_schema fallita: {e}")

ensure_buoni_carico_multi_schema(engine)



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
    n_arrivo = Column(Text)         # Nuovo - riferimento arrivo/buono
    colli = Column(Integer)
    pallet_forniti = Column(Integer) # Pallet IN
    pallet_uscita = Column(Integer)  # Pallet OUT
    ore_blue_collar = Column(Float)  # Ore Blue
    ore_white_collar = Column(Float) # Ore White



def ensure_lavorazioni_extra_schema(engine):
    """Aggiunge campi extra alla tabella lavorazioni se il DB esiste già."""
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        if "lavorazioni" not in tables:
            Base.metadata.create_all(engine)
            return
        cols = {c.get("name") for c in insp.get_columns("lavorazioni")}
        extra_cols = {
            "n_arrivo": "TEXT",
        }
        for col, typ in extra_cols.items():
            if col not in cols:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE lavorazioni ADD COLUMN {col} {typ}"))
                    print(f"[OK] aggiunta colonna lavorazioni.{col}")
                except Exception as e:
                    print(f"[WARN] impossibile aggiungere lavorazioni.{col}: {e}")
    except Exception as e:
        print(f"[WARN] ensure_lavorazioni_extra_schema fallita: {e}")

ensure_lavorazioni_extra_schema(engine)

# ========================================================
# 5. GESTIONE UTENTI (Definizione PRIMA dell'uso)
# ========================================================
DEFAULT_USERS = {
    'FINCANTIERI ARMATORE': 'Struppa100',
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'FINCANTIERI SCOPERTO': 'Struppa12',
    'SIEMGROUP': 'Struppa13','RF-DE WAVE': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'MARINE INTERIORS': 'Struppa09', 'GALVANO TECNICA': 'Struppa10', 'DE WAVE SAMA': 'Struppa11','OPS': '271214',
    'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02', 'DIEGO': 'Balleydier03', 'ADMIN': 'admin123',
    'MAGAZZINO': 'Magazzino01', 'WAREHOUSE': 'Magazzino01', 'MAG1': 'Magazzino01'
}
ADMIN_USERS = {'ADMIN', 'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO'}
WAREHOUSE_USERS = {'MAGAZZINO', 'WAREHOUSE', 'MAG1'}



def can_use_buoni_qr():
    """Permessi Buoni QR: ADMIN/OPS e MAGAZZINO. Clienti esclusi."""
    try:
        return session.get("role") in ("admin", "magazzino")
    except Exception:
        return False

app.jinja_env.globals["can_use_buoni_qr"] = can_use_buoni_qr


def require_admin(view_func):
    """Decorator: allow only admin users."""
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Accesso negato.", "danger")
            return redirect(url_for('giacenze'))
        return view_func(*args, **kwargs)
    return _wrapped


# ========================================================
#  LOG ERRORI INTERNO - ADMIN
# ========================================================
ERROR_LOG_FILE = MEDIA_DIR / "errori_gestionale.log"

def scrivi_log_errore(titolo="", errore=None):
    """Scrive gli errori applicativi in un file persistente leggibile da admin."""
    try:
        ERROR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        user = ""
        path = ""
        method = ""
        try:
            if has_request_context():
                user = (getattr(current_user, "id", "") or session.get("username") or "").strip()
                path = request.path
                method = request.method
        except Exception:
            pass

        import traceback
        dettaglio = ""
        if errore is not None:
            dettaglio = "".join(traceback.format_exception(type(errore), errore, errore.__traceback__))
        else:
            dettaglio = traceback.format_exc()

        riga = (
            "\n" + "=" * 90 + "\n"
            f"DATA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTENTE: {user or '-'}\n"
            f"ROUTE: {method} {path}\n"
            f"TITOLO: {titolo or '-'}\n"
            f"ERRORE:\n{dettaglio}\n"
        )

        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(riga)
    except Exception:
        pass


@app.errorhandler(Exception)
def gestisci_errore_generale(e):
    """Evita schermata generica senza traccia: salva errore e mostra messaggio pulito."""
    try:
        # Lascia passare gli errori HTTP noti tipo 404/403 senza trasformarli tutti in 500
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
    except Exception:
        pass

    scrivi_log_errore("Errore generale applicazione", e)

    try:
        flash("Si è verificato un errore interno. L'errore è stato registrato nei log admin.", "danger")
        return redirect(url_for("home"))
    except Exception:
        return "Internal Server Error - errore registrato nel log admin", 500


ADMIN_ERRORI_HTML = """
{% extends 'base.html' %}
{% block content %}

<style>
.buono-wrap-text{
    white-space: normal !important;
    word-break: break-word;
    overflow-wrap: anywhere;
}
</style>

<div class="container-fluid py-3">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h3>🧾 Log errori gestionale</h3>
        <div>
            <a href="{{ url_for('admin_scarica_log_errori') }}" class="btn btn-outline-primary btn-sm">Scarica log</a>
            <form method="POST" action="{{ url_for('admin_svuota_log_errori') }}" style="display:inline;" onsubmit="return confirm('Svuotare il log errori?');">
<button class="btn btn-outline-danger btn-sm">Svuota log</button>
            </form>
            <a href="{{ url_for('home') }}" class="btn btn-secondary btn-sm">Home</a>
        </div>
    </div>

    <div class="alert alert-info">
        Qui trovi gli errori interni salvati automaticamente. Gli ultimi errori sono in fondo al file.
    </div>

    <pre style="background:#111;color:#eee;padding:15px;border-radius:8px;white-space:pre-wrap;max-height:75vh;overflow:auto;">{{ contenuto }}</pre>
</div>



{% endblock %}
"""


@app.route("/admin/errori", methods=["GET"])
@login_required
@require_admin
def admin_errori():
    try:
        if ERROR_LOG_FILE.exists():
            contenuto = ERROR_LOG_FILE.read_text(encoding="utf-8", errors="ignore")
            # Mostra solo gli ultimi caratteri per non appesantire la pagina
            if len(contenuto) > 80000:
                contenuto = "... LOG TRONCATO: mostro solo la parte finale ...\n\n" + contenuto[-80000:]
        else:
            contenuto = "Nessun errore registrato."
    except Exception as e:
        contenuto = f"Impossibile leggere il file errori: {e}"

    return render_template_string(ADMIN_ERRORI_HTML, contenuto=contenuto)


@app.route("/admin/errori/download", methods=["GET"])
@login_required
@require_admin
def admin_scarica_log_errori():
    try:
        if not ERROR_LOG_FILE.exists():
            ERROR_LOG_FILE.write_text("Nessun errore registrato.", encoding="utf-8")
        return send_file(ERROR_LOG_FILE, as_attachment=True, download_name="errori_gestionale.log")
    except Exception as e:
        flash(f"Errore download log: {e}", "danger")
        return redirect(url_for("admin_errori"))


@app.route("/admin/errori/svuota", methods=["POST"])
@login_required
@require_admin
def admin_svuota_log_errori():
    try:
        ERROR_LOG_FILE.write_text("", encoding="utf-8")
        flash("Log errori svuotato.", "success")
    except Exception as e:
        flash(f"Errore svuotamento log: {e}", "danger")
    return redirect(url_for("admin_errori"))




@app.route("/admin/genera_codici_entrata", methods=["GET"])
@login_required
@require_admin
def admin_genera_codici_entrata():
    """Assegna un codice_entrata ai record storici che ne sono privi.

    Raggruppamento priorità:
    1) n_ddt_ingresso
    2) n_arrivo
    3) cliente + data_ingresso
    4) singola riga
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Articolo)
            .filter(or_(Articolo.codice_entrata == None, Articolo.codice_entrata == ''))
            .order_by(Articolo.id_articolo.asc())
            .all()
        )
        if not rows:
            flash("Nessuna entrata storica da aggiornare: tutti i record hanno già il codice entrata.", "info")
            return redirect(url_for('home'))

        groups = {}
        for art in rows:
            ddt = (art.n_ddt_ingresso or '').strip()
            arr = (art.n_arrivo or '').strip()
            cli = (art.cliente or '').strip()
            dt = (art.data_ingresso or '').strip()

            if ddt:
                key = f"DDT|{_norm_token(ddt)}|{dt or 'ND'}"
            elif arr:
                key = f"ARR|{_norm_token(arr)}|{dt or 'ND'}"
            elif cli or dt:
                key = f"CLI|{_norm_token(cli)}|{dt or 'ND'}"
            else:
                key = f"ROW|{art.id_articolo}"

            groups.setdefault(key, []).append(art)

        updated_rows = 0
        for arts in groups.values():
            first = arts[0]
            code = ensure_codice_entrata(
                None,
                n_arrivo=strip_arrivo_progressivo(first.n_arrivo),
                n_ddt=first.n_ddt_ingresso,
                data_ingresso=first.data_ingresso,
                cliente=first.cliente
            )
            for art in arts:
                art.codice_entrata = code
                updated_rows += 1

        db.commit()
        flash(f"Codici entrata generati per {len(groups)} gruppi storici ({updated_rows} righe aggiornate).", "success")
        return redirect(url_for('home'))
    except Exception as e:
        db.rollback()
        flash(f"Errore generazione codici entrata: {e}", "danger")
        return redirect(url_for('home'))
    finally:
        db.close()

def current_cliente():
    """Cliente associato all'utente corrente (per i client è bloccato)."""
    if session.get('role') == 'client':
        return (current_user.id or '').strip()
    return None

def get_users():
    """Legge utenti dal file storico/default + utenti creati dal pannello admin."""
    users = dict(DEFAULT_USERS)

    try:
        fp = APP_DIR / "password Utenti Gestionale.txt"
        if fp.exists():
            content = fp.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(r"'([^']+)'\s*[:=]\s*'?([^']+)'?", content)
            if pairs:
                users.update({k.strip().upper(): v.strip().replace("'", "") for k, v in pairs})
    except Exception as e:
        print(f"Errore lettura file utenti: {e}")

    try:
        managed_file = MEDIA_DIR / "utenti_gestionale.json"
        if managed_file.exists():
            data = json.loads(managed_file.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                for username, rec in data.items():
                    u = (username or "").strip().upper()
                    if not u:
                        continue
                    if isinstance(rec, dict):
                        if rec.get("active", True):
                            users[u] = rec.get("password", "")
                    else:
                        users[u] = str(rec or "")
    except Exception as e:
        print(f"Errore lettura utenti_gestionale.json: {e}")

    return users

# ORA possiamo chiamarla, perché è stata definita sopra
USERS_DB = get_users()

def get_clienti_utenti():
    """Elenco clienti validi ricavati dagli utenti, escludendo gli utenti admin/tecnici."""
    utenti = get_users() or {}
    out = []
    seen = set()
    for nome in utenti.keys():
        n = (nome or '').strip()
        if not n:
            continue
        up = n.upper()
        if up in ADMIN_USERS or up in WAREHOUSE_USERS:
            continue
        norm = normalize_text_key(n)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(up)
    return sorted(out)


def canonical_cliente_from_users(value, allow_blank=False):
    raw = (value or '').strip()
    if not raw:
        return '' if allow_blank else None
    norm = normalize_text_key(raw)
    if not norm:
        return '' if allow_blank else None
    for cliente in get_clienti_utenti():
        if normalize_text_key(cliente) == norm:
            return cliente
    return None


def validate_cliente_or_raise(value, allow_blank=False):
    canonical = canonical_cliente_from_users(value, allow_blank=allow_blank)
    if canonical is None:
        validi = ', '.join(get_clienti_utenti())
        raise ValueError(f"Cliente non valido. Seleziona un cliente presente negli utenti: {validi}")
    return canonical


def _is_werkzeug_hash(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    return s.startswith('pbkdf2:') or s.startswith('scrypt:') or s.startswith('argon2:')


def verify_password(stored: str, provided: str) -> bool:
    # Supporta sia password legacy in chiaro sia hash werkzeug.
    if stored is None:
        return False
    stored = str(stored).strip()
    provided = (provided or '').strip()
    if not stored or not provided:
        return False
    if _is_werkzeug_hash(stored):
        try:
            return check_password_hash(stored, provided)
        except Exception:
            return False
    return stored == provided


class User(UserMixin):
    def __init__(self, id, role):
        self.id = id; self.role = role

@login_manager.user_loader
def load_user(user_id):
    user_id = (user_id or '').strip().upper()
    users_db = get_users()
    if user_id in users_db:
        role = None
        try:
            managed_file = MEDIA_DIR / "utenti_gestionale.json"
            if managed_file.exists():
                data = json.loads(managed_file.read_text(encoding="utf-8", errors="ignore"))
                rec = data.get(user_id)
                if isinstance(rec, dict):
                    if not rec.get("active", True):
                        return None
                    role = rec.get("role")
        except Exception:
            role = None

        if role not in ('admin', 'magazzino', 'client'):
            if user_id in ADMIN_USERS:
                role = 'admin'
            elif user_id in WAREHOUSE_USERS:
                role = 'magazzino'
            else:
                role = 'client'
        return User(user_id, role)
    return None

# --- UTILS ---


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

def _destinatari_path() -> Path:
    return (MEDIA_DIR / "destinatari_saved.json") if 'MEDIA_DIR' in globals() else (APP_DIR / "destinatari_saved.json")


def _destinatari_fallback_paths():
    paths = []
    try:
        paths.append(MEDIA_DIR / "destinatari_saved.json")
    except Exception:
        pass
    try:
        paths.append(APP_DIR / "destinatari_saved.json")
        paths.append(APP_DIR / "config" / "destinatari_saved.json")
    except Exception:
        pass
    out, seen = [], set()
    for p in paths:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def save_destinatari(data: dict):
    fp = _destinatari_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    tmp.replace(fp)
    try:
        local_fp = APP_DIR / "destinatari_saved.json"
        if local_fp != fp:
            local_fp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    except Exception:
        pass


def load_destinatari():
    DESTINATARI_JSON = _destinatari_path()
    data = {}
    for candidate in _destinatari_fallback_paths():
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8")
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
                if candidate != DESTINATARI_JSON:
                    try:
                        save_destinatari(data)
                    except Exception:
                        pass
                break
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

# ========================================================
#  RUBRICA EMAIL (contatti + gruppi)
#  File: rubrica_email.json (su disco persistente se presente)
# ========================================================


def _split_email_list(raw):
    """Divide una stringa di email separate da ; , spazio o a capo."""
    out = []
    for x in re.split(r"[;,\n\r ]+", raw or ""):
        x = (x or "").strip()
        if x and "@" in x and x not in out:
            out.append(x)
    return out

def _destinatari_con_temporanei(destinatari_base, form=None):
    """Unisce destinatari normali e destinatari temporanei senza salvarli."""
    base = []
    if isinstance(destinatari_base, (list, tuple, set)):
        for d in destinatari_base:
            base.extend(_split_email_list(str(d or "")))
    else:
        base.extend(_split_email_list(str(destinatari_base or "")))

    form = form or request.form
    temp_raw = ""
    for key in ("destinatari_temp", "destinatari_extra", "email_temp", "email_extra", "altri_destinatari"):
        try:
            val = (form.get(key) or "").strip()
        except Exception:
            val = ""
        if val:
            temp_raw += ";" + val

    for d in _split_email_list(temp_raw):
        if d not in base:
            base.append(d)
    return base


def _rubrica_email_path() -> Path:
    # Su Render MEDIA_DIR punta a /var/data/app (persistente) se esiste.
    # Preferiamo sempre il disco persistente, così gli indirizzi non spariscono ai deploy.
    return (MEDIA_DIR / "rubrica_email.json") if 'MEDIA_DIR' in globals() else (APP_DIR / "rubrica_email.json")


def _rubrica_email_fallback_paths():
    paths = []
    try:
        paths.append(MEDIA_DIR / "rubrica_email.json")
    except Exception:
        pass
    try:
        paths.append(APP_DIR / "rubrica_email.json")
        paths.append(APP_DIR / "config" / "rubrica_email.json")
    except Exception:
        pass
    out, seen = [], set()
    for p in paths:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out

def load_rubrica_email():
    fp = _rubrica_email_path()

    def _normalizza_rubrica(data):
        """Rende la rubrica compatibile con vecchi e nuovi formati.
        Formato nuovo:
            {"contatti": {"Nome": {"email": "a@b.it"}}, "gruppi": {"Gruppo": ["a@b.it"]}}
        Accetta anche vecchi formati con contatti come stringhe o liste.
        """
        if not isinstance(data, dict):
            data = {}
        data.setdefault("contatti", {})
        data.setdefault("gruppi", {})

        contatti_norm = {}
        raw_contatti = data.get("contatti", {}) or {}

        if isinstance(raw_contatti, dict):
            for nome, info in raw_contatti.items():
                nome = (str(nome) or '').strip()
                if not nome:
                    continue
                if isinstance(info, dict):
                    email = (info.get('email') or info.get('mail') or info.get('indirizzo') or '').strip()
                else:
                    email = str(info or '').strip()
                if email:
                    contatti_norm[nome] = {"email": email}
        elif isinstance(raw_contatti, list):
            for item in raw_contatti:
                if isinstance(item, dict):
                    nome = (item.get('nome') or item.get('name') or item.get('ragione_sociale') or item.get('email') or '').strip()
                    email = (item.get('email') or item.get('mail') or '').strip()
                    if nome and email:
                        contatti_norm[nome] = {"email": email}

        gruppi_norm = {}
        raw_gruppi = data.get("gruppi", {}) or {}
        if isinstance(raw_gruppi, dict):
            for gruppo, emails in raw_gruppi.items():
                gruppo = (str(gruppo) or '').strip()
                if not gruppo:
                    continue
                if isinstance(emails, str):
                    gruppi_norm[gruppo] = _parse_emails(emails)
                elif isinstance(emails, list):
                    tmp = []
                    for e in emails:
                        if isinstance(e, dict):
                            val = (e.get('email') or e.get('mail') or '').strip()
                        else:
                            val = str(e or '').strip()
                        # se nel gruppo è stato salvato il NOME del contatto, lo trasformo in email
                        if val in contatti_norm:
                            val = contatti_norm[val].get('email', val)
                        if val:
                            tmp.extend(_parse_emails(val))
                    # de-dup
                    seen = set(); out = []
                    for e in tmp:
                        if e.lower() not in seen:
                            seen.add(e.lower()); out.append(e)
                    gruppi_norm[gruppo] = out

        return {"contatti": contatti_norm, "gruppi": gruppi_norm}

    # Prova prima il file persistente, poi eventuali vecchie posizioni.
    for candidate in _rubrica_email_fallback_paths():
        if candidate.exists():
            try:
                data_norm = _normalizza_rubrica(json.loads(candidate.read_text(encoding="utf-8")))
                # Se ho letto da una vecchia posizione, salvo anche sul persistente.
                if candidate != fp:
                    try:
                        save_rubrica_email(data_norm)
                    except Exception:
                        pass
                return data_norm
            except Exception:
                pass
    return {"contatti": {}, "gruppi": {}}

def save_rubrica_email(data: dict):
    fp = _rubrica_email_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(fp)
    # Copia di cortesia locale: utile in sviluppo e per backup/diagnosi.
    try:
        local_fp = APP_DIR / "rubrica_email.json"
        if local_fp != fp:
            local_fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _parse_emails(raw: str):
    # accetta ; oppure , e ripulisce
    emails = []
    for e in (raw or "").replace(";", ",").split(","):
        e = e.strip()
        if e:
            emails.append(e)
    # de-dup preservando ordine
    seen = set()
    out = []
    for e in emails:
        if e.lower() in seen: 
            continue
        seen.add(e.lower())
        out.append(e)
    return out

def _ensure_progressivi_ddt_table(db):
    """Crea (se necessario) la tabella progressivi_ddt nel DB.
    Usiamo il DB invece di un file JSON così il progressivo resta memorizzato anche su server (Render/VPS).
    """
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS progressivi_ddt (
                anno VARCHAR(4) PRIMARY KEY,
                last_num INTEGER NOT NULL
            )
        """))
        db.commit()
    except Exception:
        # su alcuni DB/permessi, può fallire ma non blocchiamo l'app
        try:
            db.rollback()
        except Exception:
            pass

def peek_next_ddt_number():
    """Restituisce il prossimo progressivo SENZA incrementarlo (anteprima)."""
    y = str(date.today().year)[-2:]
    # 1) prova DB
    try:
        db = SessionLocal()
        try:
            _ensure_progressivi_ddt_table(db)
            row = db.execute(text("SELECT last_num FROM progressivi_ddt WHERE anno=:y"), {"y": y}).fetchone()
            last_num = int(row[0]) if row and row[0] is not None else 0
            n = last_num + 1
            return f"{n:02d}/{y}"
        finally:
            db.close()
    except Exception:
        pass

    # 2) fallback file (compatibilità)
    PROG_FILE = APP_DIR / "progressivi_ddt.json"
    prog = {}
    if PROG_FILE.exists():
        try:
            prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
    n = int(prog.get(y, 0)) + 1
    return f"{n:02d}/{y}"

def next_ddt_number():
    """Incrementa e memorizza il progressivo (solo in Finalizza)."""
    y = str(date.today().year)[-2:]

    # 1) DB (preferito)
    try:
        db = SessionLocal()
        try:
            _ensure_progressivi_ddt_table(db)

            dialect = getattr(engine.dialect, "name", "")
            if dialect and dialect.lower().startswith("mysql"):
                # lock riga anno per evitare doppioni
                row = db.execute(
                    text("SELECT last_num FROM progressivi_ddt WHERE anno=:y FOR UPDATE"),
                    {"y": y}
                ).fetchone()
            else:
                row = db.execute(
                    text("SELECT last_num FROM progressivi_ddt WHERE anno=:y"),
                    {"y": y}
                ).fetchone()

            last_num = int(row[0]) if row and row[0] is not None else 0
            n = last_num + 1

            if row:
                db.execute(
                    text("UPDATE progressivi_ddt SET last_num=:n WHERE anno=:y"),
                    {"n": n, "y": y}
                )
            else:
                db.execute(
                    text("INSERT INTO progressivi_ddt (anno, last_num) VALUES (:y, :n)"),
                    {"y": y, "n": n}
                )

            db.commit()
            return f"{n:02d}/{y}"
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        # 2) fallback file (compatibilità)
        PROG_FILE = APP_DIR / "progressivi_ddt.json"
        prog = {}
        if PROG_FILE.exists():
            try:
                prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
            except Exception:
                prog = {}
        n = int(prog.get(y, 0)) + 1
        prog[y] = n
        try:
            PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return f"{n:02d}/{y}"




def consume_specific_ddt_number(n_ddt: str) -> None:
    """
    Aggiorna il progressivo salvato (tabella progressivi_ddt o file json) per evitare
    che un numero scelto manualmente (con le frecce) venga riutilizzato in futuro.

    - NON cambia il valore del DDT passato.
    - Aggiorna last_num = max(last_num, numero_scelto) per l'anno del DDT.
    """
    if not n_ddt:
        return
    n_ddt = str(n_ddt).strip()

    m = re.match(r'^(\d+)\s*/\s*(\d{2})$', n_ddt)
    if not m:
        return

    try:
        chosen_num = int(m.group(1))
        chosen_year = m.group(2)
    except Exception:
        return

    if chosen_num < 1:
        return

    # 1) DB (preferito)
    try:
        db = SessionLocal()
        try:
            _ensure_progressivi_ddt_table(db)
            row = db.execute(text("SELECT last_num FROM progressivi_ddt WHERE anno=:y"), {"y": chosen_year}).fetchone()
            last_num = int(row[0]) if row and row[0] is not None else 0
            new_last = max(last_num, chosen_num)

            if row:
                db.execute(
                    text("UPDATE progressivi_ddt SET last_num=:n WHERE anno=:y"),
                    {"n": new_last, "y": chosen_year}
                )
            else:
                db.execute(
                    text("INSERT INTO progressivi_ddt (anno, last_num) VALUES (:y, :n)"),
                    {"y": chosen_year, "n": new_last}
                )
            db.commit()
            return
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        pass

    # 2) fallback file (compatibilità)
    try:
        PROG_FILE = APP_DIR / "progressivi_ddt.json"
        prog = {}
        if PROG_FILE.exists():
            try:
                prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
            except Exception:
                prog = {}
        last_num = int(prog.get(chosen_year, 0) or 0)
        prog[chosen_year] = max(last_num, chosen_num)
        PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# --- SEZIONE TEMPLATES HTML ---
BASE_HTML = """
<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "Camar - Gestionale Web" }}</title>
    <link rel="manifest" href="/manifest.webmanifest">
    <meta name="theme-color" content="#1f6fb2">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="Gestionale Camar">
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
    <script src="https://unpkg.com/html5-qrcode"></script>

<style>
/* Pulsanti Magazzino più compatti */
.magazzino-actions .btn,
.toolbar-magazzino .btn,
.table-actions .btn,
.btn-sm,
button.btn,
a.btn {
    padding: 4px 8px !important;
    font-size: 12px !important;
    line-height: 1.2 !important;
    border-radius: 5px !important;
}

.magazzino-actions,
.toolbar-magazzino,
.table-actions {
    gap: 4px !important;
}

.btn-lg {
    padding: 6px 10px !important;
    font-size: 13px !important;
}

input.form-control-sm {
    height: 30px !important;
    font-size: 12px !important;
}
</style>


<style>
/* --- Pulsanti più lineari e compatti --- */
.btn,
button.btn,
a.btn {
    padding: 5px 9px !important;
    font-size: 12px !important;
    line-height: 1.25 !important;
    border-radius: 5px !important;
    min-height: 30px !important;
    height: auto !important;
    white-space: nowrap !important;
}

.btn-sm {
    padding: 4px 8px !important;
    font-size: 12px !important;
    min-height: 28px !important;
}

.btn-lg {
    padding: 6px 10px !important;
    font-size: 13px !important;
    min-height: 32px !important;
}

/* Bottoni principali magazzino: stessa altezza, senza blocchi enormi */
.mag-btn-compact,
.magazzino-actions .btn,
.toolbar-magazzino .btn,
.table-actions .btn {
    padding: 5px 9px !important;
    font-size: 12px !important;
    min-height: 30px !important;
    line-height: 1.25 !important;
}

/* Box aggiunta buono più ordinato */
.add-buono-box {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    padding: 5px 7px;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    background: #f8f9fa;
    margin: 6px 0;
}

.add-buono-box input {
    width: 145px !important;
    height: 29px !important;
    font-size: 12px !important;
    padding: 3px 6px !important;
}

.add-buono-box .small {
    font-size: 11px !important;
}
</style>


<style>
/* --- correzione finale bottoni testata magazzino --- */
.top-magazzino-actions{
    align-items:center !important;
    gap:6px !important;
}
.top-magazzino-actions .btn,
.top-magazzino-actions a.btn,
.top-magazzino-actions button.btn{
    padding:4px 8px !important;
    font-size:12px !important;
    line-height:1.2 !important;
    min-height:28px !important;
    height:28px !important;
    display:inline-flex !important;
    align-items:center !important;
    justify-content:center !important;
    border-radius:5px !important;
    white-space:nowrap !important;
}
.top-magazzino-actions form{
    margin:0 !important;
    display:inline-flex !important;
    align-items:center !important;
}
.top-magazzino-actions .input-group-sm .form-control,
.top-magazzino-actions .input-group-sm .input-group-text{
    height:28px !important;
    padding:3px 6px !important;
    font-size:12px !important;
}
.add-buono-box{
    display:flex !important;
    align-items:center !important;
    gap:6px !important;
    flex-wrap:wrap !important;
    padding:5px 7px !important;
    border:1px solid #d0d7de !important;
    border-radius:6px !important;
    background:#f8f9fa !important;
    margin:6px 0 !important;
}
.add-buono-box input{
    width:145px !important;
    height:28px !important;
    font-size:12px !important;
    padding:3px 6px !important;
}
.add-buono-box .btn{
    height:28px !important;
    min-height:28px !important;
    padding:4px 8px !important;
}
</style>

</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark shadow-sm no-print">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center gap-2" href="{{ url_for('home') }}">
            {% if logo_url %}<img src="{{ logo_url }}" class="logo" alt="logo">{% endif %}
            Camar - Gestionale
        </a>

        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>

        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav ms-auto align-items-center gap-2">
                
                <li class="nav-item"><a class="nav-link" href="{{ url_for('giacenze') }}">📦 Magazzino</a>
{% if can_use_buoni_qr() %}
<a class="btn btn-primary btn-sm" href="{{ url_for('buoni_carico') }}">🧾 Buoni Carico</a>
{% endif %}</li>
                {% if session.get('role') == 'admin' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('accettazione_entrata') }}">📄 Entrata</a></li>{% endif %}
                <li class="nav-item"><a class="nav-link" href="{{ url_for('chatbot') }}">🤖 Chat</a></li>
                <li class="nav-item"><a class="nav-link" href="{{ url_for('camy_ai') }}">🧠 CAMY AI</a></li>
                {% if session.get('role') == 'admin' %}
                <li class="nav-item"><a class="nav-link" href="{{ url_for('import_excel') }}">📥 Import Excel</a></li>
                {% endif %}

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
                        <a class="nav-link btn btn-outline-light text-white px-3 ms-2 btn-nav-admin" href="{{ url_for('rubrica_email') }}">
                            <i class="bi bi-journal-bookmark"></i> RUBRICA EMAIL
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link btn btn-outline-warning text-dark px-3 ms-2 btn-nav-admin" href="{{ url_for('backup_download') }}">
                            <i class="bi bi-download"></i> BACKUP
                        </a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link btn btn-outline-info text-white px-3 ms-2 btn-nav-admin" href="{{ url_for('report_fatturazione') }}">
                            <i class="bi bi-bar-chart-line"></i> FATTURAZIONE
                        </a>
                    </li>

                    <li class="nav-item">
                        <a class="nav-link btn btn-warning text-dark px-3 ms-2 btn-nav-admin" href="/admin/utenti">
                            <i class="bi bi-people-fill"></i> UTENTI
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
<head>
  <title>Inventario Totale - {{ data_rif }}</title>
  <meta charset="utf-8">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    @media print {
      .pagebreak { page-break-after: always; }
    }
    table { font-size: 12px; }
    h1 { font-size: 26px; margin-bottom: 10px; }
    h3 { font-size: 18px; }
    .thead-custom th { background: #d9e1f2 !important; }
  </style>
</head>

<body onload="window.print()">
  <div class="container mt-4">
    <h1 class="text-center">Inventario Totale</h1>
    <div class="text-center text-muted" style="margin-top:-6px;">
      Generato il {{ data_rif }}
    </div>
    <hr>

    {% if not inventario or inventario|length == 0 %}
      <div class="alert alert-warning">
        Nessun articolo trovato.
      </div>
    {% endif %}

    {% for cliente, righe in inventario.items() %}
      <h3 class="mt-4 bg-light p-2">{{ cliente }}</h3>

      <table class="table table-sm table-bordered">
        <thead class="thead-custom">
          <tr>
            <th style="width:60px;">ID</th>
            <th style="width:220px;">CODICE ARTICOLO</th>
            <th>DESCRIZIONE</th>
            <th class="text-center" style="width:130px;">Q.TA ENTRATA</th>
            <th class="text-center" style="width:130px;">Q.TA USCITA</th>
            <th class="text-center" style="width:130px;">RIMANENZA</th>
          </tr>
        </thead>
        <tbody>
          {% for r in righe %}
          <tr>
            <td class="text-center">{{ r.idx }}</td>
            <td>{{ r.codice }}</td>
            <td>{{ r.descrizione }}</td>
            <td class="text-center">{{ r.entrata }}</td>
            <td class="text-center">{{ r.uscita }}</td>
            <td class="text-center">{{ r.rimanenza }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <div class="pagebreak"></div>
    {% endfor %}
  </div>
</body>
</html>
"""


REPORT_TRASPORTI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Report Trasporti</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { font-size: 12px; }
        h1 { font-size: 22px; }
        .table th { background-color: #f0f0f0; }
        .wrap { white-space: normal; }
    </style>
</head>
<body onload="window.print()">
    <div class="container mt-4">
        <h1 class="mb-3">Report Trasporti</h1>

        <div class="mb-3 p-2 bg-light border">
            <strong>Filtri applicati:</strong><br>
            Periodo: {{ mese }} |
            Cliente: {{ cliente }} |
            Mezzo: {{ mezzo }} |
            DDT: {{ ddt_uscita }} |
            Consolidato: {{ consolidato }}
        </div>

        <table class="table table-bordered table-sm align-middle">
            <thead>
                <tr>
                    <th>Data</th>
                    <th>Mezzo</th>
                    <th>Cliente</th>
                    <th>Trasportatore</th>
                    <th>DDT</th>
                    <th>Mag.</th>
                    <th>Consolidato</th>
                    <th class="text-end">Costo</th>
                </tr>
            </thead>
            <tbody>
                {% for t in dati %}
                <tr>
                    <td>{{ t.data or '' }}</td>
                    <td>{{ t.tipo_mezzo or '' }}</td>
                    <td class="wrap">{{ t.cliente or '' }}</td>
                    <td class="wrap">{{ t.trasportatore or '' }}</td>
                    <td>{{ t.ddt_uscita or '' }}</td>
                    <td>{{ t.magazzino or '' }}</td>
                    <td>{{ t.consolidato or '' }}</td>
                    <td class="text-end">€ {{ '%.2f'|format(t.costo) if t.costo else '0.00' }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="8" class="text-center">Nessun dato trovato per i criteri selezionati.</td>
                </tr>
                {% endfor %}
            </tbody>
            <tfoot>
                <tr class="table-dark fw-bold">
                    <td colspan="7" class="text-end">TOTALE COMPLESSIVO</td>
                    <td class="text-end">€ {{ totale }}</td>
                </tr>
            </tfoot>
        </table>

        <div class="text-muted small mt-4">
            Generato il: <script>document.write(new Date().toLocaleDateString())</script>
        </div>
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
<style>
.home-kpi-card{
    border:0;
    border-radius:16px;
    box-shadow:0 4px 14px rgba(0,0,0,.07);
    height:100%;
}
.home-kpi-icon{
    width:42px;
    height:42px;
    border-radius:12px;
    display:flex;
    align-items:center;
    justify-content:center;
    background:#eef5ff;
    color:#0d6efd;
    font-size:20px;
}
.home-kpi-value{
    font-size:26px;
    font-weight:700;
    line-height:1.1;
}
.home-section-card{
    border:0;
    border-radius:16px;
    box-shadow:0 4px 14px rgba(0,0,0,.07);
}
.home-movement-table td,
.home-movement-table th{
    vertical-align:middle;
    font-size:13px;
}

.home-alert-card{
    border:0;
    border-radius:16px;
    box-shadow:0 4px 14px rgba(0,0,0,.07);
}
.home-alert-item{
    border-left:5px solid #ffc107;
    background:#fff8e1;
    border-radius:10px;
    padding:10px 12px;
    margin-bottom:8px;
}
.home-alert-item.danger{
    border-left-color:#dc3545;
    background:#fff1f1;
}
.home-alert-item.warning{
    border-left-color:#ffc107;
    background:#fff8e1;
}
.home-alert-item.info{
    border-left-color:#0d6efd;
    background:#eef5ff;
}
.home-client-table th,
.home-client-table td{
    font-size:13px;
    vertical-align:middle;
}
.home-client-table tfoot td{
    font-weight:700;
    background:#f8f9fa;
}
</style>

<div class="container-fluid py-3">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <div class="d-flex align-items-center gap-3">
            {% if logo_url %}<img src="{{ logo_url }}" style="height:50px;width:auto;">{% endif %}
            <div>
                <h3 class="m-0">Dashboard Gestionale</h3>
                <div class="text-muted small">Riepilogo operativo aggiornato al {{ today.strftime('%d/%m/%Y') if today else '' }}</div>
            </div>
        </div>
        <div class="d-flex flex-wrap gap-2">
            <a class="btn btn-primary btn-sm" href="{{ url_for('giacenze') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Giacenze</a>
            {% if session.get('role') == 'admin' %}
            <a class="btn btn-success btn-sm" href="{{ url_for('nuovo_articolo') }}"><i class="bi bi-plus-circle"></i> Nuovo articolo</a>
            {% endif %}
            {% if can_use_buoni_qr() %}
            <a class="btn btn-outline-primary btn-sm" href="{{ url_for('scan_entrata') }}"><i class="bi bi-upc-scan"></i> Scan entrata</a>
            {% endif %}
        </div>
    </div>

    <div class="row g-3 mb-3">
        <div class="col-md-6 col-xl-3">
            <div class="card home-kpi-card p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="text-muted small">Articoli in giacenza</div>
                        <div class="home-kpi-value">{{ dashboard.tot_giacenza }}</div>
                    </div>
                    <div class="home-kpi-icon"><i class="bi bi-box-seam"></i></div>
                </div>
            </div>
        </div>
        <div class="col-md-6 col-xl-3">
            <div class="card home-kpi-card p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="text-muted small">M² occupati</div>
                        <div class="home-kpi-value">{{ dashboard.tot_m2|it_num(2) }}</div>
                    </div>
                    <div class="home-kpi-icon"><i class="bi bi-rulers"></i></div>
                </div>
            </div>
        </div>
        <div class="col-md-6 col-xl-3">
            <div class="card home-kpi-card p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="text-muted small">Entrate oggi</div>
                        <div class="home-kpi-value">{{ dashboard.entrate_oggi }}</div>
                    </div>
                    <div class="home-kpi-icon"><i class="bi bi-arrow-down-circle"></i></div>
                </div>
            </div>
        </div>
        <div class="col-md-6 col-xl-3">
            <div class="card home-kpi-card p-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="text-muted small">Uscite oggi</div>
                        <div class="home-kpi-value">{{ dashboard.uscite_oggi }}</div>
                    </div>
                    <div class="home-kpi-icon"><i class="bi bi-arrow-up-circle"></i></div>
                </div>
            </div>
        </div>
    </div>

    <div class="row g-3 mb-3">
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Articoli doganali</div>
                <div class="home-kpi-value">{{ dashboard.doganali }}</div>
            </div>
        </div>
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Buoni QR aperti</div>
                <div class="home-kpi-value">{{ dashboard.buoni_aperti }}</div>
            </div>
        </div>
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Buoni creati</div>
                <div class="home-kpi-value">{{ dashboard.buoni_creati }}</div>
            </div>
        </div>
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Buoni usciti</div>
                <div class="home-kpi-value">{{ dashboard.buoni_usciti }}</div>
            </div>
        </div>
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Peso in giacenza</div>
                <div class="home-kpi-value">{{ dashboard.tot_peso|it_num(2) }}</div>
            </div>
        </div>
        <div class="col-md-6 col-xl-2">
            <div class="card home-kpi-card p-3">
                <div class="text-muted small">Colli in giacenza</div>
                <div class="home-kpi-value">{{ dashboard.tot_colli }}</div>
            </div>
        </div>
    </div>

    {% if dashboard_alerts %}
    <div class="card home-alert-card p-3 mb-3">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
            <h5 class="m-0"><i class="bi bi-bell-fill text-warning"></i> Alert automatici</h5>
            <span class="badge bg-warning text-dark">{{ dashboard_alerts|length }} segnalazioni</span>
        </div>
        <div class="row g-2">
            {% for alert in dashboard_alerts %}
            <div class="col-lg-6 col-xxl-4">
                <div class="home-alert-item {{ alert.level }}">
                    <div class="d-flex justify-content-between gap-2">
                        <strong>{{ alert.title }}</strong>
                        <span class="badge {% if alert.level == 'danger' %}bg-danger{% elif alert.level == 'warning' %}bg-warning text-dark{% else %}bg-primary{% endif %}">{{ alert.count }}</span>
                    </div>
                    <div class="small text-muted mt-1">{{ alert.message }}</div>
                    {% if alert.examples %}
                    <div class="small mt-1"><strong>Esempi:</strong> {{ alert.examples|join(', ') }}</div>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <div class="card home-section-card p-3 mb-3">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
            <h5 class="m-0"><i class="bi bi-people-fill text-primary"></i> Giacenza per cliente</h5>
            <span class="badge bg-primary">{{ dashboard_clienti|length }} clienti</span>
        </div>
        <div class="table-responsive">
            <table class="table table-sm table-striped home-client-table mb-0">
                <thead>
                    <tr>
                        <th>Cliente</th>
                        <th class="text-end">Righe</th>
                        <th class="text-end">Colli</th>
                        <th class="text-end">M²</th>
                        <th class="text-end">Peso kg</th>
                        <th class="text-end">Buoni aperti</th>
                        <th class="text-end">Buoni creati</th>
                        <th class="text-end">Buoni usciti</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in dashboard_clienti %}
                    <tr>
                        <td>{{ r.cliente }}</td>
                        <td class="text-end">{{ r.righe }}</td>
                        <td class="text-end">{{ r.colli }}</td>
                        <td class="text-end">{{ r.m2|it_num(2) }}</td>
                        <td class="text-end">{{ r.peso|it_num(2) }}</td>
                        <td class="text-end">{{ r.buoni_aperti }}</td>
                        <td class="text-end">{{ r.buoni_creati }}</td>
                        <td class="text-end">{{ r.buoni_usciti }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="8" class="text-muted text-center py-3">Nessuna giacenza attiva.</td></tr>
                    {% endfor %}
                </tbody>
                <tfoot>
                    <tr>
                        <td>Totale</td>
                        <td class="text-end">{{ dashboard.tot_giacenza }}</td>
                        <td class="text-end">{{ dashboard.tot_colli }}</td>
                        <td class="text-end">{{ dashboard.tot_m2|it_num(2) }}</td>
                        <td class="text-end">{{ dashboard.tot_peso|it_num(2) }}</td>
                        <td class="text-end">{{ dashboard.buoni_aperti }}</td>
                        <td class="text-end">{{ dashboard.buoni_creati }}</td>
                        <td class="text-end">{{ dashboard.buoni_usciti }}</td>
                    </tr>
                </tfoot>
            </table>
        </div>
        <div class="text-muted small mt-2">
            I colli sono calcolati solo sulle righe ancora in giacenza. Se un articolo ha colli vuoti o pari a 0, viene conteggiato come 0.
        </div>
    </div>

    <div class="row g-3">
        <div class="col-xl-3">
            <div class="card home-section-card p-3 mb-3">
                <h6 class="mb-3">Menu rapido</h6>
                <div class="d-grid gap-2">
                    <a class="btn btn-primary" href="{{ url_for('giacenze') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Visualizza Giacenze</a>
                    {% if session.get('role') == 'admin' %}
                    <a class="btn btn-success" href="{{ url_for('nuovo_articolo') }}"><i class="bi bi-plus-circle"></i> Nuovo Articolo</a>
                    <a class="btn btn-outline-secondary" href="{{ url_for('labels_form') }}"><i class="bi bi-tag"></i> Stampa Etichette</a>
                    <a class="btn btn-outline-primary" href="{{ url_for('accettazione_entrata') }}"><i class="bi bi-file-earmark-text"></i> Accettazione Entrata</a>
                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('import_excel') }}"><i class="bi bi-file-earmark-arrow-up"></i> Import Excel</a>
                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('export_excel') }}"><i class="bi bi-file-earmark-arrow-down"></i> Export Excel Totale</a>
                    {% endif %}
                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('export_client') }}"><i class="bi bi-people"></i> Export per Cliente</a>
                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('calcola_costi') }}"><i class="bi bi-calculator"></i> Calcola Giacenze Mensili</a>
                    {% if can_use_buoni_qr() %}
                    <a class="btn btn-outline-primary btn-sm" href="{{ url_for('scan_entrata') }}"><i class="bi bi-upc-scan"></i> Scan / Ricerca Entrata</a>
                    {% endif %}
                </div>
            </div>

            <div class="card home-section-card p-3">
                <h6 class="mb-2"><i class="bi bi-upc-scan"></i> Ricerca veloce entrata</h6>
                <form action="{{ url_for('go_scan_entrata') }}" method="post" class="d-flex gap-2">
                    <input name="codice_entrata" class="form-control" placeholder="Scansiona o incolla codice..." autocomplete="off">
                    <button class="btn btn-primary">Apri</button>
                </form>
            </div>
        </div>

        <div class="col-xl-9">
            <div class="card home-section-card p-3">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="m-0">Ultimi movimenti</h5>
                    <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm">Apri giacenze</a>
                </div>
                <div class="table-responsive">
                    <table class="table table-sm table-striped home-movement-table">
                        <thead>
                            <tr>
                                <th>Data</th>
                                <th>Tipo</th>
                                <th>Cliente</th>
                                <th>Codice</th>
                                <th>Descrizione</th>
                                <th>N. Arrivo</th>
                                <th>DDT</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for m in ultimi_movimenti %}
                            <tr>
                                <td>{{ m.data }}</td>
                                <td>
                                    {% if m.tipo == 'Entrata' %}
                                    <span class="badge bg-success">Entrata</span>
                                    {% else %}
                                    <span class="badge bg-danger">Uscita</span>
                                    {% endif %}
                                </td>
                                <td>{{ m.cliente }}</td>
                                <td>{{ m.codice }}</td>
                                <td>{{ m.descrizione }}</td>
                                <td>{{ m.n_arrivo }}</td>
                                <td>{{ m.ddt }}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="7" class="text-muted text-center py-3">Nessun movimento recente.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""
SCAN_ENTRATA_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-lg-7">
        <div class="card p-4">
            <h4 class="mb-3"><i class="bi bi-upc-scan"></i> Scan / Ricerca Entrata</h4>
            <p class="text-muted">Scansiona il barcode/QR dell'entrata oppure inserisci manualmente il codice entrata.</p>
            <form method="post" action="{{ url_for('go_scan_entrata') }}" class="d-grid gap-3">
                <input id="codiceEntrataInput" name="codice_entrata" class="form-control form-control-lg" placeholder="Es. ENT-20260407-ABC123" autofocus>
                <div class="d-flex gap-2 flex-wrap">
                    <button class="btn btn-primary"><i class="bi bi-search"></i> Apri dettaglio</button>
                    <a href="{{ url_for('home') }}" class="btn btn-outline-secondary">Home</a>
                </div>
            </form>
            <div class="alert alert-info mt-3 mb-0">
                Da smartphone puoi aprire direttamente il QR dell'etichetta.
            </div>
        </div>
    </div>
</div>
<script>
  window.addEventListener('load', function(){
    var el = document.getElementById('codiceEntrataInput');
    if (el) { el.focus(); }
  });
</script>
{% endblock %}
"""

DETTAGLIO_ENTRATA_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <div>
        <h4 class="mb-0"><i class="bi bi-qr-code-scan"></i> Dettaglio Entrata</h4>
        <div class="text-muted">Codice entrata: <strong>{{ codice_entrata }}</strong></div>
    </div>
    <div class="d-flex gap-2 flex-wrap">
        {% if can_use_buoni_qr() %}
<a href="{{ url_for('scan_entrata') }}" class="btn btn-outline-primary btn-sm"><i class="bi bi-upc-scan"></i> Nuova scansione</a>
{% endif %}
        <a href="{{ url_for('giacenze', codice_entrata=codice_entrata) }}" class="btn btn-outline-secondary btn-sm">Vedi in giacenze</a>
        {% if session.get('role') == 'admin' %}
        <a href="{{ url_for('invia_email') }}?selected_ids={{ ids_csv }}" class="btn btn-success btn-sm"><i class="bi bi-envelope"></i> Email</a>
        <form action="{{ url_for('labels_pdf') }}" method="post" target="_blank" class="d-inline">
            {% for r in rows %}<input type="hidden" name="ids" value="{{ r.id_articolo }}">{% endfor %}
            <button class="btn btn-warning btn-sm"><i class="bi bi-tag"></i> Etichetta</button>
        </form>
        <a href="{{ url_for('verifica_entrata', codice_entrata=codice_entrata) }}" class="btn btn-outline-info btn-sm"><i class="bi bi-search"></i> Verifica Entrata</a>
        {% if anomalies %}
        <form action="{{ url_for('correggi_entrata', codice_entrata=codice_entrata) }}" method="post" class="d-inline" onsubmit="return confirm('Correggere l\'entrata ricalcolando barcode e QR delle righe anomale?')">
            <button class="btn btn-danger btn-sm"><i class="bi bi-wrench-adjustable"></i> Correggi Entrata</button>
        </form>
        {% endif %}
        <form action="{{ url_for('bulk_edit') }}" method="get" class="d-inline">
{% if buono_carico_attivo %}
<input type="hidden" name="aggiungi_buono_carico" value="{{ buono_carico_attivo }}">
{% endif %}
            {% for r in rows %}<input type="hidden" name="ids" value="{{ r.id_articolo }}">{% endfor %}
            <button class="btn btn-primary btn-sm"><i class="bi bi-pencil-square"></i> Completa entrata</button>
        </form>
        {% endif %}
    </div>
</div>

<div class="row g-3 mb-3">
    <div class="col-md-3"><div class="card p-3"><div class="text-muted small">Righe</div><div class="fs-4 fw-bold">{{ rows|length }}</div></div></div>
    <div class="col-md-3"><div class="card p-3"><div class="text-muted small">Colli</div><div class="fs-4 fw-bold">{{ total_colli }}</div></div></div>
    <div class="col-md-3"><div class="card p-3"><div class="text-muted small">Peso Totale</div><div class="fs-4 fw-bold">{{ total_peso|it_num(2) }}</div></div></div>
    <div class="col-md-3"><div class="card p-3"><div class="text-muted small">M2 / M3</div><div class="fw-bold">{{ total_m2|it_num(3) }} / {{ total_m3|it_num(3) }}</div></div></div>
</div>

<div class="row g-3 mb-3">
    <div class="col-lg-7">
        <div class="card p-3 h-100">
            <h6 class="mb-3">Riepilogo</h6>
            {% if session.get('role') == 'admin' %}<div class="alert alert-info py-2 small"><b>Completa entrata:</b> usa il bottone in alto per aprire direttamente la modifica delle righe già create dall'etichetta e inserire i dati mancanti mantenendo lo stesso QR/barcode.</div>{% endif %}
            {% if anomalies %}
            <div class="alert alert-danger py-2 small mb-2"><b>⚠ Entrata da controllare:</b> sono state trovate {{ anomalies|length }} anomalie. Usa <b>Verifica Entrata</b> per il dettaglio oppure <b>Correggi Entrata</b> per sganciare solo le righe anomale dal barcode.</div>
            {% else %}
            <div class="alert alert-success py-2 small mb-2"><b>✓ Entrata verificata:</b> nessuna anomalia rilevata.</div>
            {% endif %}
            <div><b>Clienti:</b> {{ clienti|join(', ') }}</div>
            <div><b>Fornitori:</b> {{ fornitori|join(', ') }}</div>
            <div><b>DDT ingresso:</b> {{ ddt_ingresso|join(', ') if ddt_ingresso else '-' }}</div>
            <div><b>DDT uscita collegati:</b> {{ ddt_uscita|join(', ') if ddt_uscita else '-' }}</div>
            <div><b>Link diretto:</b> <a href="{{ detail_url }}" target="_blank">{{ detail_url }}</a></div>
        </div>
    </div>
    <div class="col-lg-5">
        <div class="card p-3 h-100">
            <h6 class="mb-3">Allegati entrata</h6>
            <div class="mb-2"><b>Documenti:</b> {{ docs|length }}</div>
            <div class="mb-2"><b>Foto:</b> {{ photos|length }}</div>
            {% if docs or photos %}
            <div class="small">
                {% for a in docs %}<div><a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank">📄 {{ a.filename }}</a></div>{% endfor %}
                {% for a in photos %}<div><a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank">📷 {{ a.filename }}</a></div>{% endfor %}
            </div>
            {% else %}<div class="text-muted">Nessun allegato collegato.</div>{% endif %}
        </div>
    </div>
</div>

<div class="card p-3">
    <h6 class="mb-3">Righe dell'entrata</h6>
    <div class="table-responsive">
        <table class="table table-sm table-striped align-middle">
            <thead>
                <tr>
                    <th>ID</th><th>Codice</th><th>Descrizione</th><th>Colli</th><th>Peso</th><th>Lotto</th><th>Serial</th><th>DDT Ing</th><th>DDT Usc</th><th>Doc</th><th>Foto</th>
                </tr>
            </thead>
            <tbody>
                {% for r in rows %}
                {% set docs_count, photos_count = _row_att_counts(r) %}
                {% set row_has_anomaly = anomalies_ids and (r.id_articolo in anomalies_ids) %}
                <tr{% if row_has_anomaly %} class="table-danger"{% endif %}>
                    <td>{{ r.id_articolo }}</td>
                    <td>{{ r.codice_articolo or '' }}</td>
                    <td>{{ r.descrizione or '' }}</td>
                    <td>{{ r.n_colli or '' }}</td>
                    <td>{{ r.peso|it_num(2) if r.peso else '' }}</td>
                    <td>{{ r.lotto or '' }}</td>
                    <td>{{ r.serial_number or '' }}</td>
                    <td>{{ r.n_ddt_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_uscita or '' }}</td>
                    <td>{{ docs_count }}</td>
                    <td>{{ photos_count }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}
"""

# Template Import PDF spostato in templates/import_pdf.html


    
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

                    {% if is_admin %}
                    <div class="col-auto ms-4">
                        <label class="fw-bold">Cliente (contiene):</label>
                    </div>
                    <div class="col-auto">
                        <input type="text" name="cliente" class="form-control form-control-sm" value="{{ cliente_filtro }}">
                    </div>
                    {% else %}
                    <div class="col-auto ms-4">
                        <label class="fw-bold">Cliente:</label>
                    </div>
                    <div class="col-auto">
                        <input type="text" class="form-control form-control-sm" value="{{ cliente_filtro }}" readonly>
                    </div>
                    {% endif %}

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

                    
                    <input type="hidden" name="area_manovra" id="area_manovra" value="{{ '1' if (is_admin and area_manovra) else '0' }}">
                    <div class="col-auto ms-auto d-flex gap-2">
                        <button type="button" class="btn btn-secondary border-dark px-4" style="background-color: #e0e0e0; color: black;" onclick="document.getElementById('area_manovra').value='0'; this.closest('form').submit();">Calcola</button>
                        {% if is_admin %}
                        <button type="button" class="btn btn-warning border-dark px-4" onclick="document.getElementById('area_manovra').value='1'; this.closest('form').submit();">
                            Area Manovra {% if area_manovra %}<i class="bi bi-check2-circle"></i>{% endif %}
                        </button>
                        {% endif %}
                        <button type="submit" name="export_excel" value="1" class="btn btn-success border-dark px-4">
                            <i class="bi bi-file-earmark-excel"></i> Excel
                        </button>
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
                    <th>M² effettivi</th>
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
    .table-compact td, .table-compact th { font-size: 0.78rem; padding: 4px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px; vertical-align: middle; }
    .table-compact th { background-color: #f0f0f0; font-weight: 700; text-align: center; position: sticky; top: 0; z-index: 10; }
    .fw-buono { font-weight: bold; color: #000; }
    .att-link { text-decoration: none; font-size: 1.3em; cursor: pointer; margin: 0 3px; }
    .att-link:hover { transform: scale(1.2); display:inline-block; }
    /* Paginazione */
    .pagination { margin-bottom: 0; }
    .page-link { color: #333; text-decoration: none; padding: 0.3rem 0.6rem; }
    .page-item.active .page-link { background-color: #0d6efd; border-color: #0d6efd; color: white; }
    .page-item.disabled .page-link { color: #ccc; pointer-events: none; }
</style>

<div class="d-flex justify-content-between align-items-center mb-2">
    <h4 class="mb-0"><i class="bi bi-box-seam"></i> Magazzino <small class="text-muted fs-6">({{ total_items }} articoli)</small></h4>
    <div class="d-flex gap-2 flex-wrap top-magazzino-actions">
        {% if session.get('role') == 'admin' %}
        <a href="{{ url_for('nuovo_articolo') }}" class="btn btn-success btn-sm mag-btn-compact"><i class="bi bi-plus-lg"></i> Nuovo</a>
        <a href="{{ url_for('import_pdf') }}" class="btn btn-dark btn-sm mag-btn-compact"><i class="bi bi-file-earmark-pdf"></i> Import PDF</a>
        <form action="{{ url_for('labels_pdf') }}" method="POST" target="_blank" class="d-inline">

<button class="btn btn-info btn-sm text-white mag-btn-compact"><i class="bi bi-tag"></i> Etichette</button>
        </form>
        {% endif %}
        <a href="{{ url_for('calcola_costi') }}" class="btn btn-warning btn-sm mag-btn-compact"><i class="bi bi-calculator"></i> Calcoli</a>
        <a href="{{ url_for('export_excel') }}{% if request.query_string %}?{{ request.query_string.decode('utf-8') }}{% endif %}" class="btn btn-success btn-sm mag-btn-compact"><i class="bi bi-file-earmark-excel"></i> Excel Filtri</a>

        <form action="{{ url_for('report_inventario_excel') }}" method="POST" class="d-inline-block">
            <div class="input-group input-group-sm">
                <input type="date" name="data_inventario" class="form-control" required value="{{ today }}">
                {% if session.get('role') == 'admin' %}
                    <input type="text" name="cliente_inventario" class="form-control" placeholder="Cliente (es. FINCANTIERI)" style="max-width: 200px;">
                {% else %}
                    <input type="hidden" name="cliente_inventario" value="{{ session.get('user') }}">
                {% endif %}
                <button class="btn btn-success" type="submit" title="Scarica Excel">📥 Excel</button>
            </div>
        </form>
    </div>
</div>

<div class="card mb-2 bg-light shadow-sm">
    <div class="card-header py-1" data-bs-toggle="collapse" data-bs-target="#filterBody" style="cursor:pointer">
        <small><i class="bi bi-funnel"></i> <b>Filtri Avanzati</b></small>
    </div>
    <div id="filterBody" class="collapse {% if request.args %}show{% endif %}">
        <div class="card-body py-2">
            <form method="get">
{% if buono_carico_attivo %}
<input type="hidden" name="aggiungi_buono_carico" value="{{ buono_carico_attivo }}">
{% endif %}
                <div class="row g-1 mb-1">
                    <div class="col-md-1"><input name="id" class="form-control form-control-sm" placeholder="ID" value="{{ request.args.get('id','') }}"></div>
                    <div class="col-md-2"><input name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ request.args.get('cliente','') }}"></div>
                    <div class="col-md-2"><input name="fornitore" class="form-control form-control-sm" placeholder="Fornitore" value="{{ request.args.get('fornitore','') }}"></div>
                    <div class="col-md-2"><input name="codice_articolo" class="form-control form-control-sm" placeholder="Codice" value="{{ request.args.get('codice_articolo','') }}"></div>
                    <div class="col-md-2"><input name="serial_number" class="form-control form-control-sm" placeholder="Serial" value="{{ request.args.get('serial_number','') }}"></div>
                    <div class="col-md-2"><input name="ordine" class="form-control form-control-sm" placeholder="Ordine" value="{{ request.args.get('ordine','') }}"></div>

                    <!-- FILTRO: SOLO IN GIACENZA / SOLO USCITE -->
                    <div class="col-md-2 d-flex align-items-center">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" value="1" id="solo_giacenza" name="solo_giacenza"
                                   {% if request.args.get('solo_giacenza') == '1' %}checked{% endif %}>
                            <label class="form-check-label" for="solo_giacenza">
                                Solo in giacenza
                            </label>
                        </div>
                    </div>
                    <div class="col-md-2 d-flex align-items-center">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" value="1" id="solo_uscite" name="solo_uscite"
                                   {% if request.args.get('solo_uscite') == '1' %}checked{% endif %}>
                            <label class="form-check-label" for="solo_uscite">
                                Solo uscite
                            </label>
                        </div>
                    </div>

                    <div class="col-md-1"><button type="submit" class="btn btn-primary btn-sm w-100">Cerca</button></div>
                </div>

                <div class="row g-1 mb-1">
                    <div class="col-md-2"><input name="lotto" class="form-control form-control-sm" placeholder="Lotto" value="{{ request.args.get('lotto','') }}"></div>
                    <div class="col-md-2"><input name="commessa" class="form-control form-control-sm" placeholder="Commessa" value="{{ request.args.get('commessa','') }}"></div>
                    <div class="col-md-2"><input name="protocollo" class="form-control form-control-sm" placeholder="Protocollo" value="{{ request.args.get('protocollo','') }}"></div>
                    <div class="col-md-2"><input name="magazzino" class="form-control form-control-sm" placeholder="Magazzino" value="{{ request.args.get('magazzino','') }}"></div>
                    <div class="col-md-2"><input name="descrizione" class="form-control form-control-sm" placeholder="Descrizione" value="{{ request.args.get('descrizione','') }}"></div>
                    <div class="col-md-2"><input name="m2_da" class="form-control form-control-sm" placeholder="M2 da" value="{{ request.args.get('m2_da','') }}"></div>
                    <div class="col-md-2"><input name="m2_a" class="form-control form-control-sm" placeholder="M2 a" value="{{ request.args.get('m2_a','') }}"></div>
                    <div class="col-md-2"><input name="buono_n" class="form-control form-control-sm" placeholder="N. Buono" value="{{ request.args.get('buono_n','') }}"></div>
                    <div class="col-md-2"><input name="n_arrivo" class="form-control form-control-sm" placeholder="N. Arrivo" value="{{ request.args.get('n_arrivo','') }}"></div>
                    <div class="col-md-2"><input name="codice_entrata" class="form-control form-control-sm" placeholder="Cod. Entrata" value="{{ request.args.get('codice_entrata','') }}"></div>
                    <div class="col-md-2"><input name="mezzi_in_uscita" class="form-control form-control-sm" placeholder="Mezzo Uscita" value="{{ request.args.get('mezzi_in_uscita','') }}"></div>
                    <div class="col-md-2"><input name="stato" class="form-control form-control-sm" placeholder="Stato" value="{{ request.args.get('stato','') }}"></div>
                </div>

                <div class="row g-1">
                    <div class="col-md-2"><input name="n_ddt_ingresso" class="form-control form-control-sm" placeholder="DDT Ing." value="{{ request.args.get('n_ddt_ingresso','') }}"></div>
                    <div class="col-md-2"><input name="n_ddt_uscita" class="form-control form-control-sm" placeholder="DDT Usc." value="{{ request.args.get('n_ddt_uscita','') }}"></div>
                    <div class="col-md-4">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Ingr</span>
                            <input name="data_ing_da" type="date" class="form-control" value="{{ request.args.get('data_ing_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_ing_a" type="date" class="form-control" value="{{ request.args.get('data_ing_a','') }}">
                        </div>
                    </div>
                    <div class="col-md-4 d-flex gap-1">
                        <div class="input-group input-group-sm">
                            <span class="input-group-text">Usc</span>
                            <input name="data_usc_da" type="date" class="form-control" value="{{ request.args.get('data_usc_da','') }}">
                            <span class="input-group-text">-</span>
                            <input name="data_usc_a" type="date" class="form-control" value="{{ request.args.get('data_usc_a','') }}">
                        </div>
                        <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm" onclick="localStorage.removeItem('camar_selected_articles');">Reset</a>
                    </div>
                </div>
            </form>
        </div>
    </div>
</div>

<form method="POST">
<input type="hidden" name="return_url" value="{{ request.full_path }}">

{% if buono_carico_attivo %}
<input type="hidden" name="buono_carico_id" value="{{ buono_carico_attivo }}">
{% endif %}
{% if can_use_buoni_qr() %}
<div class="add-buono-box">
    <strong>➕ Aggiungi arrivi a buono esistente:</strong>
    <input type="text" name="buono_carico_id_manual" class="form-control form-control-sm"
           placeholder="ID o BC-2026-0001" value="{{ buono_carico_attivo or '' }}">
    <button type="submit" formaction="{{ url_for('aggiungi_righe_a_buono_carico') }}" formmethod="post"
            class="btn btn-primary btn-sm fw-bold mag-btn-compact">
        ➕ Aggiungi al buono
    </button>
    <span class="text-muted small">Scrivi l'ID numerico o il codice buono, poi seleziona le righe.</span>
</div>
{% endif %}

    <div class="btn-toolbar mb-2 gap-1 flex-wrap">
        {% if session.get('role') == 'admin' %}
        
<button type="submit" formaction="{{ url_for('buono_preview') }}" class="btn btn-outline-dark btn-sm">Buono</button>
        <button type="submit" formaction="{{ url_for('ddt_preview') }}" class="btn btn-outline-dark btn-sm">DDT</button>
        <button type="submit" formaction="{{ url_for('invia_email') }}" formmethod="get" class="btn btn-success btn-sm"><i class="bi bi-envelope"></i> Email</button>
        <button type="submit" formaction="{{ url_for('bulk_edit') }}" class="btn btn-info btn-sm text-white">Modifica</button>
        <button type="submit" formaction="{{ url_for('buono_carico_da_riga') }}" formmethod="post" class="btn btn-outline-primary btn-sm fw-bold">🧾 Buono carico QR</button>
        {% if buono_carico_attivo %}
        <button type="submit" formaction="{{ url_for('aggiungi_righe_a_buono_carico') }}" formmethod="post" class="btn btn-primary btn-sm fw-bold">➕ Aggiungi al buono</button>
        {% endif %}
        <button type="submit" formaction="{{ url_for('scarico_parziale_selezionato') }}" formmethod="post" class="btn btn-warning btn-sm fw-bold">
            📤 Scarico parziale
        </button>
        <button type="submit" formaction="{{ url_for('labels_pdf') }}" formtarget="_blank" class="btn btn-warning btn-sm"><i class="bi bi-download"></i> Etichette</button>
        <button type="submit" formaction="{{ url_for('delete_rows') }}" class="btn btn-danger btn-sm" onclick="return confirm('Eliminare SELEZIONATI?')">Elimina</button>
        <button type="submit" formaction="{{ url_for('bulk_duplicate') }}" class="btn btn-primary btn-sm" onclick="return confirm('Duplicare?')">Duplica</button>
        {% endif %}
        {% if can_use_buoni_qr() %}
<a href="{{ url_for('scan_entrata') }}" class="btn btn-sm btn-outline-primary"><i class="bi bi-upc-scan"></i> Scan Entrata</a>
{% endif %}
    </div>

    <div class="table-responsive shadow-sm" style="max-height: 65vh;">
        <table class="table table-striped table-bordered table-hover table-compact mb-0">
            <thead class="sticky-top" style="top:0; z-index:5;">
                <tr>
                    <th><input type="checkbox" onclick="toggleAll(this)"></th>
                    <th>ID</th> <th>Codice</th> <th>Pz</th> <th>Larg</th> <th>Lung</th> <th>Alt</th> <th>M2</th> <th>M3</th>
                    <th>Descrizione</th> <th>Protocollo</th> <th>Commessa</th> <th>Ordine</th> <th>Colli</th> <th>Fornitore</th> <th>Magazzino</th>
                    <th>Data Ing</th> <th>DDT Ing</th> <th>DDT Usc</th> <th>Data Usc</th> <th>Mezzo Usc</th>
                    <th>Cliente</th> <th>Kg</th> <th>Posiz</th> <th>N.Arr</th> <th>Entrata</th> <th>N.Buono</th> <th>Note</th> 
                    <th>Lotto</th> <th>Ns.Rif</th> <th>Serial</th> <th>Stato</th>
                    {% if session.get('role') == 'admin' %}<th>Creato da</th> <th>Modificato da</th> <th>Ultima mod.</th>{% endif %}
                    <th>Doc</th> <th>Foto</th> <th>Act</th>
                </tr>
            </thead>
            <tbody>
                {% for r in rows %}
                <tr>
                    <td class="text-center"><input type="checkbox" name="ids" value="{{ r.id_articolo }}" class="row-checkbox"></td>
                    <td>{{ r.id_articolo }}</td>
                    <td title="{{ r.codice_articolo }}">{{ r.codice_articolo or '' }}</td>
                    <td>{{ r.pezzo or '' }}</td>
                    <td>{{ r.larghezza|it_num(2) if r.larghezza else '' }}</td>
                    <td>{{ r.lunghezza|it_num(2) if r.lunghezza else '' }}</td>
                    <td>{{ r.altezza|it_num(2) if r.altezza else '' }}</td>
                    <td>{{ r.m2|it_num(3) if r.m2 else '' }}</td>
                    <td>{{ r.m3|it_num(3) if r.m3 else '' }}</td>
                    <td title="{{ r.descrizione }}">{{ (r.descrizione or '')[:25] }}...</td>
                    <td>{{ r.protocollo or '' }}</td> <td>{{ r.commessa or '' }}</td> <td>{{ r.ordine or '' }}</td>
                    <td>{{ r.n_colli or '' }}</td> <td>{{ r.fornitore or '' }}</td> <td>{{ r.magazzino or '' }}</td>
                    <td>{{ r.data_ingresso or '' }}</td>
                    <td>{{ r.n_ddt_ingresso or '' }}</td> <td>{{ r.n_ddt_uscita or '' }}</td>
                    <td>{{ r.data_uscita or '' }}</td>
                    <td>{{ r.mezzi_in_uscita or '' }}</td> <td>{{ r.cliente or '' }}</td> <td>{{ r.peso|it_num(2) if r.peso else '' }}</td>
                    <td>{{ r.posizione or '' }}</td> <td>{{ r.n_arrivo or '' }}</td> <td>{% if r.codice_entrata %}<a href="{{ url_for('dettaglio_entrata', codice_entrata=r.codice_entrata) }}" class="text-decoration-none">{{ r.codice_entrata }}</a>{% endif %}</td> <td class="fw-buono">{{ r.buono_n or '' }}</td>
                    <td title="{{ r.note }}">{{ (r.note or '')[:15] }}...</td>
                    <td>{{ r.lotto or '' }}</td> <td>{{ r.ns_rif or '' }}</td> <td>{{ r.serial_number or '' }}</td>
                    <td>{{ r.stato or '' }}</td>
                    {% if session.get('role') == 'admin' %}
                    <td>{{ r.created_by or '' }}</td>
                    <td>{{ r.updated_by or '' }}</td>
                    <td>{{ r.updated_at or '' }}</td>
                    {% endif %}
                    <td class="text-center">
                        {% for a in r.attachments if a.kind=='doc' %}
                        <a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank" class="att-link">📄</a>
                        {% endfor %}
                    </td>
                    <td class="text-center">
                        {% for a in r.attachments if a.kind=='photo' %}
                        <a href="{{ url_for('serve_uploaded_file', filename=a.filename) }}" target="_blank" class="att-link">📷</a>
                        {% endfor %}
                    </td>
                    <td class="text-center">
                        {% if session.get('role') == 'admin' %}
                        <a href="{{ url_for('edit_articolo', id=r.id_articolo, return_url=request.full_path) }}" class="btn btn-outline-primary btn-sm py-0 px-1" title="Modifica">✏️</a>
                        <a href="{{ url_for('allegati_articolo', id_articolo=r.id_articolo, return_url=request.full_path) }}" class="btn btn-outline-secondary btn-sm py-0 px-1" title="Documenti e Foto">📎</a>
                        {% if not r.data_uscita and not r.n_ddt_uscita %}
                        <a href="{{ url_for('scarico_parziale', id_articolo=r.id_articolo, return_url=request.full_path) }}" class="btn btn-warning btn-sm py-0 px-1 fw-bold text-nowrap" title="Scarico parziale pezzi">📤 Scarico</a>
                        {% endif %}
                        <a href="{{ url_for('delete_articolo', id=r.id_articolo) }}" class="btn btn-outline-danger btn-sm py-0 px-1" onclick="return confirm('Eliminare?')" title="Elimina">🗑️</a>
                        {% else %}-{% endif %}
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="38" class="text-center p-3 text-muted">Nessun articolo trovato.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    {% if total_pages > 1 %}
    <nav class="mt-2 bg-white p-2 border-top d-flex justify-content-between align-items-center shadow-sm">
        <div>
            <span class="fw-bold">Pagina {{ page }} di {{ total_pages }}</span> 
            <small class="text-muted">({{ total_items }} articoli totali)</small>
        </div>
        <ul class="pagination pagination-sm m-0">
            <li class="page-item {% if page == 1 %}disabled{% endif %}">
                <a class="page-link" href="{{ url_for('giacenze', page=page-1, **search_params) }}">
                    <i class="bi bi-chevron-left"></i> Precedente
                </a>
            </li>
            
            <li class="page-item {% if page == total_pages %}disabled{% endif %}">
                <a class="page-link" href="{{ url_for('giacenze', page=page+1, **search_params) }}">
                    Successivo <i class="bi bi-chevron-right"></i>
                </a>
            </li>
        </ul>
    </nav>
    {% endif %}

    <div class="text-end mt-2 text-muted small bg-light p-2 border-top fw-bold">
        Totali: Colli {{ total_colli }} | M2 {{ total_m2 }} | Peso {{ total_peso }}
    </div>
</form>

<script>
    const STORAGE_KEY = 'camar_selected_articles';
    
    function saveSelection() {
        const checked = Array.from(document.querySelectorAll('input[name="ids"]:checked')).map(cb => cb.value);
        let saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        checked.forEach(id => { if(!saved.includes(id)) saved.push(id); });
        const unchecked = Array.from(document.querySelectorAll('input[name="ids"]:not(:checked)')).map(cb => cb.value);
        saved = saved.filter(id => !unchecked.includes(id));
        localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    }

    function toggleAll(source) {
        document.querySelectorAll('input[name="ids"]').forEach(c => c.checked = source.checked);
        saveSelection();
    }

    document.addEventListener("DOMContentLoaded", function() {
        const savedIds = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        document.querySelectorAll('input[name="ids"]').forEach(cb => {
            if (savedIds.includes(cb.value)) cb.checked = true;
        });
        document.addEventListener("change", function(e) {
            if (e.target && e.target.matches('input[name="ids"]')) saveSelection();
        });

        const soloGiacenza = document.getElementById('solo_giacenza');
        const soloUscite = document.getElementById('solo_uscite');
        if (soloGiacenza && soloUscite) {
            soloGiacenza.addEventListener('change', function(){ if (this.checked) soloUscite.checked = false; });
            soloUscite.addEventListener('change', function(){ if (this.checked) soloGiacenza.checked = false; });
        }

        const mainForm = document.querySelector('form[method="POST"]');
        if (mainForm) {
            mainForm.addEventListener('submit', function(e) {
                const btn = e.submitter;
                const action = (btn && (btn.getAttribute('formaction') || '')) || '';
                if (action.includes('buono_preview') || action.includes('ddt_preview') || action.includes('ddt_finalize') || action.includes('buono_finalize')) {
                    localStorage.removeItem(STORAGE_KEY);
                    setTimeout(function(){
                        document.querySelectorAll('input[name="ids"]').forEach(cb => cb.checked = false);
                    }, 100);
                }
            });
        }
    });
</script>
{% endblock %}


<script>
function apriScaricoParzialeSelezionato() {
    // Cerca la riga selezionata nella tabella giacenze.
    // Compatibile con checkbox name="ids", name="selected_ids", class="row-checkbox" e value=id articolo.
    let checked = Array.from(document.querySelectorAll(
        'input[name="ids"]:checked, input[name="selected_ids"]:checked, input.row-checkbox:checked, input[type="checkbox"][value]:checked'
    ));

    // Esclude eventuali checkbox "seleziona tutto"
    checked = checked.filter(function(cb) {
        const v = (cb.value || '').trim();
        return v && v !== 'on' && /^\d+$/.test(v);
    });

    if (checked.length !== 1) {
        alert("Seleziona una sola riga per fare lo scarico parziale.");
        return false;
    }

    const id = checked[0].value;
    window.location.href = "/scarico_parziale/" + encodeURIComponent(id);
    return false;
}
</script>

"""

EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3>
        <i class="bi bi-pencil-square"></i> 
        {% if row.id_articolo %}Modifica Articolo #{{ row.id_articolo }}{% else %}Nuovo Articolo{% endif %}
    </h3>
    <a href="{{ return_url or url_for('giacenze') }}" class="btn btn-secondary">Torna alla Lista</a>
</div>

<form method="post" enctype="multipart/form-data" class="card p-4 shadow-sm mb-4">
    <input type="hidden" name="return_url" value="{{ return_url or '' }}">
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

        <div class="col-md-4"><label class="form-label">Cliente</label>
            <input type="text" name="cliente" class="form-control" list="clientiUtentiList" value="{{ row.cliente or '' }}" required>
            <datalist id="clientiUtentiList">
                {% for c in clienti_validi %}<option value="{{ c }}">{% endfor %}
            </datalist>
        </div>
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
            <input type="number" name="n_colli" min="0" class="form-control fw-bold" value="{{ row.n_colli if row.n_colli is not none else 1 }}">
            <small class="text-muted" style="font-size:10px">Se > 1, crea N righe separate!</small>
        </div>
        <div class="col-md-2"><label class="form-label">Peso (Kg)</label><input type="number" step="0.01" name="peso" class="form-control" value="{{ row.peso or '' }}"></div>
        <div class="col-md-2"><label class="form-label">M³</label><input type="number" step="0.001" name="m3" class="form-control" value="{{ row.m3 or '' }}"></div>
        <div class="col-md-2"><label class="form-label">N. Arrivo</label><input type="text" name="n_arrivo" class="form-control" value="{{ row.n_arrivo or '' }}"></div>
        <div class="col-md-4"><label class="form-label">Codice Entrata / Barcode</label><input type="text" name="codice_entrata" class="form-control" value="{{ row.codice_entrata or request.args.get('codice_entrata','') }}" placeholder="Viene riutilizzato uguale tra etichetta e giacenze"></div>
        
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
            <input type="file" name="file" class="form-control" multiple required
                   accept="image/*,.pdf,.doc,.docx,.xls,.xlsx"
                   capture="environment">
            <button type="submit" class="btn btn-success fw-bold">
                <i class="bi bi-camera"></i> Scatta / Carica File
            </button>
        </form>
    </div>
    <div class="small text-muted mb-3">Da smartphone puoi scattare una foto direttamente oppure allegare PDF/documenti. Puoi caricare anche più file insieme.</div>
    <hr>
    
    <div class="row g-3">
        {% for att in row.attachments %}
        <div class="col-md-2 col-6">
            <div class="card h-100 text-center p-2 border bg-light position-relative shadow-sm">
                <div class="mb-2">
                    {% if att.kind == 'photo' %}
                    <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank">
                        <img src="{{ url_for('serve_uploaded_file', filename=att.filename) }}"
                             class="img-fluid rounded border"
                             style="height:95px; object-fit:cover; width:100%; background:#fff;">
                    </a>
                    {% else %}
                    <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank"
                       class="d-flex align-items-center justify-content-center border rounded bg-white text-danger text-decoration-none"
                       style="height:95px; font-size:2.4em;">
                        <i class="bi bi-file-earmark-pdf"></i>
                    </a>
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


REPORT_FATTURAZIONE_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-3">
    <div class="d-flex align-items-center gap-3">
        {% if logo_url %}<img src="{{ logo_url }}" style="height:56px; width:auto;">{% endif %}
        <div>
            <h3 class="mb-0"><i class="bi bi-bar-chart-line"></i> Report Fatturazione</h3>
            <div class="text-muted small">Area riservata agli amministratori</div>
        </div>
    </div>
    <a href="{{ url_for('export_report_fatturazione_excel', mese=mese, anno=anno) }}" class="btn btn-success">
        <i class="bi bi-file-earmark-excel"></i> Esporta Excel
    </a>
</div>

<div class="card shadow-sm mb-4">
    <div class="card-body">
        <form method="get" class="row g-3 align-items-end">
{% if buono_carico_attivo %}
<input type="hidden" name="aggiungi_buono_carico" value="{{ buono_carico_attivo }}">
{% endif %}
            <div class="col-md-2">
                <label class="form-label fw-bold">Mese</label>
                <select name="mese" class="form-select">
                    {% for m in range(1, 13) %}
                    <option value="{{ m }}" {% if m == mese %}selected{% endif %}>{{ "%02d"|format(m) }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-2">
                <label class="form-label fw-bold">Anno</label>
                <input type="number" name="anno" class="form-control" value="{{ anno }}">
            </div>
            <div class="col-md-3">
                <button type="submit" class="btn btn-primary"><i class="bi bi-search"></i> Visualizza</button>
            </div>
        </form>
        <div class="mt-3 small text-muted">
            Per i clienti standard il report mostra M2 presenti nel mese, giacenza a fine mese, M2 usciti, M2 entrate doganali e il picco M2 occupati nel mese. Per Galvano Tecnica viene mostrato solo il totale pallet ancora in giacenza a fine mese selezionato, usando la colonna N° Colli.
        </div>
    </div>
</div>

<div class="card shadow-sm">
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-striped table-bordered align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Cliente</th>
                        <th class="text-end">M2 presenti nel mese</th>
                        <th class="text-end">M2 giacenza fine mese</th>
                        <th class="text-end">M2 usciti nel mese</th>
                        <th class="text-end">Entrate doganali M2</th>
                        <th class="text-end">Picco M2 occupati</th>
                        <th class="text-end">Pallet giacenza mese</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr>
                        <td><strong>{{ r.cliente }}</strong></td>
                        <td class="text-end">{{ r.m2_presenti|it_num(2) }}</td>
                        <td class="text-end">{{ r.m2_fine_mese|it_num(2) }}</td>
                        <td class="text-end">{{ r.m2_usciti|it_num(2) }}</td>
                        <td class="text-end">{{ r.entrate_doganali_m2|it_num(2) }}</td>
                        <td class="text-end">{{ r.picco_m2_occupati|it_num(2) }}</td>
                        <td class="text-end">{{ r.pallet_giacenza|it_num(0) }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center text-muted py-4">Nessun dato disponibile per il periodo selezionato.</td></tr>
                    {% endfor %}
                </tbody>
                {% if rows %}
                <tfoot class="table-light fw-bold">
                    <tr>
                        <td>TOTALE</td>
                        <td class="text-end">{{ totals.m2_presenti|it_num(2) }}</td>
                        <td class="text-end">{{ totals.m2_fine_mese|it_num(2) }}</td>
                        <td class="text-end">{{ totals.m2_usciti|it_num(2) }}</td>
                        <td class="text-end">{{ totals.entrate_doganali_m2|it_num(2) }}</td>
                        <td class="text-end">{{ totals.picco_m2_occupati|it_num(2) }}</td>
                        <td class="text-end">{{ totals.pallet_giacenza|it_num(0) }}</td>
                    </tr>
                </tfoot>
                {% endif %}
            </table>
        </div>
    </div>
</div>
{% endblock %}
"""


BULK_EDIT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h3><i class="bi bi-ui-checks"></i> Modifica Multipla ({{ rows|length }} articoli)</h3>
        <a href="{{ return_url or url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
    </div>

    <div class="alert alert-warning shadow-sm">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <strong>Attenzione:</strong> Attiva la spunta accanto ai campi che vuoi modificare. 
        Il valore inserito verrà applicato a <b>TUTTI</b> gli articoli selezionati.
    </div>

    <form method="POST" enctype="multipart/form-data">
        <input type="hidden" name="save_bulk" value="true">
        <input type="hidden" name="return_url" value="{{ return_url or '' }}">
        {% for id in ids_csv.split(',') %}
        <input type="hidden" name="ids" value="{{ id }}">
        {% endfor %}

        <div class="card p-4 mb-4 bg-light border-dashed shadow-sm">
            <h5 class="text-primary"><i class="bi bi-cloud-upload"></i> Caricamento Allegati Massivo</h5>
            <div class="d-flex gap-2">
                <!-- ✅ CORRETTO: name="bulk_files" -->
                <input type="file" name="bulk_files" class="form-control" multiple>
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

                        {% elif field_name in ['pezzo','n_colli','lunghezza','larghezza','altezza','peso'] %}
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
<div class="card p-3 shadow-sm">
    <div class="d-flex align-items-center gap-3 mb-3">
        {% if logo_url %}<img src="{{ logo_url }}" style="height:40px">{% endif %}
        <h5 class="flex-grow-1 text-center m-0 text-uppercase fw-bold">Buono di Prelievo</h5>
        
        <div class="btn-group">
            <button type="button" class="btn btn-outline-primary" onclick="submitBuono('preview')">
                <i class="bi bi-eye"></i> Anteprima PDF
            </button>
            <button type="button" class="btn btn-success fw-bold" onclick="submitBuono('save')">
                <i class="bi bi-file-earmark-arrow-down"></i> Genera e Salva
            </button>
            <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
        </div>
    </div>

    <form id="buono-form" method="POST" action="{{ url_for('buono_finalize_and_get_pdf') }}">
        <input type="hidden" name="ids" value="{{ ids }}">

        <div class="row g-3 bg-light p-3 rounded border mb-3">
            <div class="col-md-3">
                <label class="form-label small fw-bold">N. Buono</label>
                <div class="input-group">
                    <select name="buono_mode" id="buono_mode" class="form-select" style="max-width:130px" onchange="toggleBuonoMode()">
                        <option value="auto" selected>Automatico</option>
                        <option value="manuale">Manuale</option>
                    </select>
                    <input name="buono_n" id="buono_n" class="form-control fw-bold" value="{{ meta.buono_n }}">
                </div>
                <div class="form-text">
                    Automatico: propone il prossimo numero disponibile. Manuale: puoi modificarlo tu.
                </div>
            </div>
            <div class="col-md-2">
                <label class="form-label small fw-bold">Data Em.</label>
                <input name="data_em" class="form-control" value="{{ meta.data_em }}" readonly>
            </div>
            <div class="col-md-2">
                <label class="form-label small fw-bold">Ordine</label>
                <input name="ordine" class="form-control" value="{{ meta.ordine }}">
            </div>
            <div class="col-md-2">
                <label class="form-label small fw-bold">Commessa</label>
                <input name="commessa" class="form-control" value="{{ meta.commessa }}">
            </div>
            <div class="col-md-2">
                <label class="form-label small fw-bold">Fornitore</label>
                <input name="fornitore" class="form-control" value="{{ meta.fornitore }}">
            </div>
            <div class="col-md-2">
                <label class="form-label small fw-bold">Protocollo</label>
                <input name="protocollo" class="form-control" value="{{ meta.protocollo }}">
            </div>
        </div>



        <div class="card border-success mb-3">
            <div class="card-header bg-success bg-opacity-10 d-flex align-items-center justify-content-between">
                <div>
                    <b>Picking / Lavorazioni</b>
                    <div class="small text-muted">Compila subito i dati del picking collegati al Buono.</div>
                </div>
                <label class="form-check-label fw-bold">
                    <input class="form-check-input" type="checkbox" name="picking_enable" value="1" checked>
                    Crea picking al salvataggio
                </label>
            </div>
            <div class="card-body">
                <div class="row g-2">
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Data</label>
                        <input name="picking_data" class="form-control" value="{{ meta.data_em }}">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Cliente</label>
                        <input name="picking_cliente" class="form-control" value="{{ meta.picking_cliente }}">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold">Descrizione</label>
                        <input name="picking_descrizione" class="form-control" value="{{ meta.picking_descrizione }}">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Richiesta di</label>
                        <input name="picking_richiesta_di" class="form-control" value="{{ meta.picking_richiesta_di }}">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Seriali / Buono</label>
                        <input name="picking_seriali" class="form-control" value="{{ meta.picking_seriali }}">
                    </div>
                    <div class="col-md-3">
                        <label class="form-label small fw-bold">N. Arrivo</label>
                        <input name="picking_n_arrivo" class="form-control" value="{{ meta.picking_n_arrivo }}">
                    </div>
                    <div class="col-md-1">
                        <label class="form-label small fw-bold">Colli</label>
                        <input name="picking_colli" type="number" class="form-control" value="{{ meta.picking_colli }}">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Pallet Entrati</label>
                        <input name="picking_pallet_entrati" type="number" class="form-control">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Pallet Usciti</label>
                        <input name="picking_pallet_usciti" type="number" class="form-control">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Ore Blue</label>
                        <input name="picking_ore_blue" type="number" step="0.5" class="form-control">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label small fw-bold">Ore White</label>
                        <input name="picking_ore_white" type="number" step="0.5" class="form-control">
                    </div>
                </div>
                <div class="form-text mt-2">
                    La descrizione viene proposta automaticamente come PICKING+FILMATURA+PALLETIZZAZIONE. Se non vuoi registrare il picking, togli la spunta.
                </div>
            </div>
        </div>

        <div class="alert alert-warning py-2 small">
            <b>Scarico parziale:</b> se nella cella ci sono più codici/descrizioni, lascia nei campi sotto solo il codice e la descrizione che vuoi mettere nel buono.
            Quando premi <b>Genera e Salva</b>, quel codice/descrizione verrà tolto dalla riga originale e resterà in giacenza solo il residuo.
        </div>

        <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle table-hover">
                <thead class="table-dark text-black" style="color:black !important;">
                    <tr>
                        <th style="width:10%">Ordine Orig.</th>
                        <th style="width:22%">Codice da mettere nel buono</th>
                        <th style="width:38%">Descrizione da mettere nel buono</th>
                        <th style="width:10%">Q.tà</th>
                        <th style="width:10%">N.Arr</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rows %}
                    <tr class="table-light">
                        <td class="small">{{ r.ordine or '' }}</td>
                        <td>
                            <textarea name="codice_buono_{{ r.id_articolo }}" rows="2"
                                      class="form-control form-control-sm fw-bold"
                                      title="Scrivi qui SOLO il codice articolo da inserire nel buono. Se lo modifichi, quando salvi verrà tolto dalla cella originale.">{{ r.codice_articolo or '' }}</textarea>
                            <div class="small text-muted mt-1">
                                Orig.: {{ r.codice_articolo or '' }}
                            </div>
                        </td>
                        <td>
                            <textarea name="descrizione_buono_{{ r.id_articolo }}" rows="2"
                                      class="form-control form-control-sm"
                                      title="Scrivi qui SOLO la descrizione da inserire nel buono. Se la modifichi, quando salvi verrà tolta dalla cella originale.">{{ r.descrizione or '' }}</textarea>
                            <div class="small text-muted mt-1">
                                Orig.: {{ r.descrizione or '' }}
                            </div>
                        </td>
                        <td>
                            <!-- ✅ Q.tà prende PEZZI -->
                            <input name="q_{{ r.id_articolo }}" type="number"
                                   class="form-control form-control-sm text-center fw-bold"
                                   value="{{ r.pezzo or 1 }}">
                        </td>
                        <td class="small text-center">{{ r.n_arrivo or '' }}</td>
                    </tr>
                    <tr>
                        <td colspan="2" class="text-end small text-muted align-middle" style="border-top:none;">Note:</td>
                        <td colspan="3" style="border-top:none;">
                            <textarea class="form-control form-control-sm border-0 bg-white text-primary"
                                      name="note_{{ r.id_articolo }}" rows="1"
                                      placeholder="Inserisci note aggiuntive...">{{ r.note or '' }}</textarea>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </form>
</div>

<script>
function toggleBuonoMode() {
    const mode = document.getElementById('buono_mode');
    const input = document.getElementById('buono_n');
    if (!mode || !input) return;
    if (mode.value === 'auto') {
        input.value = "{{ meta.buono_n_auto or meta.buono_n }}";
        input.classList.add('bg-light');
    } else {
        input.classList.remove('bg-light');
        input.focus();
        input.select();
    }
}
document.addEventListener('DOMContentLoaded', toggleBuonoMode);

function submitBuono(actionType) {
    const form = document.getElementById('buono-form');
    const actionField = document.getElementById('action_field');
    if (actionField) actionField.value = actionType;

    if (actionType === 'preview') {
        form.target = '_blank';
        form.submit();
    } else {
        form.target = '_self';
        const formData = new FormData(form);
        const url = "{{ url_for('buono_finalize_and_get_pdf') }}"; 
        
        fetch(url, { method: 'POST', body: formData })
        .then(resp => {
            if (resp.ok) return resp.blob();
            return resp.text().then(text => { throw new Error(text) });
        })
        .then(blob => {
            const urlBlob = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = urlBlob;
            a.download = 'Buono_Prelievo.pdf';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(urlBlob);
            setTimeout(() => { window.location.href = '{{ url_for("giacenze") }}'; }, 1500);
        })
        .catch(err => alert("Errore durante il salvataggio:\\n" + err));
    }
}
</script>
{% endblock %}
"""

DDT_PREVIEW_HTML = """ 
{% extends 'base.html' %}
{% block content %}
<style>
    .ddt-page-card{
        border:0;
        border-radius:18px;
        box-shadow:0 8px 26px rgba(15,23,42,.08);
        overflow:hidden;
    }
    .ddt-title{
        font-weight:700;
        letter-spacing:.02em;
        color:#172033;
    }
    .ddt-section-title{
        font-size:.82rem;
        font-weight:800;
        text-transform:uppercase;
        letter-spacing:.03em;
        color:#1f2937;
        margin-bottom:.25rem;
    }
    .ddt-helper{
        font-size:.76rem;
        color:#6b7280;
        margin:0;
    }
    .ddt-recipient-card{
        border:1px solid #dbe3ef;
        border-radius:14px;
        background:#fff;
        box-shadow:0 4px 14px rgba(15,23,42,.04);
    }
    .ddt-recipient-card.active{
        border-color:#0d6efd;
        box-shadow:0 0 0 .16rem rgba(13,110,253,.10);
    }
    .ddt-recipient-card.manual-active{
        border-color:#198754;
        box-shadow:0 0 0 .16rem rgba(25,135,84,.10);
    }
    .ddt-card-head{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:.75rem;
        padding:.75rem .85rem;
        background:#f8fafc;
        border-bottom:1px solid #e5eaf2;
        border-radius:14px 14px 0 0;
    }
    .ddt-list-toolbar{
        display:flex;
        gap:.45rem;
        align-items:center;
        margin-bottom:.55rem;
    }
    .ddt-search-wrap{
        position:relative;
        flex:1;
    }
    .ddt-search-wrap i{
        position:absolute;
        right:.7rem;
        top:50%;
        transform:translateY(-50%);
        color:#64748b;
    }
    #dest_search{
        padding-right:2rem;
    }
    #dest_key{
        height:178px;
        overflow:auto;
        font-size:.86rem;
        border-radius:10px;
    }
    #dest_key option{
        padding:7px 8px;
        white-space:normal;
    }
    .ddt-preview-box{
        border-left:4px solid #0d6efd;
        background:#f8fbff;
        border-radius:12px;
        padding:.65rem .75rem;
        min-height:86px;
    }
    .ddt-preview-row{
        display:grid;
        grid-template-columns:120px 1fr;
        gap:.6rem;
        margin-bottom:.25rem;
        align-items:start;
    }
    .ddt-preview-label{
        color:#64748b;
        font-size:.74rem;
    }
    .ddt-preview-value{
        font-weight:700;
        color:#111827;
        word-break:break-word;
    }
    .ddt-manual-grid{
        display:grid;
        grid-template-columns:1.2fr 1fr 1fr;
        gap:.55rem;
    }
    .ddt-field-card{
        border:1px solid #e5e7eb;
        border-radius:12px;
        padding:.75rem;
        background:#fff;
        height:100%;
    }
    .ddt-actions .btn{
        white-space:nowrap;
    }
    .ddt-field-error{
        border:2px solid #dc3545 !important;
        background:#fff5f5 !important;
    }
    .ddt-camy-banner{
        border-left:5px solid #0d6efd;
    }
    @media (max-width: 991px){
        .ddt-manual-grid{ grid-template-columns:1fr; }
        .ddt-actions{ width:100%; justify-content:flex-start; flex-wrap:wrap; }
    }
</style>

<div class="card p-3 ddt-page-card">

    <!-- ✅ HEADER -->
    <div class="d-flex align-items-center gap-3 mb-4" style="padding-bottom:10px;">
        {% if logo_url %}
            <img src="{{ logo_url }}" style="height:70px; margin-bottom:10px;">
        {% endif %}

        <h5 class="flex-grow-1 text-center m-0 ddt-title" style="padding-top:10px;">
            DOCUMENTO DI TRASPORTO
        </h5>

        <div class="btn-group ddt-actions">
            <button type="submit"
                    form="ddt-form"
                    name="action"
                    value="preview"
                    formaction="{{ url_for('ddt_finalize', mode='preview') }}"
                    formtarget="_blank"
                    class="btn btn-outline-primary">
                <i class="bi bi-printer"></i> Anteprima PDF
            </button>
            <button type="submit"
                    form="ddt-form"
                    name="action"
                    value="finalize"
                    formaction="{{ url_for('ddt_finalize', mode='finalize') }}"
                    formtarget="_self"
                    class="btn btn-success">
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
        <input type="hidden" name="dest_source" id="dest_source" value="saved">
        <input type="hidden" id="ddt_cliente_richiede_mezzi" value="{{ '1' if ddt_cliente_richiede_mezzi else '0' }}">
        <input type="hidden" id="ddt_total_righe" value="{{ total_righe_ddt or (rows|length) }}">
        <input type="hidden" id="ddt_total_colli" value="{{ total_colli_ddt or 0 }}">
        <input type="hidden" id="ddt_total_peso" value="{{ total_peso_ddt or '0,00' }}">

        <div class="alert alert-primary ddt-camy-banner py-2 mb-3" id="ddt_camy_banner">
            <b>🧠 Controllo Operativo CAMY:</b> DDT con <b>{{ total_righe_ddt or (rows|length) }}</b> righe,
            <b>{{ total_colli_ddt or 0 }}</b> colli e <b>{{ total_peso_ddt or '0,00' }} kg</b>.
            {% if protocollo_mancanti_ddt and protocollo_mancanti_ddt > 0 %}
                <div class="text-danger fw-bold mt-1">⚠️ Mancano {{ protocollo_mancanti_ddt }} protocolli obbligatori per FINCANTIERI / FINCANTIERI ARMATORE.</div>
            {% endif %}
            <div class="small mt-1">Prima di finalizzare controlla destinatario, numero DDT, data, mezzo e articoli selezionati.</div>
        </div>

        <div class="alert alert-info py-2 mb-3">
            <b>Mezzi e Trasporti:</b> vengono compilati solo per
            <b>FINCANTIERI</b>, <b>FINCANTIERI SCOPERTO</b>, <b>FINCANTIERI ARMATORE</b>,
            <b>MARINE INTERIORS</b> e <b>DE WAVE SAMA</b> quando il trasporto è gestito da Camar.
            <div class="form-check mt-1">
                <input class="form-check-input" type="checkbox" value="1" name="skip_mezzi_trasporti" id="skip_mezzi_trasporti" {% if not ddt_cliente_richiede_mezzi %}checked{% endif %}>
                <label class="form-check-label" for="skip_mezzi_trasporti">
                    Non compilare Mezzo nelle Giacenze e non inserire il record nella funzione Trasporti
                </label>
            </div>
        </div>

        <div class="row g-3 align-items-start">
            <!-- ✅ COLONNA DESTINATARIO -->
            <div class="col-lg-4 col-xl-4">
                <div class="ddt-section-title">Destinatario DDT</div>

                <div class="ddt-recipient-card active mb-3" id="box_dest_saved">
                    <div class="ddt-card-head">
                        <div>
                            <div class="fw-bold">Destinatari salvati <span class="text-muted fw-normal">(rubrica)</span></div>
                            <p class="ddt-helper">Cerca e seleziona il destinatario dalla lista.</p>
                        </div>
                        <button type="button" class="btn btn-primary btn-sm" id="btn_use_saved">
                            <i class="bi bi-check2-circle"></i> Usa salvato
                        </button>
                    </div>
                    <div class="card-body p-2">
                        <div class="ddt-list-toolbar">
                            <div class="ddt-search-wrap">
                                <input type="text" id="dest_search" class="form-control form-control-sm" placeholder="Cerca destinatario...">
                                <i class="bi bi-search"></i>
                            </div>
                            <a href="{{ url_for('manage_destinatari') }}" class="btn btn-outline-secondary btn-sm" target="_blank" title="Gestisci rubrica destinatari">
                                <i class="bi bi-pencil"></i>
                            </a>
                        </div>

                        <select class="form-select" name="dest_key" id="dest_key" size="7">
                            {% for k, v in destinatari.items() %}
                            <option value="{{ k }}"
                                    data-search="{{ (k ~ ' ' ~ (v.ragione_sociale or '') ~ ' ' ~ (v.indirizzo or '') ~ ' ' ~ (v.citta or ''))|lower }}"
                                    data-ragione="{{ v.ragione_sociale or '' }}"
                                    data-indirizzo="{{ v.indirizzo or '' }}"
                                    data-citta="{{ v.citta or '' }}">
                                {{ k }}{% if v.ragione_sociale %} - {{ v.ragione_sociale }}{% endif %}
                            </option>
                            {% endfor %}
                        </select>

                        <div id="dest_saved_preview" class="ddt-preview-box small mt-2">
                            Seleziona un destinatario dalla lista.
                        </div>
                    </div>
                </div>

                <div class="ddt-recipient-card" id="box_dest_manual">
                    <div class="ddt-card-head">
                        <div>
                            <div class="fw-bold">Destinatario occasionale <span class="text-muted fw-normal">(da non salvare)</span></div>
                            <p class="ddt-helper">Compila solo per questo DDT.</p>
                        </div>
                        <button type="button" class="btn btn-outline-success btn-sm" id="btn_use_manual">
                            <i class="bi bi-person-plus"></i> Usa occasionale
                        </button>
                    </div>
                    <div class="card-body p-2">
                        <div class="mb-2">
                            <input type="text" name="dest_ragione_manual" id="dest_ragione_manual" class="form-control form-control-sm" placeholder="Ragione sociale destinatario *">
                        </div>
                        <div class="mb-2">
                            <textarea name="dest_indirizzo_manual" id="dest_indirizzo_manual" class="form-control form-control-sm" rows="2" placeholder="Indirizzo" autocomplete="off" style="position:relative; z-index:5; pointer-events:auto;"></textarea>
                            <div class="form-text small">Puoi scrivere anche su più righe.</div>
                        </div>
                        <div>
                            <textarea name="dest_citta_manual" id="dest_citta_manual" class="form-control form-control-sm" rows="2" placeholder="Città / CAP / Prov." autocomplete="off" style="position:relative; z-index:5; pointer-events:auto;"></textarea>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ✅ COLONNA DATI DDT -->
            <div class="col-lg-8 col-xl-8">
                <div class="row g-3 align-items-start">
                    <div class="col-md-5">
                        <div class="ddt-field-card">
                            <label class="form-label">N. DDT</label>
                            <div class="input-group">
                                <button class="btn btn-outline-secondary" type="button" id="get-prev-ddt" title="Numero precedente">
                                    <i class="bi bi-arrow-left"></i>
                                </button>
                                <input name="n_ddt" id="n_ddt_input" class="form-control text-center" value="{{ n_ddt }}" required>
                                <button class="btn btn-outline-secondary" type="button" id="get-next-ddt" title="Numero successivo">
                                    <i class="bi bi-arrow-right"></i>
                                </button>
                            </div>
                            <div class="form-text">Usa ⬅️/➡️ per cambiare progressivo.</div>
                        </div>
                    </div>

                    <div class="col-md-3">
                        <div class="ddt-field-card">
                            <label class="form-label">Data DDT</label>
                            <input name="data_ddt" id="data_ddt" type="date" class="form-control" value="{{ oggi }}" required>
                        </div>
                    </div>

                    <div class="col-md-4">
                        <div class="ddt-field-card">
                            <label class="form-label">Targa</label>
                            <input name="targa" class="form-control" placeholder="Inserisci targa (opzionale)">
                        </div>
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Causale</label>
                        <input name="causale" class="form-control" value="TRASFERIMENTO">
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Porto</label>
                        <input name="porto" class="form-control" value="FRANCO">
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Aspetto</label>
                        <input name="aspetto" class="form-control" value="A VISTA">
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Trasportatore interno</label>
                        <input name="trasportatore_interno" class="form-control" placeholder="Es. Donato">
                        <div class="form-text">Salvato nei Trasporti, non stampato sul DDT cliente.</div>
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Mezzo per Giacenze</label>
                        <select name="mezzo_giacenze" id="mezzo_giacenze" class="form-select">
                            <option value="" selected>-- Seleziona --</option>
                            <option value="MOTRICE">Motrice</option>
                            <option value="BILICO">Bilico</option>
                            <option value="FURGONE">Furgone</option>
                        </select>
                        <div class="form-text">Obbligatorio solo per Fincantieri, Fincantieri Scoperto e Fincantieri Armatore.</div>
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Mezzo per Trasporti</label>
                        <input name="mezzo_trasporti" id="mezzo_trasporti" class="form-control" placeholder="Es. Motrice / Bilico / Furgone / Corriere">
                        <div class="form-text">Obbligatorio solo per Fincantieri, Fincantieri Scoperto e Fincantieri Armatore.</div>
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Costo trasporto interno €</label>
                        <input name="costo_trasporto" class="form-control" placeholder="Es. 120,00">
                        <div class="form-text">Salvato nei Trasporti, non stampato sul DDT cliente.</div>
                    </div>

                    <div class="col-md-4">
                        <label class="form-label">Note viaggio interne</label>
                        <input name="note_viaggio" class="form-control" placeholder="Es. consolidato / viaggio unico">
                    </div>
                </div>
            </div>
        </div>

        <hr style="margin-top:18px; margin-bottom:18px;">

        <div class="mt-3" style="margin-bottom:18px;">
            <h5 class="mb-0" style="font-weight:600;">Articoli nel DDT</h5>
        </div>

        <div class="table-responsive" style="margin-top:8px;">
            <table class="table table-sm table-bordered align-middle">
                <thead class="table-light">
                    <tr>
                        <th>ID</th>
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
                            <textarea class="form-control form-control-sm" name="note_{{ r.id_articolo }}" rows="1">{{ r.note or '' }}</textarea>
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
const nDdtInput = document.getElementById('n_ddt_input');

function cambiaNumeroDdt(delta) {
    if (!nDdtInput) return;
    const raw = (nDdtInput.value || '').trim();
    const match = raw.match(/^(\d+)\s*\/\s*(\d{2})$/);
    let numero;
    let anno;

    if (match) {
        numero = parseInt(match[1], 10);
        anno = match[2];
    } else {
        numero = 1;
        anno = String(new Date().getFullYear()).slice(-2);
    }

    numero = Math.max(1, numero + delta);
    nDdtInput.value = String(numero).padStart(2, '0') + '/' + anno;
    nDdtInput.dispatchEvent(new Event('change', { bubbles: true }));
}

const btnNextDdt = document.getElementById('get-next-ddt');
const btnPrevDdt = document.getElementById('get-prev-ddt');
if (btnNextDdt) btnNextDdt.addEventListener('click', function() { cambiaNumeroDdt(1); });
if (btnPrevDdt) btnPrevDdt.addEventListener('click', function() { cambiaNumeroDdt(-1); });

function escapeHtml(value) {
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function updateDestSavedPreview() {
    const sel = document.getElementById('dest_key');
    const box = document.getElementById('dest_saved_preview');
    if (!sel || !box) return;

    const opt = sel.options[sel.selectedIndex];
    if (!opt) {
        box.innerHTML = 'Seleziona un destinatario dalla lista.';
        return;
    }

    const ragione = opt.dataset.ragione || opt.text || '';
    const indirizzo = opt.dataset.indirizzo || '';
    const citta = opt.dataset.citta || '';

    box.innerHTML = `
        <div class="ddt-preview-row"><div class="ddt-preview-label">Ragione sociale</div><div class="ddt-preview-value">${escapeHtml(ragione)}</div></div>
        <div class="ddt-preview-row"><div class="ddt-preview-label">Indirizzo</div><div class="ddt-preview-value">${escapeHtml(indirizzo)}</div></div>
        <div class="ddt-preview-row mb-0"><div class="ddt-preview-label">Città / CAP / Prov.</div><div class="ddt-preview-value">${escapeHtml(citta)}</div></div>
    `;
}

function setDestSource(source) {
    const hidden = document.getElementById('dest_source');
    const savedBox = document.getElementById('box_dest_saved');
    const manualBox = document.getElementById('box_dest_manual');
    const savedBtn = document.getElementById('btn_use_saved');
    const manualBtn = document.getElementById('btn_use_manual');

    hidden.value = source;

    if (source === 'manual') {
        savedBox.classList.remove('active');
        manualBox.classList.add('manual-active');
        savedBtn.className = 'btn btn-outline-primary btn-sm';
        manualBtn.className = 'btn btn-success btn-sm';
        const active = document.activeElement;
        const isManualField = active && ['dest_ragione_manual','dest_indirizzo_manual','dest_citta_manual'].includes(active.id);
        if (!isManualField) document.getElementById('dest_ragione_manual').focus();
    } else {
        manualBox.classList.remove('manual-active');
        savedBox.classList.add('active');
        manualBtn.className = 'btn btn-outline-success btn-sm';
        savedBtn.className = 'btn btn-primary btn-sm';
        updateDestSavedPreview();
    }
}

function filterDestinatari() {
    const search = (document.getElementById('dest_search').value || '').toLowerCase().trim();
    const sel = document.getElementById('dest_key');
    if (!sel) return;

    let firstVisible = -1;
    for (let i = 0; i < sel.options.length; i++) {
        const opt = sel.options[i];
        const haystack = (opt.dataset.search || opt.text || '').toLowerCase();
        const visible = !search || haystack.includes(search);
        opt.hidden = !visible;
        opt.disabled = !visible;
        if (visible && firstVisible === -1) firstVisible = i;
    }

    if (firstVisible >= 0 && (sel.selectedIndex < 0 || sel.options[sel.selectedIndex].hidden)) {
        sel.selectedIndex = firstVisible;
    }
    updateDestSavedPreview();
}

const destSelect = document.getElementById('dest_key');
if (destSelect) {
    if (destSelect.options.length && !destSelect.value) {
        destSelect.selectedIndex = 0;
    }
    destSelect.addEventListener('change', function() {
        updateDestSavedPreview();
        setDestSource('saved');
    });
    destSelect.addEventListener('click', function() {
        setDestSource('saved');
    });
}

const destSearch = document.getElementById('dest_search');
if (destSearch) {
    destSearch.addEventListener('input', filterDestinatari);
}

document.getElementById('btn_use_saved').addEventListener('click', function() {
    setDestSource('saved');
});

document.getElementById('btn_use_manual').addEventListener('click', function() {
    setDestSource('manual');
});

['dest_ragione_manual', 'dest_indirizzo_manual', 'dest_citta_manual'].forEach(function(id) {
    const el = document.getElementById(id);
    if (el) {
        ['input','focus','click'].forEach(function(evt){
            el.addEventListener(evt, function(){ setDestSource('manual'); });
        });
        el.removeAttribute('readonly');
        el.removeAttribute('disabled');
        el.style.pointerEvents = 'auto';
        el.style.position = 'relative';
        el.style.zIndex = '5';
    }
});

updateDestSavedPreview();
setDestSource('saved');

function confermaFinalizzazioneDdt() {
    const nDdt = (document.getElementById('n_ddt_input')?.value || '').trim();
    const destSource = (document.getElementById('dest_source')?.value || 'saved');

    if (!nDdt) {
        alert('⚠️ Inserisci il numero DDT prima di continuare.');
        return false;
    }

    if (destSource === 'manual') {
        const nome = (document.getElementById('dest_ragione_manual')?.value || '').trim();
        if (!nome) {
            alert('⚠️ Inserisci almeno la ragione sociale del destinatario occasionale.');
            return false;
        }
    } else {
        const key = (document.getElementById('dest_key')?.value || '').trim();
        if (!key) {
            alert('⚠️ Seleziona un destinatario salvato.');
            return false;
        }
    }

    const richiedeMezzi = (document.getElementById('ddt_cliente_richiede_mezzi')?.value || '0') === '1';
    const skipMezzi = !!document.getElementById('skip_mezzi_trasporti')?.checked;
    if (richiedeMezzi && !skipMezzi) {
        const mezzoG = (document.getElementById('mezzo_giacenze')?.value || '').trim();
        const mezzoT = (document.getElementById('mezzo_trasporti')?.value || '').trim();
        if (!mezzoG) {
            alert('⚠️ Seleziona il Mezzo per Giacenze.');
            return false;
        }
        if (!mezzoT) {
            alert('⚠️ Inserisci il Mezzo per Trasporti.');
            return false;
        }
    }

    return confirm('Confermi la creazione del DDT N. ' + nDdt + '?');
}

</script>
{% endblock %}
"""


DDT_MEZZO_USCITA_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width:520px; margin-top:30px;">
  <div class="card shadow-sm">
    <div class="card-body">
      <h5 class="mb-2"><i class="bi bi-truck"></i> Mezzo in uscita</h5>

      {% if n_ddt %}
      <div class="alert alert-info py-2">
        DDT Uscita: <b>{{ n_ddt }}</b>
      </div>
      {% endif %}

      <form method="POST">
        <input type="hidden" name="ids" value="{{ ids }}">
        <input type="hidden" name="n_ddt" value="{{ n_ddt }}">

        <label class="form-label fw-bold">Seleziona mezzo *</label>
        <select name="mezzo" class="form-select" required>
          <option value="" selected disabled>-- Seleziona --</option>
          <option value="Motrice">Motrice</option>
          <option value="Bilico">Bilico</option>
          <option value="Furgone">Furgone</option>
        </select>

        <div class="d-flex justify-content-end mt-3">
          <button type="submit" class="btn btn-primary">
            <i class="bi bi-save"></i> Salva
          </button>
        </div>
      </form>

      <div class="text-muted small mt-3">
        Compilazione obbligatoria per aggiornare la colonna <b>Mezzo in uscita</b> nelle righe selezionate.
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""
DDT_MEZZO_USCITA_OK_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="container" style="max-width:520px; margin-top:30px;">
  <div class="alert alert-success shadow-sm">
    <b>Salvato!</b><br>
    Mezzo in uscita: <b>{{ mezzo }}</b><br>
    Righe aggiornate: <b>{{ count }}</b>
    {% if n_ddt %}<br>DDT: <b>{{ n_ddt }}</b>{% endif %}
  </div>

  <script>
    setTimeout(function(){ window.close(); }, 900);
  </script>
</div>
{% endblock %}
"""




ACCETTAZIONE_ENTRATA_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container-fluid py-3">
  <div class="card shadow-sm p-4">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h3 class="mb-0"><i class="bi bi-file-earmark-text"></i> Accettazione entrata da documento</h3>
      <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm">Magazzino</a>
    </div>
    <div class="alert alert-info py-2">
      Carica il DDT dell'autista: il gestionale prova a leggere i dati principali. Dopo il controllo crea le righe in giacenza con formato <b>770/26 N.1</b>, <b>770/26 N.2</b> ecc. Codice articolo, descrizione, protocollo e foto restano da completare dopo.
    </div>

    <form method="post" enctype="multipart/form-data" class="row g-3">
      <div class="col-md-4">
        <label class="form-label fw-bold">Documento DDT / bolla</label>
        <input type="file" name="documento" class="form-control" accept=".pdf,.jpg,.jpeg,.png,.webp" {% if not extracted %}required{% endif %}>
        <div class="form-text">PDF OCR/testuale consigliato. Se il PDF è solo immagine puoi compilare i dati manualmente.</div>
      </div>
      <div class="col-md-2 d-flex align-items-end">
        <button class="btn btn-primary w-100" name="azione" value="leggi" type="submit"><i class="bi bi-magic"></i> Leggi documento</button>
      </div>

      {% if extracted %}
      <div class="col-12"><hr></div>
      {% endif %}

      <div class="col-md-3">
        <label class="form-label fw-bold">N. Arrivo *</label>
        <input name="n_arrivo" class="form-control" placeholder="Es. 770/26" value="{{ data.n_arrivo or '' }}" required>
      </div>
      <div class="col-md-3">
        <label class="form-label">Cliente *</label>
        <input class="form-control" list="clienti-datalist-acc" name="cliente" value="{{ data.cliente or '' }}" required>
        <datalist id="clienti-datalist-acc">
          {% for c in clienti %}<option value="{{ c }}">{% endfor %}
        </datalist>
      </div>
      <div class="col-md-3">
        <label class="form-label">Fornitore</label>
        <input name="fornitore" class="form-control" value="{{ data.fornitore or '' }}">
      </div>
      <div class="col-md-3">
        <label class="form-label">DDT ingresso</label>
        <input name="n_ddt_ingresso" class="form-control" value="{{ data.n_ddt_ingresso or '' }}">
      </div>
      <div class="col-md-3">
        <label class="form-label">Data ingresso</label>
        <input name="data_ingresso" class="form-control" placeholder="gg/mm/aaaa" value="{{ data.data_ingresso or today_ita }}">
      </div>
      <div class="col-md-2">
        <label class="form-label fw-bold">Colli *</label>
        <input name="colli" type="number" min="1" class="form-control" value="{{ data.colli or 1 }}" required>
      </div>
      <div class="col-md-2">
        <label class="form-label">Peso totale kg</label>
        <input name="peso_totale" class="form-control" value="{{ data.peso_totale or '' }}">
      </div>
      <div class="col-md-2">
        <label class="form-label">Magazzino</label>
        <input name="magazzino" class="form-control" value="{{ data.magazzino or 'STRUPPA' }}">
      </div>
      <div class="col-md-2">
        <label class="form-label">Stato</label>
        <input name="stato" class="form-control" value="{{ data.stato or 'DA COMPLETARE' }}">
      </div>
      <div class="col-md-12">
        <label class="form-label">Note</label>
        <input name="note" class="form-control" value="{{ data.note or '' }}" placeholder="Eventuali note interne">
      </div>

      <input type="hidden" name="tmp_doc_path" value="{{ tmp_doc_path or '' }}">
      <input type="hidden" name="tmp_doc_name" value="{{ tmp_doc_name or '' }}">

      <div class="col-12 alert alert-warning py-2 small mb-0">
        <b>Modalità manuale sempre attiva:</b> puoi correggere tutti i campi prima di confermare. La creazione non compila codice articolo, descrizione e protocollo.
      </div>

      <div class="col-12 d-flex gap-2 flex-wrap mt-3">
        <button class="btn btn-success" name="azione" value="crea" type="submit"><i class="bi bi-check-circle"></i> Conferma e crea entrata</button>
        <a href="{{ url_for('labels_form') }}" class="btn btn-outline-primary"><i class="bi bi-tag"></i> Vai a Etichette manuali</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

LABELS_FORM_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="card p-4">
    <h3><i class="bi bi-tag"></i> Nuova Etichetta</h3>
    <hr>

    <div class="alert alert-info py-2">
        <i class="bi bi-info-circle"></i>
        Il PDF verrà <b>scaricato</b> automaticamente: aprilo e stampa dal file scaricato per mantenere il formato <b>100x62mm</b>.
    </div>

    <form method="post" action="{{ url_for('labels_pdf') }}">
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
            <div class="col-md-4"><label class="form-label">Data Ingresso</label><input name="data_ingresso" class="form-control" placeholder="gg/mm/aaaa" value="{{ today_ita }}"></div>
            <div class="col-md-4"><label class="form-label">Arrivo (es. 01/25)</label><input name="arrivo" class="form-control" required></div>
            <div class="col-md-4"><label class="form-label">Codice Entrata / Barcode (facoltativo)</label><input name="codice_entrata" class="form-control" placeholder="Se vuoto, viene creato in modo stabile da data + arrivo/DDT"></div>
            <div class="col-md-4"><label class="form-label">N. Colli</label><input name="n_colli" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Posizione</label><input name="posizione" class="form-control"></div>
            <div class="col-md-4"><label class="form-label">Magazzino</label><input name="magazzino" class="form-control" value="STRUPPA"></div>
            <div class="col-md-4"><label class="form-label">Stato</label><input name="stato" class="form-control" value="NAZIONALE"></div>
        </div>

        <div class="mt-3 alert alert-warning py-2 small">
            <b>Importante:</b> restano attive tutte le modalità manuali.
            Puoi creare solo l'etichetta, inserire solo l'entrata, oppure fare entrambe le cose insieme.
            L'entrata rapida crea una riga per ogni collo con formato <b>770/26 N.1, 770/26 N.2...</b>;
            codice articolo, descrizione, protocollo, foto e documento restano vuoti e li completi dopo.
        </div>

        <div class="mt-4 d-flex gap-2 flex-wrap">
            <button type="submit" name="azione_etichetta" value="solo_etichetta" class="btn btn-primary">
                <i class="bi bi-printer"></i> Crea Etichetta
            </button>
            <button type="submit" name="azione_etichetta" value="inserisci_entrata" class="btn btn-success">
                <i class="bi bi-box-arrow-in-down"></i> Inserisci Entrata
            </button>
            <button type="submit" name="azione_etichetta" value="etichetta_e_entrata" class="btn btn-warning">
                <i class="bi bi-lightning-charge"></i> Crea Etichetta + Inserisci Entrata
            </button>
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
          <div class="col-md-6">
            <label class="form-label">Nome Chiave (es. FINCANTIERI)</label>
            <input name="key_name" class="form-control" required>
          </div>
          <div class="col-md-6">
            <label class="form-label">Ragione Sociale</label>
            <input name="ragione_sociale" class="form-control" required>
          </div>
          <div class="col-md-6">
            <label class="form-label">Indirizzo Completo</label>
            <input name="indirizzo" class="form-control">
          </div>
          <div class="col-md-6">
            <label class="form-label">Partita IVA</label>
            <input name="piva" class="form-control">
          </div>
        </div>

        <button type="submit" class="btn btn-primary mt-3">
          <i class="bi bi-plus-lg"></i> Aggiungi
        </button>
      </form>

      <hr>
      <h5>Destinatari Esistenti</h5>

      <ul class="list-group">
        {% for key, details in destinatari.items() %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <div>
            <strong>{{ key }}</strong><br>
            <small class="text-muted">
              {{ details.ragione_sociale or '' }}{% if details.indirizzo %} - {{ details.indirizzo }}{% endif %}
            </small>
          </div>

          <!-- ✅ ELIMINAZIONE CORRETTA: POST alla stessa pagina -->
          <form method="post" class="m-0">
            <input type="hidden" name="delete_key" value="{{ key }}">
            <button type="submit"
                    class="btn btn-sm btn-outline-danger"
                    onclick="return confirm('Sei sicuro di voler eliminare questo destinatario?')">
              <i class="bi bi-trash"></i>
            </button>
          </form>
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

RUBRICA_EMAIL_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-10 col-lg-9">
    <div class="card p-4 shadow-sm">
      <div class="d-flex justify-content-between align-items-center">
        <h3 class="mb-0"><i class="bi bi-journal-bookmark"></i> Rubrica Email</h3>
        <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Torna alla Home</a>
      </div>
      <hr>

      <div class="row g-4">
        <div class="col-md-6">
          <h5>Contatti</h5>
          <form method="post" class="row g-2 mb-3">
            <input type="hidden" name="action" value="save_contact">
            <div class="col-5">
              <input class="form-control" name="nome" placeholder="Nome (es. Ufficio Genova)">
            </div>
            <div class="col-7">
              <input class="form-control" name="email" placeholder="email@dominio.it">
            </div>
            <div class="col-12 d-grid">
              <button class="btn btn-primary btn-sm">Salva Contatto</button>
            </div>
          </form>

          <div class="table-responsive">
            <table class="table table-sm table-striped align-middle">
              <thead class="table-light">
                <tr><th>Nome</th><th>Email</th><th class="text-end">Azioni</th></tr>
              </thead>
              <tbody>
              {% for nome, info in rubrica.contatti.items() %}
                <tr>
                  <td>{{ nome }}</td>
                  <td>{{ info.email }}</td>
                  <td class="text-end">
                    <form method="post" class="d-inline">
                      <input type="hidden" name="action" value="delete_contact">
                      <input type="hidden" name="nome" value="{{ nome }}">
                      <button class="btn btn-outline-danger btn-sm" onclick="return confirm('Eliminare contatto?')">
                        <i class="bi bi-trash"></i>
                      </button>
                    </form>
                  </td>
                </tr>
              {% else %}
                <tr><td colspan="3" class="text-center text-muted">Nessun contatto.</td></tr>
              {% endfor %}
              </tbody>
            </table>
          </div>
          <div class="form-text">
            Suggerimento: nei gruppi puoi incollare una lista di email separate da <b>;</b> o <b>,</b>.
          </div>
        </div>

        <div class="col-md-6">
          <h5>Gruppi</h5>
          <form method="post" class="mb-3">
            <input type="hidden" name="action" value="save_group">
            <div class="mb-2">
              <input class="form-control" name="gruppo" placeholder="Nome gruppo (es. FINCANTIERI)">
            </div>
            <div class="mb-2">
              <textarea class="form-control" name="emails" rows="3" placeholder="email1@...; email2@..."></textarea>
            </div>
            <button class="btn btn-success btn-sm w-100">Salva Gruppo</button>
          </form>

          <div class="accordion" id="accGruppi">
            {% for g, emails in rubrica.gruppi.items() %}
            <div class="accordion-item">
              <h2 class="accordion-header" id="h{{ loop.index }}">
                <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#c{{ loop.index }}">
                  {{ g }} <span class="badge bg-secondary ms-2">{{ emails|length }}</span>
                </button>
              </h2>
              <div id="c{{ loop.index }}" class="accordion-collapse collapse" data-bs-parent="#accGruppi">
                <div class="accordion-body">
                  <div class="small text-muted mb-2">Email del gruppo:</div>
                  <div class="border rounded p-2 small mb-2 bg-light">
                    {% if emails %}
                      {% for em in emails %}
                        <div class="d-flex justify-content-between align-items-center border-bottom py-1">
                          <span style="word-break:break-all;">{{ em }}</span>
                          <form method="post" class="ms-2 mb-0"
                                onsubmit="return confirm('Eliminare questa email dal gruppo?');">
                            <input type="hidden" name="action" value="delete_email_from_group">
                            <input type="hidden" name="gruppo" value="{{ g }}">
                            <input type="hidden" name="email" value="{{ em }}">
                            <button class="btn btn-outline-danger btn-sm" title="Elimina email dal gruppo">
                              <i class="bi bi-x-lg"></i>
                            </button>
                          </form>
                        </div>
                      {% endfor %}
                    {% else %}
                      <span class="text-muted">Nessuna email nel gruppo.</span>
                    {% endif %}
                  </div>

                  <button class="btn btn-outline-primary btn-sm mb-2" type="button"
                          data-bs-toggle="collapse" data-bs-target="#modificaGruppo{{ loop.index }}">
                    <i class="bi bi-pencil-square"></i> Modifica gruppo
                  </button>

                  <div class="collapse" id="modificaGruppo{{ loop.index }}">
                    <form method="post" class="border rounded p-2 bg-light mb-2">
                      <input type="hidden" name="action" value="add_email_to_group">
                      <input type="hidden" name="gruppo" value="{{ g }}">
                      <label class="form-label small fw-bold mb-1">Aggiungi destinatario al gruppo</label>
                      <input class="form-control form-control-sm mb-2" name="nome_contatto"
                             placeholder="Nome contatto opzionale">
                      <input class="form-control form-control-sm mb-2" name="nuovo_destinatario"
                             placeholder="nuova@email.it oppure più email separate da ;">
                      <button class="btn btn-primary btn-sm w-100">
                        <i class="bi bi-plus-circle"></i> Aggiungi al gruppo
                      </button>
                    </form>
                  </div>

                  <form method="post" class="mt-2">
                    <input type="hidden" name="action" value="delete_group">
                    <input type="hidden" name="gruppo" value="{{ g }}">
                    <button class="btn btn-outline-danger btn-sm" onclick="return confirm('Eliminare gruppo?')">
                      <i class="bi bi-trash"></i> Elimina gruppo
                    </button>
                  </form>
                </div>
              </div>
            </div>
            {% else %}
              <div class="text-muted">Nessun gruppo.</div>
            {% endfor %}
          </div>

        </div>
      </div>

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
        <a href="{{ url_for('home') }}" class="btn btn-secondary shadow-sm"><i class="bi bi-box-arrow-left"></i> Esci</a>
    </div>

    <div class="card p-3 mb-4 bg-light border shadow-sm">
        {% if edit_row %}
            <h5 class="mb-3 text-primary"><i class="bi bi-pencil-square"></i> Modifica Picking ID {{ edit_row.id }}</h5>
        {% else %}
            <h5 class="mb-3">Inserisci Nuovo Picking</h5>
        {% endif %}

        <form method="POST" class="row g-2">
            {% if edit_row %}
                <input type="hidden" name="edit_lavorazione" value="1">
                <input type="hidden" name="id" value="{{ edit_row.id }}">
            {% else %}
                <input type="hidden" name="add_lavorazione" value="1">
            {% endif %}

            <div class="col-md-2">
                <label class="small fw-bold">Data</label>
                <input type="date" name="data" class="form-control" required
                       value="{% if edit_row and edit_row.data %}{{ edit_row.data }}{% else %}{{ today }}{% endif %}">
            </div>

            <div class="col-md-2"><label class="small fw-bold">Cliente</label>
                <input type="text" name="cliente" class="form-control" list="clientiUtentiListPicking"
                       value="{{ edit_row.cliente if edit_row else '' }}" required>
                <datalist id="clientiUtentiListPicking">
                    {% for c in clienti_validi %}<option value="{{ c }}">{% endfor %}
                </datalist>
            </div>

            <div class="col-md-3"><label class="small fw-bold">Descrizione</label>
                <input type="text" name="descrizione" class="form-control"
                       value="{{ edit_row.descrizione if edit_row else '' }}">
            </div>

            <div class="col-md-2"><label class="small fw-bold">Richiesta Di</label>
                <input type="text" name="richiesta_di" class="form-control"
                       value="{{ edit_row.richiesta_di if edit_row else '' }}">
            </div>

            <div class="col-md-2"><label class="small fw-bold">Seriali / Buono</label>
                <input type="text" name="seriali" class="form-control"
                       value="{{ edit_row.seriali if edit_row else '' }}">
            </div>

            <div class="col-md-2"><label class="small fw-bold">N. Arrivo</label>
                <input type="text" name="n_arrivo" class="form-control"
                       value="{{ edit_row.n_arrivo if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Colli</label>
                <input type="number" name="colli" class="form-control"
                       value="{{ edit_row.colli if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Pallet Entrati</label>
                <input type="number" name="pallet_forniti" class="form-control"
                       value="{{ edit_row.pallet_forniti if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Pallet Usciti</label>
                <input type="number" name="pallet_uscita" class="form-control"
                       value="{{ edit_row.pallet_uscita if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Ore Blue</label>
                <input type="number" step="0.5" name="ore_blue_collar" class="form-control"
                       value="{{ edit_row.ore_blue_collar if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Ore White</label>
                <input type="number" step="0.5" name="ore_white_collar" class="form-control"
                       value="{{ edit_row.ore_white_collar if edit_row else '' }}">
            </div>

            <div class="col-md-12 text-end mt-2">
                {% if edit_row %}
                    <a href="{{ url_for('lavorazioni') }}" class="btn btn-secondary fw-bold">Annulla</a>
                    <button type="submit" class="btn btn-primary fw-bold">
                        <i class="bi bi-save"></i> Salva Modifica
                    </button>
                {% else %}
                    <button type="submit" class="btn btn-success fw-bold">
                        <i class="bi bi-plus-lg"></i> Aggiungi
                    </button>
                {% endif %}
            </div>
        </form>
    </div>

    <div class="card p-3 mb-3 border-warning shadow-sm">
        <h6 class="text-warning-emphasis fw-bold"><i class="bi bi-printer"></i> Stampa Report Picking</h6>
        <form action="{{ url_for('stampa_picking_pdf') }}" method="POST" target="_blank" class="row g-2 align-items-end">
            <div class="col-md-2">
                <label class="small">Mese (es. 2025-01)</label>
                <input type="month" name="mese" class="form-control form-control-sm">
            </div>
            <div class="col-md-3">
                <label class="small">Cliente</label>
                <input type="text" name="cliente" class="form-control form-control-sm" placeholder="Tutti">
            </div>
            <div class="col-md-2">
                <button type="submit" class="btn btn-warning btn-sm w-100 fw-bold">Genera PDF</button>
            </div>
        </form>
    </div>

    <div class="card p-3 mb-3 border-warning shadow-sm">
        <h6 class="text-warning-emphasis fw-bold"><i class="bi bi-funnel"></i> Filtri Tabella Picking</h6>
        <form method="GET" action="{{ url_for('lavorazioni') }}" class="row g-2 align-items-end">
            <div class="col-md-2">
                <label class="small">Data da</label>
                <input type="date" name="data_da" class="form-control form-control-sm" value="{{ filtri.get('data_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Data a</label>
                <input type="date" name="data_a" class="form-control form-control-sm" value="{{ filtri.get('data_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Cliente</label>
                <input type="text" name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ filtri.get('cliente','') }}">
            </div>
            <div class="col-md-3">
                <label class="small">Descrizione</label>
                <input type="text" name="descrizione" class="form-control form-control-sm" placeholder="Descrizione" value="{{ filtri.get('descrizione','') }}">
            </div>
            <div class="col-md-3">
                <label class="small">Richiesta di</label>
                <input type="text" name="richiesta_di" class="form-control form-control-sm" placeholder="Richiesta di" value="{{ filtri.get('richiesta_di','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Seriali / Buono</label>
                <input type="text" name="seriali" class="form-control form-control-sm" placeholder="Seriali / Buono" value="{{ filtri.get('seriali','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">N. Arrivo</label>
                <input type="text" name="n_arrivo" class="form-control form-control-sm" placeholder="N. Arrivo" value="{{ filtri.get('n_arrivo','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Colli da</label>
                <input type="number" name="colli_da" class="form-control form-control-sm" value="{{ filtri.get('colli_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Colli a</label>
                <input type="number" name="colli_a" class="form-control form-control-sm" value="{{ filtri.get('colli_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Pallet entrati da</label>
                <input type="number" name="pallet_forniti_da" class="form-control form-control-sm" value="{{ filtri.get('pallet_forniti_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Pallet entrati a</label>
                <input type="number" name="pallet_forniti_a" class="form-control form-control-sm" value="{{ filtri.get('pallet_forniti_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Pallet usciti da</label>
                <input type="number" name="pallet_uscita_da" class="form-control form-control-sm" value="{{ filtri.get('pallet_uscita_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Pallet usciti a</label>
                <input type="number" name="pallet_uscita_a" class="form-control form-control-sm" value="{{ filtri.get('pallet_uscita_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Ore Blue da</label>
                <input type="text" name="ore_blue_da" class="form-control form-control-sm" placeholder="0,0" value="{{ filtri.get('ore_blue_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Ore Blue a</label>
                <input type="text" name="ore_blue_a" class="form-control form-control-sm" placeholder="0,0" value="{{ filtri.get('ore_blue_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Ore White da</label>
                <input type="text" name="ore_white_da" class="form-control form-control-sm" placeholder="0,0" value="{{ filtri.get('ore_white_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Ore White a</label>
                <input type="text" name="ore_white_a" class="form-control form-control-sm" placeholder="0,0" value="{{ filtri.get('ore_white_a','') }}">
            </div>
            <div class="col-md-2 d-grid">
                <button type="submit" class="btn btn-warning btn-sm fw-bold">
                    <i class="bi bi-search"></i> Filtra
                </button>
            </div>
            <div class="col-md-2 d-grid">
                <a href="{{ url_for('lavorazioni') }}" class="btn btn-outline-secondary btn-sm fw-bold">
                    Reset
                </a>
            </div>
        </form>
    </div>

    <div class="card shadow-sm">
        <div class="table-responsive">
            <table class="table table-bordered table-hover mb-0 align-middle">
                <thead class="table-light" style="color:#000;">
                    <tr>
                        <th>Data</th><th>Cliente</th><th>Descrizione</th>
                        <th>Richiesta</th><th>Seriali/Buono</th><th>N. Arrivo</th><th>Colli</th>
                        <th>Pallet Entrati</th><th>Pallet Usciti</th>
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
                        <td>{{ l.n_arrivo or '' }}</td>
                        <td>{{ l.colli or '' }}</td>
                        <td>{{ l.pallet_forniti or '' }}</td>
                        <td>{{ l.pallet_uscita or '' }}</td>
                        <td>{{ l.ore_blue_collar or '' }}</td>
                        <td>{{ l.ore_white_collar or '' }}</td>
                        <td class="d-flex gap-1">
                            {% if session.get('role') == 'admin' %}
                            <a href="{{ url_for('lavorazioni', edit_id=l.id) }}"
                               class="btn btn-sm btn-primary"
                               title="Modifica">
                               <i class="bi bi-pencil"></i>
                            </a>
                            <a href="{{ url_for('elimina_record', table='lavorazioni', id=l.id) }}"
                               class="btn btn-sm btn-danger"
                               onclick="return confirm('Sei sicuro di voler eliminare?')"
                               title="Elimina"><i class="bi bi-trash"></i></a>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="12" class="text-center text-muted">Nessuna attività registrata.</td></tr>
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

  <h2>
    <i class="bi bi-calculator"></i>
    {% if metric == 'colli' %}
      Report Costi Magazzino (Colli in giacenza)
    {% else %}
      Report Costi Magazzino (M² per cliente)
    {% endif %}
  </h2>

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

              {% if metric == 'colli' %}
                <th class="text-end">Colli Tot</th>
                <th class="text-end">Colli Medio</th>
              {% else %}
                <th class="text-end">M² Tot</th>
                <th class="text-end">M² Medio</th>
              {% endif %}

              <th class="text-center">Giorni</th>
            </tr>
          </thead>
          <tbody>
            {% for r in risultati %}
            <tr>
              <td class="text-center">{{ r.periodo }}</td>
              <td>{{ r.cliente }}</td>
              <td class="text-end">{{ r.tot }}</td>
              <td class="text-end">{{ r.medio }}</td>
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
        <a href="{{ url_for('home') }}" class="btn btn-secondary shadow-sm">
            <i class="bi bi-box-arrow-left"></i> Esci
        </a>
    </div>

    <div class="card p-3 mb-4 bg-light border shadow-sm">
        {% if edit_row %}
            <h5 class="mb-3 text-primary"><i class="bi bi-pencil-square"></i> Modifica Trasporto ID {{ edit_row.id }}</h5>
        {% else %}
            <h5 class="mb-3 text-success"><i class="bi bi-plus-circle"></i> Inserisci Nuovo Trasporto</h5>
        {% endif %}

        <form method="POST" class="row g-2">
            {% if edit_row %}
                <input type="hidden" name="edit_trasporto" value="1">
                <input type="hidden" name="id" value="{{ edit_row.id }}">
            {% else %}
                <input type="hidden" name="add_trasporto" value="1">
            {% endif %}

            <div class="col-md-2">
                <label class="small fw-bold">Data</label>
                <input type="date" name="data" class="form-control" required
                       value="{% if edit_row and edit_row.data %}{{ edit_row.data }}{% else %}{{ today }}{% endif %}">
            </div>

            <div class="col-md-2"><label class="small fw-bold">Tipo Mezzo</label>
                <input type="text" name="tipo_mezzo" class="form-control"
                       value="{{ edit_row.tipo_mezzo if edit_row else '' }}" placeholder="es. Bilico">
            </div>

            <div class="col-md-2"><label class="small fw-bold">Cliente</label>
                <input type="text" name="cliente" class="form-control" list="clientiUtentiListPicking"
                       value="{{ edit_row.cliente if edit_row else '' }}" required>
                <datalist id="clientiUtentiListPicking">
                    {% for c in clienti_validi %}<option value="{{ c }}">{% endfor %}
                </datalist>
            </div>

            <div class="col-md-2"><label class="small fw-bold">Trasportatore</label>
                <input type="text" name="trasportatore" class="form-control"
                       value="{{ edit_row.trasportatore if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">N. DDT</label>
                <input type="text" name="ddt_uscita" class="form-control"
                       value="{{ edit_row.ddt_uscita if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Magazzino</label>
                <input type="text" name="magazzino" class="form-control"
                       value="{{ edit_row.magazzino if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Consolidato</label>
                <input type="text" name="consolidato" class="form-control"
                       value="{{ edit_row.consolidato if edit_row else '' }}">
            </div>

            <div class="col-md-1"><label class="small fw-bold">Costo €</label>
                <input type="text" name="costo" class="form-control" placeholder="0,00"
                       value="{% if edit_row and edit_row.costo is not none %}{{ '%.2f'|format(edit_row.costo) }}{% endif %}">
            </div>

            <div class="col-md-12 text-end mt-2">
                {% if edit_row %}
                    <a href="{{ url_for('trasporti') }}" class="btn btn-secondary fw-bold">
                        Annulla
                    </a>
                    <button type="submit" class="btn btn-primary fw-bold px-4">
                        <i class="bi bi-save"></i> Salva Modifica
                    </button>
                {% else %}
                    <button type="submit" class="btn btn-success fw-bold px-4">
                        <i class="bi bi-save"></i> Salva
                    </button>
                {% endif %}
            </div>
        </form>
    </div>

    <div class="card p-3 mb-3 border-primary shadow-sm">
        <h6 class="text-primary fw-bold"><i class="bi bi-printer"></i> Stampa Report PDF</h6>
        <form action="{{ url_for('report_trasporti') }}" method="POST" target="_blank" class="row g-2 align-items-end">
            <div class="col-md-2">
                <label class="small">Seleziona Mese</label>
                <input type="month" name="mese" class="form-control form-control-sm">
            </div>
            <div class="col-md-2">
                <label class="small">Filtra Cliente</label>
                <input type="text" name="cliente" class="form-control form-control-sm" placeholder="Tutti">
            </div>
            <div class="col-md-2">
                <label class="small">Filtra Mezzo</label>
                <input type="text" name="tipo_mezzo" class="form-control form-control-sm" placeholder="Tutti">
            </div>
            <div class="col-md-2">
                <button type="submit" class="btn btn-primary btn-sm w-100 fw-bold">
                    Genera PDF
                </button>
            </div>
        </form>
    </div>

    <div class="card p-3 mb-3 border-info shadow-sm">
        <h6 class="text-info fw-bold"><i class="bi bi-funnel"></i> Filtri Tabella Trasporti</h6>
        <form method="GET" action="{{ url_for('trasporti') }}" class="row g-2 align-items-end">
            <div class="col-md-2">
                <label class="small">Data da</label>
                <input type="date" name="data_da" class="form-control form-control-sm" value="{{ filtri.get('data_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Data a</label>
                <input type="date" name="data_a" class="form-control form-control-sm" value="{{ filtri.get('data_a','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Cliente</label>
                <input type="text" name="cliente" class="form-control form-control-sm" placeholder="Cliente" value="{{ filtri.get('cliente','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Mezzo</label>
                <input type="text" name="tipo_mezzo" class="form-control form-control-sm" placeholder="Mezzo" value="{{ filtri.get('tipo_mezzo','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Trasportatore</label>
                <input type="text" name="trasportatore" class="form-control form-control-sm" placeholder="Trasportatore" value="{{ filtri.get('trasportatore','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">DDT Uscita</label>
                <input type="text" name="ddt_uscita" class="form-control form-control-sm" placeholder="DDT" value="{{ filtri.get('ddt_uscita','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Magazzino</label>
                <input type="text" name="magazzino" class="form-control form-control-sm" placeholder="Magazzino" value="{{ filtri.get('magazzino','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Consolidato</label>
                <input type="text" name="consolidato" class="form-control form-control-sm" placeholder="Consolidato" value="{{ filtri.get('consolidato','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Costo da</label>
                <input type="text" name="costo_da" class="form-control form-control-sm" placeholder="0,00" value="{{ filtri.get('costo_da','') }}">
            </div>
            <div class="col-md-2">
                <label class="small">Costo a</label>
                <input type="text" name="costo_a" class="form-control form-control-sm" placeholder="0,00" value="{{ filtri.get('costo_a','') }}">
            </div>
            <div class="col-md-2 d-grid">
                <button type="submit" class="btn btn-info btn-sm fw-bold">
                    <i class="bi bi-search"></i> Filtra
                </button>
            </div>
            <div class="col-md-2 d-grid">
                <a href="{{ url_for('trasporti') }}" class="btn btn-outline-secondary btn-sm fw-bold">
                    Reset
                </a>
            </div>
        </form>
    </div>

    <div class="card shadow-sm">
        <div class="table-responsive">
            <table class="table table-striped table-hover mb-0 align-middle">
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
                        <td class="d-flex gap-1">
                            {% if session.get('role') == 'admin' %}
                            <a href="{{ url_for('trasporti', edit_id=t.id) }}"
                               class="btn btn-sm btn-primary"
                               title="Modifica">
                               <i class="bi bi-pencil"></i>
                            </a>
                            <a href="{{ url_for('elimina_record', table='trasporti', id=t.id) }}"
                               class="btn btn-sm btn-danger"
                               onclick="return confirm('Sei sicuro di voler eliminare questo trasporto?')"
                               title="Elimina">
                               <i class="bi bi-trash"></i>
                            </a>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="9" class="text-center text-muted py-3">Nessun trasporto inserito.</td></tr>
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
            <h4 class="mb-3"><i class="bi bi-envelope"></i> Invia Email</h4>

            {% if selected_ids %}
            <div class="alert alert-info py-2">
                <i class="bi bi-info-circle"></i> Hai selezionato <strong>{{ selected_ids.split(',')|length }}</strong> articoli.
            </div>
            {% endif %}

            <form method="post" enctype="multipart/form-data">
                <input type="hidden" name="selected_ids" value="{{ selected_ids }}">

                <div class="mb-3">
                    <label class="form-label fw-bold">Destinatari</label>

                    <div class="row g-2 mb-2">
                        <div class="col-md-6">
                            <label class="form-label">Contatto singolo (rubrica)</label>
                            <select id="contatto_email" class="form-select form-select-sm">
                                <option value="">-- Seleziona un contatto --</option>
                                {% for nome, info in (email_contacts or {}).items() %}
                                    <option value="{{ info.email if info.email is defined else info['email'] }}">{{ nome }} - {{ info.email if info.email is defined else info['email'] }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">Gruppo (rubrica)</label>
                            <select id="gruppo_email" class="form-select form-select-sm">
                                <option value="">-- Seleziona un gruppo --</option>
                                {% for g, emails in (email_groups or {}).items() %}
                                    <option value="{{ emails|join('; ') }}">{{ g }} ({{ emails|length }})</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>

                    <input
                        type="text"
                        name="destinatario"
                        class="form-control"
                        placeholder="email1@dominio.it; email2@dominio.it"
                        list="rubricaEmailList"
                        required
                    >

<div class="mb-2">
    <label class="form-label fw-bold">Destinatari aggiuntivi temporanei</label>
    <input type="text" name="destinatari_temp" class="form-control" placeholder="email1@dominio.it; email2@dominio.it">
    <div class="form-text">Questi indirizzi vengono usati solo per questa email e non vengono salvati in rubrica.</div>
</div>

                    <datalist id="rubricaEmailList">
                        {% for nome, info in (email_contacts or {}).items() %}
                            <option value="{{ info.email if info.email is defined else info['email'] }}">{{ nome }}</option>
                        {% endfor %}
                    </datalist>
                    <div class="form-text">
                        Puoi scegliere un contatto singolo, un gruppo, oppure scrivere più destinatari separati con <b>;</b> o <b>,</b>.
                    </div>
                </div>

                <div class="mb-3">
                    <label class="form-label fw-bold">Oggetto</label>
                    <input type="text" name="oggetto" class="form-control" value="Documentazione Merce - Camar S.r.l." required>
                </div>

                <div class="mb-3">
                    <label class="form-label fw-bold">Messaggio</label>
                    <textarea name="messaggio" rows="6" class="form-control" style="font-family: Arial, sans-serif;">Buongiorno,

Di seguito inviamo il riepilogo della merce in oggetto.

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
                        <h6 class="card-title">Opzioni</h6>

                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" name="genera_ddt" id="genera_ddt" checked>
                            <label class="form-check-label" for="genera_ddt">Inserisci Riepilogo Merci in email (tabella)</label>
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

<script>
document.addEventListener('DOMContentLoaded', function(){
  const gruppo = document.getElementById('gruppo_email');
  const contatto = document.getElementById('contatto_email');
  const inp = document.querySelector('input[name="destinatario"]');

  function addEmails(value, replace){
    if(!inp || !value){ return; }
    if(replace || !inp.value.trim()){
      inp.value = value;
      return;
    }
    const current = inp.value.trim();
    inp.value = current.replace(/[;,]\s*$/, '') + '; ' + value;
  }

  if(gruppo && inp){
    gruppo.addEventListener('change', function(){
      addEmails(this.value, true);
    });
  }
  if(contatto && inp){
    contatto.addEventListener('change', function(){
      addEmails(this.value, false);
      this.value = '';
    });
  }
});
</script>
{% endblock %}
"""


templates = {
        'base.html': BASE_HTML,
        'login.html': LOGIN_HTML,
        'home.html': HOME_HTML,
        'scan_entrata.html': SCAN_ENTRATA_HTML,
        'dettaglio_entrata.html': DETTAGLIO_ENTRATA_HTML,
        # 'giacenze.html': GIACENZE_HTML,  # DISATTIVATO: usa templates/giacenze.html esterno
        
        
        'edit.html': EDIT_HTML,  
        
        'bulk_edit.html': BULK_EDIT_HTML,
        # 'buono_preview.html': BUONO_PREVIEW_HTML,  # DISATTIVATO: usa templates/buono_preview.html esterno
        'ddt_preview.html': DDT_PREVIEW_HTML,
        'labels_form.html': LABELS_FORM_HTML,
        'accettazione_entrata.html': ACCETTAZIONE_ENTRATA_HTML,
        'labels_preview.html': LABELS_PREVIEW_HTML,
        
        'import_excel.html': IMPORT_EXCEL_HTML,
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
        'rubrica_email.html': RUBRICA_EMAIL_HTML,
        'calcoli.html': CALCOLI_HTML,
        'report_fatturazione.html': REPORT_FATTURAZIONE_HTML
    }

# ========================================================
# CONFIGURAZIONE FINALE (SENZA RICREARE L'APP)
# ========================================================
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(APP_DIR / 'templates')),
    DictLoader(templates)
])
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
    return dict(logo_url=logo_url(), _row_att_counts=_row_att_counts)



# ========================================================
# REPORT FATTURAZIONE spostato in routes/fatturazione.py
# ========================================================

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
        
        if username in users_db and verify_password(users_db[username], password):
            # 1. Crea l'oggetto utente
            if username in ADMIN_USERS:
                role = 'admin'
            elif username in WAREHOUSE_USERS:
                role = 'magazzino'
            else:
                role = 'client'
            user = User(username, role)
            
            # 2. PUNTO FONDAMENTALE: Effettua il login formale con Flask-Login
            login_user(user)
            
            # 3. Imposta variabili di sessione accessorie
            session['role'] = role
            session['user'] = username
            session['user_name'] = username
            
            flash(f"Benvenuto {username}", "success")
            
            # 4. Dopo il login vai SEMPRE in Home (non alle giacenze)
            return redirect(url_for('home'))
        else:
            flash("Credenziali non valide", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logout effettuato con successo", "success")
    return redirect(url_for('login'))



READONLY_WAREHOUSE_ENDPOINTS = {
    'nuovo_articolo', 'save_articolo', 'delete_rows', 'bulk_edit', 'save_bulk_edit',
    'bulk_duplicate', 'ddt_preview', 'genera_pdf_ddt', 'finalizza_ddt', 'ddt_finale_pdf',
    'buono_preview', 'genera_pdf_buono', 'invia_email', 'import_pdf', 'save_pdf_import',
    'import_excel', 'trasporti', 'lavorazioni', 'fix_db_schema', 'admin_backups',
    'admin_backup_download', 'admin_genera_codici_entrata', 'delete_attachment',
    'delete_row', 'delete_trasporto', 'delete_lavorazione', 'modifica_articolo'
}

@app.before_request
def _warehouse_readonly_guard():
    try:
        if session.get('role') != 'magazzino':
            return None
        ep = request.endpoint or ''
        if ep in READONLY_WAREHOUSE_ENDPOINTS:
            flash('Profilo magazzino in sola lettura: modifica non consentita.', 'warning')
            return redirect(url_for('giacenze'))
    except Exception:
        return None
    return None

@app.route('/')
@app.route('/home')
@login_required
def home():
    """Home alleggerita.

    Prima la Home caricava TUTTI gli articoli e TUTTI gli allegati in memoria
    con q_base.all() + selectinload(attachments). Con molti record/PDF/foto questo
    rendeva la pagina lenta e poteva causare timeout su Render.

    Questa versione usa soprattutto COUNT/SUM direttamente nel database e carica
    solo pochi record per esempi e ultimi movimenti.
    """
    db = SessionLocal()
    try:
        today_obj = date.today()
        today_iso = today_obj.strftime('%Y-%m-%d')
        today_it = today_obj.strftime('%d/%m/%Y')
        cutoff_90_iso = (today_obj - timedelta(days=90)).strftime('%Y-%m-%d')
        cliente_corrente = current_cliente()

        def _cliente_filter(model=Articolo):
            if cliente_corrente:
                return [func.upper(model.cliente) == cliente_corrente.upper()]
            return []

        active_filter = [
            or_(Articolo.data_uscita == None, Articolo.data_uscita == "")
        ] + _cliente_filter(Articolo)

        all_filter = _cliente_filter(Articolo)

        def _scalar(query, default=0):
            try:
                v = query.scalar()
                return default if v is None else v
            except Exception:
                return default

        def _count_articoli(extra_filters=None):
            q = db.query(func.count(Articolo.id_articolo))
            filters = list(extra_filters or [])
            if filters:
                q = q.filter(*filters)
            return int(_scalar(q, 0) or 0)

        def _sum_articoli(column, extra_filters=None):
            q = db.query(func.coalesce(func.sum(column), 0))
            filters = list(extra_filters or [])
            if filters:
                q = q.filter(*filters)
            try:
                return float(q.scalar() or 0)
            except Exception:
                return 0.0

        def _examples(extra_filters, attr, max_items=5):
            try:
                col = getattr(Articolo, attr)
                rows_ex = (
                    db.query(col)
                    .filter(*(extra_filters or []))
                    .filter(col != None, col != "")
                    .limit(max_items)
                    .all()
                )
                out = []
                for (val,) in rows_ex:
                    val = (str(val or "")).strip()
                    if val and val not in out:
                        out.append(val)
                return out[:max_items]
            except Exception:
                return []

        def _add_alert(alerts, level, title, count, message, examples=None):
            try:
                count = int(count or 0)
            except Exception:
                count = 0
            if count > 0:
                alerts.append({
                    'level': level,
                    'title': title,
                    'count': count,
                    'message': message,
                    'examples': examples or []
                })

        dashboard = {
            'tot_giacenza': _count_articoli(active_filter),
            'tot_m2': round(_sum_articoli(Articolo.m2, active_filter), 2),
            'tot_peso': round(_sum_articoli(Articolo.peso, active_filter), 2),
            'tot_colli': int(_sum_articoli(Articolo.n_colli, active_filter)),
            # Supporta sia formato ISO YYYY-MM-DD sia formato italiano DD/MM/YYYY.
            'entrate_oggi': _count_articoli(all_filter + [
                or_(Articolo.data_ingresso == today_iso, Articolo.data_ingresso == today_it)
            ]),
            'uscite_oggi': _count_articoli(all_filter + [
                or_(Articolo.data_uscita == today_iso, Articolo.data_uscita == today_it)
            ]),
            'doganali': _count_articoli(active_filter + [
                func.upper(func.coalesce(Articolo.stato, '')).like('%DOGANA%')
            ]),
            'buoni_aperti': 0,
            'buoni_creati': 0,
            'buoni_usciti': 0,
        }

        def _buoni_base_query():
            q = db.query(func.count(BuonoCarico.id))
            if cliente_corrente:
                q = q.filter(func.upper(func.coalesce(BuonoCarico.cliente, '')) == cliente_corrente.upper())
            return q

        try:
            stato_buono = func.upper(func.coalesce(BuonoCarico.stato, ''))
            dashboard['buoni_creati'] = int(_buoni_base_query().filter(~stato_buono.in_(['ELIMINATO'])).scalar() or 0)
            dashboard['buoni_aperti'] = int(_buoni_base_query().filter(
                ~stato_buono.in_(['CARICATO', 'CHIUSO', 'COMPLETATO', 'ELIMINATO'])
            ).scalar() or 0)
            dashboard['buoni_usciti'] = int(_buoni_base_query().filter(
                stato_buono.in_(['CARICATO', 'CHIUSO', 'COMPLETATO'])
            ).scalar() or 0)
        except Exception:
            dashboard['buoni_aperti'] = 0
            dashboard['buoni_creati'] = 0
            dashboard['buoni_usciti'] = 0

        # Ultimi movimenti: carica poche colonne e pochi record, non tutti gli articoli.
        movimenti = []

        def _add_movimenti_ingresso():
            q = db.query(
                Articolo.data_ingresso, Articolo.cliente, Articolo.codice_articolo,
                Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_ingresso
            ).filter(*(all_filter + [Articolo.data_ingresso != None, Articolo.data_ingresso != ""]))
            q = q.order_by(Articolo.id_articolo.desc()).limit(20)
            for d_in_raw, cli, cod, desc, arr, ddt in q.all():
                d_in = to_date_db(d_in_raw)
                if not d_in:
                    continue
                movimenti.append({
                    'data_sort': d_in,
                    'data': d_in.strftime('%d/%m/%Y'),
                    'tipo': 'Entrata',
                    'cliente': cli or '',
                    'codice': cod or '',
                    'descrizione': (desc or '')[:60],
                    'n_arrivo': arr or '',
                    'ddt': ddt or '',
                })

        def _add_movimenti_uscita():
            q = db.query(
                Articolo.data_uscita, Articolo.cliente, Articolo.codice_articolo,
                Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_uscita
            ).filter(*(all_filter + [Articolo.data_uscita != None, Articolo.data_uscita != ""]))
            q = q.order_by(Articolo.id_articolo.desc()).limit(20)
            for d_out_raw, cli, cod, desc, arr, ddt in q.all():
                d_out = to_date_db(d_out_raw)
                if not d_out:
                    continue
                movimenti.append({
                    'data_sort': d_out,
                    'data': d_out.strftime('%d/%m/%Y'),
                    'tipo': 'Uscita',
                    'cliente': cli or '',
                    'codice': cod or '',
                    'descrizione': (desc or '')[:60],
                    'n_arrivo': arr or '',
                    'ddt': ddt or '',
                })

        try:
            _add_movimenti_ingresso()
            _add_movimenti_uscita()
        except Exception:
            movimenti = []

        ultimi_movimenti = sorted(
            movimenti,
            key=lambda x: x.get('data_sort') or date.min,
            reverse=True
        )[:10]

        # ========================================================
        # ALERT AUTOMATICI HOME - versione ottimizzata
        # ========================================================
        dashboard_alerts = []

        missing_qr_filter = active_filter + [
            or_(Articolo.codice_entrata == None, Articolo.codice_entrata == "")
        ]
        _add_alert(
            dashboard_alerts,
            'danger',
            'QR / codice entrata mancante',
            _count_articoli(missing_qr_filter),
            'Articoli in giacenza senza codice entrata collegato.',
            _examples(missing_qr_filter, 'n_arrivo')
        )

        senza_foto_filter = active_filter + [
            ~Articolo.attachments.any(Attachment.kind == 'photo')
        ]
        senza_pdf_filter = active_filter + [
            ~Articolo.attachments.any(Attachment.kind == 'doc')
        ]

        _add_alert(
            dashboard_alerts,
            'warning',
            'Foto mancante',
            _count_articoli(senza_foto_filter),
            'Articoli in giacenza senza foto arrivo.',
            _examples(senza_foto_filter, 'n_arrivo')
        )

        _add_alert(
            dashboard_alerts,
            'warning',
            'Documento PDF mancante',
            _count_articoli(senza_pdf_filter),
            'Articoli in giacenza senza documento arrivo PDF.',
            _examples(senza_pdf_filter, 'n_arrivo')
        )

        def _duplicate_summary(attr, extra_filters=None, exclude_clienti=None):
            exclude_clienti = {c.upper() for c in (exclude_clienti or [])}
            col = getattr(Articolo, attr)
            filters = list(extra_filters or [])
            filters += [col != None, col != ""]
            if exclude_clienti:
                filters.append(~func.upper(func.coalesce(Articolo.cliente, '')).in_(list(exclude_clienti)))

            try:
                rows_dup = (
                    db.query(col, func.count(Articolo.id_articolo).label('cnt'))
                    .filter(*filters)
                    .group_by(col)
                    .having(func.count(Articolo.id_articolo) > 1)
                    .order_by(func.count(Articolo.id_articolo).desc())
                    .limit(50)
                    .all()
                )
                total_groups = len(rows_dup)
                examples = [str(v or '').strip() for v, c in rows_dup[:5] if str(v or '').strip()]
                return total_groups, examples
            except Exception:
                return 0, []

        dup_arrivi_count, dup_arrivi_examples = _duplicate_summary('n_arrivo', active_filter)
        _add_alert(
            dashboard_alerts,
            'warning',
            'N. arrivo duplicato',
            dup_arrivi_count,
            'Ci sono numeri arrivo ripetuti tra gli articoli ancora in giacenza.',
            dup_arrivi_examples
        )

        dup_serial_count, dup_serial_examples = _duplicate_summary(
            'serial_number',
            active_filter,
            exclude_clienti={'DUFERCO'}
        )
        _add_alert(
            dashboard_alerts,
            'warning',
            'Serial number duplicato',
            dup_serial_count,
            'Ci sono serial number ripetuti tra gli articoli ancora in giacenza, esclusi i clienti dove è ammesso.',
            dup_serial_examples
        )

        # DDT gestionale senza mezzo. Usiamo regex Python solo su pochi record candidati:
        # prima filtriamo lato DB con uscita presente e mezzo vuoto.
        uscite_candidate_filter = all_filter + [
            Articolo.data_uscita != None,
            Articolo.data_uscita != "",
            or_(Articolo.mezzi_in_uscita == None, Articolo.mezzi_in_uscita == ""),
            Articolo.n_ddt_uscita != None,
            Articolo.n_ddt_uscita != "",
        ]
        uscite_senza_mezzo_count = 0
        uscite_senza_mezzo_examples = []
        try:
            candidate_ddt = (
                db.query(Articolo.n_ddt_uscita)
                .filter(*uscite_candidate_filter)
                .limit(500)
                .all()
            )
            seen = set()
            for (n_ddt,) in candidate_ddt:
                n = (n_ddt or '').strip()
                if re.match(r'^\d{1,5}/\d{2}$', n):
                    uscite_senza_mezzo_count += 1
                    if n not in seen and len(uscite_senza_mezzo_examples) < 5:
                        seen.add(n)
                        uscite_senza_mezzo_examples.append(n)
        except Exception:
            uscite_senza_mezzo_count = 0
            uscite_senza_mezzo_examples = []

        _add_alert(
            dashboard_alerts,
            'danger',
            'DDT gestionale senza mezzo',
            uscite_senza_mezzo_count,
            'DDT creati dal gestionale senza Motrice / Bilico / Furgone compilato.',
            uscite_senza_mezzo_examples
        )

        # Merce ferma da oltre 90 giorni.
        # Nota: confronto SQL affidabile quando data_ingresso è in formato YYYY-MM-DD.
        # Le date non ISO restano gestibili dalle pagine di dettaglio, ma qui evitiamo scan completo.
        vecchie_filter = active_filter + [
            Articolo.data_ingresso != None,
            Articolo.data_ingresso != "",
            Articolo.data_ingresso <= cutoff_90_iso
        ]
        _add_alert(
            dashboard_alerts,
            'info',
            'Giacenze oltre 90 giorni',
            _count_articoli(vecchie_filter),
            'Articoli ancora in giacenza da almeno 90 giorni.',
            _examples(vecchie_filter, 'n_arrivo')
        )

        level_order = {'danger': 0, 'warning': 1, 'info': 2}
        dashboard_alerts = sorted(
            dashboard_alerts,
            key=lambda x: (level_order.get(x.get('level'), 9), -int(x.get('count') or 0))
        )

        # ========================================================
        # RIEPILOGO GIACENZE PER CLIENTE
        # ========================================================
        dashboard_clienti = []
        try:
            rows_clienti = (
                db.query(
                    func.coalesce(Articolo.cliente, '').label('cliente'),
                    func.count(Articolo.id_articolo).label('righe'),
                    func.coalesce(func.sum(Articolo.n_colli), 0).label('colli'),
                    func.coalesce(func.sum(Articolo.m2), 0).label('m2'),
                    func.coalesce(func.sum(Articolo.peso), 0).label('peso'),
                )
                .filter(*active_filter)
                .group_by(func.coalesce(Articolo.cliente, ''))
                .order_by(func.coalesce(Articolo.cliente, '').asc())
                .all()
            )

            # Precalcolo buoni per cliente, così non faccio query dentro al template.
            buoni_by_cliente = {}
            try:
                stato_b = func.upper(func.coalesce(BuonoCarico.stato, ''))
                q_b = db.query(
                    func.coalesce(BuonoCarico.cliente, '').label('cliente'),
                    func.count(BuonoCarico.id).label('creati'),
                    func.sum(
                        case(
                            (stato_b.in_(['CARICATO', 'CHIUSO', 'COMPLETATO']), 1),
                            else_=0
                        )
                    ).label('usciti'),
                    func.sum(
                        case(
                            (~stato_b.in_(['CARICATO', 'CHIUSO', 'COMPLETATO', 'ELIMINATO']), 1),
                            else_=0
                        )
                    ).label('aperti'),
                ).filter(~stato_b.in_(['ELIMINATO']))

                if cliente_corrente:
                    q_b = q_b.filter(func.upper(func.coalesce(BuonoCarico.cliente, '')) == cliente_corrente.upper())

                for cli_b, creati, usciti, aperti in q_b.group_by(func.coalesce(BuonoCarico.cliente, '')).all():
                    key = (cli_b or '').strip().upper()
                    buoni_by_cliente[key] = {
                        'buoni_creati': int(creati or 0),
                        'buoni_usciti': int(usciti or 0),
                        'buoni_aperti': int(aperti or 0),
                    }
            except Exception:
                buoni_by_cliente = {}

            for cli, righe, colli, m2_val, peso_val in rows_clienti:
                nome_cli = (cli or 'SENZA CLIENTE').strip() or 'SENZA CLIENTE'
                dati_b = buoni_by_cliente.get(nome_cli.upper(), {})
                dashboard_clienti.append({
                    'cliente': nome_cli,
                    'righe': int(righe or 0),
                    'colli': int(colli or 0),
                    'm2': float(m2_val or 0),
                    'peso': float(peso_val or 0),
                    'buoni_aperti': int(dati_b.get('buoni_aperti', 0) or 0),
                    'buoni_creati': int(dati_b.get('buoni_creati', 0) or 0),
                    'buoni_usciti': int(dati_b.get('buoni_usciti', 0) or 0),
                })
        except Exception:
            dashboard_clienti = []

        return render_template(
            'home.html',
            dashboard=dashboard,
            dashboard_clienti=dashboard_clienti,
            dashboard_alerts=dashboard_alerts,
            ultimi_movimenti=ultimi_movimenti,
            today=today_obj,
            tot_articoli=dashboard['tot_giacenza'],
            tot_m2=dashboard['tot_m2']
        )

    except Exception as e:
        scrivi_log_errore("Errore caricamento Home alleggerita", e)
        print(f"CRITICAL ERROR HOME: {e}")
        import traceback
        traceback.print_exc()
        return f"<h1>Errore Caricamento Home</h1><p>{e}</p><a href='/logout'>Logout</a>"
    finally:
        try:
            db.close()
        except Exception:
            pass


# ========================================================
# GESTIONE MAPPE EXCEL (CORRETTA + LOG DEBUG)
# ========================================================

def load_mappe():
    """Carica mappe_excel.json: prima da config. (con punto), poi fallback su root."""
    config_path = APP_DIR / "config" / "mappe_excel.json"   # <-- cartella con il punto
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
    import json
    import hashlib

    if 'json_file' not in request.files:
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('manage_mappe'))

    f = request.files['json_file']
    if not f or f.filename == '':
        flash("Nessun file selezionato", "warning")
        return redirect(url_for('manage_mappe'))

    target = APP_DIR / "mappe_excel.json"

    def file_digest(path):
        try:
            h = hashlib.md5()
            with open(path, "rb") as fp:
                for chunk in iter(lambda: fp.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return "N/A"

    print("\n=== DEBUG upload_mappe_json() ===")
    print(f"DEBUG upload_mappe_json: filename={f.filename}")
    print(f"DEBUG upload_mappe_json: target={target}")

    try:
        raw = f.read()

        # ✅ UTF-8 con BOM (capita spesso con file creati da Windows/Excel)
        try:
            content = raw.decode("utf-8-sig")
        except Exception:
            content = raw.decode("utf-8")

        # ✅ validazione JSON (se non è JSON valido -> eccezione)
        json.loads(content)

        # ✅ assicura cartella esista
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        target.write_text(content, encoding="utf-8")

        size = target.stat().st_size if target.exists() else "N/A"
        print(f"DEBUG upload_mappe_json: scritto OK. md5={file_digest(target)} size={size}")

        flash("File mappe_excel.json caricato correttamente.", "success")

    except Exception as e:
        print(f"DEBUG upload_mappe_json: ERRORE: {e}")
        flash(f"Errore nel file caricato: {e}", "danger")

    print("=== FINE DEBUG upload_mappe_json() ===\n")
    return redirect(url_for('manage_mappe'))


# --- GESTIONE TRASPORTI (ADMIN) ---






# --- GESTIONE LAVORAZIONI (ADMIN) ---
def canonical_cliente_picking(value):
    """Normalizza il cliente nel Picking.
    Regola importante: tutte le varianti di Galvano devono diventare sempre
    GALVANO TECNICA, altrimenti il record viene salvato ma poi non compare
    correttamente nei filtri/lista.
    """
    raw = (value or '').strip()
    if not raw:
        raise ValueError("Cliente obbligatorio.")

    norm = normalize_text_key(raw)

    # Varianti reali viste in inserimento/import: Galvano, Galvanotecnica,
    # Cotugno Galvanotecnica, Galvano Tecnica Spa, ecc.
    if 'GALVANO' in norm:
        return 'GALVANO TECNICA'

    for c in get_clienti_utenti():
        if normalize_text_key(c) == norm:
            return c

    # Se non è presente negli utenti, salva comunque pulito in maiuscolo
    # invece di perdere il record dalla visualizzazione.
    return raw.upper()


def _clean_picking_upper_bound(value):
    """Nei filtri Picking, un valore massimo 0 / 0,0 inserito dal browser
    viene spesso interpretato come filtro attivo e nasconde le righe.
    Lo trattiamo come campo vuoto.
    """
    s = str(value or '').strip().replace(' ', '')
    return '' if s in {'0', '0,0', '0.0', '0,00', '0.00'} else (value or '').strip()


def _has_active_picking_filters(filtri):
    """True solo se l'utente ha inserito un filtro reale.
    I valori automatici del telefono/browser tipo 0,0 non devono filtrare.
    """
    for v in (filtri or {}).values():
        ss = str(v or '').strip()
        if not ss:
            continue
        if ss.replace(' ', '') in {'0', '0,0', '0.0', '0,00', '0.00'}:
            continue
        return True
    return False


def _normalize_existing_galvano_picking(db):
    """Sistema anche i vecchi record Picking Galvano salvati con varianti."""
    changed = False
    try:
        rows = db.query(Lavorazione).all()
        for rec in rows:
            raw = getattr(rec, 'cliente', '') or ''
            norm = normalize_text_key(raw)
            if 'GALVANO' in norm and raw != 'GALVANO TECNICA':
                rec.cliente = 'GALVANO TECNICA'
                changed = True
        if changed:
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return changed


# ========================================================
# PICKING / LAVORAZIONI
# Le route /lavorazioni e /stampa_picking_pdf sono in routes/picking.py
# Manteniamo qui solo modello e funzioni helper condivise.
# ========================================================

@app.route('/import_excel', methods=['GET', 'POST'])
@login_required
@require_admin
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

    if 'excel_file' not in request.files:
        return redirect(request.url)

    file = request.files['excel_file']
    if not file or file.filename == '':
        return redirect(request.url)

    db = SessionLocal()
    try:
        config = mappe[profile_name]
        header_row_idx = int(config.get('header_row', 1)) - 1
        column_map = config.get('column_map', {}) or {}

        import pandas as pd
        import numpy as np
        from datetime import datetime, date

        xls = pd.ExcelFile(file, engine="openpyxl")
        df = xls.parse(0, header=header_row_idx)

        # Mappa colonne (case-insensitive)
        df_cols_upper = {str(c).strip().upper(): c for c in df.columns}

        # ✅ HELPER DATA SUPER-ROBUSTO
        def to_date_db(val):
            """
            Ritorna data in formato YYYY-MM-DD oppure None.
            Gestisce:
            - datetime / pd.Timestamp / date
            - numpy.datetime64
            - seriale Excel (int/float)
            - stringhe (dd/mm/yyyy, dd/mm/yy, dd.mm.yyyy, ecc.)
            """
            if val is None:
                return None

            # NaN/NaT
            try:
                if pd.isna(val):
                    return None
            except Exception:
                pass

            # date/datetime/pandas timestamp
            if isinstance(val, (datetime, pd.Timestamp)):
                return val.strftime("%Y-%m-%d")
            if isinstance(val, date) and not isinstance(val, datetime):
                return val.strftime("%Y-%m-%d")

            # numpy datetime64
            if isinstance(val, np.datetime64):
                try:
                    dt = pd.to_datetime(val, errors="coerce")
                    if pd.isna(dt):
                        return None
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    return None

            # Seriali Excel (giorni da 1899-12-30)
            # Pandas a volte legge le date come float/int
            if isinstance(val, (int, float)) and val > 0:
                try:
                    dt = pd.to_datetime(val, unit="D", origin="1899-12-30", errors="coerce")
                    if pd.isna(dt):
                        return None
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    pass  # continua sotto a tentare come stringa

            # Stringhe
            s = str(val).strip()
            if not s:
                return None

            # prova formati comuni
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y"):
                try:
                    return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
                except Exception:
                    pass

            # fallback Pandas (dayfirst=True per Italia)
            try:
                dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
                if pd.isna(dt):
                    return None
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return None

        imported_count = 0

        for _, row in df.iterrows():
            if row.isnull().all():
                continue

            new_art = Articolo()
            has_data = False

            for excel_header, db_field in column_map.items():
                key = str(excel_header).strip().upper()
                col_name = df_cols_upper.get(key)
                if col_name is None:
                    continue

                val = row[col_name]

                # se vuoto, skip
                try:
                    if pd.isna(val) or str(val).strip() == "":
                        continue
                except Exception:
                    pass

                # Conversioni
                if db_field in ['larghezza', 'lunghezza', 'altezza', 'peso', 'm2', 'm3']:
                    try:
                        val = float(str(val).replace(',', '.'))
                    except Exception:
                        val = 0.0

                elif db_field in ['n_colli', 'pezzo']:
                    try:
                        val = int(float(str(val).replace(',', '.')))
                    except Exception:
                        val = 1

                elif db_field in ['data_ingresso', 'data_uscita']:
                    val = to_date_db(val)  # ✅ QUI ORA PRENDE ANCHE SERIALI EXCEL

                else:
                    val = str(val).strip()

                if val is not None and str(val).strip() != "":
                    setattr(new_art, db_field, val)
                    has_data = True

            if has_data:
                # Calcoli automatici se mancano
                try:
                    if not new_art.m2 or float(new_art.m2) == 0:
                        l = float(new_art.lunghezza or 0)
                        w = float(new_art.larghezza or 0)
                        h = float(new_art.altezza or 0)
                        c = int(new_art.n_colli or 1)

                        if l > 0 and w > 0:
                            new_art.m2 = round(l * w * c, 3)
                            new_art.m3 = round(l * w * (h if h > 0 else 0) * c, 3)
                except Exception:
                    pass

                new_art.codice_entrata = ensure_codice_entrata(
                    getattr(new_art, 'codice_entrata', None),
                    n_arrivo=strip_arrivo_progressivo(getattr(new_art, 'n_arrivo', None)),
                    n_ddt=getattr(new_art, 'n_ddt_ingresso', None),
                    data_ingresso=getattr(new_art, 'data_ingresso', None),
                    cliente=getattr(new_art, 'cliente', None)
                )
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
        'n_arrivo': 'N° Arrivo', 'codice_entrata': 'Codice Entrata', 'buono_n': 'Buono N°',
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
    import math
    import re
    from sqlalchemy import func
    from datetime import datetime, date

    db = SessionLocal()
    try:
        args = request.args
        qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())

        if session.get('role') == 'client':
            user_key_norm = normalize_text_key(current_user.id or '')
            cliente_db_norm = normalized_sql_text(Articolo.cliente)
            qs = qs.filter(cliente_db_norm == user_key_norm)
        else:
            if args.get('cliente'):
                cliente_norm = normalize_text_key(args.get('cliente'))
                if cliente_norm:
                    qs = qs.filter(normalized_sql_text(Articolo.cliente) == cliente_norm)

        if args.get('id'):
            try:
                qs = qs.filter(Articolo.id_articolo == int(args.get('id')))
            except Exception:
                pass

        text_filters = [
            'commessa', 'descrizione', 'posizione', 'buono_n', 'protocollo', 'lotto',
            'fornitore', 'ordine', 'magazzino', 'mezzi_in_uscita', 'stato',
            'n_ddt_ingresso', 'n_ddt_uscita', 'codice_articolo', 'serial_number', 'n_arrivo', 'codice_entrata'
        ]
        for field in text_filters:
            val = args.get(field)
            if val and val.strip():
                qs = qs.filter(getattr(Articolo, field).ilike(f"%{val.strip()}%"))
        m2_da = args.get('m2_da')
        m2_a = args.get('m2_a')
        m2_legacy = args.get('m2')  # compatibilità: vecchio filtro singolo (es. "1,25" o "1-2")

        def _to_float_it(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip().replace(' ', '')
            if not s:
                return None
            try:
                # Gestione formati tipo 1.234,56 (migliaia + decimali)
                if ',' in s and '.' in s:
                    s2 = s.replace('.', '').replace(',', '.')
                else:
                    s2 = s.replace(',', '.')
                return float(s2)
            except Exception:
                return None

        m2_da_f = _to_float_it(m2_da)
        m2_a_f = _to_float_it(m2_a)

        # Se non usi i campi DA/A ma passi il vecchio campo "m2", usa la logica precedente
        m2_filter = None
        if m2_da_f is None and m2_a_f is None and m2_legacy:
            m2_filter = parse_float_filter(m2_legacy)

        all_rows = qs.all()

        # Nuovo filtro M2 DA/A
        if m2_da_f is not None or m2_a_f is not None:
            tmp = []
            for r in all_rows:
                n = _to_float_it(r.m2)
                if n is None:
                    continue
                if m2_da_f is not None and n < m2_da_f:
                    continue
                if m2_a_f is not None and n > m2_a_f:
                    continue
                tmp.append(r)
            all_rows = tmp
        elif m2_filter is not None:
            all_rows = [r for r in all_rows if match_numeric_filter(r.m2, m2_filter)]

        filtered_rows = []

        def get_date_arg(k):
            v = args.get(k)
            try:
                return datetime.strptime(v, "%Y-%m-%d").date() if v else None
            except Exception:
                return None

        d_ing_da, d_ing_a = get_date_arg('data_ing_da'), get_date_arg('data_ing_a')
        d_usc_da, d_usc_a = get_date_arg('data_usc_da'), get_date_arg('data_usc_a')

        def parse_d(val):
            if isinstance(val, date):
                return val
            if not val:
                return None
            if isinstance(val, str):
                s = val.strip().split(' ')[0][:10]
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(s, fmt).date()
                    except Exception:
                        pass
            return None

        if any([d_ing_da, d_ing_a, d_usc_da, d_usc_a]):
            for r in all_rows:
                keep = True
                if d_ing_da or d_ing_a:
                    rd = parse_d(r.data_ingresso)
                    if not rd or (d_ing_da and rd < d_ing_da) or (d_ing_a and rd > d_ing_a):
                        keep = False
                if keep and (d_usc_da or d_usc_a):
                    rd = parse_d(r.data_uscita)
                    if not rd or (d_usc_da and rd < d_usc_da) or (d_usc_a and rd > d_usc_a):
                        keep = False
                if keep:
                    filtered_rows.append(r)
        else:
            filtered_rows = all_rows

        if args.get('solo_giacenza') == '1':
            tmp = []
            for r in filtered_rows:
                has_data_usc = parse_d(r.data_uscita) is not None
                has_ddt_usc = bool((r.n_ddt_uscita or '').strip())
                if (not has_data_usc) and (not has_ddt_usc):
                    tmp.append(r)
            filtered_rows = tmp

        def fmt_num(val, dec=2):
            try:
                if val is None or val == '':
                    return ''
                return round(float(val), dec)
            except Exception:
                return ''

        export_rows = []
        for r in filtered_rows:
            export_rows.append({
                'ID': r.id_articolo,
                'Codice': r.codice_articolo or '',
                'Pz': r.pezzo or '',
                'Larg': fmt_num(r.larghezza, 2),
                'Lung': fmt_num(r.lunghezza, 2),
                'Alt': fmt_num(r.altezza, 2),
                'M2': fmt_num(r.m2, 3),
                'M3': fmt_num(r.m3, 3),
                'Descrizione': r.descrizione or '',
                'Protocollo': r.protocollo or '',
                'Commessa': r.commessa or '',
                'Ordine': r.ordine or '',
                'Colli': r.n_colli if r.n_colli is not None else '',
                'Fornitore': r.fornitore or '',
                'Magazzino': r.magazzino or '',
                'Data Ing': r.data_ingresso or '',
                'DDT Ing': r.n_ddt_ingresso or '',
                'DDT Usc': r.n_ddt_uscita or '',
                'Data Usc': r.data_uscita or '',
                'Mezzo Usc': r.mezzi_in_uscita or '',
                'Cliente': r.cliente or '',
                'Kg': fmt_num(r.peso, 2),
                'Posiz': r.posizione or '',
                'N.Arr': r.n_arrivo or '',
                'N.Buono': r.buono_n or '',
                'Note': r.note or '',
                'Lotto': r.lotto or '',
                'Ns.Rif': getattr(r, 'ns_rif', '') or '',
                'Serial': r.serial_number or '',
                'Stato': r.stato or '',
            })

        df = pd.DataFrame(export_rows, columns=[
            'ID', 'Codice', 'Pz', 'Larg', 'Lung', 'Alt', 'M2', 'M3', 'Descrizione',
            'Protocollo', 'Commessa', 'Ordine', 'Colli', 'Fornitore', 'Magazzino',
            'Data Ing', 'DDT Ing', 'DDT Usc', 'Data Usc', 'Mezzo Usc', 'Cliente',
            'Kg', 'Posiz', 'N.Arr', 'N.Buono', 'Note', 'Lotto', 'Ns.Rif', 'Serial', 'Stato'
        ])

        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Giacenze')
            ws = writer.book['Giacenze']
            for col_cells in ws.columns:
                max_length = 0
                col_letter = col_cells[0].column_letter
                for cell in col_cells:
                    val = '' if cell.value is None else str(cell.value)
                    if len(val) > max_length:
                        max_length = len(val)
                ws.column_dimensions[col_letter].width = min(max(max_length + 2, 10), 40)
            ws.freeze_panes = 'A2'
        bio.seek(0)

        ts = datetime.now().strftime('%Y%m%d_%H%M')
        filename = f'Giacenze_Filtrate_{ts}.xlsx' if request.args else f'Giacenze_Totali_{ts}.xlsx'
        return send_file(
            bio,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    finally:
        db.close()

@app.route('/export_client', methods=['GET', 'POST'])
@login_required
def export_client():
    db = SessionLocal()
    clienti = [c[0] for c in db.query(Articolo.cliente).distinct().filter(Articolo.cliente != None, Articolo.cliente != '').order_by(Articolo.cliente).all()]
    if session.get('role') == 'client':
        clienti = [(current_user.id or '').strip()]
    
    if request.method == 'POST':
        cliente = request.form.get('cliente')
        if session.get('role') == 'client':
            cliente = (current_user.id or '').strip()
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
    
# ==============================================================================
#  FUNZIONE INVIA EMAIL (CORRETTA CON FIRMA COMPLETA E LOGO)
# ==============================================================================




# --- FUNZIONE UPLOAD FILE MULTIPLI (CORRETTA PER EDIT_RECORD) ---

# ========================================================
#  VISUALIZZAZIONE ALLEGATI ARTICOLO - DOCUMENTI/FOTO
# ========================================================
# ========================================================
# ALLEGATI
# Le route allegati/media sono state spostate in routes/allegati.py
# ========================================================

@app.route('/scan_entrata', methods=['GET'])
@login_required
def scan_entrata():
    codice = (request.args.get('codice_entrata') or '').strip()
    if codice:
        return redirect(url_for('dettaglio_entrata', codice_entrata=codice))
    return render_template('scan_entrata.html')


@app.route('/go_scan_entrata', methods=['POST'])
@login_required
def go_scan_entrata():
    codice = (request.form.get('codice_entrata') or '').strip()
    if not codice:
        flash('Inserisci o scansiona un codice entrata.', 'warning')
        return redirect(url_for('scan_entrata'))
    return redirect(url_for('dettaglio_entrata', codice_entrata=codice))


@app.route('/entrata/<path:codice_entrata>')
@login_required
def dettaglio_entrata(codice_entrata):
    db = SessionLocal()
    try:
        varianti_codice = _codice_entrata_varianti(codice_entrata)
        qs = (
            db.query(Articolo)
            .options(selectinload(Articolo.attachments))
            .filter(Articolo.codice_entrata.in_(varianti_codice))
            .order_by(Articolo.id_articolo.desc())
        )
        if session.get('role') == 'client':
            user_key_norm = normalize_text_key(current_user.id or '')
            qs = qs.filter(normalized_sql_text(Articolo.cliente) == user_key_norm)
        rows = qs.all()
        if not rows:
            flash(f'Entrata {codice_entrata} non trovata.', 'warning')
            return redirect(url_for('scan_entrata'))

        changed_code, codice_entrata_preferito = _normalizza_codice_entrata_rows(db, codice_entrata, rows)
        if changed_code:
            return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata_preferito))
        codice_entrata = codice_entrata_preferito or codice_entrata

        total_colli = sum(int(r.n_colli or 0) for r in rows)
        total_peso = round(sum(float(r.peso or 0) for r in rows), 2)
        total_m2 = round(sum(float(r.m2 or 0) for r in rows), 3)
        total_m3 = round(sum(float(r.m3 or 0) for r in rows), 3)
        ids_csv = ','.join(str(r.id_articolo) for r in rows)
        docs, photos = _collect_entrata_attachments(rows)
        ddt_ingresso = sorted({(r.n_ddt_ingresso or '').strip() for r in rows if (r.n_ddt_ingresso or '').strip()})
        ddt_uscita = sorted({(r.n_ddt_uscita or '').strip() for r in rows if (r.n_ddt_uscita or '').strip()})
        clienti = sorted({(r.cliente or '').strip() for r in rows if (r.cliente or '').strip()})
        fornitori = sorted({(r.fornitore or '').strip() for r in rows if (r.fornitore or '').strip()})
        detail_url = build_entry_public_url(codice_entrata)
        analysis = analyze_entrata_rows(rows)
        anomalies = analysis.get('anomalies', [])
        anomalies_ids = {getattr(a.get('row'), 'id_articolo', None) for a in anomalies if a.get('row') is not None}
        return render_template('dettaglio_entrata.html', rows=rows, codice_entrata=codice_entrata, ids_csv=ids_csv, docs=docs, photos=photos, ddt_ingresso=ddt_ingresso, ddt_uscita=ddt_uscita, clienti=clienti, fornitori=fornitori, total_colli=total_colli, total_peso=total_peso, total_m2=total_m2, total_m3=total_m3, detail_url=detail_url, anomalies=anomalies, anomalies_ids=anomalies_ids)
    finally:
        db.close()

@app.route('/entrata/<path:codice_entrata>/verifica')
@login_required
def verifica_entrata(codice_entrata):
    db = SessionLocal()
    try:
        varianti_codice = _codice_entrata_varianti(codice_entrata)
        qs = db.query(Articolo).filter(Articolo.codice_entrata.in_(varianti_codice)).order_by(Articolo.id_articolo.desc())
        if session.get('role') == 'client':
            user_key_norm = normalize_text_key(current_user.id or '')
            qs = qs.filter(normalized_sql_text(Articolo.cliente) == user_key_norm)
        rows = qs.all()
        if not rows:
            flash(f'Entrata {codice_entrata} non trovata.', 'warning')
            return redirect(url_for('scan_entrata'))
        changed_code, codice_entrata_preferito = _normalizza_codice_entrata_rows(db, codice_entrata, rows)
        if changed_code:
            codice_entrata = codice_entrata_preferito or codice_entrata
        analysis = analyze_entrata_rows(rows)
        anomalies = analysis.get('anomalies', [])
        if anomalies:
            msg = " ; ".join([f"ID {getattr(a['row'], 'id_articolo', '?')}: {a['reason']}" for a in anomalies[:8]])
            if len(anomalies) > 8:
                msg += f" ; +{len(anomalies)-8} altre anomalie"
            flash(f"Verifica Entrata: trovate {len(anomalies)} anomalie. {msg}", "warning")
        else:
            flash("Verifica Entrata: nessuna anomalia rilevata.", "success")
        return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))
    finally:
        db.close()

@app.route('/entrata/<path:codice_entrata>/correggi', methods=['POST'])
@login_required
@require_admin
def correggi_entrata(codice_entrata):
    db = SessionLocal()
    try:
        varianti_codice = _codice_entrata_varianti(codice_entrata)
        rows = db.query(Articolo).filter(Articolo.codice_entrata.in_(varianti_codice)).order_by(Articolo.id_articolo.desc()).all()
        if not rows:
            flash(f'Entrata {codice_entrata} non trovata.', 'warning')
            return redirect(url_for('scan_entrata'))

        changed_code, codice_entrata_preferito = _normalizza_codice_entrata_rows(db, codice_entrata, rows)
        if changed_code:
            codice_entrata = codice_entrata_preferito or codice_entrata
            rows = db.query(Articolo).filter(Articolo.codice_entrata == codice_entrata).order_by(Articolo.id_articolo.desc()).all()

        analysis = analyze_entrata_rows(rows)
        anomalies = analysis.get('anomalies', [])
        bad_ids = {getattr(a.get('row'), 'id_articolo', None) for a in anomalies if a.get('row') is not None}

        fixed = 0
        moved = 0
        unchanged = 0

        for art in rows:
            if art.id_articolo not in bad_ids:
                continue

            new_code = ensure_codice_entrata(
                None,
                n_arrivo=strip_arrivo_progressivo(art.n_arrivo),
                n_ddt=art.n_ddt_ingresso,
                data_ingresso=art.data_ingresso,
                cliente=art.cliente
            )

            if (art.codice_entrata or '') != (new_code or ''):
                art.codice_entrata = new_code
                moved += 1
            else:
                unchanged += 1
            fixed += 1

        db.commit()

        if fixed:
            flash(
                f"Correzione completata: ricalcolate {fixed} righe anomale. Barcode e QR sono stati mantenuti o rigenerati correttamente senza eliminarli.",
                "success"
            )
        else:
            flash("Nessuna riga anomala da correggere.", "info")

        return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))
    except Exception as e:
        db.rollback()
        flash(f"Errore durante la correzione dell'entrata: {e}", "danger")
        return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))
    finally:
        db.close()

# --- GESTIONE ARTICOLI (CRUD) ---
# ========================================================
# 8. CRUD (NUOVO / MODIFICA)
# ========================================================

@app.route('/new', methods=['GET', 'POST'])
@login_required
@require_admin
def nuovo_articolo():
    # 1. Controllo permessi
    if session.get('role') != 'admin':
        flash("Accesso negato: Solo Admin.", "danger")
        return redirect(url_for('giacenze'))

    if request.method == 'POST':
        db = SessionLocal()
        try:
            # Determina quante righe creare in base al numero di colli
            n_colli_input = to_int_eu(request.form.get('n_colli'))
            if n_colli_input < 1:
                n_colli_input = 1

            created_articles = []
            cliente_form = validate_cliente_or_raise(request.form.get('cliente'))
            arrivo_base = strip_arrivo_progressivo(request.form.get('n_arrivo'))
            data_ingresso_form = request.form.get('data_ingresso')
            ddt_ingresso_form = request.form.get('n_ddt_ingresso')
            codice_entrata_form = request.form.get('codice_entrata')

            # Crea una riga per collo, con N.Arrivo progressivo per riga
            for idx in range(1, n_colli_input + 1):
                art = Articolo()
                art.codice_articolo = request.form.get('codice_articolo')
                art.descrizione = request.form.get('descrizione')
                art.cliente = current_user.id if session.get('role') == 'client' else cliente_form
                art.fornitore = request.form.get('fornitore')
                art.commessa = request.form.get('commessa')
                art.ordine = request.form.get('ordine')
                art.protocollo = request.form.get('protocollo')
                art.buono_n = request.form.get('buono_n')
                art.n_arrivo = build_arrivo_progressivo(arrivo_base or request.form.get('n_arrivo'), idx)
                art.codice_entrata = ensure_codice_entrata(
                    codice_entrata_form,
                    n_arrivo=arrivo_base or strip_arrivo_progressivo(art.n_arrivo),
                    n_ddt=ddt_ingresso_form,
                    data_ingresso=data_ingresso_form,
                    cliente=art.cliente,
                )
                art.magazzino = request.form.get('magazzino')
                art.posizione = request.form.get('posizione')
                art.stato = request.form.get('stato')
                art.note = request.form.get('note')
                art.serial_number = request.form.get('serial_number')
                art.mezzi_in_uscita = request.form.get('mezzi_in_uscita')
                art.lotto = request.form.get('lotto')
                art.ns_rif = request.form.get('ns_rif')

                art.data_ingresso = parse_date_ui(data_ingresso_form)
                art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
                art.n_ddt_ingresso = ddt_ingresso_form
                art.n_ddt_uscita = request.form.get('n_ddt_uscita')

                art.pezzo = request.form.get('pezzo')
                art.n_colli = 1
                art.peso = to_float_eu(request.form.get('peso'))
                art.lunghezza = to_float_eu(request.form.get('lunghezza'))
                art.larghezza = to_float_eu(request.form.get('larghezza'))
                art.altezza = to_float_eu(request.form.get('altezza'))
                art.m2, art.m3 = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, 1)

                db.add(art)
                created_articles.append(art)

            db.commit()

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

                    first_art = created_articles[0]
                    first_final_name = f"{first_art.id_articolo}_{fname}"
                    src_path = folder / first_final_name

                    file.seek(0)
                    file.save(str(src_path))
                    db.add(Attachment(articolo_id=first_art.id_articolo, filename=first_final_name, kind=kind))

                    for other_art in created_articles[1:]:
                        other_final_name = f"{other_art.id_articolo}_{fname}"
                        dst_path = folder / other_final_name
                        try:
                            shutil.copy2(src_path, dst_path)
                            db.add(Attachment(articolo_id=other_art.id_articolo, filename=other_final_name, kind=kind))
                        except Exception as e:
                            print(f"Errore copia file per ID {other_art.id_articolo}: {e}")
                db.commit()

            flash(f"Operazione completata: creati {len(created_articles)} articoli distinti con N. Arrivo sequenziale per riga.", "success")
            if len(created_articles) == 1:
                return redirect(url_for('edit_articolo', id=created_articles[0].id_articolo))
            return redirect(url_for('giacenze'))

        except Exception as e:
            db.rollback()
            flash(f"Errore creazione: {e}", "danger")
            return redirect(url_for('giacenze'))
        finally:
            db.close()

    # GET: Mostra form vuoto
    dummy_art = Articolo()
    dummy_art.data_ingresso = date.today().strftime("%Y-%m-%d")
    dummy_art.codice_entrata = (request.args.get('codice_entrata') or '').strip()
    dummy_art.n_arrivo = strip_arrivo_progressivo(request.args.get('n_arrivo') or '')
    dummy_art.n_ddt_ingresso = (request.args.get('n_ddt_ingresso') or '').strip()
    return render_template('edit.html', row=dummy_art, clienti_validi=get_clienti_utenti())

# 1. ELIMINA ARTICOLO (Per la pagina Magazzino)
@app.route('/delete_articolo/<int:id>')
@login_required
@require_admin
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

# --- DUPLICAZIONE SINGOLA (COMPLETA: copia TUTTI i campi tranne ID) ---
@app.route('/duplica_articolo/<int:id_articolo>')
@login_required
def duplica_articolo(id_articolo):
    if session.get('role') != 'admin':
        flash('Accesso negato: Solo Admin.', 'danger')
        return redirect(url_for('giacenze'))

    db = SessionLocal()
    try:
        originale = db.query(Articolo).filter(Articolo.id_articolo == id_articolo).first()

        if not originale:
            flash("Articolo non trovato", "danger")
            return redirect(url_for('giacenze'))

        # ✅ Copia tutti i campi della tabella Articolo eccetto la PK
        data_copy = {}
        for col in Articolo.__table__.columns:
            if col.name == 'id_articolo':
                continue
            data_copy[col.name] = getattr(originale, col.name)

        nuovo = Articolo(**data_copy)

        # ✅ Modifiche volute sulla copia
        nuovo.note = f"Copia di ID {originale.id_articolo}"
        nuovo.data_ingresso = date.today()

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
@require_admin
def edit_articolo(id):
    db = SessionLocal()
    cliente_form = get_clienti_utenti()
    # Mantiene il filtro/pagina di provenienza quando si salva una modifica.
    # Esempio: se si stava lavorando sull'arrivo 200/26, dopo Salva torna alla stessa lista filtrata.
    return_url = (request.values.get('return_url') or '').strip()
    if not return_url:
        ref = (request.referrer or '').strip()
        if '/giacenze' in ref:
            return_url = ref
    if not return_url:
        return_url = url_for('giacenze')
    try:
        art = db.query(Articolo).options(selectinload(Articolo.attachments)).filter(Articolo.id_articolo == id).first()
        if not art:
            flash("Articolo non trovato", "danger")
            return redirect(return_url)

        # Sicurezza HARD: un client non puo' accedere/modificare articoli di altri clienti
        if session.get('role') == 'client':
            art_cliente = (art.cliente or '').strip().upper()
            user_key = (current_user.id or '').strip().upper()
            art_norm = re.sub(r'[^A-Z0-9]+', '', art_cliente)
            user_norm = re.sub(r'[^A-Z0-9]+', '', user_key)
            # Se non contiene l'identificativo cliente -> blocca
            if user_norm not in art_norm:
                abort(403)

        if request.method == 'POST':
            # 1. Recupera Colli (per eventuale split)
            colli_input = to_int_eu(request.form.get('n_colli'))
            if colli_input < 0: colli_input = 0

            # 2. Aggiorna tutti i campi
            art.codice_articolo = request.form.get('codice_articolo')
            art.descrizione = request.form.get('descrizione')
            # Cliente: per i client e' bloccato sul proprio utente
            if session.get('role') == 'client':
                art.cliente = current_user.id
            else:
                art.cliente = cliente_from_form_or_current(request.form, art.cliente)
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
            art.data_ingresso = (parse_date_ui(request.form.get('data_ingresso')) or date.today()).strftime('%Y-%m-%d')
            art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')

            # Numeri
            art.pezzo = request.form.get('pezzo')
            # In modifica singola deve essere possibile salvare anche 0 colli;
            # se l'utente inserisce >1, lasciamo 1 sulla riga base e creiamo le copie aggiuntive.
            art.n_colli = colli_input if colli_input <= 1 else 1
            
            art.peso = to_float_eu(request.form.get('peso'))
            art.lunghezza = to_float_eu(request.form.get('lunghezza'))
            art.larghezza = to_float_eu(request.form.get('larghezza'))
            art.altezza = to_float_eu(request.form.get('altezza'))
            
            # Calcoli
            m2_calc, m3_calc = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, art.n_colli)
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
            return redirect(return_url)

        # GET: Mostra template modifica
        # Gli allegati devono essere già caricati prima che la sessione DB venga chiusa.
        # Evita errore SQLAlchemy: Parent instance is not bound to a Session / lazy load attachments.
        try:
            art.attachments = list(art.attachments or [])
        except Exception:
            pass
        return render_template('edit.html', row=art, clienti_validi=get_clienti_utenti(), return_url=return_url)

    except Exception as e:
        db.rollback()
        flash(f"Errore modifica: {e}", "danger")
        return redirect(return_url)
    finally:
        db.close()

@app.route('/edit/<int:id_articolo>', methods=['GET', 'POST'])
@login_required
def edit_record(id_articolo):
    db = SessionLocal()
    cliente_form = get_clienti_utenti()
    return_url = (request.values.get('return_url') or '').strip()
    if not return_url:
        ref = (request.referrer or '').strip()
        if '/giacenze' in ref:
            return_url = ref
    if not return_url:
        return_url = url_for('giacenze')
    try:
        art = db.query(Articolo).options(selectinload(Articolo.attachments)).filter(Articolo.id_articolo == id_articolo).first()
        if not art:
            flash("Articolo non trovato", "danger")
            return redirect(return_url)

        if request.method == 'POST':
            # --- SALVATAGGIO MODIFICHE ---
            colli_input = to_int_eu(request.form.get('n_colli'))
            if colli_input < 0: colli_input = 0

            # Aggiornamento campi
            art.codice_articolo = request.form.get('codice_articolo')
            art.descrizione = request.form.get('descrizione')
            # Cliente: per i client e' bloccato sul proprio utente
            if session.get('role') == 'client':
                art.cliente = current_user.id
            else:
                art.cliente = cliente_from_form_or_current(request.form, art.cliente)
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
            
            art.data_ingresso = (parse_date_ui(request.form.get('data_ingresso')) or date.today()).strftime('%Y-%m-%d')
            art.data_uscita = parse_date_ui(request.form.get('data_uscita'))
            art.n_ddt_ingresso = request.form.get('n_ddt_ingresso')
            art.n_ddt_uscita = request.form.get('n_ddt_uscita')
            
            art.pezzo = request.form.get('pezzo')
            # In modifica puoi anche salvare 0 colli; se >1 manteniamo 1 sulla riga base e creiamo copie
            art.n_colli = colli_input if colli_input <= 1 else 1 
            art.peso = to_float_eu(request.form.get('peso'))
            art.lunghezza = to_float_eu(request.form.get('lunghezza'))
            art.larghezza = to_float_eu(request.form.get('larghezza'))
            art.altezza = to_float_eu(request.form.get('altezza'))
            
            # Calcoli
            m2_calc, m3_calc = calc_m2_m3(art.lunghezza, art.larghezza, art.altezza, art.n_colli)
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
            return redirect(return_url)

        return render_template('edit.html', row=art, clienti_validi=get_clienti_utenti(), return_url=return_url)
    except Exception as e:
        db.rollback()
        flash(f"Errore: {e}", "danger")
        return redirect(return_url)
    finally:
        db.close()

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db = SessionLocal()
    return_url = (request.values.get('return_url') or '').strip()
    if not return_url:
        ref = (request.referrer or '').strip()
        if '/giacenze' in ref:
            return_url = ref
    if not return_url:
        return_url = url_for('giacenze')
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
                if f == 'cliente' and session.get('role') != 'client':
                    v = validate_cliente_or_raise(v, allow_blank=True)
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
        return redirect(return_url)

    return render_template('edit.html', row=row, fields=get_all_fields_map().items(), clienti_validi=get_clienti_utenti(), return_url=return_url)



# ========================================================
# MEDIA & ALLEGATI
# Le route /media, /serve_file, upload/delete allegati sono in routes/allegati.py
# ========================================================

# ==============================================================================
#  1. FUNZIONE GIACENZE (Visualizzazione Magazzino)
# ==============================================================================
# ==============================================================================
#  ROUTE GIACENZE SPOSTATA IN routes/magazzino.py
# ==============================================================================
# La funzione giacenze() è stata spostata nel modulo routes/magazzino.py.
# Il file principale registra il modulo in fondo con:
# from routes.magazzino import register_magazzino_routes
# register_magazzino_routes(app, globals())


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
@require_admin
def bulk_edit():
    db = SessionLocal()

    def _safe_return_url(value=None):
        """Torna alla lista filtrata di provenienza, evitando redirect esterni."""
        val = (value or "").strip()
        if val.startswith("/giacenze"):
            return val
        try:
            ref = (request.referrer or "").strip()
            if "/giacenze" in ref:
                # Se è URL assoluto dello stesso sito, tengo solo path + query.
                from urllib.parse import urlparse
                p = urlparse(ref)
                if p.path == "/giacenze":
                    return p.path + (("?" + p.query) if p.query else "")
        except Exception:
            pass
        val = (session.get("last_giacenze_url") or "").strip()
        if val.startswith("/giacenze"):
            return val
        return url_for("giacenze")

    return_url = _safe_return_url(request.values.get("return_url"))

    try:
        # Recupera ID (da form POST o query string GET)
        ids = request.form.getlist('ids') or request.args.getlist('ids')

        # Filtra ID validi
        ids = [int(i) for i in ids if str(i).isdigit()]

        if not ids:
            flash("Nessun articolo selezionato.", "warning")
            return redirect(return_url)

        articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

        # Configurazione Campi Modificabili
        editable_fields = [
            ('Cliente', 'cliente'),
            ('Fornitore', 'fornitore'),
            ('N. DDT Ingresso', 'n_ddt_ingresso'),
            ('Data Ingresso', 'data_ingresso'),
            ('Data Uscita', 'data_uscita'),
            ('N. DDT Uscita', 'n_ddt_uscita'),
            ('Protocollo', 'protocollo'),
            ('N. Buono', 'buono_n'),
            ('Magazzino', 'magazzino'),
            ('Commessa', 'commessa'),
            ('Mezzo Uscita', 'mezzi_in_uscita'),
            ('N. Arrivo', 'n_arrivo'),
            ('Peso', 'peso'),
            ('Lotto', 'lotto'),
            ('Ordine', 'ordine'),
            ('Stato', 'stato'),
            ('Descrizione', 'descrizione'),
            ('Codice Articolo', 'codice_articolo'),
            ('Serial Number', 'serial_number'),
            ('Colli', 'n_colli'),
            ('Pezzi', 'pezzo'),
            ('Lunghezza', 'lunghezza'),
            ('Larghezza', 'larghezza'),
            ('Altezza', 'altezza'),
        ]

        if request.method == 'POST' and request.form.get('save_bulk') == 'true':
            updates = {}
            recalc_dims = False

            # 1) Applica Modifiche Campi
            for key in request.form:
                if not key.startswith('chk_'):
                    continue

                field_name = key.replace('chk_', '').strip()

                # Accetta SOLO campi presenti nella lista editable_fields
                if not any(f[1] == field_name for f in editable_fields):
                    continue

                val = request.form.get(field_name)

                if field_name in ['n_colli', 'pezzo']:
                    val = to_int_eu(val)
                elif field_name in ['lunghezza', 'larghezza', 'altezza', 'peso']:
                    val = to_float_eu(val)
                elif 'data' in field_name:
                    val = parse_date_ui(val) if val else None
                else:
                    val = (val or "").strip()

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

            # 2) UPLOAD MASSIVO MULTIPLO (più file) ✅ CORRETTO
            files = request.files.getlist('bulk_files')
            count_uploaded = 0

            if files:
                from werkzeug.utils import secure_filename

                for file in files:
                    if not file or not file.filename:
                        continue

                    raw_name = secure_filename(file.filename)

                    # Legge UNA volta (poi lo duplica su ogni articolo)
                    content = file.read()
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
            return redirect(return_url)

        return render_template(
            'bulk_edit.html',
            rows=articoli,
            ids_csv=",".join(map(str, ids)),
            fields=editable_fields,
            return_url=return_url
        )

    except Exception as e:
        db.rollback()
        print(f"ERRORE BULK: {e}")
        flash(f"Errore: {e}", "danger")
        return redirect(return_url)
    finally:
        db.close()


@app.post('/delete_rows')
@login_required
@require_admin
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
@require_admin
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
                    lotto=original.lotto,
                    data_ingresso=original.data_ingresso,
                    n_ddt_ingresso=original.n_ddt_ingresso,
                    data_uscita=original.data_uscita,
                    n_ddt_uscita=original.n_ddt_uscita,
                    pezzo=original.pezzo,
                    n_colli=original.n_colli,
                    peso=original.peso,
                    lunghezza=original.lunghezza,
                    larghezza=original.larghezza,
                    altezza=original.altezza,
                    m2=original.m2,
                    m3=original.m3,
                    n_arrivo=original.n_arrivo,
                    codice_entrata=original.codice_entrata,
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

# Route /buono/preview spostata in routes/buono.py

from datetime import date
from flask import request
from datetime import date
from flask import request, redirect, url_for, flash, jsonify, render_template
from flask_login import login_required

@app.route('/ddt/preview', methods=['GET', 'POST'])
@login_required
def ddt_preview():
    # ✅ Se il browser torna indietro su /ddt/preview usa GET:
    # prima era solo POST e compariva "Method Not Allowed".
    # Ora lo rimandiamo alla schermata giacenze senza errore.
    if request.method == 'GET':
        flash("La schermata DDT non può essere riaperta con il tasto indietro. Seleziona di nuovo gli articoli.", "warning")
        return redirect(url_for('giacenze'))

    if session.get('role') != 'admin':
        flash('Accesso negato.', 'danger')
        return redirect(url_for('giacenze'))

    # ⚠️ ids può arrivare in due modi:
    # - lista di checkbox: ids=1 ids=2 ids=3
    # - stringa csv in un campo hidden: ids="1,2,3"
    ids = []

    ids_list = request.form.getlist('ids')
    if ids_list:
        # caso checkbox
        for i in ids_list:
            if str(i).isdigit():
                ids.append(int(i))
    else:
        # caso hidden "1,2,3"
        ids_csv = (request.form.get('ids') or '').strip()
        if ids_csv:
            for part in ids_csv.split(','):
                part = part.strip()
                if part.isdigit():
                    ids.append(int(part))

    if not ids:
        flash("Seleziona almeno un articolo per creare il DDT.", "warning")
        return redirect(url_for('giacenze'))

    rows = _get_rows_from_ids(ids)

    CLIENTI_MEZZO_OBBLIGATORIO = {'FINCANTIERI', 'FINCANTIERI SCOPERTO', 'FINCANTIERI ARMATORE', 'MARINE INTERIORS', 'DE WAVE SAMA'}
    CLIENTI_PROTOCOLLO_OBBLIGATORIO = {'FINCANTIERI', 'FINCANTIERI ARMATORE'}
    def _cliente_norm_ddt_preview(value):
        return re.sub(r'\s+', ' ', str(value or '').strip().upper())
    ddt_cliente_richiede_mezzi = any(
        _cliente_norm_ddt_preview(getattr(r, 'cliente', '')) in CLIENTI_MEZZO_OBBLIGATORIO
        for r in rows
    )

    total_colli_ddt = 0
    total_peso_ddt = 0.0
    protocollo_mancanti_ddt = 0
    for r in rows:
        try:
            total_colli_ddt += int(float(getattr(r, 'n_colli', 0) or 0))
        except Exception:
            pass
        try:
            total_peso_ddt += float(getattr(r, 'peso', 0) or 0)
        except Exception:
            pass
        if _cliente_norm_ddt_preview(getattr(r, 'cliente', '')) in CLIENTI_PROTOCOLLO_OBBLIGATORIO and not str(getattr(r, 'protocollo', '') or '').strip():
            protocollo_mancanti_ddt += 1

    return render_template(
        'ddt_preview.html',
        rows=rows,
        ids=",".join(map(str, ids)),
        destinatari=load_destinatari(),
        n_ddt=peek_next_ddt_number(),
        oggi=date.today().isoformat(),
        ddt_cliente_richiede_mezzi=ddt_cliente_richiede_mezzi,
        total_righe_ddt=len(rows),
        total_colli_ddt=total_colli_ddt,
        total_peso_ddt=it_num(total_peso_ddt, 2),
        protocollo_mancanti_ddt=protocollo_mancanti_ddt
    )


@app.get('/next_ddt_number')
@login_required
def get_next_ddt_number():
    """
    Restituisce il numero successivo rispetto a quello attualmente scritto nel campo,
    SENZA memorizzarlo su DB (serve solo per cambiare il valore con le frecce).
    Accetta ?current=NN/YY oppure ?current=NN.
    """
    current = (request.args.get('current') or '').strip()

    # base = numero + anno
    base_num = None
    base_year = None

    # prova formato NN/YY
    m = re.match(r'^(\d+)\s*/\s*(\d{2})$', current)
    if m:
        try:
            base_num = int(m.group(1))
            base_year = m.group(2)
        except Exception:
            base_num = None
            base_year = None

    # prova solo numero
    if base_num is None and current.isdigit():
        base_num = int(current)

    # se non valido, usa il "peek" (es. 01/26)
    if base_num is None or base_year is None:
        try:
            p = peek_next_ddt_number()
            pm = re.match(r'^(\d+)\s*/\s*(\d{2})$', (p or '').strip())
            if pm:
                base_num = int(pm.group(1))
                base_year = pm.group(2)
        except Exception:
            pass

    if base_num is None:
        base_num = 1
    if base_year is None:
        base_year = str(date.today().year)[-2:]

    nxt = base_num + 1
    return jsonify({'next_ddt': f"{nxt:02d}/{base_year}"})


@app.get('/prev_ddt_number')
@login_required
def get_prev_ddt_number():
    """
    Restituisce il numero precedente rispetto a quello attualmente scritto nel campo,
    SENZA memorizzarlo su DB (serve solo per cambiare il valore con le frecce).
    Accetta ?current=NN/YY oppure ?current=NN.
    """
    current = (request.args.get('current') or '').strip()

    base_num = None
    base_year = None

    m = re.match(r'^(\d+)\s*/\s*(\d{2})$', current)
    if m:
        try:
            base_num = int(m.group(1))
            base_year = m.group(2)
        except Exception:
            base_num = None
            base_year = None

    if base_num is None and current.isdigit():
        base_num = int(current)

    if base_num is None or base_year is None:
        try:
            p = peek_next_ddt_number()
            pm = re.match(r'^(\d+)\s*/\s*(\d{2})$', (p or '').strip())
            if pm:
                base_num = int(pm.group(1))
                base_year = pm.group(2)
        except Exception:
            pass

    if base_num is None:
        base_num = 1
    if base_year is None:
        base_year = str(date.today().year)[-2:]

    prv = max(1, base_num - 1)
    return jsonify({'prev_ddt': f"{prv:02d}/{base_year}"})





# ========================================================
#  RUBRICA EMAIL (UI) + BACKUP (download)
# ========================================================






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
    import io
    from pathlib import Path
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER

    def _to_int_safe(v, default=0):
        try:
            if v is None:
                return default
            s = str(v).strip()
            if s == "":
                return default
            s = s.replace(",", ".")
            return int(float(s))
        except Exception:
            return default

    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio,
        pagesize=A4,
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=10*mm
    )
    story = []

    styles = getSampleStyleSheet()
    s_norm  = ParagraphStyle('Norm', parent=styles['Normal'], fontSize=9, leading=11, textColor=colors.black)
    s_bold  = ParagraphStyle('Bold', parent=s_norm, fontName='Helvetica-Bold')
    s_title = ParagraphStyle('Title', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=16, spaceAfter=10, textColor=colors.black)
    s_note  = ParagraphStyle('Note', parent=s_norm, fontSize=9, textColor=colors.darkblue)

    # 1) Logo
    if 'LOGO_PATH' in globals() and LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(str(LOGO_PATH), width=50*mm, height=16*mm, hAlign='CENTER'))
    else:
        story.append(Paragraph("<b>Ca.mar. srl</b>", s_title))

    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("BUONO DI PRELIEVO", s_title))
    story.append(Spacer(1, 5*mm))

    # 2) Dati Testata
    meta_data = [
        [Paragraph("<b>Data Emissione:</b>", s_bold), Paragraph(str(form_data.get('data_em','')), s_norm)],
        [Paragraph("<b>Cliente:</b>", s_bold), Paragraph(str(rows[0].cliente if rows else ''), s_norm)],
        [Paragraph("<b>Fornitore:</b>", s_bold), Paragraph(str(form_data.get('fornitore','')), s_norm)],
        [Paragraph("<b>Commessa:</b>", s_bold), Paragraph(str(form_data.get('commessa','')), s_norm)],
        [Paragraph("<b>Ordine:</b>", s_bold), Paragraph(str(form_data.get('ordine','')), s_norm)],
        [Paragraph("<b>Protocollo:</b>", s_bold), Paragraph(str(form_data.get('protocollo','')), s_norm)],
        [Paragraph("<b>N. Buono:</b>", s_bold), Paragraph(str(form_data.get('buono_n','')), s_norm)],
    ]

    t_meta = Table(meta_data, colWidths=[40*mm, 140*mm])
    t_meta.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 8*mm))

    # 3) Articoli
    header = [
        Paragraph('<b>Codice</b>', s_bold),
        Paragraph('<b>Descrizione</b>', s_bold),
        Paragraph('<b>Q.tà</b>', s_bold),
        Paragraph('<b>N.Arr</b>', s_bold)
    ]
    table_data = [header]

    for r in rows:
        # ✅ Q.tà: prende il valore inserito nel form (q_ID), altrimenti usa PEZZI (r.pezzo)
        q_form = form_data.get(f"q_{r.id_articolo}")
        if q_form is not None and str(q_form).strip() != "":
            q = _to_int_safe(q_form, default=0)
        else:
            q = _to_int_safe(getattr(r, "pezzo", None), default=0)

        codice_pdf = (form_data.get(f"codice_buono_{r.id_articolo}") or str(r.codice_articolo or '')).strip()
        desc = (form_data.get(f"descrizione_buono_{r.id_articolo}") or str(r.descrizione or '')).strip()
        note_user = form_data.get(f"note_{r.id_articolo}")
        if note_user is None:
            note_user = r.note

        table_data.append([
            Paragraph(codice_pdf, s_norm),
            Paragraph(desc, s_norm),
            str(q),
            Paragraph(str(r.n_arrivo or ''), s_norm)
        ])

        if note_user:
            table_data.append([
                '',
                Paragraph(f"<i>Note: {note_user}</i>", s_note),
                '', ''
            ])

    t = Table(table_data, colWidths=[40*mm, 100*mm, 15*mm, 25*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4)
    ]))
    story.append(t)

    story.append(Spacer(1, 20*mm))
    sig_data = [[
        Paragraph("Firma Magazzino:<br/><br/>__________________", s_norm),
        Paragraph("Firma Cliente:<br/><br/>__________________", s_norm)
    ]]
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

# Route /buono/finalize_and_get_pdf spostata in routes/buono.py


# Accettazione Entrata spostata in routes/accettazione_entrata.py

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
        clienti_query = (
            db.query(Articolo.cliente)
              .distinct()
              .filter(Articolo.cliente != None, Articolo.cliente != '')
              .order_by(Articolo.cliente)
              .all()
        )
        clienti_db = [c[0] for c in clienti_query]
        clienti = sorted(set(clienti_db + get_clienti_utenti()))
        return render_template('labels_form.html', clienti=clienti, today_ita=date.today().strftime('%d/%m/%Y'))
    finally:
        db.close()


# ==============================================================================
#  GESTIONE ETICHETTE (PDF) - ROUTE E GENERAZIONE
# ==============================================================================


def _auto_create_entry_from_label(db, form, codice_entrata):
    """Crea automaticamente le righe giacenza partendo dai dati dell'etichetta manuale.
    Mantiene lo stesso codice_entrata / barcode / QR dell'etichetta già creata.
    Se l'entrata esiste già per lo stesso cliente, non duplica le righe.
    Clienti diversi possono usare lo stesso N. arrivo senza bloccarsi.
    """
    codice_entrata = (codice_entrata or '').strip()
    if not codice_entrata:
        return []

    cliente_value = form.get('cliente')
    try:
        cliente_value = validate_cliente_or_raise(cliente_value)
    except Exception:
        cliente_value = (cliente_value or '').strip().upper()

    existing = (
        db.query(Articolo)
          .filter(Articolo.codice_entrata == codice_entrata)
          .filter(normalized_sql_text(Articolo.cliente) == normalize_text_key(cliente_value))
          .order_by(Articolo.id_articolo.asc())
          .all()
    )
    if existing:
        return existing

    try:
        totale_colli = int(to_int_eu(form.get('n_colli')) or 1)
    except Exception:
        totale_colli = 1
    totale_colli = max(1, totale_colli)

    arrivo_base = strip_arrivo_progressivo(form.get('arrivo'))
    created = []

    for idx in range(1, totale_colli + 1):
        art = Articolo()
        art.codice_articolo = form.get('codice_articolo') or ''
        art.descrizione = form.get('descrizione') or ''
        art.cliente = cliente_value
        art.fornitore = form.get('fornitore') or ''
        art.magazzino = (form.get('magazzino') or 'STRUPPA').strip().upper()
        art.protocollo = form.get('protocollo') or ''
        art.ordine = form.get('ordine') or ''
        art.commessa = form.get('commessa') or ''
        art.buono_n = form.get('buono_n') or ''
        art.n_arrivo = build_arrivo_progressivo(arrivo_base or form.get('arrivo'), idx)
        art.ns_rif = form.get('ns_rif') or ''
        art.serial_number = form.get('serial_number') or ''
        art.pezzo = form.get('pezzo') or ''
        art.n_colli = 1
        art.peso = to_float_eu(form.get('peso')) or 0.0
        art.larghezza = to_float_eu(form.get('larghezza')) or 0.0
        art.lunghezza = to_float_eu(form.get('lunghezza')) or 0.0
        art.altezza = to_float_eu(form.get('altezza')) or 0.0
        art.m2 = to_float_eu(form.get('m2')) or 0.0
        art.m3 = to_float_eu(form.get('m3')) or 0.0
        art.posizione = form.get('posizione') or ''
        art.stato = (form.get('stato') or 'NAZIONALE').strip().upper()
        art.note = form.get('note') or ''
        art.mezzi_in_uscita = ''
        art.data_ingresso = (parse_date_ui(form.get('data_ingresso')) or date.today()).strftime('%Y-%m-%d')
        art.n_ddt_ingresso = form.get('ddt_ingresso') or ''
        art.data_uscita = ''
        art.n_ddt_uscita = ''
        art.codice_entrata = codice_entrata
        art.lotto = form.get('lotto') or ''
        db.add(art)
        created.append(art)

    db.commit()
    for art in created:
        db.refresh(art)
    return created


@app.route('/labels_pdf', methods=['POST'])
@login_required
@require_admin
def labels_pdf():
    # Se ci sono ID selezionati, prendi dal DB
    ids = request.form.getlist('ids')
    articoli = []

    if ids:
        db = SessionLocal()
        try:
            articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            changed = False
            for art in articoli:
                codice = ensure_codice_entrata(getattr(art, 'codice_entrata', None), n_arrivo=strip_arrivo_progressivo(art.n_arrivo), n_ddt=art.n_ddt_ingresso, data_ingresso=art.data_ingresso, cliente=art.cliente)
                if getattr(art, 'codice_entrata', None) != codice:
                    art.codice_entrata = codice
                    changed = True
            if changed:
                db.commit()
        finally:
            db.close()
    else:
        # Etichetta Manuale: il N. Arrivo è obbligatorio.
        # Senza arrivo il QR/barcode può diventare instabile o prendere riferimenti sbagliati.
        if not (request.form.get('arrivo') or '').strip():
            flash("Inserisci il N. Arrivo prima di creare l'etichetta: serve per generare QR e barcode corretti.", "warning")
            return redirect(url_for('labels_form'))

        arrivo_base = strip_arrivo_progressivo(request.form.get('arrivo'))
        ddt_ingresso = request.form.get('ddt_ingresso')
        data_ingresso = request.form.get('data_ingresso')
        cliente_etichetta = cliente_from_form_or_current(request.form, request.form.get('cliente'))
        codice_entrata = ensure_codice_entrata(
            request.form.get('codice_entrata'),
            n_arrivo=arrivo_base or request.form.get('arrivo'),
            n_ddt=ddt_ingresso,
            data_ingresso=data_ingresso,
            cliente=cliente_etichetta
        )

        a = Articolo()
        a.cliente = cliente_etichetta
        a.fornitore = request.form.get('fornitore')
        a.ordine = request.form.get('ordine')
        a.commessa = request.form.get('commessa')
        a.n_ddt_ingresso = ddt_ingresso  # nome campo HTML
        a.data_ingresso = (parse_date_ui(data_ingresso) or date.today()).strftime('%Y-%m-%d')
        a.n_arrivo = build_arrivo_progressivo(arrivo_base or request.form.get('arrivo'), 1)
        a.codice_entrata = codice_entrata
        a.n_colli = to_int_eu(request.form.get('n_colli'))
        a.posizione = request.form.get('posizione')
        articoli = [a]

        azione_etichetta = (request.form.get('azione_etichetta') or 'solo_etichetta').strip()
        if azione_etichetta in ('inserisci_entrata', 'etichetta_e_entrata'):
            db = SessionLocal()
            try:
                created_rows = _auto_create_entry_from_label(db, request.form, codice_entrata)
                if created_rows:
                    flash(f"Entrata inserita in giacenza con {len(created_rows)} righe. Codice articolo, descrizione, protocollo, foto e documento potranno essere completati dopo.", 'success')
                else:
                    flash(f"Attenzione: nessuna riga è stata inserita per il barcode {codice_entrata}.", 'warning')
                if azione_etichetta == 'inserisci_entrata':
                    return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))
                # Modalità combinata: crea le righe e scarica subito il PDF etichette.
                # Le etichette usano le righe appena create, quindi riportano 770/26 N.1, N.2, ecc.
                articoli = created_rows or [a]
            except Exception as e:
                db.rollback()
                flash(f"Inserimento entrata non completato: {e}", 'danger')
                return redirect(url_for('labels_form'))
            finally:
                db.close()

    # Genera PDF
    formato = request.form.get('formato', '62x100')
    pdf_bio = _genera_pdf_etichetta(articoli, formato)

    # ✅ FORZA DOWNLOAD (così poi stampi dal file scaricato con formato corretto)
    filename = f"Etichetta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_bio.seek(0)
    return send_file(
        pdf_bio,
        as_attachment=True,              # <-- IMPORTANTISSIMO
        download_name=filename,
        mimetype='application/pdf'
    )


# --- FUNZIONE ETICHETTE COMPATTA (100x62) ---

def _genera_pdf_etichetta(articoli, formato, anteprima=False):
    import io
    from pathlib import Path
    from datetime import datetime, date

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        Image as RLImage
    )
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.pagesizes import A4

    bio = io.BytesIO()

    if formato == '62x100':
        pagesize = (100 * mm, 62 * mm)
        margin = 1.2 * mm
    else:
        pagesize = A4
        margin = 10 * mm

    doc = SimpleDocTemplate(
        bio,
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )

    styles = getSampleStyleSheet()

    s_lbl = ParagraphStyle('LBL', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.0, leading=8.1)
    s_val = ParagraphStyle('VAL', parent=styles['Normal'], fontName='Helvetica', fontSize=7.7, leading=7.9)
    s_hi = ParagraphStyle('HI', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.7, leading=8.9)
    s_scan_title = ParagraphStyle('SCANTITLE', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.0, leading=9.2, alignment=1)
    s_bar_label = ParagraphStyle('BARLBL', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=6.2, leading=6.4, alignment=1)
    s_bar_value = ParagraphStyle('BARVAL', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.0, leading=7.2, alignment=1)

    if 'LOGO_PATH' in globals() and LOGO_PATH:
        logo_path = Path(LOGO_PATH)
    else:
        logo_path = Path(app.root_path) / 'static' / 'logo camar.jpg'

    def fmt_date(v):
        if not v:
            return ''
        try:
            if isinstance(v, (datetime, date)):
                return v.strftime('%d/%m/%Y')
            s = str(v).strip()
            if not s:
                return ''
            try:
                return datetime.strptime(s[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            except Exception:
                pass
            try:
                return datetime.strptime(s[:10], '%d/%m/%Y').strftime('%d/%m/%Y')
            except Exception:
                return s[:10]
        except Exception:
            return str(v)

    def build_qr_flowable(value, side_mm=24):
        try:
            value = str(value or '').strip()
            if not value:
                return Spacer(side_mm * mm, side_mm * mm)
            qr = QrCodeWidget(value)
            bounds = qr.getBounds()
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            side = side_mm * mm
            drawing = Drawing(side, side, transform=[side / width, 0, 0, side / height, 0, 0])
            drawing.add(qr)
            return drawing
        except Exception as e:
            print(f"[WARN] QR non generato: {e}")
            return Spacer(side_mm * mm, side_mm * mm)

    def build_code128_flowable(value, target_w_mm=72, target_h_mm=12):
        try:
            value = str(value or '').strip()
            if not value:
                return Spacer(target_w_mm * mm, target_h_mm * mm)
            bc = createBarcodeDrawing(
                'Code128',
                value=value,
                barHeight=target_h_mm * mm,
                barWidth=0.24 * mm,
                humanReadable=False,
            )
            try:
                sx = (target_w_mm * mm) / float(bc.width) if getattr(bc, 'width', 0) else 1
                sy = (target_h_mm * mm) / float(bc.height) if getattr(bc, 'height', 0) else 1
                bc.scale(sx, sy)
            except Exception:
                pass
            return bc
        except Exception as e:
            print(f"[WARN] Barcode non generato: {e}")
            return Spacer(target_w_mm * mm, target_h_mm * mm)

    story = []

    def extract_arrivo_progressivo(value):
        s = (value or '').strip()
        m = re.search(r'N\.?\s*(\d+)', s, flags=re.I)
        return int(m.group(1)) if m else None

    total_pages = 0
    colli_per_art = []
    saved_progressivi = []
    for art in articoli:
        try:
            tot = int(getattr(art, 'n_colli', None) or 1)
        except Exception:
            tot = 1
        tot = max(1, tot)
        colli_per_art.append(tot)
        saved_progressivi.append(extract_arrivo_progressivo(getattr(art, 'n_arrivo', '') or ''))
        total_pages += tot * 2

    totale_entrata = sum(colli_per_art) if colli_per_art else 1
    totale_entrata = max(1, int(totale_entrata or 1))

    # Se le righe arrivano già numerate come N.1, N.2, ... (tipico dalla ristampa dell'entrata),
    # usa quella sequenza per mostrare sempre X/TOTALE e non 1/1 sulla singola riga.
    progressivi_presenti = [p for p in saved_progressivi if p]
    use_saved_progressivi = len(progressivi_presenti) == len(articoli) and len(articoli) > 0
    if use_saved_progressivi:
        totale_entrata = max(totale_entrata, max(progressivi_presenti))

    page_counter = 0

    for art, tot in zip(articoli, colli_per_art):
        for i in range(1, tot + 1):
            saved_arrivo = (getattr(art, 'n_arrivo', '') or '').strip()
            saved_prog = extract_arrivo_progressivo(saved_arrivo)
            if tot <= 1:
                arr_str = saved_arrivo or build_arrivo_progressivo(saved_arrivo, 1)
                if saved_prog and totale_entrata > 1:
                    collo_str = f"{saved_prog}/{totale_entrata}"
                else:
                    collo_str = f"1/{max(1, totale_entrata)}"
            else:
                arr_str = build_arrivo_progressivo(saved_arrivo, i)
                # Se la riga ha già un progressivo salvato, trattalo come base per i colli successivi.
                start_prog = saved_prog if saved_prog else i
                current_prog = start_prog + (i - 1 if saved_prog else 0)
                denom = max(totale_entrata, current_prog)
                collo_str = f"{current_prog}/{denom}"
            codice_entrata = ensure_codice_entrata(
                getattr(art, 'codice_entrata', None),
                n_arrivo=strip_arrivo_progressivo(getattr(art, 'n_arrivo', None)),
                n_ddt=getattr(art, 'n_ddt_ingresso', None),
                data_ingresso=getattr(art, 'data_ingresso', None),
                cliente=getattr(art, 'cliente', None)
            )
            dettaglio_url = build_entry_public_url(codice_entrata)

            # Pagina 1: etichetta principale
            if logo_path.exists():
                try:
                    img = RLImage(str(logo_path), width=34 * mm, height=8.5 * mm)
                    img.hAlign = 'LEFT'
                    story.append(img)
                    story.append(Spacer(1, 0.5 * mm))
                except Exception:
                    pass

            dati = [
                [Paragraph('CLIENTE:', s_lbl),   Paragraph((getattr(art, 'cliente', '') or ''), s_val)],
                [Paragraph('FORNITORE:', s_lbl), Paragraph((getattr(art, 'fornitore', '') or ''), s_val)],
                [Paragraph('ORDINE:', s_lbl),    Paragraph((getattr(art, 'ordine', '') or ''), s_val)],
                [Paragraph('COMMESSA:', s_lbl),  Paragraph((getattr(art, 'commessa', '') or ''), s_val)],
                [Paragraph('DDT ING.:', s_lbl),  Paragraph((getattr(art, 'n_ddt_ingresso', '') or ''), s_val)],
                [Paragraph('DATA ING.:', s_lbl), Paragraph(fmt_date(getattr(art, 'data_ingresso', '')), s_val)],
                [Paragraph('ARRIVO:', s_lbl),    Paragraph(arr_str, s_hi)],
                [Paragraph('N. COLLO:', s_lbl),  Paragraph(collo_str, s_hi)],
                [Paragraph('COLLI:', s_lbl),     Paragraph(str(max(totale_entrata, tot)), s_hi)],
                [Paragraph('POSIZIONE:', s_lbl), Paragraph((getattr(art, 'posizione', '') or ''), s_val)],
            ]
            t = Table(dati, colWidths=[25 * mm, 71 * mm])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(t)
            page_counter += 1
            if page_counter < total_pages:
                story.append(PageBreak())

            # Pagina 2: mini etichetta scansione (solo QR + barcode)
            if logo_path.exists():
                try:
                    img2 = RLImage(str(logo_path), width=22 * mm, height=5.5 * mm)
                    img2.hAlign = 'CENTER'
                    story.append(img2)
                    story.append(Spacer(1, 0.8 * mm))
                except Exception:
                    pass

            story.append(Paragraph('SCANSIONE ENTRATA', s_scan_title))
            story.append(Spacer(1, 1.0 * mm))
            story.append(build_qr_flowable(dettaglio_url or codice_entrata, side_mm=24))
            story.append(Spacer(1, 1.0 * mm))
            story.append(Paragraph('CODICE ENTRATA', s_bar_label))
            story.append(Paragraph(codice_entrata, s_bar_value))
            story.append(Spacer(1, 0.8 * mm))
            bc = build_code128_flowable(codice_entrata, target_w_mm=72, target_h_mm=12)
            barcode_tbl = Table([[bc]], colWidths=[96 * mm])
            barcode_tbl.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(barcode_tbl)

            page_counter += 1
            if page_counter < total_pages:
                story.append(PageBreak())

    doc.build(story)
    bio.seek(0)
    return bio


# --- CONFIGURAZIONE FINALE E AVVIO ---
app.jinja_loader = ChoiceLoader([
    DictLoader(templates),
    FileSystemLoader(str(APP_DIR / 'templates'))
])
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
            ("lunghezza", "FLOAT"), ("larghezza", "FLOAT"), ("altezza", "FLOAT"),
            ("codice_entrata", "TEXT")
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

# Calcolo costi / giacenze mensili spostato in routes/fatturazione.py



# ========================================================
#  SCARICO PARZIALE PEZZI
# ========================================================
SCARICO_PARZIALE_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="container py-3">
    <div class="card shadow-sm">
        <div class="card-header bg-warning fw-bold">
            📤 Scarico parziale pezzi
        </div>
        <div class="card-body">
            <p class="text-muted mb-3">
                Crea una riga di scarico con data/DDT/buono e lascia la riga residua ancora in giacenza.
            </p>

            <div class="row g-2 mb-3">
                <div class="col-md-2"><strong>ID:</strong><br>{{ art.id_articolo }}</div>
                <div class="col-md-3"><strong>Cliente:</strong><br>{{ art.cliente or '' }}</div>
                <div class="col-md-3"><strong>Codice:</strong><br>{{ art.codice_articolo or '' }}</div>
                <div class="col-md-4"><strong>Descrizione:</strong><br>{{ art.descrizione or '' }}</div>
            </div>

            <div class="alert alert-info">
                Pezzi disponibili: <strong>{{ pezzi_disponibili }}</strong><br>
                Peso disponibile: <strong>{{ peso_disponibile }}</strong> kg
            </div>

            <form method="POST" onsubmit="return confirm('Confermi lo scarico parziale?');">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label fw-bold">Codice da mettere nel buono/scarico</label>
                        <textarea name="codice_scarico" class="form-control" rows="2">{{ art.codice_articolo or '' }}</textarea>
                        <div class="form-text">Se la riga contiene più codici, lascia qui solo quello da prelevare. Nella riga residua resteranno eventuali riferimenti PACKAGE / PALLET / CASSA.</div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label fw-bold">Descrizione da mettere nel buono/scarico</label>
                        <textarea name="descrizione_scarico" class="form-control" rows="2">{{ art.descrizione or '' }}</textarea>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-bold">Pezzi da scaricare</label>
                        <input type="text" name="pezzi_scarico" class="form-control" required autofocus>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-bold">Peso da scaricare (kg)</label>
                        <input type="text" name="peso_scarico" class="form-control" required>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-bold">Data uscita / data DDT</label>
                        <input type="date" name="data_uscita" class="form-control" value="{{ oggi }}" required>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-bold">N. DDT uscita</label>
                        <input type="text" name="n_ddt_uscita" class="form-control" required>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-bold">N. buono</label>
                        <input type="text" name="buono_n" class="form-control" value="{{ art.buono_n or '' }}">
                    </div>
                    <div class="col-12">
                        <label class="form-label fw-bold">Note aggiuntive</label>
                        <textarea name="note_extra" class="form-control" rows="2"></textarea>
                    </div>
                </div>

                <div class="mt-4 d-flex gap-2">
                    <button type="submit" class="btn btn-warning fw-bold">Conferma scarico</button>
                    <a href="{{ url_for('giacenze') }}" class="btn btn-secondary">Annulla</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
"""


@app.route('/scarico_parziale_selezionato', methods=['POST'])
@login_required
@require_admin
def scarico_parziale_selezionato():
    """Apre lo scarico parziale usando una sola riga selezionata dalla tabella giacenze."""
    ids = request.form.getlist('ids') or request.form.getlist('selected_ids') or request.form.getlist('selected') or []
    ids = [str(x).strip() for x in ids if str(x).strip().isdigit()]

    if len(ids) != 1:
        flash("Seleziona una sola riga per fare lo scarico parziale.", "warning")
        return redirect(url_for('giacenze'))

    return redirect(url_for('scarico_parziale', id_articolo=int(ids[0])))


@app.route('/scarico_parziale/<int:id_articolo>', methods=['GET', 'POST'])
@login_required
@require_admin
def scarico_parziale(id_articolo):
    db = SessionLocal()
    try:
        art = db.query(Articolo).options(selectinload(Articolo.attachments)).filter(Articolo.id_articolo == id_articolo).first()
        if not art:
            flash("Articolo non trovato.", "danger")
            return redirect(url_for('giacenze'))

        if art.data_uscita or art.n_ddt_uscita:
            flash("Questa riga risulta già scaricata: non posso fare uno scarico parziale.", "warning")
            return redirect(url_for('giacenze'))

        # Salvo subito i valori originali: servono per non perdere codice/descrizione
        # quando creo la nuova riga di scarico e quando aggiorno la riga residua.
        codice_originale = (art.codice_articolo or '').strip()
        descrizione_originale = (art.descrizione or '').strip()

        def _num_float(v):
            try:
                if v is None:
                    return 0.0
                s = str(v).strip()
                if not s:
                    return 0.0
                # Gestione italiana: 1.234,56 -> 1234.56 / 1234,56 -> 1234.56
                if ',' in s:
                    s = s.replace('.', '').replace(',', '.')
                return float(s)
            except Exception:
                return 0.0

        def _fmt_num(v, decimals=3):
            try:
                f = float(v or 0)
                if abs(f - int(f)) < 0.000001:
                    return str(int(f))
                return str(round(f, decimals)).replace('.', ',')
            except Exception:
                return str(v or '')

        def _fmt_peso(v):
            try:
                f = float(v or 0)
                return f
            except Exception:
                return 0.0

        def _split_materiale_tokens(value):
            """Divide codici/descrizioni mantenendo leggibili separatori comuni."""
            raw = (value or '').strip()
            if not raw:
                return []
            parts = re.split(r"\s*(?:;|\n|\+|,|\s/\s)\s*", raw)
            return [p.strip() for p in parts if p and p.strip()]

        def _is_marker_package_pallet_cassa(value):
            s = (value or '').strip().upper()
            return bool(re.search(r"\b(PACKAGE|PKG|PALLET|CASSA|CASE|COLLO)\b", s))

        def _remove_requested_preserve_markers(original, requested):
            """Rimuove il codice/descrizione prelevato dalla riga residua,
            ma NON elimina riferimenti PACKAGE / PALLET / CASSA.
            """
            original = (original or '').strip()
            requested = (requested or '').strip()
            if not original or not requested:
                return original
            if requested == original:
                # Se il testo scelto è identico alla riga originale NON svuotiamo la riga residua.
                # Nello scarico parziale di pezzi dello stesso articolo, il residuo deve mantenere
                # codice articolo e descrizione uguali alla riga iniziale.
                return original

            req_norm = normalize_text_key(requested) if 'normalize_text_key' in globals() else re.sub(r'[^A-Z0-9]+', '', requested.upper())
            kept = []
            for part in _split_materiale_tokens(original):
                part_norm = normalize_text_key(part) if 'normalize_text_key' in globals() else re.sub(r'[^A-Z0-9]+', '', part.upper())
                if _is_marker_package_pallet_cassa(part):
                    kept.append(part)
                    continue
                if req_norm and (part_norm == req_norm or req_norm in part_norm or part_norm in req_norm):
                    continue
                kept.append(part)
            if kept:
                return ' ; '.join(kept)

            cleaned = re.sub(re.escape(requested), '', original, flags=re.I)
            cleaned = re.sub(r"\s*(;|,|\+)\s*(;|,|\+)+", "; ", cleaned)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ;,+-/")
            return cleaned

        pezzi_disponibili = _num_float(art.pezzo)
        peso_disponibile = _num_float(art.peso)

        if pezzi_disponibili <= 0:
            flash("Impossibile fare lo scarico parziale: il campo Pezzi è vuoto o non numerico.", "danger")
            return redirect(url_for('giacenze'))

        if peso_disponibile <= 0:
            flash("Impossibile fare lo scarico parziale: il campo Peso è vuoto o non numerico.", "danger")
            return redirect(url_for('giacenze'))

        if request.method == 'POST':
            pezzi_scarico = _num_float(request.form.get('pezzi_scarico'))
            peso_scarico = _num_float(request.form.get('peso_scarico'))
            data_uscita_val = (request.form.get('data_uscita') or '').strip()
            n_ddt_uscita_val = (request.form.get('n_ddt_uscita') or '').strip()
            buono_val = (request.form.get('buono_n') or '').strip()
            note_extra = (request.form.get('note_extra') or '').strip()
            codice_scarico_val = (request.form.get('codice_scarico') or codice_originale or art.codice_articolo or '').strip()
            descrizione_scarico_val = (request.form.get('descrizione_scarico') or descrizione_originale or art.descrizione or '').strip()

            if pezzi_scarico <= 0:
                flash("Inserisci un numero di pezzi da scaricare maggiore di zero.", "danger")
                return redirect(url_for('scarico_parziale', id_articolo=id_articolo))

            if peso_scarico <= 0:
                flash("Inserisci un peso da scaricare maggiore di zero.", "danger")
                return redirect(url_for('scarico_parziale', id_articolo=id_articolo))

            if pezzi_scarico > pezzi_disponibili:
                flash("Non puoi scaricare più pezzi di quelli disponibili.", "danger")
                return redirect(url_for('scarico_parziale', id_articolo=id_articolo))

            if peso_scarico > peso_disponibile:
                flash("Non puoi scaricare più peso di quello disponibile.", "danger")
                return redirect(url_for('scarico_parziale', id_articolo=id_articolo))

            if not data_uscita_val or not n_ddt_uscita_val:
                flash("Data uscita e numero DDT sono obbligatori.", "danger")
                return redirect(url_for('scarico_parziale', id_articolo=id_articolo))

            # La decisione tra scarico TOTALE e PARZIALE deve dipendere dai PEZZI,
            # non dal peso. Prima confrontava anche il peso: se per errore veniva
            # inserito il peso totale, il gestionale trattava lo scarico come totale
            # e NON creava la nuova riga di uscita.
            scarico_totale = abs(pezzi_scarico - pezzi_disponibili) < 0.000001

            # Se lo scarico è parziale ma il peso inserito è uguale/superiore al peso totale,
            # calcolo automaticamente il peso proporzionale per evitare residuo a zero.
            if not scarico_totale and peso_scarico >= peso_disponibile:
                peso_scarico = peso_disponibile * (pezzi_scarico / pezzi_disponibili)

            # Scarico totale: aggiorno direttamente la riga originale
            if scarico_totale:
                art.data_uscita = data_uscita_val
                art.n_ddt_uscita = n_ddt_uscita_val
                art.buono_n = buono_val or art.buono_n
                art.codice_articolo = codice_scarico_val or art.codice_articolo
                art.descrizione = descrizione_scarico_val or art.descrizione
                art.peso = _fmt_peso(peso_scarico)
                art.note = (
                    (art.note or '').strip()
                    + f" | SCARICO TOTALE: {_fmt_num(pezzi_scarico)} pezzi / {_fmt_num(peso_scarico, 2)} kg - DDT {n_ddt_uscita_val} del {data_uscita_val}"
                    + (f" - {note_extra}" if note_extra else "")
                ).strip(" |")
                db.commit()
                flash("Scarico totale salvato sulla riga selezionata.", "success")
                return redirect(url_for('giacenze'))

            # Scarico parziale: creo riga uscita e aggiorno originale come residuo
            pezzi_residui = pezzi_disponibili - pezzi_scarico
            peso_residuo = peso_disponibile - peso_scarico

            scarico = Articolo()
            for col in Articolo.__table__.columns:
                if col.name == 'id_articolo':
                    continue
                setattr(scarico, col.name, getattr(art, col.name))

            # La nuova riga di scarico deve sempre avere codice e descrizione.
            scarico.codice_articolo = codice_scarico_val or codice_originale or scarico.codice_articolo
            scarico.descrizione = descrizione_scarico_val or descrizione_originale or scarico.descrizione
            scarico.pezzo = _fmt_num(pezzi_scarico)
            scarico.peso = _fmt_peso(peso_scarico)
            scarico.data_uscita = data_uscita_val
            scarico.n_ddt_uscita = n_ddt_uscita_val
            scarico.buono_n = buono_val
            scarico.note = (
                (scarico.note or '').strip()
                + f" | SCARICO PARZIALE da ID {art.id_articolo}: {_fmt_num(pezzi_scarico)} pezzi / {_fmt_num(peso_scarico, 2)} kg - DDT {n_ddt_uscita_val} del {data_uscita_val}"
                + (f" - {note_extra}" if note_extra else "")
            ).strip(" |")

            residuo_codice = _remove_requested_preserve_markers(codice_originale or art.codice_articolo, codice_scarico_val)
            residuo_descrizione = _remove_requested_preserve_markers(descrizione_originale or art.descrizione, descrizione_scarico_val)

            # Se lo scarico è di una parte dei pezzi dello stesso articolo, la riga residua
            # NON deve rimanere vuota: conserva codice e descrizione originali.
            art.codice_articolo = (residuo_codice or codice_originale or art.codice_articolo or '').strip()
            art.descrizione = (residuo_descrizione or descrizione_originale or art.descrizione or '').strip()
            art.pezzo = _fmt_num(pezzi_residui)
            art.peso = _fmt_peso(peso_residuo)
            art.data_uscita = ''
            art.n_ddt_uscita = ''
            art.note = (
                (art.note or '').strip()
                + f" | RESIDUO da scarico parziale: restano {_fmt_num(pezzi_residui)} pezzi / {_fmt_num(peso_residuo, 2)} kg"
            ).strip(" |")

            db.add(scarico)
            db.commit()

            flash(
                f"Scarico parziale creato: {_fmt_num(pezzi_scarico)} pezzi / {_fmt_num(peso_scarico, 2)} kg scaricati; "
                f"{_fmt_num(pezzi_residui)} pezzi / {_fmt_num(peso_residuo, 2)} kg restano in giacenza.",
                "success"
            )
            return redirect(url_for('giacenze'))

        return render_template_string(
            SCARICO_PARZIALE_HTML,
            art=art,
            pezzi_disponibili=_fmt_num(pezzi_disponibili),
            peso_disponibile=_fmt_num(peso_disponibile, 2),
            oggi=date.today().strftime('%Y-%m-%d')
        )

    except Exception as e:
        db.rollback()
        flash(f"Errore scarico parziale: {e}", "danger")
        return redirect(url_for('giacenze'))
    finally:
        db.close()









# ========================================================
#  REGISTRAZIONE MODULO TRASPORTI
# ========================================================
try:
    from routes.trasporti import register_trasporti_routes
    register_trasporti_routes(app, globals())
except Exception as e:
    scrivi_log_errore("Modulo trasporti non registrato", e)
    print(f"[WARN] modulo trasporti non registrato: {e}")



# ========================================================
#  REGISTRAZIONE MODULO EMAIL
# ========================================================
try:
    from routes.email import register_email_routes
    register_email_routes(app, globals())
except Exception as e:
    print(f"[WARN] modulo email non registrato: {e}")



# ========================================================
#  REGISTRAZIONE MODULO BUONO PRELIEVO
# ========================================================

try:
    from routes.picking import register_picking_routes
    register_picking_routes(app, globals())
    print('[OK] modulo picking registrato')
except Exception as e:
    scrivi_log_errore('Modulo picking non registrato', e)
    print(f'[WARN] modulo picking non registrato: {e}')

try:
    from routes.buono import register_buono_routes
    register_buono_routes(app, globals())
except Exception as e:
    scrivi_log_errore("Modulo buono prelievo non registrato", e)
    print(f"[WARN] modulo buono prelievo non registrato: {e}")

# ========================================================
#  REGISTRAZIONE MODULO DDT
# ========================================================
try:
    from routes.ddt import register_ddt_routes
    register_ddt_routes(app, globals())
except Exception as e:
    print(f"[WARN] modulo ddt non registrato: {e}")


# ========================================================
#  REGISTRAZIONE MODULO MAGAZZINO - PREPARAZIONE
# ========================================================
try:
    from routes.magazzino import register_magazzino_routes
    register_magazzino_routes(app, globals())
except Exception as e:
    print(f"[WARN] modulo magazzino non registrato: {e}")


# ========================================================
#  REGISTRAZIONE MODULO IMPORT PDF
#  Template Import PDF spostato in routes/import_pdf.py
# ========================================================
try:
    from routes.import_pdf import register_import_pdf_routes
    register_import_pdf_routes(app, globals())
except Exception as e:
    print(f"[WARN] modulo import_pdf non registrato: {e}")


# ========================================================
#  REGISTRAZIONE MODULO BUONI DI CARICO QR
# ========================================================

try:
    from routes.fatturazione import register_fatturazione_routes
    register_fatturazione_routes(app, globals())
except Exception as e:
    print(f"[WARN] routes.fatturazione non caricato: {e}")

from routes.buoni_qr import register_buoni_qr_routes
register_buoni_qr_routes(app, globals())



# ========================================================
#  REGISTRAZIONE MODULO ALLEGATI
# ========================================================
try:
    from routes.allegati import register_allegati_routes
    register_allegati_routes(app, globals())
    print("[OK] modulo allegati registrato")
except Exception as e:
    scrivi_log_errore("Modulo allegati non registrato", e)
    print(f"[WARN] modulo allegati non registrato: {e}")


# ========================================================
#  PWA / SMARTPHONE
# ========================================================
@app.route("/manifest.webmanifest")
def pwa_manifest():
    """Manifest PWA: permette di aggiungere il gestionale alla schermata Home dello smartphone."""
    manifest = {
        "name": "Gestionale Camar",
        "short_name": "Camar",
        "description": "Gestionale magazzino Camar",
        "start_url": "/chatbot",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1f6fb2",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/logo camar.jpg",
                "sizes": "192x192",
                "type": "image/jpeg",
                "purpose": "any maskable"
            },
            {
                "src": "/static/logo camar.jpg",
                "sizes": "512x512",
                "type": "image/jpeg",
                "purpose": "any maskable"
            }
        ]
    }
    return app.response_class(
        json.dumps(manifest, ensure_ascii=False),
        mimetype="application/manifest+json"
    )


@app.route("/service-worker.js")
def pwa_service_worker():
    """Service worker leggero: cache minima delle pagine principali, senza toccare dati sensibili."""
    js = """
const CACHE_NAME = 'camar-gestionale-v1';
const CORE_ASSETS = [
  '/login',
  '/chatbot',
  '/manifest.webmanifest'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CORE_ASSETS).catch(() => null))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Non mettere mai in cache POST, API e file allegati.
  if (req.method !== 'GET' || url.pathname.startsWith('/chatbot/api') || url.pathname.startsWith('/camy-ai/api') || url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) {
    return;
  }

  event.respondWith(
    fetch(req).then(resp => {
      const copy = resp.clone();
      if (resp.ok && (url.pathname === '/chatbot' || url.pathname === '/camy-ai' || url.pathname === '/login' || url.pathname === '/manifest.webmanifest')) {
        caches.open(CACHE_NAME).then(cache => cache.put(req, copy)).catch(() => null);
      }
      return resp;
    }).catch(() => caches.match(req))
  );
});
"""
    return app.response_class(js, mimetype="application/javascript")


@app.route("/offline")
def pwa_offline():
    return "Gestionale Camar: connessione assente. Riapri quando torna internet.", 200



# ========================================================
#  REGISTRAZIONE MODULO DASHBOARD HOME
# ========================================================
try:
    from routes.dashboard_home import register_dashboard_home_routes
    register_dashboard_home_routes(app, globals())
    print("[OK] modulo dashboard home registrato")
except Exception as e:
    try:
        scrivi_log_errore("Modulo dashboard home non registrato", e)
    except Exception:
        pass
    print(f"[WARN] modulo dashboard home non registrato: {e}")

# ========================================================
#  REGISTRAZIONE MODULO BACKUP
# ========================================================
try:
    from routes.backup import register_backup_routes
    register_backup_routes(app, globals())
    print("[OK] modulo backup registrato")
except Exception as e:
    scrivi_log_errore("Modulo backup non registrato", e)
    print(f"[WARN] modulo backup non registrato: {e}")

try:
    from routes.api import register_api_routes
    register_api_routes(app, globals())
    print("[OK] modulo API clienti registrato")
except Exception as e:
    scrivi_log_errore("Modulo API clienti non registrato", e)
    print(f"[WARN] modulo API clienti non registrato: {e}")


# ========================================================
#  REGISTRAZIONE MODULO CAMY AI
# ========================================================
try:
    from routes.camy_ai import register_camy_ai_routes
    register_camy_ai_routes(app, globals())
    print("[OK] modulo CAMY AI registrato")
except Exception as e:
    scrivi_log_errore("Modulo CAMY AI non registrato", e)
    print(f"[WARN] modulo CAMY AI non registrato: {e}")

# ========================================================
#  REGISTRAZIONE MODULO CHATBOT
# ========================================================
try:
    from routes.chatbot import register_chatbot_routes
    register_chatbot_routes(app, globals())
    print("[OK] modulo chatbot registrato")
except Exception as e:
    scrivi_log_errore("Modulo chatbot non registrato", e)
    print(f"[WARN] modulo chatbot non registrato: {e}")

# --- AVVIO FLASK APP ---

# ========================================================
#  REGISTRAZIONE MODULO GESTIONE UTENTI
# ========================================================
try:
    from routes.utenti import register_utenti_routes
    register_utenti_routes(app, globals())
    print("[OK] modulo gestione utenti registrato")
except Exception as e:
    print(f"[WARN] modulo gestione utenti non caricato: {e}")


# ========================================================
# CAMY BUONO DA EMAIL / PDF / FOTO
# ========================================================
try:
    from routes.camy_email_buono import register_camy_email_buono_routes
    register_camy_email_buono_routes(app, globals())
    print("[OK] modulo CAMY Buono da Email registrato")
except Exception as e:
    try:
        scrivi_log_errore("Modulo CAMY Buono da Email non registrato", e)
    except Exception:
        pass
    print(f"[WARN] modulo CAMY Buono da Email non registrato: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)


# ========================================================
# ROUTE ACCETTAZIONE ENTRATA DA DOCUMENTO
# ========================================================
try:
    from routes.accettazione_entrata import register_accettazione_entrata_routes
    register_accettazione_entrata_routes(app, globals())
except Exception as e:
    scrivi_log_errore("Modulo Accettazione Entrata non registrato", e)
    print(f"[WARN] modulo Accettazione Entrata non registrato: {e}")
