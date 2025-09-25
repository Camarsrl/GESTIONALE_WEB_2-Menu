# -*- coding: utf-8 -*-
"""
Gestionale Camar – versione:
- Persistenza MySQL/SQLite (env DATABASE_URL)
- Nuove schermate CREA BUONO / CREA DDT con ANTEPRIMA e PDF
- Etichette 99,82×61,98 mm con logo, testo ridotto, senza intestazioni superflue
- Giacenze: tutte le colonne, campi vuoti senza "None"
- Nuovo Articolo tramite form
"""

import os, io, re, json, uuid, smtplib
from email.message import EmailMessage
from datetime import datetime, date
from pathlib import Path

import pandas as pd
from flask import (
    Flask, request, render_template_string, redirect, url_for,
    send_file, session, flash, abort, Blueprint
)

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet

# Jinja loader (filesystem + inline)
from jinja2 import ChoiceLoader, FileSystemLoader, DictLoader

# ------------------- PATH / LOGO -------------------
APP_DIR = Path(os.environ.get("APP_DIR", "."))
APP_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

MEDIA_DIR = APP_DIR / "media"
DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"
for d in (DOCS_DIR, PHOTOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOGO_PATH = os.environ.get("LOGO_PATH") or str(STATIC_DIR / "logo.png")
if not Path(LOGO_PATH).exists():
    for alt in ("logo camar.jpg", "logo.jpg", "logo.jpeg", "logo.png"):
        p = STATIC_DIR / alt
        if p.exists():
            LOGO_PATH = str(p)
            break

# ------------------- DATABASE -------------------
DB_URL = (os.environ.get("DATABASE_URL") or "").strip()

def _normalize_db_url(u: str) -> str:
    if not u:
        return u
    if u.startswith("mysql://"):
        u = "mysql+pymysql://" + u[len("mysql://"):]
    if any(tok in u for tok in ("<PORT>", "<HOST>", "<USER>", "<PASSWORD>", "<DBNAME>", "<DATABASE>")) or re.search(r"<[^>]+>", u):
        raise ValueError("DATABASE_URL contiene segnaposto. Inserisci valori reali oppure rimuovi la variabile per usare SQLite.")
    return u

if DB_URL:
    DB_URL = _normalize_db_url(DB_URL)
    engine = create_engine(DB_URL, future=True, pool_pre_ping=True)
else:
    sqlite_path = APP_DIR / "magazzino.db"
    DB_URL = f"sqlite:///{sqlite_path}"
    engine = create_engine(DB_URL, future=True)

SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

DESTINATARI_JSON = APP_DIR / "destinatari_saved.json"
PROG_FILE = APP_DIR / "progressivi_ddt.json"

# ------------------- MODELLI -------------------
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

# ------------------- UTENTI -------------------
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

# ------------------- UTILS -------------------
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
    try:
        return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
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
    if DESTINATARI_JSON.exists():
        try:
            return json.loads(DESTINATARI_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = {
        "FINCANTIERI":{"ragione_sociale":"FINCANTIERI","indirizzo":"Via Sestri 47, Genova","piva":""}
    }
    DESTINATARI_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def save_destinatario(key, obj):
    data = load_destinatari()
    data[key] = obj
    DESTINATARI_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def next_ddt_number():
    y = str(date.today().year)
    prog = {}
    if PROG_FILE.exists():
        try:
            prog = json.loads(PROG_FILE.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
    n = int(prog.get(y, 0)) + 1
    prog[y] = n
    PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{n:03d}/{y}"

# ------------------- APP / TEMPLATES -------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.jinja_env.globals['getattr'] = getattr

BASE = """
<!doctype html><html lang='it'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{{ title or "Gestionale Web" }}</title>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>
body{background:#f7f9fc}.card{border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.06)}
.table thead th{position:sticky;top:0;background:#fff;z-index:2}
.dropzone{border:2px dashed #7aa2ff;background:#eef4ff;padding:16px;border-radius:12px;text-align:center;color:#2c4a9a}
@media print{.no-print{display:none!important}}
.logo{height:40px}
</style></head><body>
<nav class='navbar bg-white shadow-sm'><div class='container-fluid'>
  <div class='d-flex align-items-center gap-2'>
    {% if logo_url %}<img src='{{logo_url}}' class='logo' alt='logo'>{% endif %}
    <a class='navbar-brand' href='{{url_for("home")}}'>Camar • Gestionale</a>
  </div>
  <div class='ms-auto'>
    {% if session.get('user') %}
      <span class='me-3'>Utente: <b>{{session['user']}}</b></span>
      <a class='btn btn-outline-secondary btn-sm' href='{{url_for("logout")}}'>Logout</a>
    {% endif %}
  </div>
</div></nav>
<div class='container my-4'>
  {% with m=get_flashed_messages(with_categories=true) %}
    {% for c,t in m %}<div class='alert alert-{{c}} alert-dismissible fade show'>{{t}}<button class='btn-close' data-bs-dismiss='alert'></button></div>{% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'></script>
</body></html>
"""

LOGIN = """{% extends 'base.html' %}{% block content %}
<div class='row justify-content-center'><div class='col-md-5'><div class='card p-4'>
  <h4 class='mb-3'>Login</h4>
  <form method='post'>
    <div class='mb-3'><label class='form-label'>Utente</label><input name='user' class='form-control' required></div>
    <div class='mb-3'><label class='form-label'>Password</label><input type='password' name='pwd' class='form-control' required></div>
    <button class='btn btn-primary'>Entra</button>
  </form>
</div></div></div>
{% endblock %}"""

HOME = """{% extends 'base.html' %}{% block content %}
<div class='row g-3'>
  <div class='col-md-3'>
    <div class='card p-3'>
      <h6>Azioni</h6><div class='d-grid gap-2'>
        <a class='btn btn-outline-primary' href='{{url_for("labels_form")}}'>Etichette</a>
        <a class='btn btn-outline-primary' href='{{url_for("giacenze")}}'>Visualizza Giacenze</a>
        <a class='btn btn-outline-primary' href='{{url_for("import_excel")}}'>Import da Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel")}}'>Export Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel_by_client")}}'>Export per Cliente</a>
        <a class='btn btn-outline-success' href='{{url_for("add_row")}}'>Nuovo Articolo</a>
      </div>
    </div>
  </div>
  <div class='col-md-9'><div class='card p-4'>
    <h4>Benvenuto</h4>
    <p class='text-muted'>Stampe con logo, anteprime modificabili, DDT con progressivo, etichette 99,82×61,98 mm.</p>
  </div></div>
</div>
{% endblock %}"""

# ------------------- GIACENZE -------------------
GIACENZE = """{% extends 'base.html' %}{% block content %}
<div class='card p-3 mb-3'>
  <form class='row g-2' method='get'>
    {% for label,name in filters %}
      <div class='col-md-2'><label class='form-label small'>{{label}}</label>
        <input name='{{name}}' value='{{request.args.get(name,"")}}' class='form-control form-control-sm'></div>
    {% endfor %}
    <div class='col-md-2 d-grid'><button class='btn btn-primary btn-sm mt-4'>Filtra</button></div>
  </form>
</div>

<div class='card p-3'>
  <div class='d-flex flex-wrap gap-2 mb-2 no-print'>
    <form method='get' action='{{url_for("buono_setup")}}'>
      <input type='hidden' name='ids' id='ids-buono'>
      <button class='btn btn-outline-primary btn-sm' onclick="return fillIds('ids-buono')">Crea Buono (Anteprima)</button>
    </form>
    <form method='get' action='{{url_for("ddt_setup")}}'>
      <input type='hidden' name='ids' id='ids-ddt'>
      <button class='btn btn-outline-primary btn-sm' onclick="return fillIds('ids-ddt')">Crea DDT (Anteprima)</button>
    </form>
    {% if session.get('role') == 'admin' %}
      <form method='get' action='{{url_for("bulk_edit")}}'>
        <input type='hidden' name='ids' id='ids-bulk'>
        <button class='btn btn-warning btn-sm' onclick="return fillIds('ids-bulk')">Modifica multipla</button>
      </form>
    {% endif %}
  </div>

  <div class='table-responsive' style='max-height:60vh'>
    <table class='table table-sm table-hover align-middle'>
      <thead><tr>
        <th><input type='checkbox' id='checkall'></th>
        {% for c in cols %}<th>{{c}}</th>{% endfor %}
        <th>Allegati</th><th>Azione</th>
      </tr></thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td><input type='checkbox' class='sel' value='{{r.id_articolo}}'></td>
          {% for c in cols %}<td>{{ getattr(r,c) or '' }}</td>{% endfor %}
          <td>{% for a in r.attachments %}<a class='badge text-bg-light' href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.kind}}</a> {% endfor %}</td>
          <td><a class='btn btn-sm btn-outline-primary' href='{{url_for("edit_row",id=r.id_articolo)}}'>Modifica</a></td>
        </tr>{% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script>
document.getElementById('checkall')?.addEventListener('change', e=>{
  document.querySelectorAll('.sel').forEach(cb=>cb.checked=e.target.checked);
});
function selectedIds(){return [...document.querySelectorAll('.sel:checked')].map(x=>x.value).join(',')}
function fillIds(hid){
  const v=selectedIds();
  if(!v){ alert('Seleziona almeno una riga'); return false; }
  document.getElementById(hid).value=v; return true;
}
</script>
{% endblock %}
"""

# ------------------- EDIT / ADD -------------------
EDIT = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'><h5>{{ 'Modifica' if row.id_articolo else 'Nuovo' }} Articolo {% if row.id_articolo %}#{{row.id_articolo}}{% endif %}</h5>
<form method='post' enctype='multipart/form-data'>
  <div class='row g-3'>
    {% for label,name in fields %}
      <div class='col-md-4'><label class='form-label'>{{label}}</label>
        <input name='{{name}}' value='{{getattr(row,name,"") or ""}}' class='form-control'></div>
    {% endfor %}
    {% if row.id_articolo %}
    <div class='col-12'><label class='form-label'>Allega Documenti/Foto</label>
      <div class='dropzone' id='dz'>Trascina qui (o clicca) per caricare più file (PDF, JPG, PNG)</div>
      <input type='file' id='fi' name='files' multiple class='form-control mt-2' style='display:none' accept='application/pdf,image/*'>
    </div>{% endif %}
  </div>
  <div class='mt-3 d-flex gap-2'><button class='btn btn-primary'>Salva</button>
  <a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Indietro</a></div>
</form>
{% if row.id_articolo %}
<hr><h6>Allegati</h6><ul class='list-group'>
  {% for a in row.attachments %}
  <li class='list-group-item d-flex justify-content-between'>
    <div><span class='badge text-bg-light me-2'>{{a.kind}}</span><a href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.filename}}</a></div>
    <a class='btn btn-sm btn-outline-danger' href='{{url_for("delete_attachment",att_id=a.id)}}'>Elimina</a>
  </li>
  {% else %}<li class='list-group-item'>Nessun allegato</li>{% endfor %}
</ul>{% endif %}
<script>
const dz=document.getElementById('dz'),fi=document.getElementById('fi');
dz && dz.addEventListener('click',()=>fi.click());
dz && dz.addEventListener('dragover',e=>{e.preventDefault(); dz.style.opacity=.8});
dz && dz.addEventListener('dragleave',()=>dz.style.opacity=1);
dz && dz.addEventListener('drop',e=>{e.preventDefault(); fi.files=e.dataTransfer.files; dz.style.opacity=1});
</script>
{% endblock %}
"""

# ------------------- BUONO / DDT SCHERMATE -------------------
BUONO_SETUP = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'>
  <h5>Crea Buono</h5>
  <form method='post'>
    <input type='hidden' name='ids' value='{{ids}}'>
    <div class='row g-3'>
      <div class='col-md-3'><label class='form-label'>Cliente</label><input name='cliente' class='form-control' value='{{cliente}}'></div>
      <div class='col-md-3'><label class='form-label'>Commessa</label><input name='commessa' class='form-control' value='{{commessa}}'></div>
      <div class='col-md-3'><label class='form-label'>Protocollo</label><input name='protocollo' class='form-control' value='{{protocollo}}'></div>
      <div class='col-md-3'><label class='form-label'>Numero Buono</label><input name='buono_n' class='form-control' value='{{buono_n}}'></div>
    </div>
    <div class='mt-3 d-flex gap-2'>
      <button name='action' value='preview' class='btn btn-outline-primary'>Anteprima</button>
      <button name='action' value='pdf' class='btn btn-primary'>Genera PDF</button>
      <a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Annulla</a>
    </div>
  </form>
</div>
{% endblock %}
"""

BUONO_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>@media print{.no-print{display:none}} .logo{height:42px;margin-right:10px}</style></head>
<body class='p-4'>
<div class='no-print mb-3 d-flex gap-2'><a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Indietro</a><button class='btn btn-primary' onclick='window.print()'>Stampa</button></div>
<div class='d-flex align-items-center mb-3'>{% if logo_url %}<img src='{{logo_url}}' class='logo'>{% endif %}
  <h3 class='m-0'>BUONO PRELIEVO {{buono_n}}</h3></div>
<div class='mb-2'><b>{{cliente}}</b>{% if commessa %} — Commessa {{commessa}}{% endif %}{% if protocollo %} — Protocollo {{protocollo}}{% endif %}</div>
<table class='table table-sm table-bordered'>
<thead><tr><th>Ordine</th><th>Cod.Art.</th><th>Descrizione</th><th>Quantità</th><th>N.Arrivo</th></tr></thead>
<tbody>{% for r in rows %}<tr>
<td>{{r.ordine or ''}}</td><td>{{r.codice_articolo or ''}}</td><td>{{r.descrizione or ''}}</td><td>{{r.n_colli or 1}}</td><td>{{r.n_arrivo or ''}}</td>
</tr>{% endfor %}</tbody></table>
</body></html>"""

DDT_SETUP = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'>
  <h5>Crea DDT</h5>
  <form method='post'>
    <input type='hidden' name='ids' value='{{ids}}'>
    <div class='row g-3'>
      <div class='col-md-6'><label class='form-label'>Destinatario (seleziona o nuovo)</label>
        <select name='dest' class='form-select'>
          {% for k,v in destinatari.items() %}
            <option value='{{k}}' {% if k==dest_sel %}selected{% endif %}>{{k}} — {{v.ragione_sociale}}</option>
          {% endfor %}
        </select>
      </div>
      <div class='col-md-6'><label class='form-label'>Oppure nuovo Destinatario (nome chiave)</label><input name='dest_new_key' class='form-control' placeholder='es. NUOVA SEDE'></div>
      <div class='col-md-4'><label class='form-label'>Ragione Sociale</label><input name='dest_ragione' class='form-control'></div>
      <div class='col-md-4'><label class='form-label'>Indirizzo</label><input name='dest_indirizzo' class='form-control'></div>
      <div class='col-md-4'><label class='form-label'>P.IVA</label><input name='dest_piva' class='form-control'></div>

      <div class='col-md-3'><label class='form-label'>Tipologia merce</label><input name='tipo_merce' class='form-control'></div>
      <div class='col-md-3'><label class='form-label'>Vettore</label><input name='vettore' class='form-control'></div>
      <div class='col-md-3'><label class='form-label'>Causale trasporto</label><input name='causale' class='form-control' value='TRASFERIMENTO'></div>
      <div class='col-md-3'><label class='form-label'>Aspetto esteriore</label><input name='aspetto' class='form-control' value='A VISTA'></div>
      <div class='col-md-3'><label class='form-label'>Data Uscita</label><input name='data_ddt' type='date' class='form-control' value='{{oggi}}'></div>
    </div>
    <div class='mt-3 d-flex gap-2'>
      <button name='action' value='preview' class='btn btn-outline-primary'>Anteprima</button>
      <button name='action' value='pdf' class='btn btn-primary'>Genera PDF</button>
      <a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Annulla</a>
    </div>
  </form>
</div>
{% endblock %}
"""

DDT_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>@media print{.no-print{display:none}} .logo{height:44px;margin-right:10px}
.head{background:#1f5d95;color:#fff;padding:.6rem 1rem;border-radius:.5rem;margin:10px 0}
.small{font-size:.95rem}
td,th{vertical-align:middle}
</style></head><body class='p-4'>
<div class='no-print mb-3 d-flex gap-2'><a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Indietro</a><button class='btn btn-primary' onclick='window.print()'>Stampa</button></div>
<div class='d-flex align-items-center mb-2'>{% if logo_url %}<img src='{{logo_url}}' class='logo'>{% endif %}
  <h3 class='m-0'>DOCUMENTO DI TRASPORTO (DDT)</h3></div>

<div class='row g-3 mb-2'>
  <div class='col-md-6'>
    <div class='head'>Mittente</div>
    <div class='small'>Camar srl<br>Via Luigi Canepa 2<br>16165 Genova Struppa (GE)</div>
  </div>
  <div class='col-md-6'>
    <div class='head'>Destinatario</div>
    <div class='small'><b>{{dest.ragione_sociale}}</b><br>{{dest.indirizzo}}<br>{{dest.piva}}</div>
  </div>
</div>

<div class='row g-3 mb-3'>
  <div class='col-md-6'>
    <table class='table table-sm table-bordered'>
      <tr><th class='w-25'>Commessa</th><td>{{commessa}}</td></tr>
      <tr><th>Ordine</th><td>{{ordine}}</td></tr>
      <tr><th>Buono</th><td>{{buono_n}}</td></tr>
      <tr><th>Protocollo</th><td>{{protocollo}}</td></tr>
    </table>
  </div>
  <div class='col-md-6'>
    <table class='table table-sm table-bordered'>
      <tr><th class='w-25'>N. DDT</th><td>{{n_ddt}}</td></tr>
      <tr><th>Data Uscita</th><td>{{data_uscita}}</td></tr>
      <tr><th>Targa</th><td>{{targa or ''}}</td></tr>
    </table>
  </div>
</div>

<table class='table table-sm table-bordered'>
  <thead><tr><th>ID</th><th>Cod.Art.</th><th>Descrizione</th><th>Pezzi</th><th>Colli</th><th>Peso</th><th>N.Arrivo</th></tr></thead>
  <tbody>{% for r in rows %}<tr>
    <td>{{r.id_articolo}}</td><td>{{r.codice_articolo or ''}}</td><td>{{r.descrizione or ''}}</td>
    <td>{{r.pezzo or ''}}</td><td>{{r.n_colli or 1}}</td><td>{{r.peso or ''}}</td><td>{{r.n_arrivo or ''}}</td>
  </tr>{% endfor %}</tbody>
</table>

<div class='row g-3 mt-2'>
  <div class='col-md-6'>
    <table class='table table-sm table-bordered'>
      <tr><th class='w-25'>Causale</th><td>{{causale}}</td></tr>
      <tr><th>Porto</th><td>FRANCO</td></tr>
      <tr><th>Aspetto</th><td>{{aspetto}}</td></tr>
    </table>
  </div>
</div>

<div class='d-flex justify-content-between mt-3'>
  <div><b>Totale Colli:</b> {{tot_colli}}</div>
  <div><b>Totale Peso:</b> {{tot_peso}}</div>
  <div><b>Firma Vettore:</b> ________________________________</div>
</div>
</body></html>"""

# ------------------- LABELS -------------------
LABELS_FORM = """{% extends 'base.html' %}{% block content %}
<h5>Nuova Etichetta 99,82×61,98 mm</h5>
<form class="card p-3" method="post" action="{{url_for('labels_preview')}}">
  <div class="row g-3">
    <div class="col-md-4"><label class="form-label">Cliente</label><input name="cliente" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Ordine</label><input name="ordine" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Commessa</label><input name="commessa" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">DDT Ingresso</label><input name="ddt_ingresso" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Data Ingresso (GG/MM/AAAA)</label><input name="data_ingresso" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Arrivo (es. 01/24)</label><input name="arrivo" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">N. Colli</label><input name="n_colli" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Posizione</label><input name="posizione" class="form-control"></div>
    <div class="col-md-4"><label class="form-label">Protocollo</label><input name="protocollo" class="form-control"></div>
  </div>
  <div class="mt-3 d-flex gap-2">
    <button class="btn btn-outline-primary">Anteprima</button>
    <button type="submit" formaction="{{url_for('labels_pdf')}}" class="btn btn-primary">Genera PDF</button>
  </div>
</form>
{% endblock %}"""

LABELS_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>@media print{.no-print{display:none}} .logo{height:30px;margin-bottom:6px}
.rowline{font-size:18px;line-height:1.15;margin:4px 0}
.key{font-weight:800}
.box{width:100%;max-width:560px;border:1px solid #aaa;padding:10px}
</style></head><body class='p-3'>
<div class='no-print mb-2 d-flex gap-2'><a class='btn btn-secondary' href='{{url_for("labels_form")}}'>Indietro</a><button class='btn btn-primary' onclick='window.print()'>Stampa</button></div>
<div class='box'>
  {% if logo_url %}<div><img src='{{logo_url}}' class='logo'></div>{% endif %}
  {% for k,v in seq %}
    <div class='rowline'><span class='key'>{{k}}</span> {{v}}</div>
  {% endfor %}
</div>
</body></html>"""

# ------------------- REGISTER TEMPLATES -------------------
bp = Blueprint('bp', __name__)
app.register_blueprint(bp)
dict_loader = DictLoader({
    'base.html': BASE, 'login.html': LOGIN, 'home.html': HOME,
    'giacenze.html': GIACENZE, 'edit.html': EDIT,
    'buono_setup.html': BUONO_SETUP, 'buono_html.html': BUONO_HTML,
    'ddt_setup.html': DDT_SETUP, 'ddt_html.html': DDT_HTML,
    'labels_form.html': LABELS_FORM, 'labels_html.html': LABELS_HTML
})
app.jinja_loader = ChoiceLoader([FileSystemLoader('templates'), dict_loader])

def logo_url():
    file = Path(LOGO_PATH)
    if not file.exists():
        alt = STATIC_DIR / "logo.png"
        if alt.exists(): file = alt
    return url_for('static', filename='logo.png') if file.exists() else None

# ------------------- AUTH -------------------
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def w(*a, **k):
        if not session.get('user'):
            return redirect(url_for('login'))
        return fn(*a, **k)
    return w

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u_raw = request.form.get('user', '')
        p_raw = request.form.get('pwd', '')
        u = (u_raw or '').strip().upper()
        p = (p_raw or '').strip()
        users_src = get_users() or {}
        users = {str(k).upper(): str(v) for k,v in users_src.items()}
        if u in users and p == users[u]:
            session['user'] = u
            session['role'] = 'admin' if u in ADMIN_USERS else 'client'
            return redirect(url_for('home'))
        flash('Credenziali non valide','danger')
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'login.html')[0], logo_url=logo_url())

