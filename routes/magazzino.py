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

            # Memorizza l'ultima lista Giacenze aperta, con tutti i filtri.
            # Serve per tornare allo stesso arrivo dopo modifica singola o multipla.
            try:
                if request.method == 'GET':
                    session['last_giacenze_url'] = request.full_path
                    session.modified = True
            except Exception:
                pass

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
    #  CONFRONTA INVENTARIO
    # ==============================================================================

    CONFRONTA_INVENTARIO_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="mb-0">📋 Confronta Inventario</h4>
        <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm">Torna al Magazzino</a>
      </div>

      <div class="alert alert-info">
        Carica il file Excel dell'inventario. Il confronto cambia in base al cliente:<br>
        <b>GALVANO TECNICA</b>: Codice articolo + Pezzi + Peso + Lotto<br>
        <b>DUFERCO</b>: Seriali + Colli<br>
        <b>FINCANTIERI</b>: Codice articolo + Colli
      </div>

      <div class="card shadow-sm mb-3">
        <div class="card-body">
          <form method="post" enctype="multipart/form-data" class="row g-2 align-items-end">
            <div class="col-md-4">
              <label class="form-label">Cliente</label>
              <input type="text" name="cliente" class="form-control" placeholder="Es. FINCANTIERI / DUFERCO / GALVANO TECNICA" value="{{ cliente or '' }}" required>
            </div>
            <div class="col-md-5">
              <label class="form-label">File inventario Excel</label>
              <input type="file" name="file_inventario" accept=".xlsx,.xls,.csv" class="form-control" required>
            </div>
            <div class="col-md-3">
              <button type="submit" class="btn btn-primary w-100">Confronta</button>
            </div>
          </form>
        </div>
      </div>

      {% if error %}
        <div class="alert alert-danger">{{ error|safe }}</div>
      {% endif %}

      {% if summary %}
        <div class="row g-2 mb-3">
          <div class="col-md-3"><div class="card"><div class="card-body py-2"><b>OK</b><br>{{ summary.ok }}</div></div></div>
          <div class="col-md-3"><div class="card"><div class="card-body py-2"><b>Differenze</b><br>{{ summary.diff }}</div></div></div>
          <div class="col-md-3"><div class="card"><div class="card-body py-2"><b>Mancanti in inventario</b><br>{{ summary.missing }}</div></div></div>
          <div class="col-md-3"><div class="card"><div class="card-body py-2"><b>Extra nel file</b><br>{{ summary.extra }}</div></div></div>
        </div>
        {% if download_url %}
          <a href="{{ download_url }}" class="btn btn-success btn-sm mb-3">📥 Scarica risultato Excel</a>
        {% endif %}
      {% endif %}

      {% if rows %}
      <div class="table-responsive" style="max-height:70vh; overflow:auto;">
        <table class="table table-sm table-bordered table-striped align-middle">
          <thead class="table-light" style="position:sticky; top:0; z-index:1;">
            <tr>
              {% for h in headers %}<th>{{ h }}</th>{% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for r in rows %}
            <tr class="{% if r['Stato'] == 'OK' %}table-success{% elif r['Stato'] == 'DIFFERENZA' %}table-warning{% elif 'MANCANTE' in r['Stato'] %}table-danger{% else %}table-info{% endif %}">
              {% for h in headers %}<td>{{ r[h] }}</td>{% endfor %}
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}
    </div>
    {% endblock %}
    """

    def _cmp_norm_value(v):
        return re.sub(r'[^A-Z0-9]+', '', str(v or '').strip().upper())

    def _cmp_num(v):
        if v is None:
            return 0.0
        s = str(v).strip()
        if not s or s.lower() in ('nan', 'none'):
            return 0.0
        try:
            # Gestisce sia 1.234,56 sia 1234.56
            if ',' in s and '.' in s:
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '.')
            return float(s)
        except Exception:
            return 0.0

    def _cmp_fmt(v):
        try:
            f = float(v or 0)
            if abs(f - int(f)) < 0.00001:
                return str(int(f))
            return (f"{f:.3f}").rstrip('0').rstrip('.').replace('.', ',')
        except Exception:
            return str(v or '')

    def _cmp_header_key(v):
        return re.sub(r'[^A-Z0-9]+', '', str(v or '').strip().upper())

    def _cmp_find_col(columns, aliases):
        mapped = { _cmp_header_key(c): c for c in columns }
        alias_keys = [_cmp_header_key(a) for a in aliases]
        for ak in alias_keys:
            if ak in mapped:
                return mapped[ak]
        for ak in alias_keys:
            for k, original in mapped.items():
                if ak and (ak in k or k in ak):
                    return original
        return None

    def _cmp_profile(cliente):
        cn = _cmp_norm_value(cliente)
        if 'GALVANO' in cn:
            return {
                'nome': 'GALVANO TECNICA',
                'key_fields': ['codice_articolo', 'lotto'],
                'metrics': ['pezzo', 'peso'],
                'labels': {'codice_articolo': 'Codice', 'lotto': 'Lotto', 'pezzo': 'Pezzi', 'peso': 'Peso'}
            }
        if 'DUFERCO' in cn:
            return {
                'nome': 'DUFERCO',
                'key_fields': ['serial_number'],
                'metrics': ['n_colli'],
                'labels': {'serial_number': 'Seriale', 'n_colli': 'Colli'}
            }
        if 'FINCANTIERI' in cn:
            return {
                'nome': 'FINCANTIERI',
                'key_fields': ['codice_articolo'],
                'metrics': ['n_colli'],
                'labels': {'codice_articolo': 'Codice', 'n_colli': 'Colli'}
            }
        return {
            'nome': cliente or 'GENERALE',
            'key_fields': ['codice_articolo'],
            'metrics': ['n_colli'],
            'labels': {'codice_articolo': 'Codice', 'n_colli': 'Colli'}
        }

    def _cmp_key_from_values(values, key_fields):
        return tuple(_cmp_norm_value(values.get(k, '')) for k in key_fields)

    def _cmp_display_key(values, key_fields):
        return ' | '.join(str(values.get(k, '') or '').strip() for k in key_fields)

    def _cmp_read_inventory_file(file_storage):
        import pandas as pd
        filename = (getattr(file_storage, 'filename', '') or '').lower()
        if filename.endswith('.csv'):
            return pd.read_csv(file_storage, dtype=str).fillna('')
        return pd.read_excel(file_storage, dtype=str).fillna('')

    def _cmp_aliases():
        return {
            'codice_articolo': ['codice articolo', 'codice_articolo', 'codice', 'cod art', 'codice art', 'article code', 'item code', 'part number', 'pn'],
            'pezzo': ['pezzi', 'pezzo', 'pz', 'qta', 'qtà', 'quantita', 'quantità', 'quantity', 'qty'],
            'peso': ['peso', 'kg', 'peso kg', 'weight'],
            'lotto': ['lotto', 'lot', 'batch'],
            'serial_number': ['seriale', 'serial', 'serial number', 'serial_number', 's/n', 'sn'],
            'n_colli': ['colli', 'n colli', 'n_colli', 'numero colli', 'package', 'packages', 'pallet', 'pallets']
        }

    def _cmp_aggregate_db(db, cliente, profile):
        q = db.query(Articolo)
        cn = normalize_text_key(cliente)
        if cn:
            q = q.filter(normalized_sql_text(Articolo.cliente) == cn)
        q = q.filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == ''))
        q = q.filter(or_(Articolo.n_ddt_uscita == None, Articolo.n_ddt_uscita == ''))

        data = {}
        for r in q.all():
            vals = {
                'codice_articolo': getattr(r, 'codice_articolo', '') or '',
                'lotto': getattr(r, 'lotto', '') or '',
                'serial_number': getattr(r, 'serial_number', '') or '',
                'pezzo': getattr(r, 'pezzo', '') or '',
                'peso': getattr(r, 'peso', '') or '',
                'n_colli': getattr(r, 'n_colli', '') or '',
            }
            key = _cmp_key_from_values(vals, profile['key_fields'])
            if not any(key):
                continue
            item = data.setdefault(key, {'display': _cmp_display_key(vals, profile['key_fields']), 'ids': [], 'values': {m: 0.0 for m in profile['metrics']}})
            item['ids'].append(str(getattr(r, 'id_articolo', '')))
            for m in profile['metrics']:
                item['values'][m] += _cmp_num(vals.get(m))
        return data

    def _cmp_aggregate_file(df, profile):
        aliases = _cmp_aliases()
        col_map = {}
        missing = []
        for f in profile['key_fields'] + profile['metrics']:
            c = _cmp_find_col(df.columns, aliases.get(f, [f]))
            if c is None:
                missing.append(profile['labels'].get(f, f))
            else:
                col_map[f] = c
        if missing:
            raise ValueError('Nel file Excel mancano queste colonne: ' + ', '.join(missing))

        data = {}
        for _, row in df.iterrows():
            vals = {f: (row.get(col_map[f], '') if f in col_map else '') for f in profile['key_fields'] + profile['metrics']}
            key = _cmp_key_from_values(vals, profile['key_fields'])
            if not any(key):
                continue
            item = data.setdefault(key, {'display': _cmp_display_key(vals, profile['key_fields']), 'values': {m: 0.0 for m in profile['metrics']}})
            for m in profile['metrics']:
                item['values'][m] += _cmp_num(vals.get(m))
        return data, col_map

    def _cmp_compare(db_data, inv_data, profile):
        rows = []
        all_keys = sorted(set(db_data.keys()) | set(inv_data.keys()), key=lambda k: str(k))
        for key in all_keys:
            d = db_data.get(key)
            i = inv_data.get(key)
            if d and i:
                diffs = []
                rec = {
                    'Stato': 'OK',
                    'Chiave confronto': d.get('display') or i.get('display'),
                    'ID Gestionale': ', '.join(d.get('ids', [])[:12])
                }
                for m in profile['metrics']:
                    gv = d['values'].get(m, 0.0)
                    iv = i['values'].get(m, 0.0)
                    rec[f"Gestionale {profile['labels'].get(m, m)}"] = _cmp_fmt(gv)
                    rec[f"Inventario {profile['labels'].get(m, m)}"] = _cmp_fmt(iv)
                    tolerance = 0.02 if m == 'peso' else 0.0001
                    if abs(gv - iv) > tolerance:
                        diffs.append(profile['labels'].get(m, m))
                if diffs:
                    rec['Stato'] = 'DIFFERENZA'
                    rec['Note'] = 'Differenza su: ' + ', '.join(diffs)
                else:
                    rec['Note'] = ''
                rows.append(rec)
            elif d and not i:
                rec = {'Stato': 'MANCANTE IN INVENTARIO', 'Chiave confronto': d.get('display'), 'ID Gestionale': ', '.join(d.get('ids', [])[:12])}
                for m in profile['metrics']:
                    rec[f"Gestionale {profile['labels'].get(m, m)}"] = _cmp_fmt(d['values'].get(m, 0.0))
                    rec[f"Inventario {profile['labels'].get(m, m)}"] = '0'
                rec['Note'] = 'Presente nel gestionale ma non nel file inventario'
                rows.append(rec)
            elif i and not d:
                rec = {'Stato': 'EXTRA NEL FILE', 'Chiave confronto': i.get('display'), 'ID Gestionale': ''}
                for m in profile['metrics']:
                    rec[f"Gestionale {profile['labels'].get(m, m)}"] = '0'
                    rec[f"Inventario {profile['labels'].get(m, m)}"] = _cmp_fmt(i['values'].get(m, 0.0))
                rec['Note'] = 'Presente nel file inventario ma non trovato in giacenza'
                rows.append(rec)
        return rows

    @app.route('/confronta-inventario', methods=['GET', 'POST'])
    @login_required
    def confronta_inventario():
        if session.get('role') not in ('admin', 'magazzino'):
            return "Accesso negato", 403
        error = None
        rows = []
        headers = []
        summary = None
        download_url = None
        cliente = ''

        if request.method == 'POST':
            db = SessionLocal()
            try:
                cliente = (request.form.get('cliente') or '').strip()
                file_inv = request.files.get('file_inventario')
                if not cliente:
                    raise ValueError('Indica il cliente da confrontare.')
                if not file_inv or not (file_inv.filename or '').strip():
                    raise ValueError('Carica un file Excel inventario.')

                profile = _cmp_profile(cliente)
                df = _cmp_read_inventory_file(file_inv)
                db_data = _cmp_aggregate_db(db, cliente, profile)
                inv_data, col_map = _cmp_aggregate_file(df, profile)
                rows = _cmp_compare(db_data, inv_data, profile)

                # Ordine: prima differenze e mancanti, poi OK.
                order = {'DIFFERENZA': 0, 'MANCANTE IN INVENTARIO': 1, 'EXTRA NEL FILE': 2, 'OK': 3}
                rows.sort(key=lambda r: (order.get(r.get('Stato'), 9), r.get('Chiave confronto', '')))

                headers = list(rows[0].keys()) if rows else ['Stato', 'Chiave confronto', 'Note']
                summary = {
                    'ok': sum(1 for r in rows if r.get('Stato') == 'OK'),
                    'diff': sum(1 for r in rows if r.get('Stato') == 'DIFFERENZA'),
                    'missing': sum(1 for r in rows if r.get('Stato') == 'MANCANTE IN INVENTARIO'),
                    'extra': sum(1 for r in rows if r.get('Stato') == 'EXTRA NEL FILE'),
                }

                # Salva risultato Excel in docs.
                import pandas as pd
                safe_cliente = re.sub(r'[^A-Za-z0-9_-]+', '_', cliente).strip('_') or 'cliente'
                filename = f"confronto_inventario_{safe_cliente}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                out_dir = DOCS_DIR if 'DOCS_DIR' in globals() else MEDIA_DIR
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / filename
                pd.DataFrame(rows).to_excel(out_path, index=False)
                download_url = url_for('scarica_confronto_inventario', filename=filename)

            except Exception as e:
                error = str(e)
            finally:
                db.close()

        return render_template_string(
            CONFRONTA_INVENTARIO_HTML,
            cliente=cliente,
            error=error,
            rows=rows,
            headers=headers,
            summary=summary,
            download_url=download_url,
        )

    @app.route('/confronta-inventario/download/<path:filename>', methods=['GET'])
    @login_required
    def scarica_confronto_inventario(filename):
        if session.get('role') not in ('admin', 'magazzino'):
            return "Accesso negato", 403
        safe = secure_filename(filename)
        base = DOCS_DIR if 'DOCS_DIR' in globals() else MEDIA_DIR
        path = base / safe
        if not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=safe)


    # ==============================================================================
    #  3. FUNZIONE ELIMINA (Risolve l'errore 'endpoint elimina_record')
    # ==============================================================================
