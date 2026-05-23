# -*- coding: utf-8 -*-
"""
Modulo allegati Gestionale Camar.

Contiene:
- pagina documenti/foto articolo
- upload allegati
- apertura file / serve_file
- route /media/<id>
- eliminazione allegati
"""


def register_allegati_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import os
    import uuid
    from urllib.parse import unquote

    ALLEGATI_ARTICOLO_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
            <div>
                <h3 class="mb-1">📎 Documenti e foto articolo #{{ art.id_articolo }}</h3>
                <div class="text-muted small">
                    {{ art.cliente or '' }} · {{ art.codice_articolo or '' }} · {{ art.descrizione or '' }}
                </div>
            </div>
            <div class="d-flex gap-2">
                <a href="{{ url_for('edit_record', id_articolo=art.id_articolo) }}" class="btn btn-primary btn-sm">Modifica articolo</a>
                <a href="{{ url_for('giacenze') }}" class="btn btn-secondary btn-sm">Torna a Giacenze</a>
            </div>
        </div>

        {% if session.get('role') == 'admin' %}
        <div class="card shadow-sm mb-3">
            <div class="card-body">
                <form action="{{ url_for('upload_file', id_articolo=art.id_articolo) }}" method="post" enctype="multipart/form-data" class="row g-2 align-items-end">
                    <div class="col-md-9">
                        <label class="form-label fw-bold">Scatta foto o allega documenti</label>
                        <input type="file" name="file" class="form-control" multiple required
                               accept="image/*,.pdf,.doc,.docx,.xls,.xlsx"
                               capture="environment">
                        <div class="form-text">Da smartphone puoi aprire direttamente la fotocamera. Sono supportati foto, PDF e documenti.</div>
                    </div>
                    <div class="col-md-3 d-grid">
                        <button type="submit" class="btn btn-success fw-bold">📷 Carica / Scatta</button>
                    </div>
                </form>
            </div>
        </div>
        {% endif %}

        <div class="row g-3">
            {% for att in art.attachments %}
            <div class="col-6 col-md-3 col-lg-2">
                <div class="card h-100 shadow-sm">
                    <div class="card-body text-center p-2">
                        {% if att.kind == 'photo' %}
                        <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank">
                            <img src="{{ url_for('serve_uploaded_file', filename=att.filename) }}"
                                 class="img-fluid rounded border"
                                 style="height:150px; width:100%; object-fit:cover;">
                        </a>
                        {% else %}
                        <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank"
                           class="d-flex align-items-center justify-content-center rounded border text-danger text-decoration-none bg-light"
                           style="height:150px; font-size:3rem;">
                            📄
                        </a>
                        {% endif %}
                        <div class="small fw-bold text-truncate mt-2" title="{{ att.filename }}">
                            {{ att.filename.split('_', 2)[-1] }}
                        </div>
                        <div class="btn-group btn-group-sm w-100 mt-2">
                            <a href="{{ url_for('serve_uploaded_file', filename=att.filename) }}" target="_blank" class="btn btn-outline-primary">Apri</a>
                            {% if session.get('role') == 'admin' %}
                            <a href="{{ url_for('delete_attachment', id_attachment=att.id) }}" class="btn btn-outline-danger" onclick="return confirm('Eliminare allegato?')">Elimina</a>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12">
                <div class="alert alert-info">Nessun documento o foto allegato a questo articolo.</div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endblock %}
    """

    @app.route('/articolo/<int:id_articolo>/allegati', methods=['GET'])
    @login_required
    def allegati_articolo(id_articolo):
        db = SessionLocal()
        try:
            art = (
                db.query(Articolo)
                .options(selectinload(Articolo.attachments))
                .filter(Articolo.id_articolo == id_articolo)
                .first()
            )
            if not art:
                flash("Articolo non trovato.", "danger")
                return redirect(url_for('giacenze'))

            cliente_corrente = current_cliente()
            if cliente_corrente and normalize_text_key(art.cliente) != normalize_text_key(cliente_corrente):
                flash("Accesso non consentito a questo articolo.", "danger")
                return redirect(url_for('giacenze'))

            return render_template_string(ALLEGATI_ARTICOLO_HTML, art=art)
        finally:
            db.close()


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
    from urllib.parse import unquote, quote
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