@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ------------------- HOME -------------------
@app.get('/')
@login_required
def home():
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'home.html')[0], logo_url=logo_url())

# ------------------- LISTA / FILTRI -------------------
def filter_query(qs, args):
    if args.get('id'):
        qs = qs.filter(Articolo.id_articolo == args.get('id'))
    def like(col):
        nonlocal qs
        v = args.get(col)
        if v:
            qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))
    for col in ['codice_articolo','descrizione','cliente','commessa','ordine','n_arrivo','stato','posizione','buono_n']:
        like(col)
    if args.get('data_da'):
        qs = qs.filter(Articolo.data_ingresso >= parse_date_ui(args.get('data_da')))
    if args.get('data_a'):
        qs = qs.filter(Articolo.data_ingresso <= parse_date_ui(args.get('data_a')))
    return qs

def model_columns():
    # tutte le colonne (in ordine leggibile)
    cols = [c.name for c in Articolo.__table__.columns if c.name != 'id']
    # preferiamo un ordine fisso e leggibile
    order = ["id_articolo","cliente","codice_articolo","descrizione","pezzo","larghezza","lunghezza","altezza","m2","m3",
             "protocollo","ordine","commessa","magazzino","fornitore","data_ingresso","n_ddt_ingresso","n_arrivo",
             "n_colli","peso","posizione","buono_n","serial_number","ns_rif","stato","mezzi_in_uscita",
             "data_uscita","n_ddt_uscita","note"]
    return [c for c in order if c in cols]

