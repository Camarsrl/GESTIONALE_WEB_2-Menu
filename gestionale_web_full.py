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

# Jinja loader
from jinja2 import ChoiceLoader, FileSystemLoader, DictLoader


# ------------------- AUTH -------------------
from functools import wraps
from flask import session, redirect, url_for, flash

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            flash("Effettua il login per accedere", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


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

def _discover_logo_path():
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo camar.jpg", "logo_camar.png"):
        p = STATIC_DIR / name
        if p.exists():
            return str(p)
    p = os.environ.get("LOGO_PATH")
    return p if p and Path(p).exists() else None

LOGO_PATH = _discover_logo_path()

# ------------------- DATABASE -------------------
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

# ------------------- APP FLASK -------------------
app = Flask(__name__)
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
        target = STATIC_DIR / "logo.png"
        if not target.exists():
            target.write_bytes(p.read_bytes())
        return url_for('static', filename="logo.png")
    except Exception:
        return None


# ------------------- ROUTE HOME -------------------
@app.route('/')
def index():
    if not session.get('user'):
        return redirect(url_for('login'))
    return redirect(url_for('home'))

# ------------------- TEMPLATE BASE -------------------
BASE = """
<!doctype html><html lang='it'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{{ title or "Camar • Gestionale Web" }}</title>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>
body{background:#f7f9fc}
.card{border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.06)}
.table thead th{position:sticky;top:0;background:#fff;z-index:2}
.dropzone{border:2px dashed #7aa2ff;background:#eef4ff;padding:16px;border-radius:12px;text-align:center;color:#2c4a9a}
@media print{.no-print{display:none!important}}
.logo{height:40px}
</style></head><body>
<nav class='navbar bg-white shadow-sm'>
  <div class='container-fluid'>
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
  </div>
</nav>
<div class='container-fluid my-4'>
  {% with m=get_flashed_messages(with_categories=true) %}
    {% for c,t in m %}
      <div class='alert alert-{{c}} alert-dismissible fade show'>
        {{t}}<button class='btn-close' data-bs-dismiss='alert'></button>
      </div>
    {% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'></script>
</body></html>
"""

# ------------------- LOGIN -------------------
LOGIN = """{% extends 'base.html' %}{% block content %}
<div class='row justify-content-center'>
  <div class='col-md-5'>
    <div class='card p-4 text-center'>
      {% if logo_url %}<img src='{{logo_url}}' class='mb-3' style='height:56px'>{% endif %}
      <h4 class='mb-3'>Login al gestionale</h4>
      <form method='post' class='text-start'>
        <div class='mb-3'><label class='form-label'>Utente</label><input name='user' class='form-control' required></div>
        <div class='mb-3'><label class='form-label'>Password</label><input type='password' name='pwd' class='form-control' required></div>
        <button class='btn btn-primary w-100'>Accedi</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}"""

# ------------------- HOME -------------------
HOME = """{% extends 'base.html' %}{% block content %}
<div class='row g-3'>
  <div class='col-lg-3'>
    <div class='card p-3'>
      <h6>Azioni</h6>
      <div class='d-grid gap-2'>
        <a class='btn btn-outline-primary' href='{{url_for("labels_form")}}'>Etichette</a>
        <a class='btn btn-outline-primary' href='{{url_for("giacenze")}}'>Visualizza Giacenze</a>
        <a class='btn btn-outline-primary' href='{{url_for("import_excel")}}'>Import Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel")}}'>Export Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel_by_client")}}'>Export per Cliente</a>
        <a class='btn btn-outline-success' href='{{url_for("new_row")}}'>Nuovo Articolo</a>
      </div>
    </div>
  </div>
  <div class='col-lg-9'>
    <div class='card p-4 d-flex align-items-center gap-3'>
      {% if logo_url %}<img src='{{logo_url}}' style='height:48px'>{% endif %}
      <div>
        <h4 class='m-0'>Benvenuto</h4>
        <p class='text-muted m-0'>Gestione completa giacenze, DDT, buoni e stampa PDF.</p>
      </div>
    </div>
  </div>
</div>
{% endblock %}"""
# ------------------- VISUALIZZA GIACENZE -------------------
GIACENZE = """{% extends 'base.html' %}{% block content %}
<div class='card p-3 mb-3'>
  <form class='row g-2' method='get'>
    {% for label,name in [
      ('ID(=)','id'),
      ('Cod.Art.(~=)','codice_articolo'),
      ('Cliente(~=)','cliente'),
      ('Fornitore(~=)','fornitore'),
      ('Magazzino(~=)','magazzino'),
      ('Commessa(~=)','commessa'),
      ('Ordine(~=)','ordine'),
      ('Descrizione(~=)','descrizione'),
      ('Posizione(~=)','posizione'),
      ('N. Arrivo(~=)','n_arrivo'),
      ('Buono N.(~=)','buono_n'),
      ('N. DDT Ingr.(~=)','n_ddt_ingresso'),
      ('N. DDT Uscita(~=)','n_ddt_uscita'),
      ('Protocollo(~=)','protocollo'),
      ('NS Rif(~=)','ns_rif'),
      ('Serial Number(~=)','serial_number'),
      ('Stato(~=)','stato'),
      ('Mezzo Uscito(~=)','mezzi_in_uscita'),
      ('Data Ingr. Da','data_da'),
      ('Data Ingr. A','data_a'),
      ('Data Uscita Da','data_usc_da'),
      ('Data Uscita A','data_usc_a')
    ] %}
      <div class='col-md-2'>
        <label class='form-label small'>{{label}}</label>
        <input name='{{name}}' value='{{request.args.get(name,"")}}' class='form-control form-control-sm'>
      </div>
    {% endfor %}
    <div class='col-md-2 d-grid'><button class='btn btn-primary btn-sm mt-4'>Filtra</button></div>
  </form>
</div>

<div class='card p-3'>
  <div class='d-flex flex-wrap gap-2 mb-3 no-print'>
    <form method='post' action='{{url_for("buono_preview")}}'>
      <input type='hidden' name='ids' id='ids-bpr'>
      <button class='btn btn-outline-secondary btn-sm' onclick="return setIds('ids-bpr')">
        <i class='bi bi-receipt'></i> Crea Buono (Anteprima)
      </button>
    </form>

    <form method='post' action='{{url_for("ddt_preview")}}'>
      <input type='hidden' name='ids' id='ids-dpr'>
      <button class='btn btn-outline-secondary btn-sm' onclick="return setIds('ids-dpr')">
        <i class='bi bi-truck'></i> Crea DDT (Anteprima)
      </button>
    </form>

    <form method='post' action='{{url_for("pdf_buono")}}' target='_blank'>
      <input type='hidden' name='ids' id='ids-bp'>
      <button class='btn btn-outline-primary btn-sm' onclick="return setIds('ids-bp')">Buono (PDF)</button>
    </form>

    <form method='post' action='{{url_for("pdf_ddt")}}' target='_blank'>
      <input type='hidden' name='ids' id='ids-dp'>
      <button class='btn btn-outline-primary btn-sm' onclick="return setIds('ids-dp')">DDT (PDF)</button>
    </form>

    {% if session.get('role') == 'admin' %}
      <a class='btn btn-success btn-sm' href='{{url_for("ddt_setup")}}?ids=' id='btn-scarico'>Scarico + DDT</a>
    {% endif %}

    <form method='get' action='{{url_for("bulk_edit")}}'>
      <input type='hidden' name='ids' id='ids-bulk'>
      <button class='btn btn-warning btn-sm' onclick="return setIds('ids-bulk')">Modifica multipla</button>
    </form>
  </div>

  <div class='table-responsive' style='max-height:70vh'>
    <table class='table table-sm table-hover align-middle'>
      <thead class='table-light'>
        <tr>
          <th style='width:28px'><input type='checkbox' id='checkall'></th>
          {% for c in cols %}<th>{{c}}</th>{% endfor %}
          <th>Allegati</th><th>Azione</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
          <tr>
            <td><input type='checkbox' class='sel' value='{{r.id_articolo}}'></td>
            {% for c in cols %}
              {% set v = getattr(r,c) %}
              <td>{% if c in ['data_ingresso','data_uscita'] %}{{ v|fmt_date }}{% else %}{{ v or '' }}{% endif %}</td>
            {% endfor %}
            <td>{% for a in r.attachments %}
              <a class='badge text-bg-light' href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.kind}}</a>
            {% endfor %}</td>
            <td><a class='btn btn-sm btn-outline-primary' href='{{url_for("edit_row",id=r.id_articolo)}}'>Modifica</a></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script>
const all=document.getElementById('checkall');
if(all){
  all.addEventListener('change', e=>{
    document.querySelectorAll('.sel').forEach(cb=>cb.checked=all.checked);
  });
}
function collectIds(){ return [...document.querySelectorAll('.sel:checked')].map(x=>x.value).join(','); }
function setIds(hiddenId){
  const v = collectIds();
  if(!v){ alert('Seleziona almeno una riga'); return false; }
  const el = document.getElementById(hiddenId); if (el) el.value = v;
  const l = document.getElementById('btn-scarico'); if (l) l.href = '{{url_for("ddt_setup")}}?ids=' + encodeURIComponent(v);
  return true;
}
</script>
{% endblock %}
"""
# ------------------- EDIT SINGOLA RIGA + ALLEGATI -------------------
EDIT = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'>
  <h5>{{ 'Modifica' if row.id_articolo else 'Nuovo' }} Articolo {% if row.id_articolo %}#{{row.id_articolo}}{% endif %}</h5>
  <form method='post' enctype='multipart/form-data'>
    <div class='row g-3'>
      {% for label,name in fields %}
        <div class='col-md-4'>
          <label class='form-label'>{{label}}</label>
          <input name='{{name}}' value='{{getattr(row,name,"") or ""}}' class='form-control'>
        </div>
      {% endfor %}
      {% if row.id_articolo %}
      <div class='col-12'>
        <label class='form-label'>Allega Documenti/Foto</label>
        <div class='dropzone' id='dz'>Trascina qui (o clicca) per caricare file (PDF/immagini)</div>
        <input type='file' id='fi' name='files' multiple class='form-control mt-2' style='display:none' accept='application/pdf,image/*'>
      </div>
      {% endif %}
    </div>
    <div class='mt-3 d-flex gap-2'>
      <button class='btn btn-primary'>Salva</button>
      <a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Indietro</a>
    </div>
  </form>

  {% if row.id_articolo %}
  <hr>
  <h6>Allegati</h6>
  <ul class='list-group'>
    {% for a in row.attachments %}
      <li class='list-group-item d-flex justify-content-between align-items-center'>
        <div>
          <span class='badge text-bg-light me-2'>{{a.kind}}</span>
          <a href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.filename}}</a>
        </div>
        <a class='btn btn-sm btn-outline-danger' href='{{url_for("delete_attachment",att_id=a.id)}}'>Elimina</a>
      </li>
    {% else %}
      <li class='list-group-item'>Nessun allegato</li>
    {% endfor %}
  </ul>
  {% endif %}
