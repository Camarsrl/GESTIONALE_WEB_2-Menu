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

            # ✅ CAMPI SEPARATI:
            # - mezzo_giacenze / mezzi_in_uscita: compila Articolo.mezzi_in_uscita nelle Giacenze
            # - mezzo_trasporti / tipo_mezzo_trasporto: compila Trasporto.tipo_mezzo nella funzione Trasporti
            mezzo_giacenze = (
                request.form.get('mezzo_giacenze')
                or request.form.get('mezzi_in_uscita')
                or ''
            ).strip()
            mezzo_trasporti = (
                request.form.get('mezzo_trasporti')
                or request.form.get('tipo_mezzo_trasporto')
                or request.form.get('tipo_mezzo')
                or ''
            ).strip()
            trasportatore_interno = (request.form.get('trasportatore_interno') or '').strip()
            note_viaggio = (request.form.get('note_viaggio') or '').strip()

            # ✅ COSTO TRASPORTO INTERNO
            # Campo da aggiungere nella schermata DDT con name="costo_trasporto".
            # Compatibilità: accetta anche name="costo" o name="costo_viaggio" se già presenti in template.
            costo_trasporto_raw = (
                request.form.get('costo_trasporto')
                or request.form.get('costo')
                or request.form.get('costo_viaggio')
                or ''
            ).strip()

            def _to_float_costo(value):
                s = str(value or '').strip().replace('€', '').replace(' ', '')
                if not s:
                    return None
                try:
                    if ',' in s and '.' in s:
                        # esempio 1.200,50
                        s = s.replace('.', '').replace(',', '.')
                    else:
                        s = s.replace(',', '.')
                    return float(s)
                except Exception:
                    return None

            costo_trasporto = _to_float_costo(costo_trasporto_raw)

            # ✅ Mezzo giacenze / Trasporti obbligatori SOLO per clienti Fincantieri.
            # Per tutti gli altri clienti non vengono compilati né la colonna mezzo nelle Giacenze
            # né la funzione Trasporti, salvo futura scelta diversa.
            CLIENTI_MEZZO_OBBLIGATORIO = {'FINCANTIERI', 'FINCANTIERI SCOPERTO', 'FINCANTIERI ARMATORE', 'MARINE INTERIORS', 'DE WAVE SAMA'}
            skip_mezzi_trasporti = (request.form.get('skip_mezzi_trasporti') or '').strip() == '1'

            def _cliente_norm_ddt(value):
                return re.sub(r'\s+', ' ', str(value or '').strip().upper())

            # 2. Dati Testata
            n_ddt = request.form.get('n_ddt', '').strip()
            data_ddt_str = request.form.get('data_ddt')

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
                dest_ragione = (
                    request.form.get('dest_ragione_manual')
                    or request.form.get('manual_ragione')
                    or request.form.get('dest_ragione_occasionale')
                    or request.form.get('ragione_sociale_occasionale')
                    or ''
                ).strip()
                dest_indirizzo = (
                    request.form.get('dest_indirizzo_manual')
                    or request.form.get('manual_indirizzo')
                    or request.form.get('dest_indirizzo_occasionale')
                    or request.form.get('indirizzo_occasionale')
                    or ''
                ).strip()
                dest_citta = (
                    request.form.get('dest_citta_manual')
                    or request.form.get('manual_citta')
                    or request.form.get('dest_citta_occasionale')
                    or request.form.get('citta_occasionale')
                    or ''
                ).strip()

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
            if not articoli:
                flash("⚠️ Nessun articolo selezionato per il DDT. Torna alle Giacenze e seleziona almeno una riga.", "warning")
                return redirect(url_for('giacenze'))

            clienti_ddt = {_cliente_norm_ddt(getattr(a, 'cliente', '')) for a in articoli}
            richiede_mezzi_trasporti = any(c in CLIENTI_MEZZO_OBBLIGATORIO for c in clienti_ddt)
            salva_mezzi_trasporti = bool(richiede_mezzi_trasporti and not skip_mezzi_trasporti)

            CLIENTI_PROTOCOLLO_OBBLIGATORIO = {'FINCANTIERI', 'FINCANTIERI ARMATORE'}
            if action == 'finalize' and any(c in CLIENTI_PROTOCOLLO_OBBLIGATORIO for c in clienti_ddt):
                senza_protocollo = [a for a in articoli if not str(getattr(a, 'protocollo', '') or '').strip()]
                if senza_protocollo:
                    flash(f"⚠️ Protocollo obbligatorio per FINCANTIERI / FINCANTIERI ARMATORE. Mancano {len(senza_protocollo)} righe: correggi prima di finalizzare il DDT.", "danger")
                    return redirect(url_for('giacenze'))

            if action == 'finalize' and salva_mezzi_trasporti and not mezzo_giacenze:
                flash("⚠️ Seleziona il Mezzo per Giacenze prima di finalizzare. Obbligatorio per FINCANTIERI / ARMATORE / SCOPERTO e per MARINE INTERIORS o DE WAVE SAMA quando il trasporto è gestito da Camar.", "danger")
                return redirect(url_for('giacenze'))
            if action == 'finalize' and salva_mezzi_trasporti and not mezzo_trasporti:
                flash("⚠️ Inserisci il Mezzo per Trasporti prima di finalizzare. Verifica anche la funzione Trasporti.", "danger")
                return redirect(url_for('giacenze'))

            # ✅ Consuma il progressivo SOLO DOPO che tutti i controlli sono superati.
            # In questo modo un destinatario mancante o un altro errore di validazione
            # non fa avanzare inutilmente la numerazione DDT.
            if action == 'finalize':
                try:
                    prossimo = peek_next_ddt_number()
                    if (not n_ddt) or (n_ddt == prossimo):
                        n_ddt = next_ddt_number()
                    else:
                        # Numero scelto manualmente con le frecce: memorizzalo
                        # senza incrementare prima un altro progressivo.
                        consume_specific_ddt_number(n_ddt)
                except Exception:
                    if not n_ddt:
                        n_ddt = next_ddt_number()
                    else:
                        consume_specific_ddt_number(n_ddt)

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
                    if salva_mezzi_trasporti:
                        art.mezzi_in_uscita = mezzo_giacenze  # ✅ Solo per FINCANTIERI / SCOPERTO / ARMATORE
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
            if action == 'finalize' and salva_mezzi_trasporti:
                # Dati interni viaggio/trasporto: servono per responsabili, report giornaliero e quaderno digitale.
                # Non vengono passati a _genera_pdf_ddt_file, quindi NON compaiono nel PDF cliente.
                try:
                    cliente_trasporto = ''
                    magazzini = []
                    for art in articoli:
                        if not cliente_trasporto and (art.cliente or '').strip():
                            cliente_trasporto = (art.cliente or '').strip()
                        if (art.magazzino or '').strip() and (art.magazzino or '').strip() not in magazzini:
                            magazzini.append((art.magazzino or '').strip())

                    trasporto = db.query(Trasporto).filter(Trasporto.ddt_uscita == n_ddt).first()
                    if not trasporto:
                        trasporto = Trasporto()
                        db.add(trasporto)
                    trasporto.data = data_ddt_obj
                    trasporto.tipo_mezzo = mezzo_trasporti or None  # ✅ QUI COMPILIAMO SOLO LA FUNZIONE TRASPORTI
                    trasporto.trasportatore = trasportatore_interno or None
                    trasporto.cliente = cliente_trasporto or None
                    trasporto.ddt_uscita = n_ddt
                    trasporto.magazzino = ', '.join(magazzini) if magazzini else None
                    trasporto.consolidato = note_viaggio or None
                    trasporto.costo = costo_trasporto
                except Exception as e:
                    print(f"[WARN] Trasporto interno non salvato per DDT {n_ddt}: {e}")

            if action == 'finalize':
                db.commit()
                if salva_mezzi_trasporti:
                    msg_extra = f" - Trasportatore: {trasportatore_interno}" if trasportatore_interno else ""
                    costo_extra = f" - Costo: € {costo_trasporto:.2f}" if costo_trasporto is not None else ""
                    flash(f"DDT N.{n_ddt} del {data_formatted} salvato con successo. Mezzo giacenze: {mezzo_giacenze} - Mezzo trasporti: {mezzo_trasporti}{msg_extra}{costo_extra}", "success")
                else:
                    flash(f"DDT N.{n_ddt} del {data_formatted} salvato con successo. Mezzo giacenze e funzione Trasporti non compilati.", "success")

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

            # Anteprima: apre direttamente il PDF in una nuova scheda.
            if action != 'finalize':
                return send_file(
                    pdf_bio,
                    as_attachment=False,
                    download_name=filename,
                    mimetype='application/pdf'
                )

            # Finalizzazione robusta: il form viene inviato normalmente, senza dipendere
            # dal JavaScript della schermata DDT. La pagina scarica il PDF e torna alle Giacenze.
            import base64
            import json as _json

            pdf_base64 = base64.b64encode(pdf_bio.getvalue()).decode('ascii')
            filename_js = _json.dumps(filename)
            giacenze_url_js = _json.dumps(url_for('giacenze'))

            return f"""<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DDT finalizzato</title>
</head>
<body>
    <p>DDT N. {n_ddt} salvato correttamente. Download in corso...</p>
    <script>
    (function() {{
        try {{
            const binary = atob("{pdf_base64}");
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {{
                bytes[i] = binary.charCodeAt(i);
            }}
            const blob = new Blob([bytes], {{type: "application/pdf"}});
            const blobUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = blobUrl;
            link.download = {filename_js};
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(function() {{
                URL.revokeObjectURL(blobUrl);
                window.location.replace({giacenze_url_js});
            }}, 1000);
        }} catch (e) {{
            document.body.innerHTML = '<p>Il DDT è stato salvato, ma il download automatico non è riuscito.</p>' +
                '<p><a href=' + {giacenze_url_js} + '>Torna alle Giacenze</a></p>';
        }}
    }})();
    </script>
</body>
</html>"""

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