@app.get('/giacenze')
@login_required
def giacenze():
    db = SessionLocal()
    qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())
    if session.get('role') == 'client':
        qs = qs.filter(Articolo.cliente == session['user'])
    rows = filter_query(qs, request.args).all()
    cols = model_columns()
    filters = [('ID(=)','id'),('Cod.Art.(~=)','codice_articolo'),('Descr.(~=)','descrizione'),('Cliente(~=)','cliente'),
               ('Commessa(~=)','commessa'),('Ordine(~=)','ordine'),('N.Arrivo(~=)','n_arrivo'),('Stato(~=)','stato'),
               ('Posizione(~=)','posizione'),('Data Ingr. Da','data_da'),('Data Ingr. A','data_a'),('Buono N(~=)','buono_n')]
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'giacenze.html')[0],
                                  rows=rows, cols=cols, filters=filters, logo_url=logo_url())

# ------------------- NUOVO / EDIT -------------------
@app.get('/add')
@login_required
def add_row():
    # form "nuovo articolo"
    a = Articolo()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'edit.html')[0],
                                  row=a, fields=edit_fields(), logo_url=logo_url())

@app.post('/add')
@login_required
def add_row_post():
    db = SessionLocal()
    a = Articolo()
    apply_fields_from_form(a, request.form)
    a.m2, a.m3 = calc_m2_m3(a.lunghezza, a.larghezza, a.altezza, a.n_colli)
    db.add(a); db.commit()
    flash('Articolo creato','success')
    return redirect(url_for('giacenze'))

