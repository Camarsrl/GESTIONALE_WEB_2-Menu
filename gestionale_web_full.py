# -*- coding: utf-8 -*-
import os, io, re, json, uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, render_template_string, redirect, url_for, send_file, session, flash, abort, Blueprint

from sqlalchemy import create_engine, Column, Integer, String, Float, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

# Jinja loader combinato (filesystem + inline)
from jinja2 import ChoiceLoader, FileSystemLoader, DictLoader

APP_DIR = Path(os.environ.get("APP_DIR", "."))
APP_DIR.mkdir(parents=True, exist_ok=True)

MEDIA_DIR = APP_DIR / "media"; DOCS_DIR = MEDIA_DIR / "docs"; PHOTOS_DIR = MEDIA_DIR / "photos"
for d in (DOCS_DIR, PHOTOS_DIR): d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{APP_DIR / 'magazzino.db'}"
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

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
    kind = Column(String(10)) # doc/foto
    filename = Column(String(512))
    articolo = relationship("Articolo", back_populates="attachments")

Base.metadata.create_all(engine)

# --- Utenti e ruoli ---
DEFAULT_USERS = {
    # Clienti
    'DE WAVE': 'Struppa01',
    'FINCANTIERI': 'Struppa02',
    'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04',       # SAN GIORGIO DEL PORTO
    'WINGECO': 'Struppa05',
    'AMICO': 'Struppa06',
    'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08',
    'MARINE INTERIORS':Struppa09,

    # Amministrativi/Interni
    'OPS': '271214',
    'CUSTOMS': 'Balleydier01',
    'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03',
    'ADMIN': 'admin123'
}

# separiamo in due insiemi
CLIENT_USERS = {
    'DE WAVE','FINCANTIERI','DE WAVE REFITTING','SGDP',
    'WINGECO','AMICO','DUFERCO','SCORZA'
}
ADMIN_USERS = {'OPS','CUSTOMS','TAZIO','DIEGO','ADMIN'}

def get_users():
    """Carica utenti da file oppure da DEFAULT_USERS"""
    fp = APP_DIR / "password Utenti Gestionale.txt"
    if fp.exists():
        try:
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(r"'([^']+)'\s*:\s*'([^']+)'", raw)
            m = {k.strip().upper(): v.strip() for k,v in pairs}
            if m: return m
        except Exception:
            pass
    return DEFAULT_USERS

def parse_date_ui(d):
    if not d: return None
    try: return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception: return d