</div>

<script>
const dz=document.getElementById('dz'), fi=document.getElementById('fi');
if(dz && fi){
  dz.addEventListener('click',()=>fi.click());
  dz.addEventListener('dragover',e=>{e.preventDefault(); dz.style.opacity=.85});
  dz.addEventListener('dragleave',()=>dz.style.opacity=1);
  dz.addEventListener('drop',e=>{e.preventDefault(); fi.files=e.dataTransfer.files; dz.style.opacity=1});
}
</script>
{% endblock %}
"""

@app.get('/new')
@login_required
def new_row():
    db = SessionLocal()
    a = Articolo(data_ingresso=datetime.today().strftime("%Y-%m-%d"))
    db.add(a); db.commit()
    return redirect(url_for('edit_row', id=a.id_articolo))

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db = SessionLocal(); row = db.get(Articolo, id)
    if not row: abort(404)

    if request.method == 'POST':
        # Campi modificabili (singola riga)
        fields = [
            'codice_articolo','pezzo','larghezza','lunghezza','altezza','protocollo','ordine','commessa',
            'magazzino','fornitore','data_ingresso','n_ddt_ingresso','cliente','descrizione','peso','n_colli',
            'posizione','n_arrivo','buono_n','note','serial_number','data_uscita','n_ddt_uscita','ns_rif',
            'stato','mezzi_in_uscita'
        ]
        numeric_float = {'larghezza','lunghezza','altezza','peso','m2','m3'}
        numeric_int   = {'n_colli'}

        for f in fields:
            v = request.form.get(f) or None
            if f in ('data_ingresso','data_uscita'):
                v = parse_date_ui(v) if v else None
            elif f in numeric_float:
                v = to_float_eu(v)
            elif f in numeric_int:
                v = to_int_eu(v)
            setattr(row, f, v)

        # Ricalcolo m2/m3
        row.m2, row.m3 = calc_m2_m3(row.lunghezza, row.larghezza, row.altezza, row.n_colli)

        # Upload allegati
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

    # Campi e label mostrati in edit
    fields = [
        ('Codice Articolo','codice_articolo'),('Descrizione','descrizione'),('Cliente','cliente'),
        ('Protocollo','protocollo'),('Ordine','ordine'),('Peso','peso'),('N Colli','n_colli'),
        ('Posizione','posizione'),('Stato','stato'),('N.Arrivo','n_arrivo'),('Buono N','buono_n'),
        ('Fornitore','fornitore'),('Magazzino','magazzino'),
        ('Data Ingresso (GG/MM/AAAA)','data_ingresso'),('Data Uscita (GG/MM/AAAA)','data_uscita'),
        ('N DDT Ingresso','n_ddt_ingresso'),('N DDT Uscita','n_ddt_uscita'),
        ('Larghezza (m)','larghezza'),('Lunghezza (m)','lunghezza'),('Altezza (m)','altezza'),
        ('Serial Number','serial_number'),('NS Rif','ns_rif'),('Mezzi in Uscita','mezzi_in_uscita'),('Note','note')
    ]
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env,'edit.html')[0] if False else EDIT,
        row=row, fields=fields, logo_url=logo_url()
    )

# ------------------- MEDIA & ALLEGATI -------------------
@app.get('/attachment/<int:att_id>/delete')
@login_required
def delete_attachment(att_id):
    db = SessionLocal(); att = db.get(Attachment, att_id)
    if att:
        path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
        try:
            if path.exists(): path.unlink()
        except Exception:
            pass
        db.delete(att); db.commit(); flash('Allegato eliminato', 'success')
    return redirect(url_for('giacenze'))

@app.get('/media/<int:att_id>')
@login_required
def media(att_id):
    db = SessionLocal(); att = db.get(Attachment, att_id)
    if not att: abort(404)
    path = (DOCS_DIR if att.kind=='doc' else PHOTOS_DIR) / att.filename
    if not path.exists(): abort(404)
    return send_file(path, as_attachment=False)
# ------------------- ANTEPRIME HTML (BUONO / DDT) -------------------
BAR_CSS = "background:#1f6fb2;color:#fff;padding:8px 12px;border-radius:6px;margin-bottom:12px"

BUONO_PREVIEW_HTML = """{% extends 'base.html' %}{% block content %}
<form method="post" action="{{url_for('pdf_buono')}}" target="_blank" class="card p-3">
  <div class='d-flex align-items-center gap-3 mb-2'>
    {% if logo_url %}<img src='{{logo_url}}' style='height:40px'>{% endif %}
    <div style='{{bar}}' class='flex-grow-1 text-center fw-bold'>BUONO PRELIEVO (ANTEPRIMA)</div>
    <button class='btn btn-primary'>Stampa / PDF</button>
  </div>
  <input type="hidden" name="ids" value="{{ids}}">
  <div class="row g-3">
    <div class="col-md-3"><label class="form-label">N. Buono</label><input name="buono_n" class="form-control" value="{{meta.buono_n}}"></div>
    <div class="col-md-3"><label class="form-label">Data Emissione</label><input name="data_em" class="form-control" value="{{meta.data_em}}"></div>
    <div class="col-md-3"><label class="form-label">Commessa</label><input name="commessa" class="form-control" value="{{meta.commessa}}"></div>
    <div class="col-md-3"><label class="form-label">Fornitore</label><input name="fornitore" class="form-control" value="{{meta.fornitore}}"></div>
    <div class="col-md-3"><label class="form-label">Protocollo</label><input name="protocollo" class="form-control" value="{{meta.protocollo}}"></div>
  </div>
  <hr>
  <div class="table-responsive">
    <table class="table table-sm table-bordered">
      <thead><tr><th>Ordine</th><th>Codice Articolo</th><th>Descrizione</th><th>Quantità</th><th>N.Arrivo</th></tr></thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td>{{r.ordine or ''}}</td>
          <td>{{r.codice_articolo or ''}}</td>
          <td>{{r.descrizione or ''}}</td>
          <td><input name="q_{{r.id_articolo}}" class="form-control form-control-sm" value="{{r.n_colli or 1}}"></td>
          <td>{{r.n_arrivo or ''}}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</form>
{% endblock %}
"""

DDT_PREVIEW_HTML = """{% extends 'base.html' %}{% block content %}
<form method="post" action="{{url_for('pdf_ddt')}}" target="_blank" class="card p-3">
  <div class='d-flex align-items-center gap-3 mb-2'>
    {% if logo_url %}<img src='{{logo_url}}' style='height:40px'>{% endif %}
    <div style='{{bar}}' class='flex-grow-1 text-center fw-bold'>DOCUMENTO DI TRASPORTO (ANTEPRIMA)</div>
    <button class='btn btn-primary'>Stampa / PDF</button>
  </div>
  <input type="hidden" name="ids" value="{{ids}}">
  <div class="row g-3">
    <div class="col-md-4">
      <label class="form-label">Destinatario</label>
      <select class="form-select" name="dest_key">
        {% for k,v in destinatari.items() %}
          <option value="{{k}}">{{k}} — {{v.ragione_sociale}}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-md-2"><label class="form-label">N. DDT</label><input name="n_ddt" class="form-control" value="{{n_ddt}}"></div>
    <div class="col-md-2"><label class="form-label">Data DDT</label><input name="data_ddt" type="date" class="form-control" value="{{oggi}}"></div>
    <div class="col-md-2"><label class="form-label">Targa</label><input name="targa" class="form-control"></div>
    <div class="col-md-2"><label class="form-label">Note</label><input name="note" class="form-control"></div>
  </div>
  <hr>
  <div class="table-responsive">
    <table class="table table-sm table-bordered align-middle">
      <thead><tr><th>ID</th><th>Cod.Art.</th><th>Descrizione</th><th style='width:110px'>Colli</th><th style='width:110px'>Peso</th><th>N.Arrivo</th></tr></thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td>{{r.id_articolo}}</td>
          <td>{{r.codice_articolo or ''}}</td>
          <td>{{r.descrizione or ''}}</td>
          <td><input class="form-control form-control-sm" name="colli_{{r.id_articolo}}" value="{{r.n_colli or 1}}"></td>
          <td><input class="form-control form-control-sm" name="peso_{{r.id_articolo}}" value="{{r.peso or ''}}"></td>
          <td>{{r.n_arrivo or ''}}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</form>
{% endblock %}
"""

def _get(ids_csv):
    ids=[int(x) for x in (ids_csv or "").split(',') if x.strip().isdigit()]
    if not ids: return []
    db=SessionLocal(); return db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

@app.post('/buono/preview')
@login_required
def buono_preview():
    rows=_get(request.form.get('ids',''))
    first = rows[0] if rows else None
    meta = {
        "buono_n": first.buono_n if first else "",
        "data_em": datetime.today().strftime("%d/%m/%Y"),
        "commessa": (first.commessa or "") if first else "",
        "fornitore": (first.fornitore or "") if first else "",
        "protocollo": (first.protocollo or "") if first else "",
    }
    return render_template_string(BUONO_PREVIEW_HTML,
                                  rows=rows, meta=meta,
                                  ids=request.form.get('ids',''),
                                  bar=BAR_CSS, logo_url=logo_url())

@app.post('/ddt/preview')
@login_required
def ddt_preview():
    rows=_get(request.form.get('ids',''))
    return render_template_string(DDT_PREVIEW_HTML,
                                  rows=rows,
                                  ids=request.form.get('ids',''),
                                  destinatari=load_destinatari(),
                                  n_ddt=next_ddt_number(),
                                  oggi=date.today().isoformat(),
                                  bar=BAR_CSS,
                                  logo_url=logo_url())


# ------------------- PDF BUONO / DDT -------------------

_styles = getSampleStyleSheet()
PRIMARY = colors.HexColor("#1f6fb2")
BORDER  = colors.HexColor("#aeb6bf")

def _pdf_table(data, col_widths=None, header=True, hAlign='LEFT'):
    t = Table(data, colWidths=col_widths, hAlign=hAlign)
    style = [
        ('FONT', (0,0), (-1,-1), 'Helvetica', 9),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]
    if header and data:
        style += [
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('FONT', (0,0), (-1,0), 'Helvetica-Bold', 9)
        ]
    t.setStyle(TableStyle(style))
    return t

def _copyright_para():
    tiny = _styles['Normal'].clone('copyright')
    tiny.fontSize = 7
    tiny.textColor = colors.grey
    tiny.alignment = 1
    return Paragraph("© Alessia Moncalvo — Gestionale Camar Web Edition", tiny)

def _sp(h=6): 
    return Spacer(1, h)

def _doc_with_header(title, pagesize=A4):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=pagesize,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=12*mm, bottomMargin=12*mm
    )
    story = []
    # Logo in alto a sinistra
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=40*mm, height=15*mm))
        story.append(_sp(4))
    # Barra blu titolo
    title_style = _styles['Heading2'].clone('title_bar')
    title_style.textColor = colors.white
    title_style.alignment = 1
    title_tbl = Table(
        [[Paragraph(title, title_style)]],
        colWidths=[doc.width],
        style=[
            ('BACKGROUND',(0,0),(-1,-1),PRIMARY),
            ('BOX',(0,0),(-1,-1),0.25,PRIMARY),
            ('LEFTPADDING',(0,0),(-1,-1),8),
            ('RIGHTPADDING',(0,0),(-1,-1),8),
            ('TOPPADDING',(0,0),(-1,-1),6),
            ('BOTTOMPADDING',(0,0),(-1,-1),6)
        ]
    )
    story += [title_tbl, _sp(8)]
    return doc, story, bio


@app.post('/pdf/buono')
@login_required
def pdf_buono():
    ids_csv = request.form.get('ids','')
    rows = _get(ids_csv)
    buono_n = (request.form.get('buono_n') or '').strip()
    db = SessionLocal()
    for r in rows:
        if buono_n:
            r.buono_n = buono_n
        q_val = request.form.get(f"q_{r.id_articolo}")
        if q_val is not None:
            r.n_colli = to_int_eu(q_val) or 1
    db.commit()

    doc, story, bio = _doc_with_header("BUONO PRELIEVO")
    d_row = rows[0] if rows else None
    meta = [
        ["Data Emissione", datetime.today().strftime("%d/%m/%Y")],
        ["Commessa", (d_row.commessa or "") if d_row else ""],
        ["Fornitore", (d_row.fornitore or "") if d_row else ""],
        ["Protocollo", (d_row.protocollo or "") if d_row else ""],
        ["N. Buono", (d_row.buono_n or "") if d_row else (buono_n or "")]
    ]
    story.append(_pdf_table(meta, [35*mm, None], header=False))
    story.append(_sp(6))
    story.append(Paragraph(f"<b>Cliente:</b> {(d_row.cliente or '').upper()}", _styles['Normal']))
    story.append(_sp(8))

    data = [['Ordine','Codice Articolo','Descrizione','Quantità','N.Arrivo']]
    for r in rows:
        data.append([r.ordine or '', r.codice_articolo or '', r.descrizione or '', (r.n_colli or 1), r.n_arrivo or ''])
    story.append(_pdf_table(data, col_widths=[25*mm, 45*mm, None, 20*mm, 25*mm]))
    story += [
        _sp(16),
        Table([["Firma Magazzino: ______________________", "Firma Cliente: ______________________"]],
              colWidths=[doc.width/2 - 4*mm, doc.width/2 - 4*mm]),
        _sp(6), _copyright_para()
    ]
    doc.build(story)
    bio.seek(0)
    return send_file(bio, as_attachment=False, download_name='buono.pdf')


@app.post('/pdf/ddt')
@login_required
def pdf_ddt():
    ids_csv = request.form.get('ids','')
    rows = _get(ids_csv)
    db = SessionLocal()
    for r in rows:
        colli = request.form.get(f"colli_{r.id_articolo}")
        peso = request.form.get(f"peso_{r.id_articolo}")
        if colli is not None: r.n_colli = to_int_eu(colli) or 1
        if peso is not None: r.peso = to_float_eu(peso) or 0
    db.commit()

    n_ddt = (request.form.get('n_ddt') or '').strip()
    data_ddt = request.form.get('data_ddt') or date.today().isoformat()
    targa = (request.form.get('targa') or '')
    note = (request.form.get('note') or '')
    dest_key = request.form.get('dest_key')
    dest = load_destinatari().get(dest_key, {})

    doc, story, bio = _doc_with_header("DOCUMENTO DI TRASPORTO (DDT)")

    mitt = [["Mittente", "Camar srl<br/>Via Luigi Canepa 2<br/>16165 Genova Struppa (GE)"]]
    mitt_tbl = _pdf_table(mitt, [35*mm, None], header=False)
    dest_text = f"{dest.get('ragione_sociale','')}"
    if dest.get('indirizzo'): dest_text += f"<br/>{dest['indirizzo']}"
    if dest.get('piva'): dest_text += f"<br/>P.IVA {dest['piva']}"
    dest_tbl = _pdf_table([["Destinatario", dest_text]], [35*mm, None], header=False)

    header_tbl = Table([[mitt_tbl, dest_tbl]],
                       colWidths=[doc.width/2 - 3*mm, doc.width/2 - 3*mm],
                       style=[('VALIGN',(0,0),(-1,-1),'TOP')])
    story.append(header_tbl)
    story.append(_sp(8))

    info = [
        ["N. DDT", n_ddt],
        ["Data DDT", fmt_date(data_ddt)],
        ["Targa", targa],
        ["Note", note]
    ]
    story.append(_pdf_table(info, [35*mm, None], header=False))
    story.append(_sp(8))

    data = [['ID','Cod.Art.','Descrizione','Colli','Peso','N.Arrivo']]
    tot_colli = 0; tot_peso = 0.0
    for r in rows:
        data.append([r.id_articolo, r.codice_articolo or '', r.descrizione or '',
                     (r.n_colli or 1), (r.peso or 0), r.n_arrivo or ''])
        tot_colli += (r.n_colli or 1)
        tot_peso += float(r.peso or 0)
    story.append(_pdf_table(data, col_widths=[16*mm, 38*mm, None, 20*mm, 20*mm, 22*mm]))
    story.append(_sp(6))
    story.append(Paragraph(f"<b>Totale Colli:</b> {tot_colli} &nbsp;&nbsp; <b>Totale Peso:</b> {tot_peso} Kg", _styles['Normal']))
    story += [_sp(8), _copyright_para()]
    doc.build(story)
    bio.seek(0)
    return send_file(bio, as_attachment=False, download_name='ddt.pdf')
# ------------------- ETICHETTE (ANTEPRIMA + PDF IN MEMORIA) -------------------

LABELS_FORM = """{% extends 'base.html' %}{% block content %}
<h3>Nuova Etichetta (99,82×61,98 mm)</h3>
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
    <button class="btn btn-primary">Anteprima / Stampa</button>
    <button type="submit" formaction="{{url_for('labels_pdf')}}" class="btn btn-outline-primary" target="_blank">Apri PDF</button>
  </div>
