# -*- coding: utf-8 -*-
"""
Modulo Magazzino/Giacenze - Step 1.

Spostata qui la route principale:
- giacenze

Le altre route collegate al magazzino restano ancora nel file principale
e verranno spostate nei prossimi step per evitare errori.
"""

def register_magazzino_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    @app.route('/giacenze', methods=['GET', 'POST'])
    @login_required
    def giacenze():
        import logging
        import re
        import math
        from sqlalchemy.orm import selectinload
        from sqlalchemy import func
        from datetime import datetime, date

        db = SessionLocal()
        try:
            # Configurazione Paginazione
            PER_PAGE = 50
            page = request.args.get('page', 1, type=int)
            args = request.args

            # 1) Query Base
            qs = (
                db.query(Articolo)
                .options(selectinload(Articolo.attachments))
                .order_by(Articolo.id_articolo.desc())
            )

            # 2) Filtri Base (cliente)
            if session.get('role') == 'client':
                user_key_norm = normalize_text_key(current_user.id or '')
                cliente_db_norm = normalized_sql_text(Articolo.cliente)

                qs = qs.filter(cliente_db_norm == user_key_norm)

            else:
                if args.get('cliente'):
                    cliente_norm = normalize_text_key(args.get('cliente'))
                    if cliente_norm:
                        qs = qs.filter(normalized_sql_text(Articolo.cliente) == cliente_norm)

            # 3) Filtro ID
            if args.get('id'):
                try:
                    qs = qs.filter(Articolo.id_articolo == int(args.get('id')))
                except:
                    pass

            # 4) Filtri Testuali
            # Filtro BUONO: esatto. Se scrivi 452 trova solo 452, non 1452 o 452/26.
            buono_val = (args.get('buono_n') or '').strip()
            if buono_val:
                qs = qs.filter(func.upper(func.trim(Articolo.buono_n)) == buono_val.upper())

            # Gli altri campi restano a ricerca parziale. Protocollo compreso:
            # puoi inserire anche solo le ultime cifre.
            text_filters = [
                'commessa', 'descrizione', 'posizione', 'protocollo', 'lotto',
                'fornitore', 'ordine', 'magazzino', 'mezzi_in_uscita', 'stato',
                'n_ddt_ingresso', 'n_ddt_uscita', 'codice_articolo', 'serial_number', 'n_arrivo'
            ]
            for field in text_filters:
                val = args.get(field)
                if val and val.strip():
                    qs = qs.filter(getattr(Articolo, field).ilike(f"%{val.strip()}%"))

            # 5) Filtro M2 (range DA/A + compatibilità col vecchio campo singolo)
            m2_da = args.get('m2_da')
            m2_a = args.get('m2_a')
            m2_legacy = args.get('m2')

            def _to_float_it(v):
                if v is None:
                    return None
                if isinstance(v, (int, float)):
                    return float(v)
                s = str(v).strip().replace(' ', '')
                if not s:
                    return None
                try:
                    if ',' in s and '.' in s:
                        s2 = s.replace('.', '').replace(',', '.')
                    else:
                        s2 = s.replace(',', '.')
                    return float(s2)
                except Exception:
                    return None

            m2_da_f = _to_float_it(m2_da)
            m2_a_f = _to_float_it(m2_a)

            m2_filter = None
            if m2_da_f is None and m2_a_f is None and m2_legacy:
                m2_filter = parse_float_filter(m2_legacy)

            # 5) Recupero righe (per filtro date in Python)
            all_rows = qs.all()

            if m2_da_f is not None or m2_a_f is not None:
                tmp = []
                for r in all_rows:
                    n = _to_float_it(r.m2)
                    if n is None:
                        continue
                    if m2_da_f is not None and n < m2_da_f:
                        continue
                    if m2_a_f is not None and n > m2_a_f:
                        continue
                    tmp.append(r)
                all_rows = tmp
            elif m2_filter is not None:
                all_rows = [r for r in all_rows if match_numeric_filter(r.m2, m2_filter)]

            filtered_rows = []

            # 6) Filtri Date
            def get_date_arg(k):
                v = args.get(k)
                try:
                    return datetime.strptime(v, "%Y-%m-%d").date() if v else None
                except:
                    return None

            d_ing_da, d_ing_a = get_date_arg('data_ing_da'), get_date_arg('data_ing_a')
            d_usc_da, d_usc_a = get_date_arg('data_usc_da'), get_date_arg('data_usc_a')

            def parse_d(val):
                if isinstance(val, date):
                    return val
                if not val:
                    return None
                if isinstance(val, str):
                    try:
                        return datetime.strptime(val[:10], "%Y-%m-%d").date()
                    except:
                        return None
                return None

            if any([d_ing_da, d_ing_a, d_usc_da, d_usc_a]):
                for r in all_rows:
                    keep = True

                    # Ingresso
                    if d_ing_da or d_ing_a:
                        rd = parse_d(r.data_ingresso)
                        if not rd or (d_ing_da and rd < d_ing_da) or (d_ing_a and rd > d_ing_a):
                            keep = False

                    # Uscita
                    if keep and (d_usc_da or d_usc_a):
                        rd = parse_d(r.data_uscita)
                        if not rd or (d_usc_da and rd < d_usc_da) or (d_usc_a and rd > d_usc_a):
                            keep = False

                    if keep:
                        filtered_rows.append(r)
            else:
                filtered_rows = all_rows

            # ✅ 7) FILTRO: SOLO IN GIACENZA / SOLO USCITE
            # In giacenza = NON ha data_uscita e NON ha n_ddt_uscita
            # Uscite = ha data_uscita oppure n_ddt_uscita
            if args.get("solo_giacenza") == "1" and args.get("solo_uscite") != "1":
                tmp = []
                for r in filtered_rows:
                    has_data_usc = parse_d(r.data_uscita) is not None
                    has_ddt_usc = bool((r.n_ddt_uscita or "").strip())
                    if (not has_data_usc) and (not has_ddt_usc):
                        tmp.append(r)
                filtered_rows = tmp
            elif args.get("solo_uscite") == "1":
                tmp = []
                for r in filtered_rows:
                    has_data_usc = parse_d(r.data_uscita) is not None
                    has_ddt_usc = bool((r.n_ddt_uscita or "").strip())
                    if has_data_usc or has_ddt_usc:
                        tmp.append(r)
                filtered_rows = tmp

            # 8) Totali (sui risultati filtrati)
            total_colli = 0
            total_m2 = 0.0
            total_peso = 0.0

            for r in filtered_rows:
                try:
                    total_colli += int(r.n_colli or 0)
                except:
                    pass
                try:
                    total_m2 += float(r.m2) if r.m2 else 0.0
                except:
                    pass
                try:
                    total_peso += float(r.peso) if r.peso else 0.0
                except:
                    pass

            # 9) Paginazione
            total_items = len(filtered_rows)
            total_pages = math.ceil(total_items / PER_PAGE) if total_items else 1

            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages

            start = (page - 1) * PER_PAGE
            end = start + PER_PAGE
            current_page_rows = filtered_rows[start:end]

            # ✅ FIX: parametri senza "page"
            search_params = request.args.copy()
            if 'page' in search_params:
                del search_params['page']

            return render_template(
                'giacenze.html',
                rows=current_page_rows,
                result=current_page_rows,
                page=page,
                total_pages=total_pages,
                total_items=total_items,
                total_colli=total_colli,
                total_m2=it_num(total_m2, 2),
                total_peso=it_num(total_peso, 2),
                today=date.today(),
                search_params=search_params,
                current_return_url=request.full_path
            )

        except Exception as e:
            logging.error(f"ERRORE GIACENZE: {e}")
            return f"<h1>Errore: {e}</h1>"
        finally:
            db.close()

    # ==============================================================================
    #  3. FUNZIONE ELIMINA (Risolve l'errore 'endpoint elimina_record')
    # ==============================================================================
