# -*- coding: utf-8 -*-
"""
Modulo DDT - Step 5.

Sono state spostate qui le route DDT più isolate:
- ddt_finalize
- ddt_mezzo_uscita

Le altre parti collegate al DDT restano ancora nel file principale e verranno spostate
in uno step successivo per evitare errori.
"""

def register_ddt_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    @app.route('/ddt/finalize', methods=['POST'])
    @login_required
    def ddt_finalize():
        import io
        db = SessionLocal()
        try:
            # 1. Recupera ID e Azione
            ids_str = request.form.get('ids', '')
            ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
            action = request.form.get('action', 'preview')

            # ✅ MEZZO IN USCITA (colonna: Mezzo Usc / campo DB: mezzi_in_uscita)
            mezzo_uscita = (request.form.get('mezzi_in_uscita') or '').strip()

            # ✅ obbligatorio SOLO quando finalizzi
            if action == 'finalize' and not mezzo_uscita:
                flash("Seleziona il Mezzo in uscita (Motrice / Bilico / Furgone) prima di finalizzare.", "danger")
                return redirect(url_for('giacenze'))

            # 2. Dati Testata
            n_ddt = request.form.get('n_ddt', '').strip()
            data_ddt_str = request.form.get('data_ddt')

            # ✅ Progressivo DDT: viene salvato SOLO quando si preme "Finalizza"
            # In anteprima mostriamo il prossimo numero senza consumarlo.
            if action == 'finalize':
                try:
                    if (not n_ddt) or (n_ddt == peek_next_ddt_number()):
                        n_ddt = next_ddt_number()
                except Exception:
                    # fallback: se qualcosa va storto, non blocchiamo la finalizzazione
                    if not n_ddt:
                        n_ddt = next_ddt_number()

            # ✅ Se l'utente ha scelto un numero diverso (con le frecce),
            # aggiorniamo comunque il progressivo per evitare riutilizzi futuri.
            if action == 'finalize':
                consume_specific_ddt_number(n_ddt)

            try:
                data_ddt_obj = datetime.strptime(data_ddt_str, "%Y-%m-%d").date()
                data_formatted = data_ddt_obj.strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                data_ddt_obj = date.today()
                data_formatted = date.today().strftime("%d/%m/%Y")
                data_ddt_str = date.today().strftime("%Y-%m-%d")

            # 3. Recupera Destinatario
            # L'utente sceglie esplicitamente quale blocco usare:
            # - saved  = destinatario salvato in rubrica
            # - manual = destinatario occasionale NON salvato
            dest_source = (request.form.get('dest_source') or 'saved').strip().lower()
            dest_key = (request.form.get('dest_key') or '').strip()

            dest_ragione = ''
            dest_indirizzo = ''
            dest_citta = ''

            if dest_source == 'manual':
                dest_ragione = (request.form.get('dest_ragione_manual') or '').strip()
                dest_indirizzo = (request.form.get('dest_indirizzo_manual') or '').strip()
                dest_citta = (request.form.get('dest_citta_manual') or '').strip()

                if not dest_ragione:
                    flash("Inserisci almeno la ragione sociale del destinatario occasionale.", "danger")
                    return redirect(url_for('giacenze'))
            else:
                try:
                    dest_info = load_destinatari().get(dest_key, {}) if dest_key else {}
                    if dest_info:
                        dest_ragione = (dest_info.get('ragione_sociale', '') or '').strip()
                        dest_indirizzo = (dest_info.get('indirizzo', '') or '').strip()
                        dest_citta = (dest_info.get('citta', '') or '').strip()
                except Exception:
                    dest_info = {}

                # fallback per compatibilità con eventuali vecchi campi form
                if not dest_ragione:
                    dest_ragione = (request.form.get('dest_ragione') or '').strip()
                    dest_indirizzo = (request.form.get('dest_indirizzo') or '').strip()
                    dest_citta = (request.form.get('dest_citta') or '').strip()

                if not dest_ragione:
                    flash("Seleziona un destinatario salvato oppure usa il destinatario occasionale.", "danger")
                    return redirect(url_for('giacenze'))

            # 4. Recupera Articoli
            articoli = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            righe_per_pdf = []

            # 5. Loop Articoli
            for art in articoli:
                raw_pezzi = request.form.get(f"pezzi_{art.id_articolo}")
                raw_colli = request.form.get(f"colli_{art.id_articolo}")
                raw_peso = request.form.get(f"peso_{art.id_articolo}")
                nuove_note = request.form.get(f"note_{art.id_articolo}", art.note)

                nuovi_pezzi = to_int_eu(raw_pezzi) if raw_pezzi is not None else art.pezzo
                nuovi_colli = to_int_eu(raw_colli) if raw_colli is not None else art.n_colli
                nuovo_peso = to_float_eu(raw_peso) if raw_peso is not None else art.peso

                # ✅ Se Finalizza -> Salva su DB
                if action == 'finalize':
                    art.data_uscita = data_ddt_obj
                    art.n_ddt_uscita = n_ddt
                    art.mezzi_in_uscita = mezzo_uscita  # ✅ QUI COMPILIAMO "MEZZO USC"
                    if nuove_note is not None:
                        art.note = nuove_note

                # Prepara righe PDF (PDF NON CAMBIA)
                righe_per_pdf.append({
                    'codice_articolo': art.codice_articolo or '',
                    'descrizione': art.descrizione or '',
                    'pezzo': nuovi_pezzi,
                    'n_colli': nuovi_colli,
                    'peso': nuovo_peso,
                    'n_arrivo': art.n_arrivo or '',
                    'note': nuove_note,
                    'commessa': art.commessa,
                    'ordine': art.ordine,
                    'buono': art.buono_n,
                    'protocollo': art.protocollo
                })

            # 6. Salvataggio DB
            if action == 'finalize':
                db.commit()
                flash(f"DDT N.{n_ddt} del {data_formatted} salvato con successo. Mezzo uscita: {mezzo_uscita}", "success")

            # 7. Dati Generali PDF
            ddt_data = {
                'n_ddt': n_ddt,
                'data_uscita': data_formatted,
                'destinatario': dest_ragione,
                'dest_indirizzo': dest_indirizzo,
                'dest_citta': dest_citta,
                'causale': request.form.get('causale', ''),
                'vettore': request.form.get('targa', ''),
                'porto': request.form.get('porto', 'FRANCO'),
                'aspetto': request.form.get('aspetto', 'A VISTA')
            }

            # 8. Genera PDF
            pdf_bio = io.BytesIO()
            _genera_pdf_ddt_file(ddt_data, righe_per_pdf, pdf_bio)
            pdf_bio.seek(0)

            safe_n = n_ddt.replace('/', '-').replace('\\', '-')
            filename = f"DDT_{safe_n}_{data_ddt_str}.pdf"

            return send_file(
                pdf_bio,
                as_attachment=(action == 'finalize'),
                download_name=filename,
                mimetype='application/pdf'
            )

        except Exception as e:
            db.rollback()
            print(f"Errore DDT Finalize: {e}")
            return f"Errore durante la creazione del DDT: {e}", 500
        finally:
            db.close()


    @app.route('/ddt/mezzo_uscita', methods=['GET', 'POST'])
    @login_required
    @require_admin
    def ddt_mezzo_uscita():
        """
        Popup dopo finalizzazione DDT:
        salva la colonna mezzi_in_uscita (Motrice/Bilico/Furgone) sugli articoli selezionati.
        """
        if request.method == 'GET':
            ids_str = (request.args.get('ids') or '').strip()
            n_ddt = (request.args.get('n_ddt') or '').strip()
            return render_template('ddt_mezzo_uscita.html', ids=ids_str, n_ddt=n_ddt)

        # POST
        ids_str = (request.form.get('ids') or '').strip()
        n_ddt = (request.form.get('n_ddt') or '').strip()
        mezzo = (request.form.get('mezzo') or '').strip()

        ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
        if not ids:
            return "ERRORE: nessun articolo selezionato.", 400

        # ✅ obbligatorio e solo valori ammessi
        allowed = {"Motrice", "Bilico", "Furgone"}
        if mezzo not in allowed:
            flash("Seleziona un Mezzo valido (Motrice / Bilico / Furgone).", "danger")
            return redirect(url_for('ddt_mezzo_uscita', ids=ids_str, n_ddt=n_ddt))

        db = SessionLocal()
        try:
            q = db.query(Articolo).filter(Articolo.id_articolo.in_(ids))

            # (consigliato) aggiorna solo righe che hanno quel DDT di uscita
            if n_ddt:
                q = q.filter(Articolo.n_ddt_uscita == n_ddt)

            rows = q.all()

            for art in rows:
                if hasattr(art, "mezzi_in_uscita"):
                    art.mezzi_in_uscita = mezzo
                else:
                    raise Exception("Nel modello Articolo manca la colonna 'mezzi_in_uscita'.")

            db.commit()

            return render_template('ddt_mezzo_uscita_ok.html', mezzo=mezzo, count=len(rows), n_ddt=n_ddt)

        except Exception as e:
            db.rollback()
            return f"Errore salvataggio mezzo in uscita: {e}", 500
        finally:
            db.close()