</form>
{% endblock %}"""

LABELS_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>
  @media print { .no-print{display:none} body{margin:0} }
  .logo{height:26px;margin-right:10px}
  /* area simulata con proporzioni reali dell'etichetta; nessun bordo inutile */
  .wrap{width:1000px;height:620px;padding:18px}
  .row-line{font-size:38px;line-height:1.2;margin:8px 0}
  .key{font-weight:800}
</style></head><body class='p-4'>
<div class='no-print mb-3'>
  <button class='btn btn-primary' onclick='window.print()'>Stampa</button>
  <a class='btn btn-outline-secondary' href='{{url_for("labels_form")}}'>Indietro</a>
</div>
<div class='wrap'>
  <div class='d-flex align-items-center mb-2'>
    {% if logo_url %}<img src='{{logo_url}}' class='logo' alt='logo'>{% endif %}
    <h5 class='m-0'>Etichetta 99,82×61,98 mm</h5>
  </div>
  <div class='row-line'><span class='key'>CLIENTE:</span> {{d.cliente}}</div>
  <div class='row-line'><span class='key'>FORNITORE:</span> {{d.fornitore}}</div>
  <div class='row-line'><span class='key'>ORDINE:</span> {{d.ordine}}</div>
  <div class='row-line'><span class='key'>COMMESSA:</span> {{d.commessa}}</div>
  <div class='row-line'><span class='key'>DDT:</span> {{d.ddt_ingresso}}</div>
  <div class='row-line'><span class='key'>DATA INGRESSO:</span> {{d.data_ingresso}}</div>
  <div class='row-line'><span class='key'>ARRIVO:</span> {{d.arrivo}}</div>
  <div class='row-line'><span class='key'>POSIZIONE:</span> {{d.posizione}}</div>
  <div class='row-line'><span class='key'>COLLI:</span> {{d.n_colli}}</div>
</div>
</body></html>"""