# Back compat (vecchio /new -> mostra form add)
@app.get('/new')
@login_required
def new_row():
    return redirect(url_for('add_row'))

def edit_fields():
    return [('Codice Articolo','codice_articolo'),('Descrizione','descrizione'),('Cliente','cliente'),
            ('Protocollo','protocollo'),('Ordine','ordine'),('Commessa','commessa'),
            ('Peso','peso'),('N Colli','n_colli'),('Posizione','posizione'),
            ('Stato','stato'),('N.Arrivo','n_arrivo'),('Buono N','buono_n'),
            ('Fornitore','fornitore'),('Magazzino','magazzino'),
            ('Data Ingresso (GG/MM/AAAA)','data_ingresso'),('Data Uscita (GG/MM/AAAA)','data_uscita'),
            ('N DDT Ingresso','n_ddt_ingresso'),('N DDT Uscita','n_ddt_uscita'),
            ('Larghezza (m)','larghezza'),('Lunghezza (m)','lunghezza'),('Altezza (m)','altezza'),
            ('Serial Number','serial_number'),('NS Rif','ns_rif'),('Mezzi in Uscita','mezzi_in_uscita'),('Note','note')]

def apply_fields_from_form(row, form):
    fields=['codice_articolo','pezzo','larghezza','lunghezza','altezza','protocollo','ordine','commessa','magazzino','fornitore',
            'data_ingresso','n_ddt_ingresso','cliente','descrizione','peso','n_colli','posizione','n_arrivo','buono_n','note',
            'serial_number','data_uscita','n_ddt_uscita','ns_rif','stato','mezzi_in_uscita']
    numeric_float={'larghezza','lunghezza','altezza','peso','m2','m3'}
    numeric_int={'n_colli'}
    for f in fields:
        v = form.get(f) or None
        if f in ('data_ingresso','data_uscita'):
            v = parse_date_ui(v) if v else None
        elif f in numeric_float:
            v = to_float_eu(v)
        elif f in numeric_int:
            v = to_int_eu(v)
        setattr(row, f, v)

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db = SessionLocal(); row = db.get(Articolo, id)
    if not row: abort(404)
    if request.method == 'POST':
        apply_fields_from_form(row, request.form)
        row.m2, row.m3 = calc_m2_m3(row.lunghezza, row.larghezza, row.altezza, row.n_colli)
        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if not f or not f.filename: 
                    continue
                name=f"{id}_{uuid.uuid4().hex}_{f.filename.replace(' ','_')}"
                ext=os.path.splitext(name)[1].lower()
                kind='doc' if ext=='.pdf' else 'foto'
                folder = DOCS_DIR if kind=='doc' else PHOTOS_DIR
                f.save(str(folder / name))
                db.add(Attachment(articolo_id=id,kind=kind,filename=name))
        db.commit(); flash('Riga salvata','success')
        return redirect(url_for('giacenze'))
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'edit.html')[0],
                                  row=row, fields=edit_fields(), logo_url=logo_url())

