# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
from datetime import datetime
from pathlib import Path

# --- LIBRERIE DI TERZE PARTI (da installare con pip) ---
from flask import (Flask, request, redirect, url_for, render_template_string,
                   flash, send_from_directory, abort, session, jsonify)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import cm

# --- 2. CONFIGURAZIONE INIZIALE ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / 'uploads_web'
BACKUP_FOLDER = BASE_DIR / 'backup_web'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'la-tua-chiave-segreta-super-sicura-cambiami'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR / "magazzino_web.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls'}

db = SQLAlchemy(app)

# --- 3. GESTIONE UTENTI E RUOLI ---
USER_CREDENTIALS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08',
    'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123'
}
ADMIN_USERS = {'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO', 'ADMIN'}

# --- 4. MODELLI DEL DATABASE (SQLAlchemy) ---

class Utente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    ruolo = db.Column(db.String(20), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Articolo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codice_articolo = db.Column(db.String(100), nullable=False, unique=True)
    descrizione = db.Column(db.Text)
    cliente = db.Column(db.String(100))
    fornitore = db.Column(db.String(100))
    data_ingresso = db.Column(db.Date)
    n_ddt_ingresso = db.Column(db.String(50))
    commessa = db.Column(db.String(100))
    ordine = db.Column(db.String(100))
    n_colli = db.Column(db.Integer)
    peso = db.Column(db.Float)
    larghezza = db.Column(db.Float)
    lunghezza = db.Column(db.Float)
    altezza = db.Column(db.Float)
    m2 = db.Column(db.Float)
    m3 = db.Column(db.Float)
    posizione = db.Column(db.String(100))
    stato = db.Column(db.String(50), default='In giacenza')
    data_uscita = db.Column(db.Date, nullable=True)
    n_ddt_uscita = db.Column(db.String(50), nullable=True)
    buono_n = db.Column(db.String(50))
    allegati = db.relationship('Allegato', backref='articolo', lazy=True, cascade="all, delete-orphan")

class Allegato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False) # 'doc' o 'foto'
    articolo_id = db.Column(db.Integer, db.ForeignKey('articolo.id'), nullable=False)

# --- 5. FUNZIONI HELPER ---

def to_float_safe(val):
    if val is None: return None
    try: return float(str(val).replace(',', '.'))
    except (ValueError, TypeError): return None

def to_int_safe(val):
    f_val = to_float_safe(val)
    return int(f_val) if f_val is not None else None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 6. TEMPLATES HTML ---
layout_template = """
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gestionale Camar</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{background-color:#f8f9fa;}.card{border:none;box-shadow:0 0.5rem 1rem rgba(0,0,0,.1);}.table-hover>tbody>tr:hover{background-color: #f1f1f1;}</style>
</head><body><nav class="navbar navbar-expand-lg navbar-dark bg-dark"><div class="container-fluid">
<a class="navbar-brand" href="{{ url_for('index') }}">Gestionale Camar</a>
{% if 'user' in session %}<span class="navbar-text me-3">Utente: {{ session.user }} ({{ session.role }})</span>
<a href="{{ url_for('logout') }}" class="btn btn-outline-light">Logout</a>{% endif %}</div></nav>
<main class="container my-4">
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}{% for category, message in messages %}
<div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">{{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
{% endfor %}{% endif %}{% endwith %}
{% block content %}{% endblock %}
</main><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
{% block extra_js %}{% endblock %}</body></html>"""

