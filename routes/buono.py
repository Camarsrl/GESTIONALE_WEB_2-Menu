# -*- coding: utf-8 -*-
"""
Modulo Buono di Prelievo.

Gestisce:
- anteprima buono
- generazione/salvataggio buono
- scarico parziale da celle "codice articolo" e "descrizione"

Uso operativo:
se in una riga sono presenti più codici/descrizioni, nel preview del buono si lascia
solo il codice/descrizione da prelevare. Con lo scarico parziale viene creata una nuova riga con N. buono, note e pezzi prelevati;
la riga originale resta in giacenza con il residuo, senza note del buono e senza N. buono.
"""

def register_buono_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    def _split_multi_value(value):
        """Divide una cella multi-valore senza essere troppo aggressivo."""
        s = (value or "").strip()
        if not s:
            return []
        # separatori più comuni nei campi misti
        parts = re.split(r"\s*(?:\n|;|\||,|\s/\s|\s-\s|\s\+\s)\s*", s)
        return [p.strip() for p in parts if p and p.strip()]

    def _norm_for_match(value):
        return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())

    def _num_float(value):
        """Converte numeri italiani/inglesi in float."""
        try:
            if value is None:
                return 0.0
            s = str(value).strip()
            if not s:
                return 0.0
            if ',' in s:
                s = s.replace('.', '').replace(',', '.')
            return float(s)
        except Exception:
            return 0.0

    def _fmt_num_clean(value):
        """Restituisce numero pulito da salvare nel campo pezzo."""
        try:
            f = float(value or 0)
            if abs(f - int(f)) < 0.000001:
                return str(int(f))
            return str(round(f, 3)).replace('.', ',')
        except Exception:
            return str(value or '')

    def _split_quantita(orig_pezzi, q_scelta, orig_valore):
        """Ripartisce peso/m2/m3 proporzionalmente ai pezzi."""
        op = _num_float(orig_pezzi)
        q = _num_float(q_scelta)
        val = _num_float(orig_valore)
        if op <= 0 or q <= 0 or val <= 0:
            return orig_valore, orig_valore
        if q > op:
            q = op
        scelto = val * (q / op)
        residuo = max(0.0, val - scelto)
        return residuo, scelto

    def _remove_selected_from_cell(original, selected):
        """Rimuove dalla cella originale il codice/descrizione scelto per il buono.

        Se trova il valore come elemento separato, lo elimina e ricompone il residuo.
        Se non lo trova come elemento, prova una rimozione testuale semplice.
        """
        original = (original or "").strip()
        selected = (selected or "").strip()

        if not original or not selected:
            return original

        if _norm_for_match(original) == _norm_for_match(selected):
            return ""

        parts = _split_multi_value(original)
        if len(parts) > 1:
            selected_norm = _norm_for_match(selected)
            kept = [p for p in parts if _norm_for_match(p) != selected_norm]
            if len(kept) != len(parts):
                return " / ".join(kept).strip()

        # fallback: rimozione frase esatta case-insensitive
        pattern = re.compile(re.escape(selected), re.IGNORECASE)
        new_val = pattern.sub("", original, count=1)
        new_val = re.sub(r"\s*(?:/|;|\||,|\+|-)\s*(?:/|;|\||,|\+|-)\s*", " / ", new_val)
        new_val = re.sub(r"^\s*(?:/|;|\||,|\+|-)\s*", "", new_val)
        new_val = re.sub(r"\s*(?:/|;|\||,|\+|-)\s*$", "", new_val)
        new_val = re.sub(r"\s{2,}", " ", new_val).strip()
        return new_val

    def _extract_package_context(*values):
        """Estrae riferimenti logistici da conservare sulla riga residua.

        Nello scarico parziale del Buono di Prelievo il pallet/cassa/package
        identifica il collo fisico, quindi NON deve sparire dalla riga rimasta
        in giacenza anche se viene tolto un codice dal buono.
        """
        found = []
        seen = set()
        patterns = [
            r"\b(?:N\.?\s*)?(?:PACKAGE|PKG)\s*[:#\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
            r"\bPALLET\s*[:#\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
            r"\bCASSA\s*[:#\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
            r"\bCASE\s*[:#\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
        ]
        for value in values:
            txt = str(value or "")
            for pat in patterns:
                for m in re.finditer(pat, txt, flags=re.I):
                    label = re.sub(r"\s+", " ", m.group(0).strip())
                    key = _norm_for_match(label)
                    if key and key not in seen:
                        seen.add(key)
                        found.append(label)
        return found

    def _preserve_package_context(residuo, *sources):
        """Riaggiunge package/pallet/cassa se la rimozione del codice lo ha tolto."""
        residuo = (residuo or "").strip()
        labels = _extract_package_context(*sources)
        if not labels:
            return residuo
        current_norm = _norm_for_match(residuo)
        da_aggiungere = [x for x in labels if _norm_for_match(x) not in current_norm]
        if not da_aggiungere:
            return residuo
        extra = " / ".join(da_aggiungere)
        return f"{residuo} / {extra}".strip(" /") if residuo else extra



    def _safe_int_picking(value):
        """Converte interi lasciando None se il campo è vuoto."""
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    def _safe_float_picking(value):
        """Converte numeri italiani/inglesi lasciando None se il campo è vuoto."""
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    def _date_from_buono_form(value):
        """Accetta DD/MM/YYYY o YYYY-MM-DD e restituisce date."""
        s = str(value or "").strip()
        if not s:
            return date.today()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        return date.today()

    def _join_unique(values, max_len=500):
        out, seen = [], set()
        for v in values or []:
            s = str(v or "").strip()
            if not s:
                continue
            key = s.upper()
            if key not in seen:
                seen.add(key)
                out.append(s)
        return "; ".join(out)[:max_len]

    def _sum_int_attr(rows, attr):
        tot = 0
        for r in rows or []:
            try:
                tot += int(float(getattr(r, attr, 0) or 0))
            except Exception:
                pass
        return tot

    def _create_picking_from_buono_form(db, form, rows, buono_n):
        """Crea SEMPRE la riga Picking/Lavorazioni quando si salva un Buono.

        Versione robusta:
        - non dipende piu' solo dalla checkbox picking_enable;
        - usa INSERT SQL diretto, cosi' evita problemi di sessione ORM;
        - se la colonna n_arrivo non esiste ancora nel DB, salva comunque il resto;
        - non duplica se nella stessa data esiste gia' lo stesso buono in seriali.
        """
        try:
            dt = _date_from_buono_form(form.get('picking_data') or form.get('data_em'))
            cliente = (form.get('picking_cliente') or _join_unique([getattr(r, 'cliente', '') for r in rows], 120)).strip()
            descrizione = (form.get('picking_descrizione') or 'PICKING+FILMATURA+PALLETIZZAZIONE').strip()
            richiesta_di = (form.get('picking_richiesta_di') or '').strip()
            seriali = (form.get('picking_seriali') or buono_n or '').strip()
            n_arrivo = (form.get('picking_n_arrivo') or _join_unique([getattr(r, 'n_arrivo', '') for r in rows], 500)).strip()
            colli = _safe_int_picking(form.get('picking_colli'))
            if colli is None:
                colli = _sum_int_attr(rows, 'n_colli') or len(rows or []) or None
            pallet_forniti = _safe_int_picking(form.get('picking_pallet_entrati'))
            pallet_uscita = _safe_int_picking(form.get('picking_pallet_usciti'))
            ore_blue = _safe_float_picking(form.get('picking_ore_blue'))
            ore_white = _safe_float_picking(form.get('picking_ore_white'))

            # Se l'utente ha lasciato tutto vuoto e non c'e' nemmeno il buono, non creo righe inutili.
            if not (cliente or seriali or n_arrivo):
                return False, "Picking non creato: dati insufficienti"

            # Controllo duplicato su stessa data + stesso buono/seriale.
            try:
                dup = db.execute(
                    text("""
                        SELECT id FROM lavorazioni
                        WHERE data = :data
                          AND UPPER(COALESCE(seriali, '')) = UPPER(:seriali)
                        LIMIT 1
                    """),
                    {"data": dt, "seriali": seriali or str(buono_n or '')}
                ).fetchone()
                if dup:
                    return False, "Picking gia' presente per questo buono nella data indicata"
            except Exception:
                # Se il controllo duplicato fallisce, non blocco il salvataggio.
                pass

            # Verifico se la colonna n_arrivo esiste davvero nel DB Render.
            has_n_arrivo = True
            try:
                cols = db.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'lavorazioni'
                """)).fetchall()
                col_names = {str(c[0]) for c in cols}
                has_n_arrivo = 'n_arrivo' in col_names
            except Exception:
                has_n_arrivo = hasattr(Lavorazione, 'n_arrivo') if 'Lavorazione' in globals() else True

            if has_n_arrivo:
                db.execute(text("""
                    INSERT INTO lavorazioni
                    (data, cliente, descrizione, richiesta_di, seriali, n_arrivo, colli,
                     pallet_forniti, pallet_uscita, ore_blue_collar, ore_white_collar)
                    VALUES
                    (:data, :cliente, :descrizione, :richiesta_di, :seriali, :n_arrivo, :colli,
                     :pallet_forniti, :pallet_uscita, :ore_blue_collar, :ore_white_collar)
                """), {
                    "data": dt,
                    "cliente": cliente,
                    "descrizione": descrizione,
                    "richiesta_di": richiesta_di,
                    "seriali": seriali,
                    "n_arrivo": n_arrivo,
                    "colli": colli,
                    "pallet_forniti": pallet_forniti,
                    "pallet_uscita": pallet_uscita,
                    "ore_blue_collar": ore_blue,
                    "ore_white_collar": ore_white,
                })
            else:
                db.execute(text("""
                    INSERT INTO lavorazioni
                    (data, cliente, descrizione, richiesta_di, seriali, colli,
                     pallet_forniti, pallet_uscita, ore_blue_collar, ore_white_collar)
                    VALUES
                    (:data, :cliente, :descrizione, :richiesta_di, :seriali, :colli,
                     :pallet_forniti, :pallet_uscita, :ore_blue_collar, :ore_white_collar)
                """), {
                    "data": dt,
                    "cliente": cliente,
                    "descrizione": descrizione,
                    "richiesta_di": richiesta_di,
                    "seriali": seriali,
                    "colli": colli,
                    "pallet_forniti": pallet_forniti,
                    "pallet_uscita": pallet_uscita,
                    "ore_blue_collar": ore_blue,
                    "ore_white_collar": ore_white,
                })

            return True, "Picking creato correttamente"
        except Exception as e:
            try:
                scrivi_log_errore("Errore INSERT picking da buono", e)
            except Exception:
                pass
            raise

    def _next_buono_number(db):
        """Genera automaticamente il prossimo N. buono.

        Formato usato: 001/26, 002/26, ...
        Legge i buoni già presenti in Articolo.buono_n e incrementa il numero più alto
        riferito all'anno corrente; se non trova riferimenti all'anno, incrementa comunque
        il numero più alto disponibile.
        """
        yy = datetime.today().strftime("%y")
        max_current_year = 0
        max_any = 0
        try:
            values = db.query(Articolo.buono_n).filter(Articolo.buono_n != None).all()
        except Exception:
            values = []

        for row in values:
            raw = row[0] if isinstance(row, (tuple, list)) else row
            txt = str(raw or "").strip()
            if not txt:
                continue
            m = re.search(r"(\d{1,6})", txt)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            max_any = max(max_any, n)
            if re.search(rf"(?:/|-|\b){re.escape(yy)}\b", txt):
                max_current_year = max(max_current_year, n)

        base = max_current_year or max_any
        return f"{base + 1:03d}/{yy}"

    @app.route('/buono/preview', methods=['POST'])
    @login_required
    def buono_preview():
        if session.get('role') != 'admin':
            flash('Accesso negato.', 'danger')
            return redirect(url_for('giacenze'))

        ids_str_list = request.form.getlist('ids')
        ids = [int(i) for i in ids_str_list if str(i).isdigit()]

        if not ids:
            flash("Seleziona almeno un articolo per creare il buono.", "warning")
            return redirect(url_for('giacenze'))

        db = SessionLocal()
        try:
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

            protocolli_trovati = set()
            for r in rows:
                if r.protocollo and str(r.protocollo).strip():
                    protocolli_trovati.add(str(r.protocollo).strip())
            protocollo_auto = ", ".join(sorted(protocolli_trovati))

            commessa_auto = next((r.commessa for r in rows if r.commessa), "")
            fornitore_auto = next((r.fornitore for r in rows if r.fornitore), "")
            buono_n_esistente = next((r.buono_n for r in rows if r.buono_n), "")
            buono_n_auto = buono_n_esistente or _next_buono_number(db)
            ordine_auto = next((r.ordine for r in rows if r.ordine), "")

            picking_cliente_auto = _join_unique([getattr(r, 'cliente', '') for r in rows], 120)
            picking_n_arrivo_auto = _join_unique([getattr(r, 'n_arrivo', '') for r in rows], 500)
            picking_colli_auto = _sum_int_attr(rows, 'n_colli') or len(rows)

            meta = {
                "buono_n": buono_n_auto,
                "buono_n_auto": buono_n_auto,
                "buono_n_esistente": buono_n_esistente,
                "data_em": datetime.today().strftime("%d/%m/%Y"),
                "commessa": commessa_auto,
                "fornitore": fornitore_auto,
                "protocollo": protocollo_auto,
                "ordine": ordine_auto,
                "picking_cliente": picking_cliente_auto,
                "picking_descrizione": "PICKING+FILMATURA+PALLETIZZAZIONE",
                "picking_richiesta_di": "",
                "picking_seriali": buono_n_auto,
                "picking_n_arrivo": picking_n_arrivo_auto,
                "picking_colli": picking_colli_auto,
            }

            return render_template('buono_preview.html', rows=rows, meta=meta, ids=",".join(map(str, ids)))
        finally:
            db.close()

    @app.route('/buono/finalize_and_get_pdf', methods=['POST'])
    @login_required
    def buono_finalize_and_get_pdf():
        db = SessionLocal()
        try:
            req_data = request.form
            ids = [int(i) for i in req_data.get('ids','').split(',') if i.strip().isdigit()]
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()

            action = req_data.get('action')
            buono_mode = (req_data.get('buono_mode') or 'auto').strip().lower()
            bn = (req_data.get('buono_n') or '').strip()
            if buono_mode == 'auto' or not bn:
                # Se l'utente lascia automatico, oppure non compila il numero manuale,
                # assegno il prossimo numero disponibile prima di salvare/generare il PDF.
                bn = _next_buono_number(db)
            scarico_parziale_eseguito = False

            for r in rows:
                codice_scelto = (req_data.get(f"codice_buono_{r.id_articolo}") or str(r.codice_articolo or '')).strip()
                descr_scelta = (req_data.get(f"descrizione_buono_{r.id_articolo}") or str(r.descrizione or '')).strip()

                # Le note del buono NON devono essere copiate subito sulla riga originale.
                # Nel parziale vanno solo sulla nuova riga creata; la riga residua mantiene le sue note originali.
                note_inserite = req_data.get(f"note_{r.id_articolo}")
                note_originale = r.note

                # Scarico parziale:
                # deve funzionare sia quando viene tolto solo un codice/descrizione da una cella multi-valore,
                # sia quando viene prelevata solo una parte dei pezzi/colli della stessa riga.
                #
                # Logica corretta:
                # 1) la riga originale resta in giacenza con il residuo;
                # 2) viene creata una nuova riga per il materiale messo nel buono;
                # 3) la nuova riga mantiene codice/descrizione del buono e N. buono;
                # 4) se lo scarico è solo quantitativo, la riga residua mantiene lo stesso codice/descrizione.
                if action == 'save':
                    old_cod = (r.codice_articolo or '').strip()
                    old_desc = (r.descrizione or '').strip()

                    q_scelta = req_data.get(f"q_{r.id_articolo}")
                    pezzi_originali = _num_float(getattr(r, 'pezzo', None))
                    pezzi_scelti = _num_float(q_scelta) if q_scelta is not None else pezzi_originali
                    if pezzi_originali > 0 and (pezzi_scelti <= 0 or pezzi_scelti > pezzi_originali):
                        pezzi_scelti = pezzi_originali
                    pezzi_residui = max(0.0, pezzi_originali - pezzi_scelti) if pezzi_originali > 0 else 0.0

                    cod_parziale = bool(codice_scelto and _norm_for_match(codice_scelto) != _norm_for_match(old_cod))
                    desc_parziale = bool(descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc))

                    # Parziale anche se il codice/descrizione resta uguale ma viene indicata una quantità inferiore.
                    qta_parziale = bool(
                        q_scelta is not None
                        and pezzi_originali > 0
                        and pezzi_scelti > 0
                        and pezzi_scelti < pezzi_originali
                    )

                    if cod_parziale or desc_parziale or qta_parziale:
                        scarico_parziale_eseguito = True

                        # Scarico parziale:
                        # la riga originale resta in giacenza SENZA numero buono;
                        # il numero buono va solo sulla nuova riga del materiale prelevato.
                        r.buono_n = ""

                        # Prima creo la riga "materiale del buono", così non si perde nulla.
                        riga_buono = Articolo()
                        for col in Articolo.__table__.columns:
                            if col.name == 'id_articolo':
                                continue
                            setattr(riga_buono, col.name, getattr(r, col.name))

                        riga_buono.codice_articolo = codice_scelto or old_cod
                        riga_buono.descrizione = descr_scelta or old_desc
                        riga_buono.buono_n = bn or r.buono_n

                        # I pezzi scaricati vanno sulla nuova riga; sulla riga originale resta il residuo.
                        if pezzi_originali > 0:
                            riga_buono.pezzo = _fmt_num_clean(pezzi_scelti)
                            r.pezzo = _fmt_num_clean(pezzi_residui)

                            for campo in ('peso', 'm2', 'm3'):
                                residuo_val, scelto_val = _split_quantita(pezzi_originali, pezzi_scelti, getattr(r, campo, None))
                                try:
                                    setattr(riga_buono, campo, scelto_val)
                                    setattr(r, campo, residuo_val)
                                except Exception:
                                    pass

                        riga_buono.data_uscita = getattr(r, 'data_uscita', '') or ''
                        riga_buono.n_ddt_uscita = getattr(r, 'n_ddt_uscita', '') or ''

                        # Le note scritte nel buono vanno solo sulla nuova riga.
                        # Non aggiungo testi automatici tipo "scarico parziale".
                        riga_buono.note = (note_inserite or '').strip()

                        db.add(riga_buono)

                        # Poi aggiorno la riga originale lasciando solo il residuo.
                        # Se il parziale è solo quantitativo, codice e descrizione devono restare sulla riga in giacenza.
                        if cod_parziale:
                            codice_residuo = _remove_selected_from_cell(old_cod, codice_scelto)
                            # Mantiene sulla riga residua eventuale N. package / pallet / cassa.
                            r.codice_articolo = _preserve_package_context(codice_residuo, old_cod, codice_scelto)
                        else:
                            r.codice_articolo = old_cod

                        if desc_parziale:
                            descr_residua = _remove_selected_from_cell(old_desc, descr_scelta)
                            # Mantiene sulla riga residua eventuale N. package / pallet / cassa anche se scritto in descrizione.
                            r.descrizione = _preserve_package_context(descr_residua, old_desc, descr_scelta)
                        else:
                            r.descrizione = old_desc

                        # La riga residua mantiene le note originali.
                        r.note = note_originale
                    else:
                        # Buono normale/non parziale: qui il N. buono e le note restano sulla riga selezionata.
                        if bn:
                            r.buono_n = bn
                        if note_inserite is not None:
                            r.note = note_inserite
                        if q_scelta is not None and _num_float(q_scelta) > 0:
                            r.pezzo = _fmt_num_clean(_num_float(q_scelta))

            picking_msg = ""
            if action == 'save':
                # 1) Salvo SEMPRE prima il Buono e le modifiche alle Giacenze.
                # Il Picking è un'operazione collegata ma non deve mai bloccare
                # la creazione del PDF del Buono.
                db.commit()

                # 2) Creo il Picking in una transazione separata.
                # Se il Picking fallisce per schema/colonne/dati, faccio rollback
                # solo del Picking e lascio valido il Buono appena creato.
                picking_created = False
                try:
                    try:
                        # Crea il Picking SEMPRE quando si salva il Buono.
                        # Se l'utente non vuole registrarlo, puo' lasciare i campi vuoti oppure cancellarlo dalla pagina Picking.
                        fresh_rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
                        picking_created, picking_msg = _create_picking_from_buono_form(db, req_data, fresh_rows, bn)
                        db.commit()
                    except Exception as e_pick_inner:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        picking_msg = "Picking non creato automaticamente: controllare la sezione Picking/Lavorazioni."
                        try:
                            scrivi_log_errore("Errore creazione picking da buono", e_pick_inner)
                        except Exception:
                            pass
                except Exception as e_pick:
                    picking_msg = "Picking non creato automaticamente: controllare la sezione Picking/Lavorazioni."
                    try:
                        scrivi_log_errore("Errore creazione picking da buono", e_pick)
                    except Exception:
                        pass

                if picking_msg:
                    try:
                        flash(picking_msg, "success" if picking_created else "warning")
                    except Exception:
                        pass

                if scarico_parziale_eseguito:
                    flash(
                        "Scarico parziale salvato. Pezzi, note e N. buono sono stati inseriti solo sulla nuova riga prelevata; la riga residua resta pulita.",
                        "success"
                    )
                else:
                    flash("Buono salvato correttamente.", "success")

            pdf_bio = _generate_buono_pdf(req_data, rows)

            safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
            return send_file(
                pdf_bio,
                as_attachment=(action == 'save'),
                download_name=f'Buono_{safe_bn}.pdf',
                mimetype='application/pdf'
            )

        except Exception as e:
            db.rollback()
            scrivi_log_errore("Errore Buono di Prelievo", e)
            print(f"ERRORE BUONO: {e}")
            return f"Errore server: {e}", 500
        finally:
            db.close()