# ------------------- ALLEGATI -------------------
@app.get('/attachment/<int:att_id>/delete')
@login_required
def delete_attachment(att_id):
    db=SessionLocal(); att=db.get(Attachment,att_id)
    if att:
        path=(DOCS_DIR if att.kind=='doc' else PHOTOS_DIR)/att.filename
        try:
            if path.exists(): path.unlink()
        except Exception: 
            pass
        db.delete(att); db.commit(); flash('Allegato eliminato','success')
    return redirect(url_for('giacenze'))

@app.get('/media/<int:att_id>')
@login_required
def media(att_id):
    db=SessionLocal(); att=db.get(Attachment,att_id)
    if not att: abort(404)
    path=(DOCS_DIR if att.kind=='doc' else PHOTOS_DIR)/att.filename
    if not path.exists(): abort(404)
    return send_file(path, as_attachment=False)

# ------------------- IMPORT / EXPORT -------------------
PROFILES_PATH = APP_DIR / "mappe_excel.json"

DEFAULT_PROFILE = {
    "header_row": 0,
    "column_map": {
        "Codice Articolo": "codice_articolo",
        "Cod.Art": "codice_articolo",
        "Descrizione": "descrizione",
        "Cliente": "cliente",
        "Protocollo": "protocollo",
        "Ordine": "ordine",
        "Peso": "peso",
        "N Colli": "n_colli",
        "Colli": "n_colli",
        "Posizione": "posizione",
        "N Arrivo": "n_arrivo",
        "Buono N": "buono_n",
        "Fornitore": "fornitore",
        "Data Ingresso": "data_ingresso",
        "Data Ingr.": "data_ingresso",
    }
}

