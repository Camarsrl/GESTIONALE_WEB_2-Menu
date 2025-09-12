# -*- coding: utf-8 -*-
"""
Impostazioni SMTP per invio email (facoltative):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TLS (default: '1'), FROM_EMAIL
Logo:
  Metti il file in static/logo.png oppure imposta LOGO_PATH env.
"""

import os, io, re, json, uuid, smtplib
from email.message import EmailMessage
from datetime import datetime, date
from pathlib import Path

import pandas as pd

def is_blank(v):
    # True per None, "", spazi, NaN, NaT
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return (v is None) or (isinstance(v, str) and not v.strip())


from flask import (
    Flask, request, render_template_string, redirect, url_for,
    send_file, session, flash, abort, Blueprint
)

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

import pandas as pd

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet

# Jinja loader (filesystem + inline)
from jinja2 import ChoiceLoader, FileSystemLoader, DictLoader

# ------------------- PATH / DB -------------------
APP_DIR = Path(os.environ.get("APP_DIR", "."))
APP_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

MEDIA_DIR = APP_DIR / "media"
DOCS_DIR = MEDIA_DIR / "docs"
PHOTOS_DIR = MEDIA_DIR / "photos"
for d in (DOCS_DIR, PHOTOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{APP_DIR / 'magazzino.db'}"
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

LOGO_PATH = os.environ.get("LOGO_PATH") or str(STATIC_DIR / "logo.png")
if not Path(LOGO_PATH).exists():
    for alt in ("logo camar.jpg", "logo.jpg", "logo.jpeg", "logo.png"):
        p = STATIC_DIR / alt
        if p.exists():
            LOGO_PATH = str(p)
            break


DESTINATARI_JSON = APP_DIR / "destinatari_saved.json"   # <-- caricato nella maschera DDT
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
    if not d: return None
    try: return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception: return d

def fmt_date(d):
    if not d: return ""
    try: return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception: return d

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
    # fallback esempio
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
app.jinja_env.globals['getattr'] = getattr  # utile nei template

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
        <a class='btn btn-outline-primary' href='{{url_for("giacenze")}}'>Visualizza Giacenze</a>
        <a class='btn btn-outline-primary' href='{{url_for("import_excel")}}'>Import da Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel")}}'>Export Excel</a>
        <a class='btn btn-outline-primary' href='{{url_for("export_excel_by_client")}}'>Export per Cliente</a>
        <a class='btn btn-outline-success' href='{{url_for("new_row")}}'>Nuovo Articolo</a>
      </div>
    </div>
  </div>
  <div class='col-md-9'><div class='card p-4'>
    <h4>Benvenuto</h4>
    <p class='text-muted'>Stampe HTML e PDF (con logo), profili import, progressivo DDT, etichette 62×100 mm, invio e-mail.</p>
  </div></div>
</div>
{% endblock %}"""

GIACENZE = """{% extends 'base.html' %}{% block content %}
<div class='card p-3 mb-3'><form class='row g-2' method='get'>
  {% for label,name in [('ID(=)','id'),('Cod.Art.(~=)','codice_articolo'),('Descr.(~=)','descrizione'),('Cliente(~=)','cliente'),
    ('Commessa(~=)','commessa'),('Ordine(~=)','ordine'),('N.Arrivo(~=)','n_arrivo'),('Stato(~=)','stato'),
    ('Posizione(~=)','posizione'),('Data Ingr. Da','data_da'),('Data Ingr. A','data_a'),('Buono N(~=)','buono_n')] %}
    <div class='col-md-2'><label class='form-label small'>{{label}}</label><input name='{{name}}' value='{{request.args.get(name,"")}}' class='form-control form-control-sm'></div>
  {% endfor %}
  <div class='col-md-2 d-grid'><button class='btn btn-primary btn-sm mt-4'>Filtra</button></div>
</form></div>

<div class='card p-3'>
  <div class='d-flex flex-wrap gap-2 mb-2 no-print'>
    <form method='post' action='{{url_for("crea_buono_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-b1'><button class='btn btn-outline-secondary btn-sm'>Buono (Stampa)</button></form>
    <form method='post' action='{{url_for("crea_ddt_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-d1'><button class='btn btn-outline-secondary btn-sm'>DDT (Stampa)</button></form>
    <form method='post' action='{{url_for("crea_etichetta_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-e1'><button class='btn btn-outline-secondary btn-sm'>Etichette (Stampa)</button></form>
    <form method='post' action='{{url_for("pdf_buono")}}' target='_blank'><input type='hidden' name='ids' id='ids-bp'><button class='btn btn-outline-primary btn-sm'>Buono (PDF)</button></form>
    <form method='post' action='{{url_for("pdf_ddt")}}' target='_blank'><input type='hidden' name='ids' id='ids-dp'><button class='btn btn-outline-primary btn-sm'>DDT (PDF)</button></form>
    <form method='post' action='{{url_for("pdf_etichette")}}' target='_blank'><input type='hidden' name='ids' id='ids-ep'><button class='btn btn-outline-primary btn-sm'>Etichette (PDF)</button></form>
    {% if session.get('role') == 'admin' %}
      <a class='btn btn-success btn-sm' href='{{url_for("ddt_setup")}}?ids=' id='btn-scarico'>Scarico + DDT (PDF)</a>
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
          {% for c in cols %}<td>{{getattr(r,c)}}</td>{% endfor %}
          <td>{% for a in r.attachments %}<a class='badge text-bg-light' href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.kind}}</a> {% endfor %}</td>
          <td><a class='btn btn-sm btn-outline-primary' href='{{url_for("edit_row",id=r.id_articolo)}}'>Modifica</a></td>
        </tr>{% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script>
const all=document.getElementById('checkall');
all&&all.addEventListener('change',e=>document.querySelectorAll('.sel').forEach(cb=>cb.checked=all.checked));
function setIds(id){
  const v=[...document.querySelectorAll('.sel:checked')].map(x=>x.value).join(',');
  const el=document.getElementById(id); if(el) el.value=v;
  const l=document.getElementById('btn-scarico'); if(l) l.href='{{url_for("ddt_setup")}}?ids='+encodeURIComponent(v);
}
['ids-b1','ids-d1','ids-e1','ids-bp','ids-dp','ids-ep'].forEach(n=>{
  const f=document.getElementById(n)?.closest('form'); f&&f.addEventListener('submit',()=>setIds(n));
});
</script>
{% endblock %}
"""

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

PRINT_DOC = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>@media print{.no-print{display:none}} .logo{height:40px;margin-right:10px}</style></head><body class='p-4'>
<div class='no-print mb-3'><button class='btn btn-primary' onclick='window.print()'>Stampa</button></div>
<div class='d-flex align-items-center mb-3'>{% if logo_url %}<img src='{{logo_url}}' class='logo'>{% endif %}<h3 class='m-0'>{{title}}</h3></div>
<table class='table table-sm table-bordered'><thead><tr>{% for h in headers %}<th>{{h}}</th>{% endfor %}</tr></thead>
<tbody>{% for row in data %}<tr>{% for v in row %}<td>{{v}}</td>{% endfor %}</tr>{% endfor %}</tbody></table></body></html>"""

# DDT SETUP PAGE
DDT_SETUP = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'>
  <h5>Impostazioni DDT</h5>
  <form method='post'>
    <input type='hidden' name='ids' value='{{ids}}'>
    <div class='row g-3'>
      <div class='col-md-6'>
        <label class='form-label'>Destinatario</label>
        <select name='dest' class='form-select'>
          {% for k,v in destinatari.items() %}
          <option value='{{k}}'>{{k}} — {{v.ragione_sociale}}</option>
          {% endfor %}
        </select>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Tipologia merce</label>
        <input name='tipo_merce' class='form-control' placeholder='Es. Profili alluminio'>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Vettore</label>
        <input name='vettore' class='form-control' placeholder='Nome vettore'>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Causale trasporto</label>
        <input name='causale' class='form-control' value='Conto lavoro'>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Aspetto esteriore</label>
        <input name='aspetto' class='form-control' value='Colli'>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Data DDT</label>
        <input name='data_ddt' type='date' class='form-control' value='{{oggi}}'>
      </div>
      <div class='col-md-3'>
        <label class='form-label'>Email invio (opz.)</label>
        <input name='email_to' type='email' class='form-control' placeholder='destinatario@dominio'>
      </div>
    </div>
    <div class='mt-3 d-flex gap-2'>
      <button class='btn btn-success'>Genera DDT & Scarico</button>
      <a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Annulla</a>
    </div>
    <p class='text-muted mt-3'>Sotto la tipologia merce, nel PDF, è presente lo spazio “Firma Vettore”.</p>
  </form>
</div>
{% endblock %}
"""

bp = Blueprint('bp', __name__)
app.register_blueprint(bp)
dict_loader = DictLoader({
    'base.html': BASE, 'login.html': LOGIN, 'home.html': HOME,
    'giacenze.html': GIACENZE, 'edit.html': EDIT, 'print_doc.html': PRINT_DOC,
    'ddt_setup.html': DDT_SETUP
})
app.jinja_loader = ChoiceLoader([FileSystemLoader('templates'), dict_loader])

def logo_url():
    return url_for('static', filename='logo.png') if Path(LOGO_PATH).exists() else None

# ------------------- AUTH -------------------
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def w(*a, **k):
        if not session.get('user'):
            return redirect(url_for('login'))
        return fn(*a, **k)
    return w

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('user', '').strip().upper()
        p = request.form.get('pwd', '')
        users = get_users()
        if u in users and users[u] == p:
            session['user'] = u
            session['role'] = 'admin' if u in ADMIN_USERS else 'client'
            return redirect(url_for('home'))
        flash('Credenziali non valide', 'danger')
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
        if v: qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))
    for col in ['codice_articolo','descrizione','cliente','commessa','ordine','n_arrivo','stato','posizione','buono_n']:
        like(col)
    if args.get('data_da'):
        qs = qs.filter(Articolo.data_ingresso >= parse_date_ui(args.get('data_da')))
    if args.get('data_a'):
        qs = qs.filter(Articolo.data_ingresso <= parse_date_ui(args.get('data_a')))
    return qs

@app.get('/giacenze')
@login_required
def giacenze():
    db = SessionLocal()
    qs = db.query(Articolo).order_by(Articolo.id_articolo.desc())
    if session.get('role') == 'client':
        qs = qs.filter(Articolo.cliente == session['user'])
    rows = filter_query(qs, request.args).all()
    cols = ["id_articolo","cliente","descrizione","peso","n_colli","posizione","n_arrivo","buono_n","stato","data_ingresso","data_uscita","n_ddt_uscita","m2","m3"]
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env, 'giacenze.html')[0],
        rows=rows, cols=cols, logo_url=logo_url()
    )

# ------------------- NUOVO / EDIT -------------------
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
        fields=['codice_articolo','pezzo','larghezza','lunghezza','altezza','protocollo','ordine','commessa','magazzino','fornitore',
                'data_ingresso','n_ddt_ingresso','cliente','descrizione','peso','n_colli','posizione','n_arrivo','buono_n','note',
                'serial_number','data_uscita','n_ddt_uscita','ns_rif','stato','mezzi_in_uscita']
        numeric_float={'larghezza','lunghezza','altezza','peso','m2','m3'}
        numeric_int={'n_colli'}
        for f in fields:
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
                if not f or not f.filename: continue
                name=f"{id}_{uuid.uuid4().hex}_{f.filename.replace(' ','_')}"
                ext=os.path.splitext(name)[1].lower()
                kind='doc' if ext=='.pdf' else 'foto'
                folder = DOCS_DIR if kind=='doc' else PHOTOS_DIR
                f.save(str(folder / name))
                db.add(Attachment(articolo_id=id,kind=kind,filename=name))
        db.commit(); flash('Riga salvata','success')
        return redirect(url_for('giacenze'))
    fields=[('Codice Articolo','codice_articolo'),('Descrizione','descrizione'),('Cliente','cliente'),
            ('Protocollo','protocollo'),('Ordine','ordine'),
            ('Peso','peso'),('N Colli','n_colli'),('Posizione','posizione'),
            ('Stato','stato'),('N.Arrivo','n_arrivo'),('Buono N','buono_n'),
            ('Fornitore','fornitore'),('Magazzino','magazzino'),
            ('Data Ingresso (GG/MM/AAAA)','data_ingresso'),('Data Uscita (GG/MM/AAAA)','data_uscita'),
            ('N DDT Ingresso','n_ddt_ingresso'),('N DDT Uscita','n_ddt_uscita'),
            ('Larghezza (m)','larghezza'),('Lunghezza (m)','lunghezza'),('Altezza (m)','altezza'),
            ('Serial Number','serial_number'),('NS Rif','ns_rif'),('Mezzi in Uscita','mezzi_in_uscita'),('Note','note')]
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env,'edit.html')[0],
        row=row, fields=fields, logo_url=logo_url()
    )

# ------------------- ALLEGATI -------------------
@app.get('/attachment/<int:att_id>/delete')
@login_required
def delete_attachment(att_id):
    db=SessionLocal(); att=db.get(Attachment,att_id)
    if att:
        path=(DOCS_DIR if att.kind=='doc' else PHOTOS_DIR)/att.filename
        try:
            if path.exists(): path.unlink()
        except Exception: pass
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

# Profilo di default nel formato atteso: { "header_row": int, "column_map": { "ColonnaExcel": "campo_db", ... } }
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
    """Carica i profili da file; se mancano uso un 'Generico' di default."""
    if PROFILES_PATH.exists():
        try:
            return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"Generico": DEFAULT_PROFILE}

@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_excel():
    profiles = load_profile()
    selected = request.args.get('profile') or next(iter(profiles.keys()))

    # Alias/normalizzazioni della destinazione
    def norm_target(t: str) -> str | None:
        if not t:
            return None
        t0 = t.strip()
        aliases = {
            "ID": "id_articolo",
            "M2": "m2",
            "M3": "m3",
            "Notes": "note",
            "NS RIF": "ns_rif",
            "NS.RIF": "ns_rif",
            "MEZZO IN USCITA": "mezzi_in_uscita",
            "Mezzo_in _uscita": "mezzi_in_uscita",
            # colonne da ignorare
            "TRUCKER": None,
            "DESTINATARI": None,
            "TIPO DI IMBALLO": None,
        }
        return aliases.get(t0, t0.lower())

    # Helper per verificare celle vuote/NaN/NaT/stringhe vuote
    def is_blank(v) -> bool:
        try:
            import pandas as _pd  # già importato sopra, ma così evitiamo linting
            if _pd.isna(v):
                return True
        except Exception:
            pass
        return (v is None) or (isinstance(v, str) and v.strip() == "")

    if request.method == 'POST':
        selected = request.form.get('profile') or selected
        prof = profiles.get(selected)
        if not prof:
            flash("Profilo non trovato", "danger")
            return redirect(request.url)

        # Rende compatibili anche profili “vecchi” senza column_map
        header_row = int(prof.get("header_row", 0))
        column_map: dict[str, str] = prof.get("column_map", {})
        if not column_map:
            tmp = {}
            for target, aliases in prof.items():
                if target in ("header_row", "column_map"):
                    continue
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str):
                            tmp[alias] = target
            if tmp:
                column_map = tmp

        f = request.files.get('file')
        if not f or not f.filename:
            flash('Seleziona un file .xlsx', 'warning')
            return redirect(request.url)

        try:
            # Lettura più tollerante → non trasformiamo subito NaN/NaT in stringhe
            df = pd.read_excel(f, header=header_row, keep_default_na=True)
        except Exception as e:
            flash(f"Errore lettura Excel: {e}", "danger")
            return redirect(request.url)

        # mappa 'NOME COLONNA UPPER' -> nome originale
        excel_cols = {c.strip().upper(): c for c in df.columns if isinstance(c, str)}

        db = SessionLocal()
        added = 0
        numeric_float = {'larghezza', 'lunghezza', 'altezza', 'peso', 'm2', 'm3'}
        numeric_int = {'n_colli'}

        for _, r in df.iterrows():
            a = Articolo()
            any_value = False

            # Scorro le colonne Excel definite nel profilo
            for excel_name, target in column_map.items():
                if not isinstance(excel_name, str) or not isinstance(target, str):
                    continue
                key = excel_cols.get(excel_name.strip().upper())
                if not key:
                    continue

                value = r.get(key, None)
                if is_blank(value):
                    value = None

                field = norm_target(target)
                if not field or not hasattr(Articolo, field):
                    continue

                if field in ("data_ingresso", "data_uscita"):
                    if is_blank(value):
                        value = None
                    elif isinstance(value, (pd.Timestamp, datetime, date)):
                        # Evita NaT: pd.isna(value) già intercettato da is_blank
                        value = value.strftime("%Y-%m-%d")
                    elif isinstance(value, str):
                        value = parse_date_ui(value)
                    else:
                        # numeri Excel o altri tipi
                        try:
                            value = pd.to_datetime(value).strftime("%Y-%m-%d")
                        except Exception:
                            value = parse_date_ui(str(value))
                elif field in numeric_float:
                    value = None if is_blank(value) else to_float_eu(value)
                elif field in numeric_int:
                    value = None if is_blank(value) else to_int_eu(value)

                if value not in (None, ""):
                    any_value = True
                setattr(a, field, value)

            # Se non ho riempito nulla, salto la riga
            if not any_value:
                continue

            # calcolo m2/m3 se ho misure
            a.m2, a.m3 = calc_m2_m3(a.lunghezza, a.larghezza, a.altezza, a.n_colli)
            db.add(a)
            added += 1

        db.commit()
        flash(f"Import completato ({added} righe)", "success")
        return redirect(url_for('giacenze'))

    # GET: form caricamento
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
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w: df.to_excel(w, index=False, sheet_name='Giacenze')
    bio.seek(0); return send_file(bio, as_attachment=True, download_name='giacenze_export.xlsx')

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
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w: df.to_excel(w, index=False, sheet_name=(client[:31] or 'Export'))
    bio.seek(0); return send_file(bio, as_attachment=True, download_name=f'export_{client}.xlsx')

# ------------------- STAMPE HTML -------------------
PRINT = PRINT_DOC
def _get(ids_csv):
    ids=[int(x) for x in ids_csv.split(',') if x.strip().isdigit()]
    if not ids: return []
    db=SessionLocal(); return db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

@app.post('/crea_buono_html')
@login_required
def crea_buono_html():
    rows=_get(request.form.get('ids',''))
    hdr=['Ordine','Cod.Art.','Descrizione','Quantità','N.Arrivo']
    data=[[r.ordine or '', r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.n_arrivo or ''] for r in rows]
    return render_template_string(PRINT, title="Buono Prelievo", headers=hdr, data=data, logo_url=logo_url())

@app.post('/crea_ddt_html')
@login_required
def crea_ddt_html():
    rows=_get(request.form.get('ids',''))
    hdr=['ID','Cod.Art.','Descrizione','Colli','Peso','Protocollo','Ordine']
    data=[[r.id_articolo, r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.peso or '', r.protocollo or '', r.ordine or ''] for r in rows]
    return render_template_string(PRINT, title="Documento di Trasporto (DDT)", headers=hdr, data=data, logo_url=logo_url())

@app.post('/crea_etichetta_html')
@login_required
def crea_etichetta_html():
    rows=_get(request.form.get('ids',''))
    html=["<!doctype html><html><head><meta charset='utf-8'><style>@media print{.no-print{display:none}} .lbl{border:1px solid #aaa;padding:8px;width:420px;height:260px;margin:6px;float:left;font-family:sans-serif} .k{font-weight:bold}</style></head><body>"]
    html.append("<div class='no-print'><button onclick='window.print()'>Stampa</button></div>")
    for r in rows:
        html.append("<div class='lbl'>")
        html.append(f"<div class='k'>Cliente:</div> {r.cliente or ''}<br>")
        html.append(f"<div class='k'>Protocollo:</div> {r.protocollo or ''}<br>")
        html.append(f"<div class='k'>Ordine/Arrivo:</div> {(r.ordine or '')} / {(r.n_arrivo or '')}<br>")
        html.append(f"<div class='k'>Cod.Art:</div> {r.codice_articolo or ''}<br>")
        html.append(f"<div class='k'>Descr.:</div> {(r.descrizione or '')[:80]}<br>")
        html.append(f"<div class='k'>Colli/Peso:</div> {(r.n_colli or 1)} / {(r.peso or '')}")
        html.append("</div>")
    html.append("</body></html>")
    return "".join(html)

# ------------------- PDF HELPERS -------------------
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
    if Path(LOGO_PATH).exists():
        story.append(Image(LOGO_PATH, width=40*mm, height=15*mm))
    story.append(Paragraph(title, _styles['Heading2'])); story.append(Spacer(1,6))
    return doc, story, bio

# ------------------- PDF BUONO / DDT / ETICHETTE -------------------
@app.post('/pdf/buono')
@login_required
def pdf_buono():
    rows=_get(request.form.get('ids',''))
    doc, story, bio = _doc_with_header("Buono di Prelievo")
    data=[['Ordine','Cod.Art.','Descrizione','Quantità','N.Arrivo']]
    for r in rows:
        data.append([r.ordine or '', r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.n_arrivo or ''])
    story.append(_pdf_table(data, col_widths=[25*mm, 25*mm, 80*mm, 20*mm, 25*mm])); doc.build(story)
    bio.seek(0); return send_file(bio, as_attachment=True, download_name='buono.pdf')

@app.post('/pdf/ddt')
@login_required
def pdf_ddt():
    rows=_get(request.form.get('ids',''))
    doc, story, bio = _doc_with_header("Documento di Trasporto (DDT)")
    data=[['ID','Cod.Art.','Descrizione','Colli','Peso','Protocollo','Ordine']]
    for r in rows:
        data.append([r.id_articolo, r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.peso or '', r.protocollo or '', r.ordine or ''])
    story.append(_pdf_table(data, col_widths=[15*mm, 25*mm, 80*mm, 15*mm, 20*mm, 30*mm, 25*mm])); doc.build(story)
    bio.seek(0); return send_file(bio, as_attachment=True, download_name='ddt.pdf')

@app.post('/pdf/etichette')
@login_required
def pdf_etichette():
    # 62mm x 100mm (w x h) — una etichetta per pagina
    from reportlab.lib.pagesizes import landscape
    label_size = (100*mm, 62*mm)
    rows=_get(request.form.get('ids',''))
    bio=io.BytesIO()
    for i, r in enumerate(rows):
        doc=SimpleDocTemplate(bio if i==len(rows)-1 else io.BytesIO(),
                              pagesize=label_size, leftMargin=5*mm, rightMargin=5*mm, topMargin=5*mm, bottomMargin=5*mm)
        story=[]
        if Path(LOGO_PATH).exists():
            story.append(Image(LOGO_PATH, width=40*mm, height=12*mm))
        story += [
            Paragraph(f"<b>Cliente:</b> {r.cliente or ''}", _styles['Normal']),
            Paragraph(f"<b>Protocollo:</b> {r.protocollo or ''}", _styles['Normal']),
            Paragraph(f"<b>Ordine/Arrivo:</b> {(r.ordine or '')} / {(r.n_arrivo or '')}", _styles['Normal']),
            Paragraph(f"<b>Cod.Art:</b> {r.codice_articolo or ''}", _styles['Normal']),
            Paragraph(f"<b>Descr.:</b> {(r.descrizione or '')[:120]}", _styles['Normal']),
            Paragraph(f"<b>Colli/Peso:</b> {(r.n_colli or 1)} / {(r.peso or '')}", _styles['Normal']),
        ]
        doc.build(story)
        if i < len(rows)-1:
            pass  # successive pagine nello stesso stream non sono immediate; generiamo singoli file? qui una pagina per output
    bio.seek(0); return send_file(bio, as_attachment=True, download_name='etichette.pdf')

# ------------------- SCARICO + DDT (con impostazioni) -------------------
@app.get('/ddt_setup')
@login_required
def ddt_setup():
    if session.get('role') != 'admin': abort(403)
    ids = request.args.get('ids','')
    if not ids: flash("Seleziona almeno una riga", "warning"); return redirect(url_for('giacenze'))
    destinatari = load_destinatari()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'ddt_setup.html')[0],
                                  ids=ids, destinatari=destinatari, oggi=date.today().isoformat(), logo_url=logo_url())

@app.post('/ddt_setup')
@login_required
def ddt_setup_post():
    if session.get('role') != 'admin': abort(403)
    ids = request.form.get('ids','')
    rows = _get(ids)
    if not rows: flash("Nessuna riga selezionata","warning"); return redirect(url_for('giacenze'))
    dest_key = request.form.get('dest')
    destinatari = load_destinatari().get(dest_key, {})
    tipo_merce = request.form.get('tipo_merce','')
    vettore = request.form.get('vettore','')
    causale = request.form.get('causale','')
    aspetto = request.form.get('aspetto','')
    data_ddt = request.form.get('data_ddt') or date.today().isoformat()
    email_to = request.form.get('email_to','').strip()

    # assegna numero DDT e scarica
    n_ddt = next_ddt_number()
    db=SessionLocal()
    for r in rows:
        r.n_ddt_uscita = n_ddt
        r.data_uscita = data_ddt
    db.commit()

    # PDF DDT con intestazione, destinatario e "firma vettore"
    doc, story, bio = _doc_with_header(f"DDT n. {n_ddt} del {datetime.strptime(data_ddt,'%Y-%m-%d').strftime('%d/%m/%Y')}")
    # intestazione destinatario
    info = [
        ["Destinatario", destinatari.get("ragione_sociale","")],
        ["Indirizzo", destinatari.get("indirizzo","")],
        ["P.IVA", destinatari.get("piva","")],
        ["Vettore", vettore],
        ["Tipologia merce", tipo_merce],
        ["Causale", causale],
        ["Aspetto", aspetto],
        ["Firma vettore", ""],  # spazio per firma
    ]
    story.append(_pdf_table(info, col_widths=[35*mm, None], header=False)); story.append(Spacer(1,6))

    data=[['ID','Cod.Art.','Descrizione','Colli','Peso','Protocollo','Ordine']]
    for r in rows:
        data.append([r.id_articolo, r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.peso or '',
                     r.protocollo or '', r.ordine or ''])
    story.append(_pdf_table(data, col_widths=[15*mm, 25*mm, 80*mm, 15*mm, 20*mm, 30*mm, 25*mm]))
    doc.build(story)
    bio.seek(0)

    # invio e-mail (opzionale)
    if email_to:
        try:
            _send_email(email_to, f"DDT {n_ddt}", "In allegato il DDT.", [("ddt.pdf", bio.getvalue(), "application/pdf")])
            flash(f"DDT inviato a {email_to}", "success")
        except Exception as e:
            flash(f"Invio e-mail fallito: {e}", "warning")

    return send_file(bio, as_attachment=True, download_name=f"DDT_{n_ddt}.pdf")

# ------------------- EMAIL -------------------
def _send_email(to_addr, subject, body, attachments=None):
    host=os.environ.get("SMTP_HOST")
    port=int(os.environ.get("SMTP_PORT","587"))
    user=os.environ.get("SMTP_USER")
    pwd=os.environ.get("SMTP_PASS")
    use_tls=os.environ.get("SMTP_TLS","1") not in ("0","false","False","")
    from_addr=os.environ.get("FROM_EMAIL", user)
    if not (host and from_addr):
        raise RuntimeError("Config SMTP mancante (SMTP_HOST, FROM_EMAIL/SMTP_USER).")
    msg=EmailMessage()
    msg["From"]=from_addr; msg["To"]=to_addr; msg["Subject"]=subject
    msg.set_content(body)
    for name, data, mime in (attachments or []):
        msg.add_attachment(data, maintype=mime.split("/")[0], subtype=mime.split("/")[1], filename=name)
    with smtplib.SMTP(host, port) as s:
        if use_tls: s.starttls()
        if user and pwd: s.login(user, pwd)
        s.send_message(msg)

# ------------------- HEALTH -------------------
@app.get('/health')
def health():
    return {'ok': True}

# ------------------- RUN -------------------
if __name__=='__main__':
    # copia logo se è stato messo in percorso diverso
    if Path(LOGO_PATH).exists() and not (STATIC_DIR/"logo.png").exists():
        try:
            (STATIC_DIR/"logo.png").write_bytes(Path(LOGO_PATH).read_bytes())
        except Exception:
            pass
    port=int(os.environ.get('PORT',8000))
    app.run(host='0.0.0.0', port=port)
