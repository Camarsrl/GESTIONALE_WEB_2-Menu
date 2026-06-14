# -*- coding: utf-8 -*-
"""
Modulo Accettazione Entrata da Documento.

Funzioni:
- carica PDF/foto del DDT ingresso
- lettura automatica dei dati tramite testo PDF/OCR già presente
- conferma manuale dei dati
- creazione righe giacenza tipo 770/26 N.1, 770/26 N.2, ...
- allega il documento caricato all'entrata

Nota: se il PDF è una scansione immagine senza testo OCR, il modulo mantiene la modalità manuale:
l'utente compila i dati e crea comunque l'entrata rapida.
"""


def register_accettazione_entrata_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import os
    import re
    import uuid
    import shutil
    from pathlib import Path
    from datetime import date, datetime

    from flask import request, redirect, url_for, flash, render_template_string
    from flask_login import login_required
    from werkzeug.utils import secure_filename
    from sqlalchemy import or_

    ACCETTAZIONE_ENTRATA_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
      <div class="card shadow-sm p-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h3 class="mb-0">📄 Accettazione Entrata da Documento</h3>
            <small class="text-muted">Carica il DDT dell'autista: CAMY prova a leggere i dati e tu confermi prima di creare le righe.</small>
          </div>
          <a href="{{ url_for('labels_form') }}" class="btn btn-outline-secondary btn-sm">Etichetta manuale</a>
        </div>

        <div class="alert alert-info py-2">
          Questa funzione <b>non sostituisce</b> la modalità manuale. Se il documento non viene letto bene, puoi compilare o correggere i campi a mano.
        </div>

        <form method="POST" enctype="multipart/form-data" class="row g-3">
          <input type="hidden" name="step" value="upload">
          <div class="col-md-8">
            <label class="form-label">Documento DDT ingresso / bolla / lettera vettura</label>
            <input type="file" name="documento" class="form-control" accept=".pdf,.jpg,.jpeg,.png" required>
          </div>
          <div class="col-md-4 d-flex align-items-end">
            <button class="btn btn-primary w-100"><i class="bi bi-search"></i> Leggi Documento</button>
          </div>
        </form>
      </div>
    </div>
    {% endblock %}
    """

    ACCETTAZIONE_CONFERMA_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
      <div class="card shadow-sm p-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h3 class="mb-0">✅ Conferma Entrata</h3>
            <small class="text-muted">Controlla i dati letti dal documento e crea le righe in giacenza.</small>
          </div>
          <a href="{{ url_for('accettazione_entrata') }}" class="btn btn-outline-secondary btn-sm">Nuovo documento</a>
        </div>

        {% if not extracted.has_text %}
        <div class="alert alert-warning py-2">
          Non ho trovato testo leggibile nel file. Se è una scansione PDF, il gestionale prova l'OCR automatico: se non legge, controlla le dipendenze su Render. Puoi comunque compilare i campi a mano e confermare l'entrata.<br>
          {% if extracted.ocr_detail %}<small><b>Dettaglio OCR:</b> {{ extracted.ocr_detail }}</small>{% endif %}
        </div>
        {% else %}
        <div class="alert alert-success py-2">
          Documento letto. Verifica i campi prima di confermare.
        </div>
        {% endif %}

        <form method="POST" class="row g-3">
          <input type="hidden" name="step" value="confirm">
          <input type="hidden" name="saved_filename" value="{{ saved_filename }}">
          <input type="hidden" name="original_filename" value="{{ original_filename }}">

          <div class="col-md-3">
            <label class="form-label fw-bold">N. Arrivo *</label>
            <input name="arrivo" class="form-control" placeholder="Es. 50/26" required>
            <small class="text-muted">Verranno create righe tipo 50/26 N.1, 50/26 N.2.</small>
          </div>

          <div class="col-md-3">
            <label class="form-label">Cliente</label>
            <select class="form-select" name="cliente" required>
              <option value="">-- Seleziona cliente --</option>
              {% for c in clienti %}
              <option value="{{ c }}" {% if extracted.cliente and (c|norm_key) == (extracted.cliente|norm_key) %}selected{% endif %}>{{ c }}</option>
              {% endfor %}
            </select>
            {% if extracted.cliente %}<small class="text-muted">Cliente proposto dal documento: {{ extracted.cliente }}</small>{% endif %}
          </div>

          <div class="col-md-3">
            <label class="form-label">Fornitore</label>
            <input name="fornitore" class="form-control" value="{{ extracted.fornitore }}">
          </div>

          <div class="col-md-3">
            <label class="form-label">DDT ingresso / Bolla</label>
            <input name="ddt_ingresso" class="form-control" value="{{ extracted.ddt_ingresso }}">
          </div>

          <div class="col-md-3">
            <label class="form-label">Data ingresso</label>
            <input name="data_ingresso" class="form-control" value="{{ extracted.data_ingresso or today_ita }}" placeholder="gg/mm/aaaa">
          </div>

          <div class="col-md-2">
            <label class="form-label fw-bold">Colli *</label>
            <input name="n_colli" class="form-control" value="{{ extracted.colli or 1 }}" required>
          </div>

          <div class="col-md-2">
            <label class="form-label">Peso kg</label>
            <input name="peso" class="form-control" value="{{ extracted.peso_lordo or extracted.peso_netto }}">
          </div>

          <div class="col-md-2">
            <label class="form-label">Magazzino</label>
            <input name="magazzino" class="form-control" value="STRUPPA">
          </div>

          <div class="col-md-2">
            <label class="form-label">Stato</label>
            <input name="stato" class="form-control" value="DA COMPLETARE">
          </div>

          <div class="col-md-6">
            <label class="form-label">Posizione</label>
            <input name="posizione" class="form-control" placeholder="facoltativa">
          </div>

          <div class="col-md-6">
            <label class="form-label">Note</label>
            <input name="note" class="form-control" value="Documento caricato da accettazione entrata">
          </div>

          <div class="col-12 alert alert-light border small">
            <b>Campi lasciati vuoti apposta:</b> codice articolo, descrizione, protocollo, foto. Li completerai dopo dall'entrata o dalle giacenze.
          </div>

          <div class="col-12 d-flex gap-2 flex-wrap">
            <button class="btn btn-success"><i class="bi bi-box-arrow-in-down"></i> Crea Entrata Rapida</button>
            <a href="{{ url_for('labels_form') }}" class="btn btn-outline-primary">Vai a Etichetta Manuale</a>
          </div>
        </form>

        {% if extracted.preview_text %}
        <details class="mt-4">
          <summary>Testo letto dal documento</summary>
          <pre class="small bg-light border rounded p-2" style="max-height:280px; overflow:auto; white-space:pre-wrap;">{{ extracted.preview_text }}</pre>
        </details>
        {% endif %}
      </div>
    </div>
    {% endblock %}
    """

    def _safe_to_float_it(value):
        try:
            s = str(value or '').strip()
            if not s:
                return 0.0
            if ',' in s:
                s = s.replace('.', '').replace(',', '.')
            return float(s)
        except Exception:
            return 0.0

    def _safe_to_int(value, default=1):
        try:
            s = str(value or '').strip()
            if not s:
                return default
            s = re.sub(r'[^0-9]', '', s)
            return int(s) if s else default
        except Exception:
            return default

    def _fmt_date_ita(value):
        if not value:
            return ''
        s = str(value).strip()
        for fmt in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y'):
            try:
                return datetime.strptime(s, fmt).strftime('%d/%m/%Y')
            except Exception:
                pass
        return s

    def _ocr_image_with_tesseract(image):
        """OCR leggero su immagine PIL.
        Importante su Render Free: limitiamo dimensione e tempo per evitare SIGKILL/timeout.
        """
        try:
            import pytesseract
            from PIL import ImageOps

            # Riduce il peso dell'immagine prima dell'OCR.
            try:
                image = ImageOps.grayscale(image)
                max_w, max_h = 1500, 2100
                image.thumbnail((max_w, max_h))
            except Exception:
                pass

            config = '--oem 1 --psm 6'
            # Timeout breve: se una pagina è troppo pesante, non blocca tutto il servizio.
            try:
                return pytesseract.image_to_string(image, lang='ita+eng', config=config, timeout=18) or ''
            except Exception:
                return pytesseract.image_to_string(image, lang='eng', config=config, timeout=18) or ''
        except Exception as e:
            raise RuntimeError(f"Tesseract OCR non disponibile o troppo lento: {e}")

    def _ocr_pdf_with_fitz(path, max_pages=1):
        """OCR PDF scansionato usando PyMuPDF/fitz per trasformare le pagine in immagini."""
        try:
            import fitz
            from PIL import Image
            import io
            out = []
            doc = fitz.open(str(path))
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes('png')))
                out.append(_ocr_image_with_tesseract(img))
            return '\n'.join(out).strip()
        except Exception as e:
            raise RuntimeError(f"PyMuPDF/fitz: {e}")

    def _ocr_pdf_with_pypdfium2(path, max_pages=1):
        """OCR PDF scansionato usando pypdfium2, più facile da usare su Render."""
        try:
            import pypdfium2 as pdfium
            out = []
            pdf = pdfium.PdfDocument(str(path))
            n = min(len(pdf), max_pages)
            for i in range(n):
                page = pdf[i]
                bitmap = page.render(scale=1.35).to_pil()
                out.append(_ocr_image_with_tesseract(bitmap))
            return '\n'.join(out).strip()
        except Exception as e:
            raise RuntimeError(f"pypdfium2: {e}")

    def _ocr_pdf_with_pdf2image(path, max_pages=1):
        """OCR PDF scansionato usando pdf2image/poppler."""
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(path), dpi=140, first_page=1, last_page=max_pages)
            out = []
            for img in images:
                out.append(_ocr_image_with_tesseract(img))
            return '\n'.join(out).strip()
        except Exception as e:
            raise RuntimeError(f"pdf2image/poppler: {e}")

    def _ocr_image_file(path):
        try:
            from PIL import Image
            img = Image.open(path)
            return _ocr_image_with_tesseract(img).strip()
        except Exception as e:
            raise RuntimeError(f"OCR immagine: {e}")

    def _extract_pdf_text(path):
        """Legge testo da PDF normale; se è scansione, prova OCR automatico."""
        path = Path(path)
        text = ''
        detail = []

        # 1) PDF con testo incorporato
        try:
            if str(path).lower().endswith('.pdf'):
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    parts = []
                    for p in pdf.pages:
                        try:
                            parts.append(p.extract_text() or '')
                        except Exception:
                            parts.append('')
                    text = '\n'.join(parts).strip()
        except Exception as e:
            detail.append(f"pdfplumber: {e}")

        if text and len(text.strip()) >= 25:
            return text, 'Testo PDF letto senza OCR.'

        # 2) PDF scansionato: OCR
        if str(path).lower().endswith('.pdf'):
            for func in (_ocr_pdf_with_pypdfium2, _ocr_pdf_with_fitz, _ocr_pdf_with_pdf2image):
                try:
                    ocr_text = func(path)
                    if ocr_text and len(ocr_text.strip()) >= 25:
                        return ocr_text, f"OCR riuscito con {func.__name__.replace('_ocr_pdf_with_', '')}."
                except Exception as e:
                    detail.append(str(e))
        else:
            # 3) foto JPG/PNG
            try:
                ocr_text = _ocr_image_file(path)
                if ocr_text and len(ocr_text.strip()) >= 25:
                    return ocr_text, 'OCR riuscito su immagine.'
            except Exception as e:
                detail.append(str(e))

        return text or '', ' | '.join(detail) if detail else 'Nessun testo rilevato.'

    def _first_match(text, patterns, flags=re.I | re.M):
        for pat in patterns:
            m = re.search(pat, text or '', flags)
            if m:
                return (m.group(1) or '').strip()
        return ''

    def _extract_arrival_fields(text):
        clean = text or ''
        one = re.sub(r'[ \t]+', ' ', clean)

        ddt = _first_match(one, [
            r'DDT\s*[:nN°\.]*\s*([A-Z0-9\-/]+)',
            r'DOCUMENTO\s+DI\s+TRASPORTO.*?DDT\s*n[°\.]*\s*([A-Z0-9\-/]+)',
            r'Numero\s+Bolla\s+Data\s+Bolla\s+([A-Z0-9\-/]+)',
            r'Numero\s+Bolla\s*\n?\s*([A-Z0-9\-/]+)',
            r'n\.\s*ddt\.\s*cliente\s*[:\s]+([A-Z0-9\-/]+)',
        ])

        data = _first_match(one, [
            r'Data\s+Bolla\s+([0-9]{2}/[0-9]{2}/[0-9]{4})',
            r'DDT\s*n[°\.]*\s*[A-Z0-9\-/]+\s+Data\s*[:\s]+([0-9]{2}/[0-9]{2}/[0-9]{4})',
            r'data\s+ddt\.\s+cliente\s*[:\s]+([0-9]{2}/[0-9]{2}/[0-9]{4})',
            r'Data\s+Bolla\s*\n?\s*([0-9]{2}/[0-9]{2}/[0-9]{4})',
            r'DATA\s*[:\s]+([0-9]{2}/[0-9]{2}/[0-9]{2,4})',
        ])

        colli = _first_match(one, [
            r'Totale\s+colli\s+([0-9]{1,5})',
            r'N[°\.]*\s*colli\s*[:\s]+0*([0-9]{1,5})',
            r'\bColli\s+Peso\s*\(kg\).*?\b([0-9]{1,5})\s+[0-9]+(?:[,.][0-9]+)?',
            r'\bBancali\s+Colli\s+Peso.*?\b[0-9]+\s+([0-9]{1,5})\s+[0-9]+',
        ])

        peso_lordo = _first_match(one, [
            r'Peso\s+lordo\s*[:\s]+([0-9\.]+,[0-9]+|[0-9]+)',
            r'Peso\s*\(kg\).*?\b[0-9]+\s+[0-9]+\s+([0-9]+(?:[,.][0-9]+)?)',
        ])
        peso_netto = _first_match(one, [
            r'Peso\s+netto\s*[:\s]+([0-9\.]+,[0-9]+|[0-9]+)',
            r'Peso\s+netto\s+Peso\s+lordo\s+([0-9\.]+,[0-9]+|[0-9]+)',
        ])

        # Riconoscimento semplice dei fornitori più comuni nei documenti caricati.
        upper = one.upper()
        fornitore = ''
        if 'ATOTECH' in upper:
            fornitore = 'ATOTECH ITALIA SRL'
        elif 'CEIA' in upper or 'COSTRUZIONI ELETTRONICHE INDUSTRIALI AUTOMATISMI' in upper:
            fornitore = 'CEIA S.p.A.'
        else:
            fornitore = _first_match(one, [
                r'Merce\s+di\s+propriet[aà]\s+di\s+(.+?)(?:\s+Via|\n)',
                r'Mittente\s+(.+?)(?:\s+Via|\n)',
            ])

        cliente = ''
        if 'FINCANTIERI' in upper:
            cliente = 'FINCANTIERI'
        elif 'COTUGNO GALVANOTECNICA' in upper:
            cliente = 'COTUGNO GALVANOTECNICA'
        else:
            cliente = _first_match(one, [
                r'Destinatario\s+merci\s+(.+?)(?:\s+VIA|\n)',
                r'Destinatario\s+(.+?)(?:\s+VIA|\n)',
            ])

        return {
            'has_text': bool(clean.strip()),
            'ddt_ingresso': ddt,
            'data_ingresso': _fmt_date_ita(data),
            'colli': colli,
            'peso_lordo': peso_lordo,
            'peso_netto': peso_netto,
            'fornitore': fornitore,
            'cliente': cliente,
            'preview_text': clean[:5000],
            'ocr_detail': '',
        }

    def _copy_to_docs(file_storage):
        original = secure_filename(file_storage.filename or 'documento.pdf')
        ext = Path(original).suffix.lower() or '.pdf'
        saved = f"accettazione_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        out = DOCS_DIR / saved
        file_storage.save(out)
        return saved, original, out

    @app.route('/accettazione_entrata', methods=['GET', 'POST'])
    @login_required
    def accettazione_entrata():
        if session.get('role') not in ('admin', 'magazzino'):
            flash('Accesso negato.', 'danger')
            return redirect(url_for('giacenze'))

        clienti = []
        db = SessionLocal()
        try:
            try:
                clienti_db = [x[0] for x in db.query(Articolo.cliente).distinct().filter(Articolo.cliente != None, Articolo.cliente != '').all()]
                clienti = sorted(set(clienti_db + get_clienti_utenti()))
            except Exception:
                clienti = []
        finally:
            db.close()

        if request.method == 'GET':
            return render_template_string(ACCETTAZIONE_ENTRATA_HTML)

        step = (request.form.get('step') or 'upload').strip()

        if step == 'upload':
            f = request.files.get('documento')
            if not f or not (f.filename or '').strip():
                flash('Carica un documento prima di continuare.', 'warning')
                return redirect(url_for('accettazione_entrata'))
            try:
                saved_filename, original_filename, saved_path = _copy_to_docs(f)
                text, ocr_detail = _extract_pdf_text(saved_path)
                extracted = _extract_arrival_fields(text)
                extracted['ocr_detail'] = ocr_detail
                return render_template_string(
                    ACCETTAZIONE_CONFERMA_HTML,
                    extracted=extracted,
                    saved_filename=saved_filename,
                    original_filename=original_filename,
                    clienti=clienti,
                    today_ita=date.today().strftime('%d/%m/%Y')
                )
            except Exception as e:
                flash(f'Errore lettura documento: {e}', 'danger')
                return redirect(url_for('accettazione_entrata'))

        # Conferma creazione righe
        db = SessionLocal()
        try:
            arrivo_base = strip_arrivo_progressivo(request.form.get('arrivo'))
            if not arrivo_base:
                flash('Inserisci il N. Arrivo.', 'warning')
                return redirect(url_for('accettazione_entrata'))

            cliente_value = request.form.get('cliente')
            try:
                cliente_value = validate_cliente_or_raise(cliente_value)
            except Exception:
                cliente_value = (cliente_value or '').strip().upper()

            totale_colli = max(1, _safe_to_int(request.form.get('n_colli'), 1))
            data_ingresso = (parse_date_ui(request.form.get('data_ingresso')) or date.today()).strftime('%Y-%m-%d')
            ddt_ingresso = (request.form.get('ddt_ingresso') or '').strip()
            codice_entrata = ensure_codice_entrata(
                None,
                n_arrivo=arrivo_base,
                n_ddt=ddt_ingresso,
                data_ingresso=data_ingresso,
                cliente=cliente_value,
            )

            existing = db.query(Articolo).filter(Articolo.codice_entrata == codice_entrata).all()
            if existing:
                flash(f'Entrata già presente: {codice_entrata}. Non ho creato duplicati.', 'warning')
                return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))

            peso_tot = _safe_to_float_it(request.form.get('peso'))
            peso_per_collo = round(peso_tot / totale_colli, 3) if peso_tot and totale_colli else 0.0
            created = []

            for idx in range(1, totale_colli + 1):
                art = Articolo()
                art.codice_articolo = ''
                art.descrizione = ''
                art.cliente = cliente_value
                art.fornitore = (request.form.get('fornitore') or '').strip()
                art.magazzino = (request.form.get('magazzino') or 'STRUPPA').strip().upper()
                art.protocollo = ''
                art.ordine = ''
                art.commessa = ''
                art.buono_n = ''
                art.n_arrivo = build_arrivo_progressivo(arrivo_base, idx)
                art.ns_rif = ''
                art.serial_number = ''
                art.pezzo = ''
                art.n_colli = 1
                art.peso = peso_per_collo
                art.larghezza = 0.0
                art.lunghezza = 0.0
                art.altezza = 0.0
                art.m2 = 0.0
                art.m3 = 0.0
                art.posizione = (request.form.get('posizione') or '').strip()
                art.stato = (request.form.get('stato') or 'DA COMPLETARE').strip().upper()
                art.note = (request.form.get('note') or '').strip()
                art.mezzi_in_uscita = ''
                art.data_ingresso = data_ingresso
                art.n_ddt_ingresso = ddt_ingresso
                art.data_uscita = ''
                art.n_ddt_uscita = ''
                art.codice_entrata = codice_entrata
                if hasattr(art, 'lotto'):
                    art.lotto = ''
                db.add(art)
                created.append(art)

            db.flush()

            saved_filename = (request.form.get('saved_filename') or '').strip()
            if saved_filename:
                for art in created:
                    try:
                        db.add(Attachment(articolo_id=art.id_articolo, kind='doc', filename=saved_filename))
                    except Exception:
                        pass

            db.commit()
            flash(f'Entrata creata: {len(created)} righe generate da {arrivo_base} N.1 a N.{len(created)}. Documento allegato.', 'success')
            return redirect(url_for('dettaglio_entrata', codice_entrata=codice_entrata))

        except Exception as e:
            db.rollback()
            flash(f'Errore creazione entrata: {e}', 'danger')
            return redirect(url_for('accettazione_entrata'))
        finally:
            db.close()