@app.get('/labels')
@login_required
def labels_form():
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env, 'labels_form.html')[0],
        logo_url=logo_url()
    )

def _labels_clean(form):
    def g(k): return (form.get(k) or "").strip()
    return {k: g(k) for k in ("cliente","fornitore","ordine","commessa","ddt_ingresso",
                               "data_ingresso","arrivo","n_colli","posizione","protocollo")}

@app.post('/labels/preview')
@login_required
def labels_preview():
    d = _labels_clean(request.form)
    return render_template_string(LABELS_HTML, d=d, logo_url=logo_url())

@app.post('/labels/pdf')
@login_required
def labels_pdf():
    # PDF in memoria, senza forzare il download (as_attachment=False)
    d = _labels_clean(request.form)
    pagesize = (99.82*mm, 61.98*mm)  # esatto formato
    bio = io.BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=pagesize,
        leftMargin=4*mm, rightMargin=4*mm, topMargin=3*mm, bottomMargin=3*mm
    )
    story = []
    # Logo a sinistra, niente bordi
    if LOGO_PATH and Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=24*mm, height=8*mm))
        story.append(Spacer(1, 2))

    row = _styles['Normal'].clone('label_line')
    row.fontName='Helvetica-Bold'
    row.fontSize=11
    row.leading=13

    def P(label, value): 
        return Paragraph(f"{label}: <b>{value or ''}</b>", row)

    story += [
        P("CLIENTE", d['cliente']),
        P("FORNITORE", d['fornitore']),
        P("ORDINE", d['ordine']),
        P("COMMESSA", d['commessa']),
        P("DDT", d['ddt_ingresso']),
        P("DATA INGRESSO", d['data_ingresso']),
        P("ARRIVO", d['arrivo']),
        P("POSIZIONE", d['posizione']),
        P("COLLI", d['n_colli']),
        Spacer(1, 2),
        Paragraph("© Alessia Moncalvo — Gestionale Camar Web Edition", _styles['Normal'])
    ]

    doc.build(story)
    bio.seek(0)
    return send_file(bio, as_attachment=False, download_name='etichetta.pdf')

