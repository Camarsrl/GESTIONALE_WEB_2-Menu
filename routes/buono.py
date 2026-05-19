# -*- coding: utf-8 -*-
"""
Modulo Buono di Prelievo.

Gestisce:
- anteprima buono
- generazione/salvataggio buono
- scarico parziale da celle "codice articolo" e "descrizione"

Uso operativo:
se in una riga sono presenti più codici/descrizioni, nel preview del buono si lascia
solo il codice/descrizione da prelevare. Al salvataggio il testo scelto viene tolto
dalla cella originale e resta in giacenza il residuo.
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

            for r in rows:
                codice_scelto = (req_data.get(f"codice_buono_{r.id_articolo}") or str(r.codice_articolo or '')).strip()
                descr_scelta = (req_data.get(f"descrizione_buono_{r.id_articolo}") or str(r.descrizione or '')).strip()

                if action == 'save' and bn:
                    r.buono_n = bn

                note_inserite = req_data.get(f"note_{r.id_articolo}")
                if note_inserite is not None:
                    r.note = note_inserite

                # Scarico parziale testuale:
                # se nel buono hai lasciato solo un codice/descrizione specifica,
                # quello viene tolto dalla cella originale.
                if action == 'save':
                    old_cod = (r.codice_articolo or '').strip()
                    old_desc = (r.descrizione or '').strip()

                    if codice_scelto and _norm_for_match(codice_scelto) != _norm_for_match(old_cod):
                        r.codice_articolo = _remove_selected_from_cell(old_cod, codice_scelto)

                    if descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc):
                        r.descrizione = _remove_selected_from_cell(old_desc, descr_scelta)

            if action == 'save':
                db.commit()
                flash("Buono salvato. Se hai indicato un codice/descrizione parziale, è stato tolto dalla riga originale.", "success")

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