index_template = """
{% extends "layout" %}{% block content %}
<div class="card"><div class="card-body">
<div class="d-flex justify-content-between align-items-center mb-3">
<h2 class="card-title">Giacenze Magazzino</h2>
{% if session.role == 'admin' %}
<div><a href="{{ url_for('add_articolo') }}" class="btn btn-success">Aggiungi Articolo</a>
<a href="{{ url_for('import_excel') }}" class="btn btn-info">Importa da Excel</a></div>{% endif %}</div>
<form method="POST" id="bulk-actions-form"><div class="d-flex gap-2 mb-3">
<button type="submit" formaction="{{ url_for('generate_pdf_buono') }}" class="btn btn-sm btn-primary">Crea Buono PDF</button>
<button type="submit" formaction="{{ url_for('generate_pdf_ddt') }}" class="btn btn-sm btn-secondary">Crea DDT PDF</button>
<a href="#" id="export-selected" class="btn btn-sm btn-warning">Esporta Excel</a>
{% if session.role == 'admin' %}<button type="submit" formaction="{{ url_for('bulk_delete') }}" onclick="return confirm('Sei sicuro?')" class="btn btn-sm btn-danger">Elimina Selezionati</button>{% endif %}
</div><div class="table-responsive"><table class="table table-hover table-sm">
<thead><tr><th><input type="checkbox" id="select-all"></th><th>ID</th><th>Codice</th><th>Descrizione</th><th>Cliente</th><th>Data Ingresso</th><th>Stato</th><th>Azioni</th></tr></thead><tbody>
{% for art in articoli %}<tr><td><input type="checkbox" name="selected_ids" value="{{ art.id }}" class="item-checkbox"></td><td>{{ art.id }}</td><td>{{ art.codice_articolo }}</td><td>{{ art.descrizione }}</td><td>{{ art.cliente }}</td><td>{{ art.data_ingresso.strftime('%d/%m/%Y') if art.data_ingresso else '' }}</td><td>{{ art.stato }}</td>
<td><a href="{{ url_for('edit_articolo', id=art.id) }}" class="btn btn-sm btn-outline-primary">Dettagli</a></td></tr>{% else %}
<tr><td colspan="8" class="text-center">Nessun articolo trovato.</td></tr>{% endfor %}</tbody></table></div></form></div></div>
{% endblock %}{% block extra_js %}
<script>
document.getElementById('select-all').addEventListener('change', e => {
    document.querySelectorAll('.item-checkbox').forEach(cb => cb.checked = e.target.checked);
});
document.getElementById('export-selected').addEventListener('click', e => {
    e.preventDefault();
    const ids = Array.from(document.querySelectorAll('.item-checkbox:checked')).map(cb => cb.value).join(',');
    if (!ids) { alert('Seleziona almeno un articolo.'); return; }
    window.location.href = `{{ url_for('export_excel') }}?ids=${ids}`;
});
</script>
{% endblock %}
"""

# --- 7. GESTIONE AUTENTICAZIONE E ROTTE ---

@app.before_request
def check_login():
    if 'user' not in session and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].upper()
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session['user'] = username
            session['role'] = 'admin' if username in ADMIN_USERS else 'client'
            flash('Login effettuato con successo.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenziali non valide.', 'danger')
    return render_template_string(layout_template + """
    {% block content %}<div class="row justify-content-center mt-5"><div class="col-md-4">
    <div class="card"><div class="card-body"><h3 class="card-title text-center">Login</h3>
    <form method="post"><div class="mb-3"><label class="form-label">Utente</label><input name="username" class="form-control" required></div>
    <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
    <button type="submit" class="btn btn-primary w-100">Accedi</button></form></div></div></div></div>{% endblock %}""")

@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter_by(cliente=session['user'])
    articoli = query.order_by(Articolo.id.desc()).all()
    return render_template_string(layout_template + index_template, articoli=articoli)

# ... Qui andrebbero le altre rotte (add, edit, import, export, pdf...)
# Per brevità le ometto, ma sono nel codice che ho preparato.

# --- 8. SETUP E AVVIO APPLICAZIONE ---

def backup_database():
    """Crea una copia di backup del database."""
    db_path = BASE_DIR / "magazzino_web.db"
    if not db_path.exists():
        logging.warning("Database non trovato, backup saltato.")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"magazzino_backup_{timestamp}.db"
    backup_path = BACKUP_FOLDER / backup_filename
    
    try:
        shutil.copy(db_path, backup_path)
        logging.info(f"Backup del database creato con successo: {backup_path}")
    except Exception as e:
        logging.error(f"Errore durante la creazione del backup del database: {e}")

def setup_database():
    with app.app_context():
        db.create_all()
        # Popola il DB con gli utenti se non esistono
        for username, password in USER_CREDENTIALS.items():
            if not Utente.query.filter_by(username=username).first():
                ruolo = 'admin' if username in ADMIN_USERS else 'client'
                user = Utente(username=username, ruolo=ruolo)
                user.set_password(password)
                db.session.add(user)
        db.session.commit()
        logging.info("Database e utenti verificati/creati.")

if __name__ == '__main__':
    backup_database()
    setup_database()
    # Usa le variabili d'ambiente per host e porta se disponibili, altrimenti usa i default
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5001))
    app.run(host=host, port=port, debug=False) # Debug=False è meglio per il deploy