# ------------------- VISUALIZZA GIACENZE (FILTRI COMPLETI + LOGO + TOOLBAR) -------------------

@app.get('/giacenze')
@login_required
def giacenze():
    db = SessionLocal()
    qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())
    if session.get('role') == 'client':
        qs = qs.filter(Articolo.cliente == session['user'])

    # Applica tutti i filtri
    def like(col):
        v = request.args.get(col)
        if v:
            nonlocal qs
            qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))

    equal_cols = ['id_articolo']
    like_cols = ['codice_articolo','cliente','fornitore','magazzino','buono_n','commessa','posizione',
                 'mezzi_in_uscita','descrizione','ordine','n_ddt_uscita','stato','n_arrivo','ns_rif',
                 'serial_number','n_ddt_ingresso','protocollo']
    date_cols = {
        'ingresso_da':'data_ingresso >=',
        'ingresso_a':'data_ingresso <=',
        'uscita_da':'data_uscita >=',
        'uscita_a':'data_uscita <='
    }

    # Filtri
    if request.args.get('id'):
        qs = qs.filter(Articolo.id_articolo == request.args.get('id'))
    for c in like_cols:
        like(c)
    for arg, expr in date_cols.items():
        val = request.args.get(arg)
        if val:
            date_sql = parse_date_ui(val)
            col, op = expr.split()
            if op == '>=':
                qs = qs.filter(getattr(Articolo, col) >= date_sql)
            else:
                qs = qs.filter(getattr(Articolo, col) <= date_sql)

    rows = qs.all()

    cols = ["id_articolo","codice_articolo","descrizione","cliente","fornitore","protocollo","ordine",
            "commessa","magazzino","posizione","stato","peso","n_colli","larghezza","lunghezza","altezza",
            "m2","m3","n_arrivo","buono_n","n_ddt_ingresso","data_ingresso","data_uscita","n_ddt_uscita",
            "mezzi_in_uscita","serial_number","ns_rif"]

    GIACENZE_TEMPLATE = """{% extends 'base.html' %}{% block content %}
<div class='d-flex align-items-center mb-3'>
  {% if logo_url %}<img src='{{logo_url}}' style='height:45px' class='me-3'>{% endif %}
  <h4 class='m-0'>Visualizza Giacenze</h4>
</div>

<div class='card p-3 mb-3'>
  <form class='row g-2' method='get'>
    <div class='col-md-1'><label class='form-label small'>ID</label><input name='id' value='{{request.args.get("id","")}}' class='form-control form-control-sm'></div>
    {% for label,name in [
      ('Cod.Art.','codice_articolo'),('Cliente','cliente'),('Fornitore','fornitore'),
      ('Magazzino','magazzino'),('Buono N.','buono_n'),('Commessa','commessa'),('Posizione','posizione'),
      ('Mezzo Uscito','mezzi_in_uscita'),('Descrizione','descrizione'),('Ordine','ordine'),
      ('DDT Uscita','n_ddt_uscita'),('Stato','stato'),('N.Arrivo','n_arrivo'),
      ('NS Rif','ns_rif'),('Serial Number','serial_number'),('DDT Ingresso','n_ddt_ingresso'),
      ('Protocollo','protocollo')
    ] %}
    <div class='col-md-2'><label class='form-label small'>{{label}}</label>
      <input name='{{name}}' value='{{request.args.get(name,"")}}' class='form-control form-control-sm'>
    </div>
    {% endfor %}
    <div class='col-md-2'><label class='form-label small'>Ingresso Da</label><input name='ingresso_da' value='{{request.args.get("ingresso_da","")}}' class='form-control form-control-sm'></div>
    <div class='col-md-2'><label class='form-label small'>Ingresso A</label><input name='ingresso_a' value='{{request.args.get("ingresso_a","")}}' class='form-control form-control-sm'></div>
    <div class='col-md-2'><label class='form-label small'>Uscita Da</label><input name='uscita_da' value='{{request.args.get("uscita_da","")}}' class='form-control form-control-sm'></div>
    <div class='col-md-2'><label class='form-label small'>Uscita A</label><input name='uscita_a' value='{{request.args.get("uscita_a","")}}' class='form-control form-control-sm'></div>
    <div class='col-md-2 d-grid'><button class='btn btn-primary btn-sm mt-4'>Filtra</button></div>
  </form>
</div>

<div class='card p-3'>
  <div class='d-flex flex-wrap gap-2 mb-2 no-print'>
    <form method='post' action='{{url_for("buono_preview")}}'>
      <input type='hidden' name='ids' id='ids-bpr'>
      <button class='btn btn-outline-secondary btn-sm' onclick="return setIds('ids-bpr')">Crea Buono</button>
    </form>
    <form method='post' action='{{url_for("ddt_preview")}}'>
      <input type='hidden' name='ids' id='ids-dpr'>
      <button class='btn btn-outline-secondary btn-sm' onclick="return setIds('ids-dpr')">Crea DDT</button>
    </form>
    <form method='post' action='{{url_for("pdf_buono")}}' target='_blank'>
      <input type='hidden' name='ids' id='ids-bp'>
      <button class='btn btn-outline-primary btn-sm' onclick="return setIds('ids-bp')">PDF Buono</button>
    </form>
    <form method='post' action='{{url_for("pdf_ddt")}}' target='_blank'>
      <input type='hidden' name='ids' id='ids-dp'>
      <button class='btn btn-outline-primary btn-sm' onclick="return setIds('ids-dp')">PDF DDT</button>
    </form>
    {% if session.get('role') == 'admin' %}
      <a class='btn btn-success btn-sm' href='{{url_for("ddt_setup")}}?ids=' id='btn-scarico'>Scarico + DDT</a>
    {% endif %}
    <form method='get' action='{{url_for("bulk_edit")}}'>
      <input type='hidden' name='ids' id='ids-bulk'>
      <button class='btn btn-warning btn-sm' onclick="return setIds('ids-bulk')">Modifica multipla</button>
    </form>
  </div>

  <div class='table-responsive' style='max-height:70vh'>
    <table class='table table-sm table-hover align-middle'>
      <thead>
        <tr>
          <th style='width:28px'><input type='checkbox' id='checkall'></th>
          {% for c in cols %}<th>{{c}}</th>{% endfor %}
          <th>Allegati</th><th>Azione</th>
        </tr>
      </thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td><input type='checkbox' class='sel' value='{{r.id_articolo}}'></td>
          {% for c in cols %}
            {% set v = getattr(r,c) %}
            <td>{% if c in ['data_ingresso','data_uscita'] %}{{ v|fmt_date }}{% else %}{{ v or '' }}{% endif %}</td>
          {% endfor %}
          <td>
            {% for a in r.attachments %}
              <a class='badge text-bg-light' href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.kind}}</a>
            {% endfor %}
          </td>
          <td><a class='btn btn-sm btn-outline-primary' href='{{url_for("edit_row",id=r.id_articolo)}}'>Modifica</a></td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script>
const all=document.getElementById('checkall');
if(all){all.addEventListener('change',e=>{
  document.querySelectorAll('.sel').forEach(cb=>cb.checked=all.checked);
});}
function collectIds(){
  return [...document.querySelectorAll('.sel:checked')].map(x=>x.value).join(',');
}
function setIds(hiddenId){
  const v = collectIds();
  if(!v){ alert('Seleziona almeno una riga'); return false; }
  const el = document.getElementById(hiddenId); if(el) el.value=v;
  const l = document.getElementById('btn-scarico'); if(l) l.href='{{url_for("ddt_setup")}}?ids='+encodeURIComponent(v);
  return true;
}
</script>
{% endblock %}"""

    return render_template_string(GIACENZE_TEMPLATE, rows=rows, cols=cols, logo_url=logo_url())
  # ------------------- FOOTER / COPYRIGHT / AVVIO APP -------------------