def load_profile():
    if PROFILES_PATH.exists():
        try:
            return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"Generico": DEFAULT_PROFILE}

@app.route('/import', methods=['GET','POST'])
@login_required
def import_excel():
    profiles = load_profile()
    selected = request.args.get('profile') or next(iter(profiles.keys()))
    def norm_target(t: str) -> str | None:
        if not t: return None
        t0 = t.strip()
        aliases = {
            "ID":"id_articolo","M2":"m2","M3":"m3","Notes":"note",
            "NS RIF":"ns_rif","NS.RIF":"ns_rif",
            "MEZZO IN USCITA":"mezzi_in_uscita","Mezzo_in _uscita":"mezzi_in_uscita",
            "TRUCKER":None,"DESTINATARI":None,"TIPO DI IMBALLO":None,
        }
        return aliases.get(t0, t0.lower())
    if request.method=='POST':
        selected = request.form.get('profile') or selected
        prof = profiles.get(selected)
        if not prof:
            flash("Profilo non trovato","danger")
            return redirect(request.url)
        header_row = int(prof.get("header_row", 0))
        column_map: dict[str,str] = prof.get("column_map", {})
        if not column_map:
            tmp={}
            for target,aliases in prof.items():
                if target in ("header_row","column_map"): continue
                if isinstance(aliases,list):
                    for alias in aliases:
                        if isinstance(alias,str): tmp[alias]=target
            if tmp: column_map=tmp
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Seleziona un file .xlsx','warning'); return redirect(request.url)
        try:
            df = pd.read_excel(f, header=header_row, keep_default_na=True)
        except Exception as e:
            flash(f"Errore lettura Excel: {e}","danger"); return redirect(request.url)
        excel_cols = {c.strip().upper(): c for c in df.columns if isinstance(c,str)}
        db = SessionLocal(); added=0
        numeric_float={'larghezza','lunghezza','altezza','peso','m2','m3'}
        numeric_int={'n_colli'}
        for _,r in df.iterrows():
            a=Articolo(); any_value=False
            for excel_name, target in column_map.items():
                if not isinstance(excel_name,str) or not isinstance(target,str): continue
                key = excel_cols.get(excel_name.strip().upper())
                if not key: continue
                value = r.get(key,None)
                if is_blank(value): value=None
                field = norm_target(target)
                if not field or not hasattr(Articolo,field): continue
                if field in ("data_ingresso","data_uscita"):
                    if is_blank(value):
                        value=None
                    elif isinstance(value,(pd.Timestamp,datetime,date)):
                        value=value.strftime("%Y-%m-%d")
                    elif isinstance(value,str):
                        value=parse_date_ui(value)
                    else:
                        try: value=pd.to_datetime(value).strftime("%Y-%m-%d")
                        except Exception: value=parse_date_ui(str(value))
                elif field in numeric_float:
                    value=None if is_blank(value) else to_float_eu(value)
                elif field in numeric_int:
                    value=None if is_blank(value) else to_int_eu(value)
                if value not in (None,""): any_value=True
                setattr(a,field,value)
            if not any_value: continue
            a.m2,a.m3=calc_m2_m3(a.lunghezza,a.larghezza,a.altezza,a.n_colli)
            db.add(a); added+=1
        db.commit(); flash(f"Import completato ({added} righe)","success")
        return redirect(url_for('giacenze'))
    html = """
    {% extends 'base.html' %}{% block content %}
    <div class='card p-4'><h5>Importa da Excel</h5>
    <form method='post' enctype='multipart/form-data'>
      <div class='row g-3'>
        <div class='col-md-6'><label class='form-label'>File Excel (.xlsx)</label>
          <input type='file' name='file' accept='.xlsx,.xlsm' class='form-control' required></div>
        <div class='col-md-6'><label class='form-label'>Profilo</label>
          <select class='form-select' name='profile'>
            {% for k in profiles.keys() %}
              <option value='{{k}}' {% if k==selected %}selected{% endif %}>{{k}}</option>
            {% endfor %}
          </select></div>
      </div><button class='btn btn-primary mt-3'>Importa</button></form></div>{% endblock %}
    """
    return render_template_string(html, profiles=profiles, selected=selected, logo_url=logo_url())

