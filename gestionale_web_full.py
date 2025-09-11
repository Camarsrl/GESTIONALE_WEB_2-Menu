# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
from datetime import datetime, date
from pathlib import Path
import io

# --- LIBRERIE DI TERZE PARTI (da installare con pip) ---
from flask import (Flask, request, redirect, url_for, render_template,
                   flash, send_from_directory, abort, session, jsonify, send_file)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
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

# Percorso per i dati persistenti (funziona sia localmente che su Render)
DATA_DIR = Path(os.environ.get('RENDER_DISK_PATH', '.'))
UPLOAD_FOLDER = DATA_DIR / 'uploads_web'
BACKUP_FOLDER = DATA_DIR / 'backup_web'
CONFIG_FOLDER = DATA_DIR / 'config'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(CONFIG_FOLDER, exist_ok=True)


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-it')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATA_DIR / "magazzino_web.db"}'
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
    codice_articolo = db.Column(db.String(100))
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
    pezzo = db.Column(db.String(100))
    protocollo = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    n_arrivo = db.Column(db.String(100))
    ns_rif = db.Column(db.String(100))
    mezzi_in_uscita = db.Column(db.String(100))
    note = db.Column(db.Text)
    allegati = db.relationship('Allegato', backref='articolo', lazy=True, cascade="all, delete-orphan")

class Allegato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    articolo_id = db.Column(db.Integer, db.ForeignKey('articolo.id'), nullable=False)

# --- 5. FUNZIONI HELPER ---
def to_float_safe(val):
    if val is None: return None
    try: return float(str(val).replace(',', '.'))
    except (ValueError, TypeError): return None

def to_int_safe(val):
    f_val = to_float_safe(val)
    return int(f_val) if f_val is not None else None
    
def parse_date_safe(date_string):
    if not date_string:
        return None
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 6. ROTTE DELL'APPLICAZIONE ---
@app.before_request
def check_login():
    if 'user' not in session and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].upper().strip()
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session['user'] = username
            session['role'] = 'admin' if username in ADMIN_USERS else 'client'
            flash('Login effettuato con successo.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenziali non valide.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    query = Articolo.query
    if session.get('role') == 'client':
        query = query.filter(Articolo.cliente.ilike(session['user']))
    articoli = query.order_by(Articolo.id.desc()).all()
    return render_template('index.html', articoli=articoli)

@app.route('/articolo/nuovo', methods=['GET', 'POST'])
def add_articolo():
    if session.get('role') != 'admin': abort(403)
    if request.method == 'POST':
        # Logica per aggiungere un nuovo articolo
        data_ingresso = parse_date_safe(request.form.get('data_ingresso'))
        
        m2, m3 = 0,0 # Logica calcolo M2/M3
        
        nuovo_articolo = Articolo(
            codice_articolo=request.form.get('codice_articolo'),
            descrizione=request.form.get('descrizione'),
            cliente=request.form.get('cliente'),
            fornitore=request.form.get('fornitore'),
            data_ingresso=data_ingresso,
            n_ddt_ingresso=request.form.get('n_ddt_ingresso'),
            commessa=request.form.get('commessa'),
            ordine=request.form.get('ordine'),
            n_colli=to_int_safe(request.form.get('n_colli')),
            peso=to_float_safe(request.form.get('peso')),
            larghezza=to_float_safe(request.form.get('larghezza')),
            lunghezza=to_float_safe(request.form.get('lunghezza')),
            altezza=to_float_safe(request.form.get('altezza')),
            m2=m2, m3=m3,
            posizione=request.form.get('posizione'),
            stato=request.form.get('stato', 'In giacenza'),
            note=request.form.get('note')
        )
        db.session.add(nuovo_articolo)
        db.session.commit()
        flash('Articolo aggiunto con successo!', 'success')
        return redirect(url_for('index'))
    return render_template('edit.html', articolo=None, title="Aggiungi Articolo")

@app.route('/articolo/<int:id>/modifica', methods=['GET', 'POST'])
def edit_articolo(id):
    articolo = Articolo.query.get_or_404(id)
    if session.get('role') == 'client' and session.get('user') != articolo.cliente:
        abort(403)

    if request.method == 'POST':
        if session.get('role') != 'admin': abort(403)
        # Logica per modificare l'articolo
        articolo.codice_articolo=request.form.get('codice_articolo')
        #... (aggiorna tutti gli altri campi)
        db.session.commit()
        flash('Articolo aggiornato con successo!', 'success')
        return redirect(url_for('index'))
        
    return render_template('edit.html', articolo=articolo, title="Modifica Articolo")

# Altre rotte (import/export/pdf) qui...

# --- 7. SETUP E AVVIO APPLICAZIONE ---
def backup_database():
    db_path = DATA_DIR / "magazzino_web.db"
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
        for username, password in USER_CREDENTIALS.items():
            if not Utente.query.filter_by(username=username).first():
                ruolo = 'admin' if username in ADMIN_USERS else 'client'
                user = Utente(username=username, ruolo=ruolo)
                user.set_password(password)
                db.session.add(user)
        db.session.commit()
        logging.info("Database e utenti verificati/creati.")

if __name__ == '__main__':
    with app.app_context():
        backup_database()
        setup_database()
    
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)

