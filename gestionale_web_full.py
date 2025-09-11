# -*- coding: utf-8 -*-

# --- 1. IMPORT LIBRERIE ---
import os
import shutil
import json
import logging
from datetime import datetime, date
from pathlib import Path
import io

# --- LIBRERIE DI TERZE PARTI ---
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

DATA_DIR = Path(os.environ.get('RENDER_DISK_PATH', '.'))
UPLOAD_FOLDER = DATA_DIR / 'uploads_web'
BACKUP_FOLDER = DATA_DIR / 'backup_web'
CONFIG_FOLDER = DATA_DIR / 'config'

for folder in [UPLOAD_FOLDER, BACKUP_FOLDER, CONFIG_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-that-is-very-long')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATA_DIR / "magazzino_web.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'xls'}

db = SQLAlchemy(app)

# --- 3. GESTIONE UTENTI E RUOLI ---
USER_CREDENTIALS = {
    'DE WAVE': 'Struppa01', 'FINCANTIERI': 'Struppa02', 'DE WAVE REFITTING': 'Struppa03',
    'SGDP': 'Struppa04', 'WINGECO': 'Struppa05', 'AMICO': 'Struppa06', 'DUFERCO': 'Struppa07',
    'SCORZA': 'Struppa08', 'OPS': '271214', 'CUSTOMS': 'Balleydier01', 'TAZIO': 'Balleydier02',
    'DIEGO': 'Balleydier03', 'ADMIN': 'admin123'
}
ADMIN_USERS = {'OPS', 'CUSTOMS', 'TAZIO', 'DIEGO', 'ADMIN'}

# --- 4. MODELLI DEL DATABASE ---
class Utente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    ruolo = db.Column(db.String(20), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

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
    if not date_string: return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try: return datetime.strptime(date_string, fmt).date()
        except (ValueError, TypeError): continue
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
def calculate_m2_m3(form_data):
    l = to_float_safe(form_data.get('lunghezza', 0)) or 0
    w = to_float_safe(form_data.get('larghezza', 0)) or 0
    h = to_float_safe(form_data.get('altezza', 0)) or 0
    c = to_int_safe(form_data.get('n_colli', 1)) or 1
    m2 = round(l * w * c, 3)
    m3 = round(l * w * h * c, 3)
    return m2, m3

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

def populate_articolo_from_form(articolo, form):
    articolo.codice_articolo = form.get('codice_articolo')
    articolo.descrizione = form.get('descrizione')
    articolo.cliente = form.get('cliente')
    articolo.fornitore = form.get('fornitore')
    articolo.data_ingresso = parse_date_safe(form.get('data_ingresso'))
    articolo.n_ddt_ingresso = form.get('n_ddt_ingresso')
    articolo.commessa = form.get('commessa')
    articolo.ordine = form.get('ordine')
    articolo.n_colli = to_int_safe(form.get('n_colli'))
    articolo.peso = to_float_safe(form.get('peso'))
    articolo.larghezza = to_float_safe(form.get('larghezza'))
    articolo.lunghezza = to_float_safe(form.get('lunghezza'))
    articolo.altezza = to_float_safe(form.get('altezza'))
    articolo.m2, articolo.m3 = calculate_m2_m3(form)
    articolo.posizione = form.get('posizione')
    articolo.stato = form.get('stato')
    articolo.note = form.get('note')
    articolo.pezzo = form.get('pezzo')
    articolo.protocollo = form.get('protocollo')
    articolo.serial_number = form.get('serial_number')
    articolo.n_arrivo = form.get('n_arrivo')
    articolo.ns_rif = form.get('ns_rif')
    articolo.mezzi_in_uscita = form.get('mezzi_in_uscita')
    articolo.buono_n = form.get('buono_n')
    articolo.data_uscita = parse_date_safe(form.get('data_uscita'))
    articolo.n_ddt_uscita = form.get('n_ddt_uscita')
    return articolo

@app.route('/articolo/nuovo', methods=['GET', 'POST'])
def add_articolo():
    if session.get('role') != 'admin': abort(403)
    if request.method == 'POST':
        nuovo_articolo = Articolo()
        populate_articolo_from_form(nuovo_articolo, request.form)
        db.session.add(nuovo_articolo)
        db.session.commit()
        flash('Articolo aggiunto con successo!', 'success')
        return redirect(url_for('edit_articolo', id=nuovo_articolo.id))
    return render_template('edit.html', articolo=None, title="Aggiungi Articolo")

@app.route('/articolo/<int:id>/modifica', methods=['GET', 'POST'])
def edit_articolo(id):
    articolo = Articolo.query.get_or_404(id)
    if session.get('role') == 'client' and session.get('user') != articolo.cliente: abort(403)

    if request.method == 'POST':
        if session.get('role') != 'admin': abort(403)
        populate_articolo_from_form(articolo, request.form)
        
        # Gestione allegati
        files = request.files.getlist('files')
        for file in files:
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"{articolo.id}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                ext = filename.rsplit('.', 1)[1].lower()
                tipo = 'doc' if ext == 'pdf' else 'foto'
                allegato = Allegato(filename=filename, tipo=tipo, articolo_id=articolo.id)
                db.session.add(allegato)

        db.session.commit()
        flash('Articolo aggiornato con successo!', 'success')
        return redirect(url_for('edit_articolo', id=id))
        
    return render_template('edit.html', articolo=articolo, title="Modifica Articolo")

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/allegato/<int:id>/elimina', methods=['POST'])
def delete_attachment(id):
    if session.get('role') != 'admin': abort(403)
    allegato = Allegato.query.get_or_404(id)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], allegato.filename))
    except OSError:
        pass # File non trovato, ma lo rimuoviamo dal DB comunque
    db.session.delete(allegato)
    db.session.commit()
    flash('Allegato eliminato.', 'success')
    return redirect(url_for('edit_articolo', id=allegato.articolo_id))

# ... (Altre rotte verranno aggiunte qui)

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