def fmt_date(d):
    if not d: return ""
    try: return datetime.strptime(d,"%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception: return d

def calc_m2_m3(l, w, h, colli):
    def f(x):
        return float(str(x).replace(',','.')) if x not in (None,'') else 0.0
    try:
        l=f(l); w=f(w); h=f(h); colli=int(f(colli) or 1)
    except Exception:
        l=w=h=0.0; colli=1
    return round(colli*l*w,3), round(colli*l*w*h,3)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","dev-secret")
app.jinja_env.globals['getattr'] = getattr
# ---------------- TEMPLATES INLINE ----------------
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
</style></head><body>
<nav class='navbar bg-white shadow-sm'><div class='container-fluid'>
<a class='navbar-brand' href='{{url_for("home")}}'>Camar • Gestionale</a>
<div class='ms-auto'>{% if session.get('user') %}<span class='me-3'>Utente: <b>{{session['user']}}</b></span><a class='btn btn-outline-secondary btn-sm' href='{{url_for("logout")}}'>Logout</a>{% endif %}</div>
</div></nav>
<div class='container my-4'>{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class='alert alert-{{c}} alert-dismissible fade show'>{{t}}<button class='btn-close' data-bs-dismiss='alert'></button></div>{% endfor %}{% endwith %}
{% block content %}{% endblock %}</div>
<script src='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'></script>
</body></html>
"""

LOGIN = """{% extends 'base.html' %}{% block content %}
<div class='row justify-content-center'><div class='col-md-5'><div class='card p-4'>
<h4 class='mb-3'>Login</h4>
<form method='post'><div class='mb-3'><label class='form-label'>Utente</label><input name='user' class='form-control' required></div>
<div class='mb-3'><label class='form-label'>Password</label><input type='password' name='pwd' class='form-control' required></div>
<button class='btn btn-primary'>Entra</button></form></div></div></div>{% endblock %}"""

HOME = """{% extends 'base.html' %}{% block content %}
<div class='row g-3'><div class='col-md-3'><div class='card p-3'>
<h6>Azioni</h6><div class='d-grid gap-2'>
<a class='btn btn-outline-primary' href='{{url_for("giacenze")}}'>Visualizza Giacenze</a>
<a class='btn btn-outline-primary' href='{{url_for("import_excel")}}'>Import da Excel</a>
<a class='btn btn-outline-primary' href='{{url_for("export_excel")}}'>Export Excel</a>
<a class='btn btn-outline-primary' href='{{url_for("export_excel_by_client")}}'>Export per Cliente</a>
</div></div></div>
<div class='col-md-9'><div class='card p-4'>
<h4>Benvenuto</h4><p class='text-muted'>Versione web con multi-upload, stampa da browser, profili import e MySQL opzionale.</p>
</div></div></div>{% endblock %}"""

GIACENZE = """{% extends 'base.html' %}{% block content %}
<div class='card p-3 mb-3'><form class='row g-2' method='get'>
{% for label,name in [('ID(=)','id'),('Cod.Art.(~=)','codice_articolo'),('Descr.(~=)','descrizione'),('Cliente(~=)','cliente'),('Commessa(~=)','commessa'),('Ordine(~=)','ordine'),('N.Arrivo(~=)','n_arrivo'),('Stato(~=)','stato'),('Posizione(~=)','posizione'),('Data Ingr. Da','data_da'),('Data Ingr. A','data_a'),('Buono N(~=)','buono_n')] %}
<div class='col-md-2'><label class='form-label small'>{{label}}</label><input name='{{name}}' value='{{request.args.get(name,"")}}' class='form-control form-control-sm'></div>
{% endfor %}
<div class='col-md-2 d-grid'><button class='btn btn-primary btn-sm mt-4'>Filtra</button></div></form></div>
<div class='card p-3'><div class='d-flex gap-2 mb-2 no-print'>
<form method='post' action='{{url_for("crea_buono_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-b1'><button class='btn btn-outline-secondary btn-sm'>Buono (Stampa)</button></form>
<form method='post' action='{{url_for("crea_ddt_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-d1'><button class='btn btn-outline-secondary btn-sm'>DDT (Stampa)</button></form>
<form method='post' action='{{url_for("crea_etichetta_html")}}' target='_blank'><input type='hidden' name='ids' id='ids-e1'><button class='btn btn-outline-secondary btn-sm'>Etichette (Stampa)</button></form>
</div>
<div class='table-responsive' style='max-height:60vh'><table class='table table-sm table-hover align-middle'>
<thead><tr><th><input type='checkbox' id='checkall'></th>{% for c in cols %}<th>{{c}}</th>{% endfor %}<th>Allegati</th><th>Azione</th></tr></thead>
<tbody>{% for r in rows %}<tr>
<td><input type='checkbox' class='sel' value='{{r.id_articolo}}'></td>
{% for c in cols %}<td>{{getattr(r,c)}}</td>{% endfor %}
<td>{% for a in r.attachments %}<a class='badge text-bg-light' href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.kind}}</a> {% endfor %}</td>
<td><a class='btn btn-sm btn-outline-primary' href='{{url_for("edit_row",id=r.id_articolo)}}'>Modifica</a></td>
</tr>{% endfor %}</tbody></table></div></div>
<script>
const all=document.getElementById('checkall'); all&&all.addEventListener('change',e=>document.querySelectorAll('.sel').forEach(cb=>cb.checked=all.checked));
function setIds(id){const v=[...document.querySelectorAll('.sel:checked')].map(x=>x.value).join(','); document.getElementById(id).value=v;}
['ids-b1','ids-d1','ids-e1'].forEach(n=>{const f=document.getElementById(n)?.closest('form'); f&&f.addEventListener('submit',()=>setIds(n));});
</script>
{% endblock %}"""

EDIT = """{% extends 'base.html' %}{% block content %}
<div class='card p-4'><h5>Modifica Articolo #{{row.id_articolo}}</h5>
<form method='post' enctype='multipart/form-data'><div class='row g-3'>
{% for label,name in fields %}<div class='col-md-4'><label class='form-label'>{{label}}</label><input name='{{name}}' value='{{getattr(row,name,"") or ""}}' class='form-control'></div>{% endfor %}
<div class='col-12'><label class='form-label'>Allega Documenti/Foto</label><div class='dropzone' id='dz'>Trascina qui (o clicca) per caricare più file (PDF, JPG, PNG)</div>
<input type='file' id='fi' name='files' multiple class='form-control mt-2' style='display:none' accept='application/pdf,image/*'></div>
</div><div class='mt-3 d-flex gap-2'><button class='btn btn-primary'>Salva</button><a class='btn btn-secondary' href='{{url_for("giacenze")}}'>Indietro</a></div></form>
<hr><h6>Allegati</h6><ul class='list-group'>{% for a in row.attachments %}<li class='list-group-item d-flex justify-content-between'>
<div><span class='badge text-bg-light me-2'>{{a.kind}}</span><a href='{{url_for("media",att_id=a.id)}}' target='_blank'>{{a.filename}}</a></div>
<a class='btn btn-sm btn-outline-danger' href='{{url_for("delete_attachment",att_id=a.id,back=row.id_articolo)}}'>Elimina</a></li>{% else %}<li class='list-group-item'>Nessun allegato</li>{% endfor %}</ul></div>
<script>
const dz=document.getElementById('dz'),fi=document.getElementById('fi'); dz.addEventListener('click',()=>fi.click());
dz.addEventListener('dragover',e=>{e.preventDefault(); dz.style.opacity=.8}); dz.addEventListener('dragleave',()=>dz.style.opacity=1);
dz.addEventListener('drop',e=>{e.preventDefault(); fi.files=e.dataTransfer.files; dz.style.opacity=1});
</script>
{% endblock %}"""

PRINT_DOC = """<!doctype html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>@media print{.no-print{display:none}}</style></head><body class='p-4'>
<div class='no-print mb-3'><button class='btn btn-primary' onclick='window.print()'>Stampa</button></div>
<h3 class='mb-3'>{{title}}</h3>
<table class='table table-sm table-bordered'><thead><tr>{% for h in headers %}<th>{{h}}</th>{% endfor %}</tr></thead>
<tbody>{% for row in data %}<tr>{% for v in row %}<td>{{v}}</td>{% endfor %}</tr>{% endfor %}</tbody></table></body></html>"""

# ---- Configura Jinja: cartella templates + template inline ----
bp = Blueprint('bp', __name__); app.register_blueprint(bp)
dict_loader = DictLoader({
    'base.html': BASE,
    'login.html': LOGIN,
    'home.html': HOME,
    'giacenze.html': GIACENZE,
    'edit.html': EDIT,
    'print_doc.html': PRINT_DOC
})
app.jinja_loader = ChoiceLoader([FileSystemLoader('templates'), dict_loader])
# ---------------------------------------------------------------

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def w(*a, **k):
        if not session.get('user'): return redirect(url_for('login'))
        return fn(*a, **k)
    return w

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form.get('user','').strip().upper()
        p = request.form.get('pwd','')
        users = get_users()
        if u in users and users[u]==p:
            session['user']=u
            return redirect(url_for('home'))
        flash('Credenziali non valide','danger')
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'login.html')[0])

@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.get('/')
@login_required
def home():
    return render_template_string(app.jinja_loader.get_source(app.jinja_env,'home.html')[0])

def filter_query(qs, args):
    if args.get('id'):
        qs = qs.filter(Articolo.id_articolo == args.get('id'))

    def like(col):
        nonlocal qs
        v = args.get(col)
        if v:
            qs = qs.filter(getattr(Articolo, col).ilike(f"%{v}%"))

    for col in [
        'codice_articolo','descrizione','cliente','commessa','ordine',
        'n_arrivo','stato','posizione','buono_n'
    ]:
        like(col)

    if args.get('data_da'):
        qs = qs.filter(Articolo.data_ingresso >= parse_date_ui(args.get('data_da')))
    if args.get('data_a'):
        qs = qs.filter(Articolo.data_ingresso <= parse_date_ui(args.get('data_a')))

    return qs


@app.get('/giacenze')
@login_required
def giacenze():
    db=SessionLocal()
    rows=filter_query(db.query(Articolo).order_by(Articolo.id_articolo.desc()), request.args).all()
    cols=["id_articolo","cliente","descrizione","peso","n_colli","posizione","n_arrivo","buono_n","stato","data_ingresso","data_uscita","n_ddt_uscita","m2","m3"]
    # >>> PASSO getattr AL TEMPLATE
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env,'giacenze.html')[0],
        rows=rows, cols=cols, getattr=getattr
    )

@app.route('/edit/<int:id>', methods=['GET','POST'])
@login_required
def edit_row(id):
    db=SessionLocal(); row=db.get(Articolo,id)
    if not row: abort(404)
    if request.method=='POST':
        fields=['codice_articolo','pezzo','larghezza','lunghezza','altezza','protocollo','ordine','commessa','magazzino','fornitore','data_ingresso','n_ddt_ingresso','cliente','descrizione','peso','n_colli','posizione','n_arrivo','buono_n','note','serial_number','data_uscita','n_ddt_uscita','ns_rif','stato','mezzi_in_uscita']
        for f in fields:
            v=request.form.get(f) or None
            if f in ('data_ingresso','data_uscita'): v=parse_date_ui(v) if v else None
            setattr(row,f,v)
        m2,m3 = calc_m2_m3(row.lunghezza,row.larghezza,row.altezza,row.n_colli); row.m2, row.m3 = m2, m3
        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if not f or not f.filename: continue
                name=f"{id}_{uuid.uuid4().hex}_{f.filename.replace(' ','_')}"; ext=os.path.splitext(name)[1].lower()
                kind='doc' if ext=='.pdf' else 'foto'; folder = DOCS_DIR if kind=='doc' else PHOTOS_DIR
                f.save(str(folder/name)); db.add(Attachment(articolo_id=id,kind=kind,filename=name))
        db.commit(); flash('Riga aggiornata','success'); return redirect(url_for('giacenze'))
    fields=[('Codice Articolo','codice_articolo'),('Descrizione','descrizione'),('Cliente','cliente'),('Commessa','commessa'),('Ordine','ordine'),('Peso','peso'),('N Colli','n_colli'),('Posizione','posizione'),('Stato','stato'),('N.Arrivo','n_arrivo'),('Buono N','buono_n'),('Protocollo','protocollo'),('Fornitore','fornitore'),('Data Ingresso (GG/MM/AAAA)','data_ingresso'),('Data Uscita (GG/MM/AAAA)','data_uscita'),('N DDT Ingresso','n_ddt_ingresso'),('N DDT Uscita','n_ddt_uscita'),('Larghezza (m)','larghezza'),('Lunghezza (m)','lunghezza'),('Altezza (m)','altezza'),('Serial Number','serial_number'),('NS Rif','ns_rif'),('Mezzi in Uscita','mezzi_in_uscita'),('Note','note')]
    # >>> PASSO getattr AL TEMPLATE
    return render_template_string(
        app.jinja_loader.get_source(app.jinja_env,'edit.html')[0],
        row=row, fields=fields, getattr=getattr
    )

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

# ---------------- Import/Export ----------------
PROFILES_PATH = APP_DIR / "import_profiles.json"
DEFAULT_PROFILE = {
  "codice_articolo": ["Codice Articolo","Cod.Art","codice_articolo"],
  "descrizione": ["Descrizione","descrizione"],
  "cliente": ["Cliente","cliente"],
  "commessa": ["Commessa","commessa"],
  "ordine": ["Ordine","ordine"],
  "peso": ["Peso","peso"],
  "n_colli": ["N Colli","n_colli","Colli"],
  "posizione": ["Posizione","posizione"],
  "n_arrivo": ["N Arrivo","n_arrivo"],
  "buono_n": ["Buono N","buono_n"],
  "protocollo": ["Protocollo","protocollo"],
  "fornitore": ["Fornitore","fornitore"],
  "data_ingresso": ["Data Ingresso","data_ingresso","Data Ingr."]
}
def load_profile():
    if PROFILES_PATH.exists():
        try: return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception: 
            pass
    return {"Generico": DEFAULT_PROFILE}

@app.route('/import', methods=['GET','POST'])
@login_required
def import_excel():
    profiles = load_profile(); selected = request.args.get('profile') or list(profiles.keys())[0]
    if request.method=='POST':
        selected = request.form.get('profile') or selected
        f = request.files.get('file')
        if not f: 
            flash('Seleziona un file','warning'); 
            return redirect(request.url)
        df = pd.read_excel(f).fillna("")
        prof = profiles[selected]
        def getv(row, alts):
            if isinstance(alts,str): alts=[alts]
            for a in alts:
                if a in row: return row[a]
            return ""
        db=SessionLocal()
        for _,row in df.iterrows():
            a=Articolo()
            for k,alts in prof.items():
                v=getv(row,alts); setattr(a,k, v if v!="" else None)
            db.add(a)
        db.commit(); flash('Import completato','success'); return redirect(url_for('giacenze'))
    html = """
    {% extends 'base.html' %}{% block content %}
    <div class='card p-4'><h5>Importa da Excel</h5>
    <form method='post' enctype='multipart/form-data'>
      <div class='row g-3'>
        <div class='col-md-6'><label class='form-label'>File Excel</label><input type='file' name='file' accept='.xlsx,.xlsm' class='form-control' required></div>
        <div class='col-md-6'><label class='form-label'>Profilo</label><select class='form-select' name='profile'>{% for k in profiles.keys() %}<option value='{{k}}' {% if k==selected %}selected{% endif %}>{{k}}</option>{% endfor %}</select></div>
      </div>
      <button class='btn btn-primary mt-3'>Importa</button>
    </form></div>
    {% endblock %}
    """
    return render_template_string(html, profiles=profiles, selected=selected)

@app.get('/export')
@login_required
def export_excel():
    db=SessionLocal(); rows=db.query(Articolo).all()
    df = pd.DataFrame([{k:v for k,v in r.__dict__.items() if not k.startswith('_') and k!='attachments'} for r in rows])
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w:
        df.to_excel(w, index=False, sheet_name='Giacenze')
    bio.seek(0); return send_file(bio, as_attachment=True, download_name='giacenze_export.xlsx')

@app.get('/export_by_client')
@login_required
def export_excel_by_client():
    db=SessionLocal(); client=request.args.get('cliente')
    if not client:
        clients=[c[0] or "Senza Cliente" for c in db.query(Articolo.cliente).distinct().all()]
        html="<h5>Seleziona Cliente</h5><ul>"+"".join([f"<li><a href='{url_for('export_excel_by_client')}?cliente={c}'>{c}</a></li>" for c in clients])+"</ul>"
        return html
    if client=="Senza Cliente":
        rows=db.query(Articolo).filter((Articolo.cliente==None)|(Articolo.cliente=="")).all()
    else:
        rows=db.query(Articolo).filter(Articolo.cliente==client).all()
    df = pd.DataFrame([{k:v for k,v in r.__dict__.items() if not k.startswith('_') and k!='attachments'} for r in rows])
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w:
        df.to_excel(w, index=False, sheet_name=(client[:31] or 'Export'))
    bio.seek(0); return send_file(bio, as_attachment=True, download_name=f'export_{client}.xlsx')

# ---------------- Stampa HTML ----------------
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
    return render_template_string(PRINT, title="Buono Prelievo", headers=hdr, data=data)

@app.post('/crea_ddt_html')
@login_required
def crea_ddt_html():
    rows=_get(request.form.get('ids',''))
    hdr=['ID','Cod.Art.','Descrizione','Colli','Peso','Commessa','Ordine']
    data=[[r.id_articolo, r.codice_articolo or '', r.descrizione or '', r.n_colli or 1, r.peso or '', r.commessa or '', r.ordine or ''] for r in rows]
    return render_template_string(PRINT, title="Documento di Trasporto (DDT)", headers=hdr, data=data)

@app.post('/crea_etichetta_html')
@login_required
def crea_etichetta_html():
    rows=_get(request.form.get('ids',''))
    html=["<!doctype html><html><head><meta charset='utf-8'><style>@media print{.no-print{display:none}} .lbl{border:1px solid #aaa; padding:8px; width:420px; height:260px; margin:6px; float:left; font-family:sans-serif} .k{font-weight:bold}</style></head><body>"]
    html.append("<div class='no-print'><button onclick='window.print()'>Stampa</button></div>")
    for r in rows:
        html.append("<div class='lbl'>")
        html.append(f"<div class='k'>Cliente:</div> {r.cliente or ''}<br>")
        html.append(f"<div class='k'>Commessa:</div> {r.commessa or ''}<br>")
        html.append(f"<div class='k'>Ordine/Arrivo:</div> {(r.ordine or '')} / {(r.n_arrivo or '')}<br>")
        html.append(f"<div class='k'>Cod.Art:</div> {r.codice_articolo or ''}<br>")
        html.append(f"<div class='k'>Descr.:</div> {(r.descrizione or '')[:80]}<br>")
        html.append(f"<div class='k'>Colli/Peso:</div> {(r.n_colli or 1)} / {(r.peso or '')}")
        html.append("</div>")
    html.append("</body></html>")
    return "".join(html)

@app.get('/health')
def health():
    return {'ok':True}

if __name__=='__main__':
    port=int(os.environ.get('PORT',8000))
    app.run(host='0.0.0.0', port=port)