@app.get('/export')
@login_required
def export_excel():
    db=SessionLocal(); rows=db.query(Articolo).all()
    df=pd.DataFrame([{k:v for k,v in r.__dict__.items() if not k.startswith('_') and k!='attachments'} for r in rows])
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w: 
        df.to_excel(w, index=False, sheet_name='Giacenze')
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name='giacenze_export.xlsx')

@app.get('/export_by_client')
@login_required
def export_excel_by_client():
    db=SessionLocal(); client=request.args.get('cliente')
    if not client:
        clients=[c[0] or "Senza Cliente" for c in db.query(Articolo.cliente).distinct().all()]
        return "<h5>Seleziona Cliente</h5><ul>"+"".join([f"<li><a href='{url_for('export_excel_by_client')}?cliente={c}'>{c}</a></li>" for c in clients])+"</ul>"
    rows = db.query(Articolo).filter((Articolo.cliente==client) if client!="Senza Cliente" else ((Articolo.cliente==None)|(Articolo.cliente==""))).all()
    df=pd.DataFrame([{k:v for k,v in r.__dict__.items() if not k.startswith('_') and k!='attachments'} for r in rows])
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w: 
        df.to_excel(w, index=False, sheet_name=(client[:31] or 'Export'))
    bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=f'export_{client}.xlsx')

