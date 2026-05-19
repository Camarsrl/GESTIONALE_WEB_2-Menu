# -*- coding: utf-8 -*-
"""
Modulo Buono di Prelievo.

Gestisce:
- anteprima buono
- generazione/salvataggio buono
- scarico parziale da celle "codice articolo" e "descrizione"

Uso operativo:
se in una riga sono presenti più codici/descrizioni, nel preview del buono si lascia
solo il codice/descrizione da prelevare. Con lo scarico parziale viene creata una nuova riga con il N. buono indicato,
mentre la riga originale resta in giacenza senza N. buono.
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
            buono_n_auto = next((r.buono_n for r in rows if r.buono_n), "")
            ordine_auto = next((r.ordine for r in rows if r.ordine), "")

            meta = {
                "buono_n": buono_n_auto,
                "data_em": datetime.today().strftime("%d/%m/%Y"),
                "commessa": commessa_auto,
                "fornitore": fornitore_auto,
                "protocollo": protocollo_auto,
                "ordine": ordine_auto,
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
            bn = (req_data.get('buono_n') or '').strip()
            scarico_parziale_eseguito = False

            for r in rows:
                codice_scelto = (req_data.get(f"codice_buono_{r.id_articolo}") or str(r.codice_articolo or '')).strip()
                descr_scelta = (req_data.get(f"descrizione_buono_{r.id_articolo}") or str(r.descrizione or '')).strip()

                # Il N. buono NON va scritto subito sulla riga originale.
                # Se è scarico parziale, il N. buono deve andare solo sulla nuova riga creata per il materiale prelevato.
                # Se invece non è parziale, verrà scritto sulla riga originale più sotto.
                note_inserite = req_data.get(f"note_{r.id_articolo}")
                if note_inserite is not None:
                    r.note = note_inserite

                # Scarico parziale testuale:
                # se nel buono hai lasciato solo un codice/descrizione specifica,
                # NON deve sparire il materiale scelto.
                #
                # Logica corretta:
                # 1) la riga originale resta in giacenza con il residuo;
                # 2) viene creata una nuova riga per il materiale messo nel buono;
                # 3) la nuova riga mantiene il codice/descrizione del buono e il N. buono.
                if action == 'save':
                    old_cod = (r.codice_articolo or '').strip()
                    old_desc = (r.descrizione or '').strip()

                    cod_parziale = bool(codice_scelto and _norm_for_match(codice_scelto) != _norm_for_match(old_cod))
                    desc_parziale = bool(descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc))

                    if cod_parziale or desc_parziale:
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
                        riga_buono.data_uscita = getattr(r, 'data_uscita', '') or ''
                        riga_buono.n_ddt_uscita = getattr(r, 'n_ddt_uscita', '') or ''
                        riga_buono.note = (
                            (getattr(riga_buono, 'note', '') or '').strip()
                            + f" | RIGA CREATA DA BUONO PARZIALE da ID {r.id_articolo}"
                        ).strip(" |")

                        db.add(riga_buono)

                        # Poi aggiorno la riga originale lasciando solo il residuo.
                        if cod_parziale:
                            r.codice_articolo = _remove_selected_from_cell(old_cod, codice_scelto)

                        if desc_parziale:
                            r.descrizione = _remove_selected_from_cell(old_desc, descr_scelta)

                        r.note = (
                            (r.note or '').strip()
                            + f" | RESIDUO dopo buono parziale {bn or ''}: tolto codice/descrizione inserito nel buono"
                        ).strip(" |")
                    else:
                        # Scarico normale/non parziale: qui il N. buono resta sulla riga selezionata.
                        if bn:
                            r.buono_n = bn

            if action == 'save':
                db.commit()

                if scarico_parziale_eseguito:
                    flash(
                        "Scarico parziale salvato. Il N. buono è stato inserito solo sulle nuove righe prelevate; ora puoi filtrare per N.Buono e creare il buono finale.",
                        "success"
                    )
                    try:
                        return redirect(url_for('giacenze', buono_n=bn))
                    except Exception:
                        return redirect(url_for('giacenze'))

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