FOOTER = """
<footer class='text-center text-muted py-3 small'>
  © Alessia Moncalvo – Gestionale Camar Web Edition • Tutti i diritti riservati.
</footer>
<script>
  document.body.insertAdjacentHTML('beforeend', `{{ footer|safe }}`);
</script>
"""

@app.context_processor
def inject_footer():
    return {"footer": FOOTER}

# ------------------- SMTP (commentato per configurazione futura) -------------------
"""
# Per abilitare l'invio email:
# import smtplib
# from email.message import EmailMessage
# EMAIL_HOST = os.environ.get('SMTP_HOST','smtp.office365.com')
# EMAIL_USER = os.environ.get('SMTP_USER','user@example.com')
# EMAIL_PASS = os.environ.get('SMTP_PASS','password')
# def send_mail(to, subject, body):
#     msg = EmailMessage()
#     msg['From'] = EMAIL_USER
#     msg['To'] = to
#     msg['Subject'] = subject
#     msg.set_content(body)
#     with smtplib.SMTP(EMAIL_HOST,587) as s:
#         s.starttls()
#         s.login(EMAIL_USER,EMAIL_PASS)
#         s.send_message(msg)
"""

# ------------------- AVVIO FLASK APP -------------------

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Avvio Gestionale Camar Web Edition su porta {port}")
    app.run(host='0.0.0.0', port=port, debug=False)