# ------------------- HELPERS PDF -------------------
_styles = getSampleStyleSheet()

def _pdf_table(data, col_widths=None, header=True, hAlign='LEFT'):
    t=Table(data, colWidths=col_widths, hAlign=hAlign)
    style=[('FONT',(0,0),(-1,-1),'Helvetica',9),('GRID',(0,0),(-1,-1),0.25,colors.grey),('VALIGN',(0,0),(-1,-1),'MIDDLE')]
    if header and data: style += [('BACKGROUND',(0,0),(-1,0),colors.whitesmoke),('FONT',(0,0),(-1,0),'Helvetica-Bold',9)]
    t.setStyle(TableStyle(style)); return t

def _doc_with_header(title, pagesize=A4):
    bio=io.BytesIO()
    doc=SimpleDocTemplate(bio, pagesize=pagesize, leftMargin=15*mm, rightMargin=15*mm, topMargin=12*mm, bottomMargin=12*mm)
    story=[]
    logo_file = Path(LOGO_PATH)
    if not logo_file.exists():
        alt = STATIC_DIR / "logo.png"
        if alt.exists(): logo_file = alt
    if logo_file.exists():
        story.append(Image(str(logo_file), width=40*mm, height=15*mm))
    story.append(Paragraph(title, _styles['Heading2'])); story.append(Spacer(1,6))
    return doc, story, bio

def _get(ids_csv):
    ids=[int(x) for x in ids_csv.split(',') if x.strip().isdigit()]
    if not ids: return []
    db=SessionLocal(); return db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

# ------------------- BUONO -------------------
@app.get('/buono_setup')
@login_required
def buono_setup():
    ids = request.args.get('ids','')
    rows = _get(ids)
    if not rows:
        flash('Seleziona almeno una riga','warning'); return redirect(url_for('giacenze'))
    cliente = rows[0].cliente or ''
    commessa = rows[0].commessa or ''
    protocollo = rows[0].protocollo or ''
    buono_n = rows[0].buono_n or ''
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'buono_setup.html')[0],
                                  ids=ids, cliente=cliente, commessa=commessa, protocollo=protocollo, buono_n=buono_n,
                                  logo_url=logo_url())

@app.post('/buono_setup')
@login_required
def buono_setup_post():
    ids = request.form.get('ids',''); rows = _get(ids)
    if not rows: flash('Nessuna riga','warning'); return redirect(url_for('giacenze'))
    cliente = request.form.get('cliente',''); commessa=request.form.get('commessa','')
    protocollo=request.form.get('protocollo',''); buono_n=request.form.get('buono_n','')
    action = request.form.get('action')
    if action=='preview':
        return render_template_string(app.jinja_loader.get_source(app.jinja_env,'buono_html.html')[0],
                                      rows=rows, cliente=cliente, commessa=commessa, protocollo=protocollo,
                                      buono_n=buono_n, logo_url=logo_url())
    # PDF
    doc, story, bio = _doc_with_header(f"Buono Prelievo {buono_n}")
    story.append(Paragraph(f"<b>{cliente}</b> — Commessa {commessa} — Protocollo {protocollo}", _styles['Normal']))
    story.append(Spacer(1,6))
    data=[['Ordine','Cod.Art.','Descrizione','Quantità','N.Arrivo']]
    for r in rows:
        data.append([r.ordine or '', r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.n_arrivo or ''])
    story.append(_pdf_table(data, col_widths=[25*mm, 35*mm, 80*mm, 20*mm, 25*mm])); doc.build(story)
    bio.seek(0); return send_file(bio, as_attachment=False, download_name='buono.pdf', mimetype='application/pdf')

# ------------------- DDT -------------------
@app.get('/ddt_setup')
@login_required
def ddt_setup():
    ids = request.args.get('ids','')
    rows = _get(ids)
    if not rows:
        flash('Seleziona almeno una riga','warning'); return redirect(url_for('giacenze'))
    destinatari = load_destinatari()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'ddt_setup.html')[0],
                                  ids=ids, destinatari=destinatari, dest_sel=next(iter(destinatari.keys()), ''),
                                  oggi=date.today().isoformat(), logo_url=logo_url())

@app.post('/ddt_setup')
@login_required
def ddt_setup_post():
    ids = request.form.get('ids',''); rows = _get(ids)
    if not rows: flash('Nessuna riga selezionata','warning'); return redirect(url_for('giacenze'))
    dest_key = request.form.get('dest')
    # opzionale: nuovo destinatario
    if (nk := (request.form.get('dest_new_key') or '').strip()):
        save_destinatario(nk, {
            "ragione_sociale": request.form.get('dest_ragione',''),
            "indirizzo": request.form.get('dest_indirizzo',''),
            "piva": request.form.get('dest_piva',''),
        })
        dest_key = nk
    dest = load_destinatari().get(dest_key, {"ragione_sociale": dest_key, "indirizzo":"", "piva":""})
    tipo_merce = request.form.get('tipo_merce',''); vettore = request.form.get('vettore','')
    causale = request.form.get('causale',''); aspetto = request.form.get('aspetto','


