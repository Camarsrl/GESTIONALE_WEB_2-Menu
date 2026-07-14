# -*- coding: utf-8 -*-
"""
Modulo Email / Rubrica - Step 6.

Route email/rubrica spostate dal file principale.
Gli endpoint restano invariati perché vengono registrati sulla stessa app.
"""

def register_email_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    @app.route('/invia_email', methods=['GET', 'POST'])
    @login_required
    @require_admin
    def invia_email():
        from email.header import Header
        from email.mime.image import MIMEImage
        import html

        # =========================
        # Helper: Riepilogo Merci (tabella in email)
        # =========================
        def _build_riepilogo_schema_html(rows):
            def esc(x):
                return html.escape("" if x is None else str(x))

            def fnum(x, nd=2):
                try:
                    return f"{float(x):.{nd}f}"
                except:
                    return ""

            total_colli = 0
            total_peso = 0.0
            trs = []

            for r in rows:
                try:
                    total_colli += int(r.n_colli or 0)
                except:
                    pass
                try:
                    total_peso += float(r.peso or 0)
                except:
                    pass

                misure = f"{fnum(r.larghezza,2)} × {fnum(r.lunghezza,2)} × {fnum(r.altezza,2)}"

                trs.append(f"""
                <tr>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.commessa)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.ordine)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(misure)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.cliente)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.fornitore)}</td>
                  <td style="border:1px solid #ddd;padding:6px;text-align:right;">{fnum(r.peso,2)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.descrizione)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.codice_articolo)}</td>
                  <td style="border:1px solid #ddd;padding:6px;text-align:right;">{esc(r.n_colli)}</td>
                  <td style="border:1px solid #ddd;padding:6px;">{esc(r.n_arrivo)}</td>
                </tr>
                """)

            return f"""
            <div style="margin:12px 0 20px 0; font-family: Arial, sans-serif;">
              <b>Riepilogo merce selezionata</b>

              <table style="border-collapse:collapse;width:100%;font-size:12px;margin-top:6px;">
                <thead>
                  <tr style="background:#f2f2f2;">
                    <th style="border:1px solid #ddd;padding:6px;">Commessa</th>
                    <th style="border:1px solid #ddd;padding:6px;">Ordine</th>
                    <th style="border:1px solid #ddd;padding:6px;">Misure pallet (L×P×H)</th>
                    <th style="border:1px solid #ddd;padding:6px;">Cliente</th>
                    <th style="border:1px solid #ddd;padding:6px;">Fornitore</th>
                    <th style="border:1px solid #ddd;padding:6px;text-align:right;">Peso (kg)</th>
                    <th style="border:1px solid #ddd;padding:6px;">Descrizione</th>
                    <th style="border:1px solid #ddd;padding:6px;">Codice Articolo</th>
                    <th style="border:1px solid #ddd;padding:6px;text-align:right;">Colli</th>
                    <th style="border:1px solid #ddd;padding:6px;">N. Arrivo</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(trs)}
                </tbody>
              </table>

              <div style="margin-top:8px;font-size:12px;">
                <b>Totali:</b> Colli = {total_colli} | Peso = {total_peso:.2f} kg
              </div>
            </div>
            """

        # =========================
        # Firma completa + Avviso Importante (come da testo)
        # =========================
        firma_completa_html = """
        <div style="font-size:12px;color:#444;line-height:1.4;">
          <div style="margin-top:10px;">
            <b>Numero Ufficio :</b> 010265995<br>
            <b>Numero Fax:</b> 010 4550943<br>
            <b>Mobili:</b><br><br>

            Sig.  Tazio Marcellino&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; +39 334 6892992<br>
            Sig.ra Alessia Moncalvo&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; +39 324 9255537<br>
            Sig.  Giorgio Cabella&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; +39 338 7255224<br>
            Sig.  Hugo Esviza&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; +39 327 4573767<br><br>
            Sig.  Allosia Alessandro;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; +39 351 5105697<br><br>

            <i>a simple but ingenious company ®</i><br><br>

            <b>INDIRIZZO CONTABILITA':</b> <a href="mailto:contabilita@camarsrl.net">contabilita@camarsrl.net</a><br><br>

            HEAD OFFICE: Via Balleydier 52r – 16149 GENOVA<br>
            BRANCH OFFICE: La Spezia - Savona - Vado Ligure - Civitavecchia - Marina Di Carrara - Venezia<br><br>

            Tutte le parti accettano il presente documento e stabiliscono che per ogni eventuale e futura controversia derivante dal presente accordo, o connesse allo stesso, è competente il Tribunale di Roma .<br><br>

            Si ritiene accettato con la conferma del trasporto o la conferma della vendita .<br><br>

            All the parts agree upon the present document and establish that for any possible future controversy related to the present agreement, or connected to it, the Tribunal of Rome is in charge.<br>
            This is considered as accepted once the transport or the sale has been confermed
          </div>

          <hr style="border:0;border-top:1px solid #ccc;margin:15px 0;">

          <p style="font-size:10px;color:#777;text-align:justify;margin-top:10px;">
          <b>AVVISO IMPORTANTE.</b>Le informazioni contenute nella presente comunicazione e i relativi allegati possono essere riservate e sono, comunque, destinate esclusivamente alle persone o alla Società sopraindicati. La comunicazione, diffusione, distribuzione e/o copiatura del documento trasmesso nonché qualsiasi forma di trattamento dei dati ivi contenuti da parte di qualsiasi soggetto diverso dal destinatario è proibita, sia ai sensi dell’art. 616 c.p., che ai sensi del D. Lgs. n. 196/2003, ed in ogni caso espressamente inibita. Le informazioni e tutte le indicazioni, dati, contenuti in questo messaggio hanno una scadenza decennale. Se avete ricevuto questo messaggio per errore, vi preghiamo di distruggerlo e di informarci immediatamente per telefono allo 010 265995 o inviando un messaggio. L’operazione eseguita per vostro conto, segue l’accordo/le tariffe stabilite appositamente, fa parte di un appalto di servizi in esclusiva per le operazioni marittime della vostra azienda. La sopracitata operazione, che sarà effettuata con il massimo dell’attenzione e più velocemente possibile, viene eseguita tramite Autorizzazione Doganale, di Polizia ,o di Capitaneria, ed è riconducibile e discrezionale solo da parte dell’Autorità Ministeriale/Statale, pertanto la nostra azienda si manleva da qualsiasi responsabilità relativa all’esito della stessa. Le disposizioni di cui sopra si ritengono accettate dalle controparti, dal momento dell’incarico e dello svolgimento del lavoro sopra menzionato nella email. Questo messaggio, con gli eventuali allegati e informazioni contiene documentazione, dati, notizie, nomi, riservate esclusivamente per fini lavorativi al destinatario inteso come azienda, e alla sua direzione. La nostra azienda non accetta nessun tipo di addebito per ritardi o errori, deficienze o negligenze, nella compilazione o nell’esecuzione, assistenza della documentazione richiesta o fornita.La scrivente agisce come intermediario tra IMPORTANTE. Mandato di trasporto e assicurativo: eseguiamo l’ordine di trasporto e assicuriamo la merce al valore dichiarato. La risposta a questa email è da considerare come mandato assicurativo( quello assicurativo se esplicitamente manifestato dal cliente) e di trasporto a tutti gli effetti.Vi preghiamo di avvisarci nel caso di imprevisti.Comunichiamo che il cambio della data di consegna da noi indicata, non deve essere soggetta a richieste danni o spese. Comunichiamo, inoltre, che dall’uscita dei varchi doganali sino a Vs destinazione, le spese e i costi derivanti da eventuali blocchi traffico, soste, verbali, sanzioni, incidenti non sono a noi imputabili.Se il valore della merce trasportata non è stato dichiarato, il cliente anche per conto dei propri mandatari rinuncia a far valere nei confronti della società e del vettore qualsiasi credito per danni o perdita delle merci in misura superiore al valore indicato dal decreto riportato. Si obbliga a tenere indenne e manlevare la società e il vettore a fronte di qualsiasi richiesta di risarcimento da parte di terzi a fronte di perdite delle merci in misura superiore al valore indicato dal decreto sotto riportato.Il trasporto oggetto della presente prenotazione è disciplinato dalle disposizioni del decreto legislativo 21.11.2005 n.286. Tali disposizioni, tra l’altro, prevedono a carico del committente, caricatore, e proprietario delle merci responsabilità e sanzioni in relazione a violazione delle disposizioni in materia di sicurezza della circolazione quali quelle relative alla massa limite e alla sistemazione del carico sui veicoli. Il cliente garantisce l’esattezza e la completezza delle informazioni fornite alla società in merito alle merci oggetto della prenotazione, nonché, laddove vi preveda l’accuratezza e l’idoneità della sistemazione del carico sui veicoli nel rispetto delle norme descritte si terrà indenne e manleverà la società e il vettore da quest’ultima incaricato per suo conto a fronte di qualsiasi sanzione e responsabilità che dovesse derivare dall’inesattezza incompletezza o inidoneità delle predette informazioni e sistemazioni.È a conoscenza e quindi manleva da qualsiasi danno o addebito la scrivente, nel caso che l’ordine di trasporto venga disdetto da quest’ultima per motivi logistici.La nostra azienda si occupa d’intermediazione nel campo della logistica e trasporti.Eseguiamo operazioni solo ed esclusivamente per Vs conto senza alcuna responsabilità civile, economica, legale.Le disposizioni di cui sopra si ritengono accettate dal momento dell’incarico.
          </p>
        </div>
        """

        # =========================
        # GET
        # =========================
        if request.method == 'GET':
            selected_ids = request.args.getlist('ids')
            rubrica_email = load_rubrica_email()
            return render_template(
                'invia_email.html',
                selected_ids=",".join(selected_ids),
                email_groups=rubrica_email.get('gruppi', {}),
                email_contacts=rubrica_email.get('contatti', {})
            )

        # =========================
        # POST
        # =========================
        selected_ids = request.form.get('selected_ids', '')
        ids_list = [int(i) for i in selected_ids.split(',') if i.isdigit()]

        destinatari = [
            e.strip() for e in request.form.get('destinatario', '').replace(";", ",").split(",") if e.strip()
        ]

        if not destinatari:
            flash("Inserire almeno un destinatario valido", "danger")
            return redirect(url_for('giacenze'))

        oggetto = request.form.get('oggetto')
        messaggio = request.form.get('messaggio') or ""
        genera_ddt = 'genera_ddt' in request.form
        allega_file = 'allega_file' in request.form
        allegati_extra = request.files.getlist('allegati_extra')

        SMTP_SERVER = os.environ.get("MAIL_SERVER") or os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        SMTP_PORT = int(os.environ.get("MAIL_PORT") or os.environ.get("SMTP_PORT", 587))
        SMTP_USER = os.environ.get("MAIL_USERNAME") or os.environ.get("SMTP_USER", "")
        SMTP_PASS = os.environ.get("MAIL_PASSWORD") or os.environ.get("SMTP_PASS", "")

        if not SMTP_USER or not SMTP_PASS:
            flash("Configurazione email mancante.", "warning")
            return redirect(url_for('giacenze'))

        try:
            riepilogo_html = ""
            if genera_ddt and ids_list:
                db = SessionLocal()
                try:
                    rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
                    if rows:
                        riepilogo_html = _build_riepilogo_schema_html(rows)
                finally:
                    db.close()

            msg_root = MIMEMultipart('related')
            msg_root['From'] = SMTP_USER
            msg_root['To'] = ", ".join(destinatari)
            msg_root['Subject'] = Header(oggetto, 'utf-8')

            msg_alt = MIMEMultipart('alternative')
            msg_root.attach(msg_alt)

            msg_alt.attach(MIMEText(messaggio, 'plain', 'utf-8'))

            html_body = f"""
            <html>
              <head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head>
              <body style="font-family:Arial, sans-serif; font-size:14px; color:#333;">
                <div style="margin-bottom:18px;">{html.escape(messaggio).replace(chr(10), '<br>')}</div>
                {riepilogo_html}

                <div style="margin: 16px 0 12px 0;">
                  <img src="cid:logo_camar" alt="Camar S.r.l." style="height:65px; width:auto; display:block;">
                </div>

                {firma_completa_html}
              </body>
            </html>
            """
            msg_alt.attach(MIMEText(html_body, 'html', 'utf-8'))

            # ✅ Allega LOGO inline (CID)
            possible_logos = ["logo camar.jpg", "logo_camar.jpg", "logo.jpg"]
            logo_found = False
            for name in possible_logos:
                logo_path = os.path.join(app.root_path, "static", name)
                if os.path.exists(logo_path):
                    with open(logo_path, "rb") as f:
                        img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<logo_camar>')
                    img.add_header('Content-Disposition', 'inline', filename='logo_camar.jpg')
                    msg_root.attach(img)
                    logo_found = True
                    break

            if not logo_found:
                print("⚠️ Logo non trovato in static: l'email partirà senza logo.")

            # ✅ Allegati esistenti (foto/pdf articoli)
            if allega_file and ids_list:
                db = SessionLocal()
                try:
                    rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids_list)).all()
                    for r in rows:
                        for att in r.attachments:
                            fname = att.filename
                            path = (DOCS_DIR if att.kind == 'doc' else PHOTOS_DIR) / fname
                            if not path.exists():
                                from urllib.parse import unquote, quote
                                path = (DOCS_DIR if att.kind == 'doc' else PHOTOS_DIR) / unquote(fname)

                            if path.exists():
                                with open(path, "rb") as f:
                                    part = MIMEBase('application', "octet-stream")
                                    part.set_payload(f.read())
                                encoders.encode_base64(part)
                                part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                                msg_root.attach(part)
                finally:
                    db.close()

            # ✅ Allegati extra
            for file in allegati_extra:
                if file and file.filename:
                    part = MIMEBase('application', "octet-stream")
                    part.set_payload(file.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{secure_filename(file.filename)}"')
                    msg_root.attach(part)

            # ✅ Invio SMTP
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg_root, from_addr=SMTP_USER, to_addrs=destinatari)
            server.quit()

            flash("Email inviata correttamente", "success")

        except Exception as e:
            print(f"DEBUG EMAIL EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            flash(str(e), "danger")

        return redirect(url_for('giacenze'))


    @app.route('/manage_destinatari', methods=['GET', 'POST'])
    @login_required
    def manage_destinatari():
        import json

        dest_file = _destinatari_path()
        destinatari = load_destinatari()

        if request.method == 'POST':

            # =========================
            # ELIMINAZIONE DESTINATARIO
            # =========================
            if 'delete_key' in request.form:
                key_to_delete = (request.form.get('delete_key') or '').strip()

                if key_to_delete and key_to_delete in destinatari:
                    del destinatari[key_to_delete]
                    try:
                        save_destinatari(destinatari)
                        flash(f"Destinatario '{key_to_delete}' eliminato.", "success")
                    except Exception as e:
                        flash(f"Errore salvataggio file: {e}", "danger")
                else:
                    flash("Destinatario non trovato.", "warning")

            # =========================
            # AGGIUNTA / MODIFICA
            # =========================
            else:
                key_name = (request.form.get('key_name') or '').strip()

                if not key_name:
                    flash("Il Nome Chiave è obbligatorio.", "warning")
                else:
                    destinatari[key_name] = {
                        "ragione_sociale": (request.form.get('ragione_sociale') or '').strip(),
                        "indirizzo": (request.form.get('indirizzo') or '').strip(),
                        "piva": (request.form.get('piva') or '').strip()
                    }

                    try:
                        save_destinatari(destinatari)
                        flash(f"Destinatario '{key_name}' salvato.", "success")
                    except Exception as e:
                        flash(f"Errore salvataggio file: {e}", "danger")

            return redirect(url_for('manage_destinatari'))

        # =========================
        # GET
        # =========================
        return render_template(
            'destinatari.html',
            destinatari=destinatari
        )


    @login_required
    @require_admin
    def rubrica_email():
        data = load_rubrica_email()

        if request.method == 'POST':
            action = request.form.get('action', 'save')

            if action == 'save_contact':
                nome = (request.form.get('nome') or '').strip()
                email = (request.form.get('email') or '').strip()
                if not nome or not email:
                    flash("Nome ed email sono obbligatori.", "warning")
                else:
                    data["contatti"][nome] = {"email": email}
                    save_rubrica_email(data)
                    flash("Contatto salvato.", "success")

            elif action == 'delete_contact':
                nome = (request.form.get('nome') or '').strip()
                if nome in data.get("contatti", {}):
                    email_da_rimuovere = data.get("contatti", {}).get(nome, {}).get("email")
                    del data["contatti"][nome]
                    # rimuovi anche dai gruppi
                    for g, emails in list(data.get("gruppi", {}).items()):
                        data["gruppi"][g] = [e for e in emails if e != nome and e != email_da_rimuovere]
                    save_rubrica_email(data)
                    flash("Contatto eliminato.", "success")

            elif action == 'save_group':
                gruppo = (request.form.get('gruppo') or '').strip()
                raw = (request.form.get('emails') or '').strip()
                if not gruppo:
                    flash("Nome gruppo obbligatorio.", "warning")
                else:
                    emails = _parse_emails(raw)
                    data["gruppi"][gruppo] = emails
                    save_rubrica_email(data)
                    flash("Gruppo salvato.", "success")

            elif action == 'add_email_to_group':
                gruppo = (request.form.get('gruppo') or '').strip()
                raw_email = (request.form.get('nuovo_destinatario') or '').strip()
                nome_contatto = (request.form.get('nome_contatto') or '').strip()

                if not gruppo:
                    flash("Nome gruppo obbligatorio.", "warning")
                elif gruppo not in data.get("gruppi", {}):
                    flash("Gruppo non trovato.", "warning")
                elif not raw_email:
                    flash("Inserisci almeno un destinatario da aggiungere al gruppo.", "warning")
                else:
                    nuove_email = _parse_emails(raw_email)
                    if not nuove_email:
                        flash("Inserisci un indirizzo email valido.", "warning")
                    else:
                        gruppo_emails = list(data.get("gruppi", {}).get(gruppo, []) or [])
                        esistenti = {str(e).strip().lower() for e in gruppo_emails if str(e).strip()}
                        aggiunte = []

                        for e in nuove_email:
                            e = (e or '').strip()
                            if not e:
                                continue
                            if e.lower() not in esistenti:
                                gruppo_emails.append(e)
                                esistenti.add(e.lower())
                                aggiunte.append(e)

                        data["gruppi"][gruppo] = gruppo_emails

                        # Se indicato il nome, salvo anche il destinatario nei contatti.
                        if nome_contatto and nuove_email:
                            data.setdefault("contatti", {})
                            data["contatti"][nome_contatto] = {"email": nuove_email[0]}

                        save_rubrica_email(data)

                        if aggiunte:
                            flash(f"Aggiunto/i {len(aggiunte)} destinatario/i al gruppo {gruppo}.", "success")
                        else:
                            flash("Il destinatario era già presente nel gruppo.", "info")

            elif action == 'delete_email_from_group':
                gruppo = (request.form.get('gruppo') or '').strip()
                email_da_eliminare = (request.form.get('email') or '').strip()

                if not gruppo or gruppo not in data.get("gruppi", {}):
                    flash("Gruppo non trovato.", "warning")
                elif not email_da_eliminare:
                    flash("Email da eliminare non indicata.", "warning")
                else:
                    gruppo_emails = list(data.get("gruppi", {}).get(gruppo, []) or [])
                    prima = len(gruppo_emails)
                    data["gruppi"][gruppo] = [
                        e for e in gruppo_emails
                        if str(e or '').strip().lower() != email_da_eliminare.lower()
                    ]
                    if len(data["gruppi"][gruppo]) < prima:
                        save_rubrica_email(data)
                        flash(f"Email eliminata dal gruppo {gruppo}.", "success")
                    else:
                        flash("Email non trovata nel gruppo.", "warning")

            elif action == 'delete_group':
                gruppo = (request.form.get('gruppo') or '').strip()
                if gruppo in data.get("gruppi", {}):
                    del data["gruppi"][gruppo]
                    save_rubrica_email(data)
                    flash("Gruppo eliminato.", "success")

            return redirect(url_for('rubrica_email'))

        return render_template('rubrica_email.html', rubrica=data)

    # Registra la route Rubrica Email in modo sicuro:
    # se esiste già un endpoint rubrica_email, sostituisce la funzione invece di bloccare il modulo.
    try:
        if 'rubrica_email' in app.view_functions:
            app.view_functions['rubrica_email'] = rubrica_email
        else:
            app.add_url_rule('/rubrica_email', endpoint='rubrica_email', view_func=rubrica_email, methods=['GET', 'POST'])
    except Exception as e:
        try:
            scrivi_log_errore("Route rubrica_email non registrata", e)
        except Exception:
            pass
        print(f"[WARN] route rubrica_email non registrata: {e}")

