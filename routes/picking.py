# -*- coding: utf-8 -*-
"""
Modulo Picking / Lavorazioni.

Route:
- /lavorazioni
- /stampa_picking_pdf

Nota:
- Mostra di default solo il mese corrente.
- Con ?mese=YYYY-MM mostra il mese scelto.
- Con ?view=tutti mostra tutto l'archivio.
- NON contiene report_inventario_excel: quella route resta nel file principale.
"""

def register_picking_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import io
    import re
    from datetime import date, datetime
    from flask import request, redirect, url_for, flash, render_template, send_file, session
    from flask_login import login_required
    from sqlalchemy import text

    def _parse_date_any_local(v):
        if not v:
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v).strip().split(" ")[0][:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        try:
            if "parse_any_date" in globals():
                return parse_any_date(v)
        except Exception:
            pass
        return None

    def _safe_int_local(v):
        try:
            if v is None or str(v).strip() == "":
                return None
            return int(float(str(v).replace(",", ".")))
        except Exception:
            return None

    def _safe_float_local(v):
        try:
            if v is None or str(v).strip() == "":
                return None
            return float(str(v).replace(",", "."))
        except Exception:
            return None

    def _clean_upper_bound_local(value):
        try:
            return _clean_picking_upper_bound(value)
        except Exception:
            s = str(value or '').strip().replace(' ', '')
            return '' if s in {'0', '0,0', '0.0', '0,00', '0.00'} else (value or '').strip()

    def _canonical_cliente_local(value):
        try:
            return canonical_cliente_picking(value)
        except Exception:
            raw = (value or '').strip()
            if not raw:
                raise ValueError("Cliente obbligatorio.")
            try:
                norm = normalize_text_key(raw)
                if 'GALVANO' in norm:
                    return 'GALVANO TECNICA'
            except Exception:
                pass
            return raw.upper()

    def _month_bounds_from_request():
        mese = (request.args.get('mese') or '').strip()
        view = (request.args.get('view') or '').strip().lower()
        if view == 'tutti':
            return '', None, None, 'tutti'

        has_filters = any((request.args.get(k) or '').strip() for k in [
            'data_da','data_a','cliente','descrizione','richiesta_di','seriali','n_arrivo',
            'colli_da','colli_a','pallet_forniti_da','pallet_forniti_a',
            'pallet_uscita_da','pallet_uscita_a','ore_blue_da','ore_blue_a',
            'ore_white_da','ore_white_a'
        ])

        if not mese and not has_filters:
            mese = date.today().strftime('%Y-%m')

        if not mese:
            return '', None, None, ''

        try:
            y, m = [int(x) for x in mese.split('-', 1)]
            start = date(y, m, 1)
            end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            return mese, start, end, 'mese'
        except Exception:
            return '', None, None, ''

    def _prev_next_month(mese):
        try:
            y, m = [int(x) for x in (mese or date.today().strftime('%Y-%m')).split('-', 1)]
            py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            return f"{py:04d}-{pm:02d}", f"{ny:04d}-{nm:02d}"
        except Exception:
            cur = date.today().strftime('%Y-%m')
            return cur, cur

    def _ensure_n_arrivo_column(db):
        try:
            db.execute(text("ALTER TABLE lavorazioni ADD COLUMN IF NOT EXISTS n_arrivo TEXT"))
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    def _redirect_lavorazioni_current():
        return redirect(url_for('lavorazioni', mese=date.today().strftime('%Y-%m')))

    @app.route('/lavorazioni', methods=['GET', 'POST'])
    @login_required
    def lavorazioni():
        db = SessionLocal()
        try:
            _ensure_n_arrivo_column(db)

            # --- MODIFICA ---
            if request.method == 'POST' and request.form.get('edit_lavorazione'):
                if session.get('role') != 'admin':
                    flash("ACCESSO NEGATO: Solo Admin.", "danger")
                    return _redirect_lavorazioni_current()

                lid = int(request.form.get('id') or 0)
                rec = db.query(Lavorazione).filter(Lavorazione.id == lid).first()
                if not rec:
                    flash("Record non trovato.", "danger")
                    return _redirect_lavorazioni_current()

                rec.data = datetime.strptime(request.form.get('data'), '%Y-%m-%d').date()
                rec.cliente = _canonical_cliente_local(request.form.get('cliente'))
                rec.descrizione = request.form.get('descrizione')
                rec.richiesta_di = request.form.get('richiesta_di')
                rec.seriali = request.form.get('seriali')
                if hasattr(rec, 'n_arrivo'):
                    rec.n_arrivo = request.form.get('n_arrivo')
                rec.colli = int(request.form.get('colli') or 0)
                rec.pallet_forniti = int(request.form.get('pallet_forniti') or 0)
                rec.pallet_uscita = int(request.form.get('pallet_uscita') or 0)
                rec.ore_blue_collar = float(request.form.get('ore_blue_collar') or 0)
                rec.ore_white_collar = float(request.form.get('ore_white_collar') or 0)

                db.commit()
                flash("Picking modificato!", "success")
                return redirect(url_for('lavorazioni', mese=(request.form.get('mese_corrente') or date.today().strftime('%Y-%m'))))

            # --- INSERIMENTO ---
            if request.method == 'POST' and request.form.get('add_lavorazione'):
                if session.get('role') != 'admin':
                    flash("ACCESSO NEGATO: Solo Admin.", "danger")
                    return _redirect_lavorazioni_current()

                d_val = datetime.strptime(request.form.get('data'), '%Y-%m-%d').date()
                nuovo = Lavorazione(
                    data=d_val,
                    cliente=_canonical_cliente_local(request.form.get('cliente')),
                    descrizione=request.form.get('descrizione'),
                    richiesta_di=request.form.get('richiesta_di'),
                    seriali=request.form.get('seriali'),
                    colli=int(request.form.get('colli') or 0),
                    pallet_forniti=int(request.form.get('pallet_forniti') or 0),
                    pallet_uscita=int(request.form.get('pallet_uscita') or 0),
                    ore_blue_collar=float(request.form.get('ore_blue_collar') or 0),
                    ore_white_collar=float(request.form.get('ore_white_collar') or 0)
                )
                if hasattr(nuovo, 'n_arrivo'):
                    nuovo.n_arrivo = request.form.get('n_arrivo')
                db.add(nuovo)
                db.commit()
                flash(f"Picking aggiunto per {nuovo.cliente} in data {nuovo.data}.", "success")
                return redirect(url_for('lavorazioni', mese=d_val.strftime('%Y-%m')))

            # --- EDIT MODE ---
            edit_id = request.args.get('edit_id')
            edit_row = None
            if edit_id and session.get('role') == 'admin':
                try:
                    edit_row = db.query(Lavorazione).filter(Lavorazione.id == int(edit_id)).first()
                except Exception:
                    edit_row = None

            filtri = {
                'data_da': (request.args.get('data_da') or '').strip(),
                'data_a': (request.args.get('data_a') or '').strip(),
                'cliente': (request.args.get('cliente') or '').strip(),
                'descrizione': (request.args.get('descrizione') or '').strip(),
                'richiesta_di': (request.args.get('richiesta_di') or '').strip(),
                'seriali': (request.args.get('seriali') or '').strip(),
                'n_arrivo': (request.args.get('n_arrivo') or '').strip(),
                'colli_da': (request.args.get('colli_da') or '').strip(),
                'colli_a': _clean_upper_bound_local(request.args.get('colli_a')),
                'pallet_forniti_da': (request.args.get('pallet_forniti_da') or '').strip(),
                'pallet_forniti_a': _clean_upper_bound_local(request.args.get('pallet_forniti_a')),
                'pallet_uscita_da': (request.args.get('pallet_uscita_da') or '').strip(),
                'pallet_uscita_a': _clean_upper_bound_local(request.args.get('pallet_uscita_a')),
                'ore_blue_da': (request.args.get('ore_blue_da') or '').strip(),
                'ore_blue_a': _clean_upper_bound_local(request.args.get('ore_blue_a')),
                'ore_white_da': (request.args.get('ore_white_da') or '').strip(),
                'ore_white_a': _clean_upper_bound_local(request.args.get('ore_white_a')),
                'mese': (request.args.get('mese') or '').strip(),
                'view': (request.args.get('view') or '').strip(),
            }

            mese_attivo, mese_start, mese_end, vista_mese = _month_bounds_from_request()
            filtri['mese'] = mese_attivo
            filtri['view'] = vista_mese

            data_da = _parse_date_any_local(filtri['data_da'])
            data_a = _parse_date_any_local(filtri['data_a'])
            colli_da = _safe_int_local(filtri['colli_da'])
            colli_a = _safe_int_local(filtri['colli_a'])
            pallet_forniti_da = _safe_int_local(filtri['pallet_forniti_da'])
            pallet_forniti_a = _safe_int_local(filtri['pallet_forniti_a'])
            pallet_uscita_da = _safe_int_local(filtri['pallet_uscita_da'])
            pallet_uscita_a = _safe_int_local(filtri['pallet_uscita_a'])
            ore_blue_da = _safe_float_local(filtri['ore_blue_da'])
            ore_blue_a = _safe_float_local(filtri['ore_blue_a'])
            ore_white_da = _safe_float_local(filtri['ore_white_da'])
            ore_white_a = _safe_float_local(filtri['ore_white_a'])

            def _match_txt(value, filtro):
                filtro = (filtro or '').strip()
                if not filtro:
                    return True
                v = str(value or '')
                try:
                    nf = normalize_text_key(filtro)
                    nv = normalize_text_key(v)
                    if filtro.lower() in v.lower() or nf in nv:
                        return True
                    if nf in {'GALVANOTECNICA', 'COTUGNOGALVANOTECNICA', 'GALVANO'} and nv == 'GALVANOTECNICA':
                        return True
                except Exception:
                    return filtro.lower() in v.lower()
                return False

            try:
                _normalize_existing_galvano_picking(db)
            except Exception:
                pass

            rows = (
                db.query(Lavorazione)
                .order_by(Lavorazione.data.desc(), Lavorazione.id.desc())
                .all()
            )

            filtered = []
            for rec in rows:
                rec_date = _parse_date_any_local(getattr(rec, 'data', None))
                if mese_start and (not rec_date or rec_date < mese_start or rec_date >= mese_end):
                    continue
                if data_da and (not rec_date or rec_date < data_da):
                    continue
                if data_a and (not rec_date or rec_date > data_a):
                    continue
                if not _match_txt(rec.cliente, filtri['cliente']):
                    continue
                if not _match_txt(rec.descrizione, filtri['descrizione']):
                    continue
                if not _match_txt(rec.richiesta_di, filtri['richiesta_di']):
                    continue
                if not _match_txt(rec.seriali, filtri['seriali']):
                    continue
                if not _match_txt(getattr(rec, 'n_arrivo', ''), filtri.get('n_arrivo','')):
                    continue
                if colli_da is not None and int(rec.colli or 0) < colli_da:
                    continue
                if colli_a is not None and int(rec.colli or 0) > colli_a:
                    continue
                if pallet_forniti_da is not None and int(rec.pallet_forniti or 0) < pallet_forniti_da:
                    continue
                if pallet_forniti_a is not None and int(rec.pallet_forniti or 0) > pallet_forniti_a:
                    continue
                if pallet_uscita_da is not None and int(rec.pallet_uscita or 0) < pallet_uscita_da:
                    continue
                if pallet_uscita_a is not None and int(rec.pallet_uscita or 0) > pallet_uscita_a:
                    continue
                if ore_blue_da is not None and float(rec.ore_blue_collar or 0) < ore_blue_da:
                    continue
                if ore_blue_a is not None and float(rec.ore_blue_collar or 0) > ore_blue_a:
                    continue
                if ore_white_da is not None and float(rec.ore_white_collar or 0) < ore_white_da:
                    continue
                if ore_white_a is not None and float(rec.ore_white_collar or 0) > ore_white_a:
                    continue
                filtered.append(rec)

            mese_base = mese_attivo or date.today().strftime('%Y-%m')
            mese_precedente, mese_successivo = _prev_next_month(mese_base)

            return render_template(
                'lavorazioni.html',
                lavorazioni=filtered,
                today=date.today(),
                edit_row=edit_row,
                filtri=filtri,
                clienti_validi=get_clienti_utenti(),
                mese_corrente=date.today().strftime('%Y-%m'),
                mese_precedente=mese_precedente,
                mese_successivo=mese_successivo
            )

        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                scrivi_log_errore("Errore pagina Picking/Lavorazioni", e)
            except Exception:
                pass
            flash(f"Errore apertura Picking/Lavorazioni: {e}", "danger")
            return redirect(url_for('home'))
        finally:
            try:
                db.close()
            except Exception:
                pass

    @app.route('/stampa_picking_pdf', methods=['POST'])
    @login_required
    def stampa_picking_pdf():
        if session.get('role') != 'admin':
            return "No Access", 403

        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter

        mese = (request.form.get('mese') or '').strip()
        cliente = (request.form.get('cliente') or '').strip()

        db = SessionLocal()
        try:
            rows = db.query(Lavorazione).all()
            dati = []
            start = end = None
            if mese:
                try:
                    y, m = [int(x) for x in mese.split('-', 1)]
                    start = date(y, m, 1)
                    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                except Exception:
                    start = end = None

            for r in rows:
                d = _parse_date_any_local(getattr(r, 'data', None))
                if start and (not d or d < start or d >= end):
                    continue
                if cliente:
                    try:
                        if normalize_text_key(cliente) not in normalize_text_key(getattr(r, 'cliente', '')):
                            continue
                    except Exception:
                        if cliente.lower() not in str(getattr(r, 'cliente', '') or '').lower():
                            continue
                dati.append(r)

            dati.sort(key=lambda r: (_parse_date_any_local(getattr(r, 'data', None)) or date.min, getattr(r, 'id', 0) or 0))

            wb = Workbook()
            ws = wb.active
            ws.title = "Picking"

            bold = Font(bold=True)
            center = Alignment(horizontal="center", vertical="center", wrap_text=True)
            left = Alignment(horizontal="left", vertical="center", wrap_text=True)
            header_fill = PatternFill("solid", fgColor="D9E1F2")

            ws["A1"] = "REPORT PICKING / LAVORAZIONI"
            ws["A1"].font = Font(bold=True, size=16)
            ws.merge_cells("A1:K1")
            ws["A1"].alignment = center
            ws["A3"] = "Filtri:"
            ws["A3"].font = bold
            ws["B3"] = f"Mese={mese or 'Tutti'} | Cliente={cliente or 'Tutti'}"
            ws.merge_cells("B3:K3")

            headers = ["Data", "Cliente", "Descrizione", "Richiesta di", "Seriali/Buono", "N. Arrivo", "Colli", "Pallet Entrati", "Pallet Usciti", "Ore Blue", "Ore White"]
            start_row = 5
            for col, h in enumerate(headers, start=1):
                cell = ws.cell(row=start_row, column=col, value=h)
                cell.font = bold
                cell.fill = header_fill
                cell.alignment = center

            riga = start_row + 1
            totals = {'colli': 0, 'pin': 0, 'pout': 0, 'blue': 0.0, 'white': 0.0}
            for r in dati:
                d = _parse_date_any_local(getattr(r, 'data', None))
                colli = int(getattr(r, 'colli', 0) or 0)
                pin = int(getattr(r, 'pallet_forniti', 0) or 0)
                pout = int(getattr(r, 'pallet_uscita', 0) or 0)
                blue = float(getattr(r, 'ore_blue_collar', 0) or 0.0)
                white = float(getattr(r, 'ore_white_collar', 0) or 0.0)
                totals['colli'] += colli; totals['pin'] += pin; totals['pout'] += pout; totals['blue'] += blue; totals['white'] += white

                vals = [
                    d.strftime("%Y-%m-%d") if d else "",
                    getattr(r, 'cliente', '') or "",
                    getattr(r, 'descrizione', '') or "",
                    getattr(r, 'richiesta_di', '') or "",
                    getattr(r, 'seriali', '') or "",
                    getattr(r, 'n_arrivo', '') or "",
                    colli, pin, pout, blue, white
                ]
                for c, val in enumerate(vals, 1):
                    cell = ws.cell(riga, c, val)
                    cell.alignment = left if c in (2,3,4,5,6) else center
                    if c in (10,11):
                        cell.number_format = "0.00"
                riga += 1

            ws.cell(riga, 1, "TOTALI").font = bold
            ws.merge_cells(start_row=riga, start_column=1, end_row=riga, end_column=6)
            ws.cell(riga, 1).alignment = Alignment(horizontal="right", vertical="center")
            ws.cell(riga, 7, totals['colli']).font = bold
            ws.cell(riga, 8, totals['pin']).font = bold
            ws.cell(riga, 9, totals['pout']).font = bold
            c10 = ws.cell(riga, 10, totals['blue']); c10.font = bold; c10.number_format = '0.00'; c10.alignment = center
            c11 = ws.cell(riga, 11, totals['white']); c11.font = bold; c11.number_format = '0.00'; c11.alignment = center

            for i, w in enumerate([12, 18, 40, 20, 22, 18, 10, 14, 14, 10, 10], start=1):
                ws.column_dimensions[get_column_letter(i)].width = w
            ws.freeze_panes = "A6"

            bio = io.BytesIO()
            wb.save(bio)
            bio.seek(0)
            safe_mese = mese.replace("-", "_") if mese else "TUTTO"
            return send_file(
                bio,
                as_attachment=True,
                download_name=f"Report_Picking_{safe_mese}.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            try:
                scrivi_log_errore("Errore export Picking Excel", e)
            except Exception:
                pass
            return f"Errore export Picking Excel: {e}", 500
        finally:
            try:
                db.close()
            except Exception:
                pass
