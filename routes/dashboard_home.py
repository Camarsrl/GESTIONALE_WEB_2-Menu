# -*- coding: utf-8 -*-
"""
Modulo Dashboard/Home Gestionale Camar.

Correzioni:
- riepilogo colli/M2/peso per cliente
- buoni QR creati/aperti/usciti
- conteggio giacenze attive più robusto su data_uscita vuota/None/NaT
"""

HOME_HTML = ''  # Template spostato in templates/dashboard_home.html


def register_dashboard_home_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    from pathlib import Path
    from datetime import date, timedelta, datetime
    from flask import render_template, render_template_string, request, redirect, url_for
    from flask_login import login_required
    from sqlalchemy import func, or_, case

    def _is_active_expr():
        return func.upper(func.trim(func.coalesce(Articolo.data_uscita, ''))).in_(['', 'NONE', 'NULL', 'NAT'])

    def _cliente_key_expr(col):
        return func.upper(func.trim(func.coalesce(col, '')))

    try:
        app_obj.view_functions.pop('home', None)
    except Exception:
        pass


    @app_obj.route('/dashboard/clienti-da-verificare', endpoint='dashboard_clienti_da_verificare')
    @login_required
    def dashboard_clienti_da_verificare():
        """Mostra le righe che la dashboard non riesce ad associare a un cliente valido.
        Serve per capire quali record generano la riga 'SENZA CLIENTE' / 'CLIENTE DA VERIFICARE'.
        """
        db = SessionLocal()
        try:
            def _norm_cliente_token(v):
                return re.sub(r'[^A-Z0-9]+', '', (v or '').upper())

            try:
                clienti_validi = list(get_clienti_utenti())
            except Exception:
                clienti_validi = []

            alias_cliente = {}
            for c in clienti_validi:
                cn = (c or '').strip().upper()
                if not cn:
                    continue
                alias_cliente[_norm_cliente_token(cn)] = cn
                if _norm_cliente_token(cn) == 'RFDEWAVE':
                    alias_cliente['DEWAVERF'] = cn
                if _norm_cliente_token(cn) == 'DEWAVERF':
                    alias_cliente['RFDEWAVE'] = cn
                if _norm_cliente_token(cn) == 'GALVANOTECNICA':
                    alias_cliente['GALVANOTECNICA'] = cn

            def _cliente_riconosciuto(raw_cliente, codice_entrata=None):
                raw = (raw_cliente or '').strip()
                raw_up = raw.upper()
                if raw and raw_up not in ('NONE', 'NULL', 'NAT', 'NAN', 'SENZA CLIENTE'):
                    nraw = _norm_cliente_token(raw)
                    if nraw in alias_cliente:
                        return alias_cliente[nraw], True, nraw
                    # Se il campo cliente è valorizzato ma non corrisponde agli utenti,
                    # lo mostriamo comunque come da verificare.
                    return raw_up, False, nraw

                codice = (codice_entrata or '').strip().upper()
                if codice.startswith('ENT-'):
                    parts = codice.split('-')
                    if len(parts) >= 4:
                        token = _norm_cliente_token(parts[2])
                        if token in alias_cliente:
                            return alias_cliente[token], True, token
                        if token in ('RFDEWAVE', 'DEWAVERF') and 'RF-DE WAVE' in clienti_validi:
                            return 'RF-DE WAVE', True, token
                return 'SENZA CLIENTE', False, ''

            cliente_corrente = current_cliente()
            filters = [_is_active_expr()]
            if cliente_corrente:
                filters.append(_cliente_key_expr(Articolo.cliente) == cliente_corrente.upper())

            rows = (
                db.query(Articolo)
                .filter(*filters)
                .order_by(Articolo.id_articolo.desc())
                .limit(1000)
                .all()
            )

            problemi = []
            for a in rows:
                nome, ok, norm = _cliente_riconosciuto(getattr(a, 'cliente', None), getattr(a, 'codice_entrata', None))
                raw = (getattr(a, 'cliente', '') or '').strip()
                if (not ok) or nome in ('SENZA CLIENTE', 'CLIENTE DA VERIFICARE'):
                    problemi.append({
                        'id': getattr(a, 'id_articolo', ''),
                        'cliente_raw': raw or '-',
                        'cliente_letto': nome,
                        'normalizzato': norm or '-',
                        'codice_entrata': getattr(a, 'codice_entrata', '') or '-',
                        'n_arrivo': getattr(a, 'n_arrivo', '') or '-',
                        'ddt': getattr(a, 'n_ddt_ingresso', '') or '-',
                        'codice': getattr(a, 'codice_articolo', '') or '-',
                        'descrizione': (getattr(a, 'descrizione', '') or '-')[:120],
                        'colli': getattr(a, 'n_colli', '') or 0,
                    })

            html = """
            {% extends 'base.html' %}
            {% block content %}
            <div class="container-fluid py-3">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div>
                        <h4 class="mb-0">Righe cliente da verificare</h4>
                        <div class="text-muted small">Queste sono le righe che generano la voce SENZA CLIENTE / CLIENTE DA VERIFICARE nella dashboard.</div>
                    </div>
                    <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Torna alla dashboard</a>
                </div>
                <div class="alert alert-info">
                    Se qui vedi un cliente valorizzato, significa che il nome nel database non coincide perfettamente con l'elenco utenti/clienti. Puoi aprire la riga e correggere il campo Cliente.
                </div>
                <div class="table-responsive">
                    <table class="table table-sm table-striped align-middle">
                        <thead>
                            <tr>
                                <th>ID</th><th>Cliente nel DB</th><th>Cliente letto</th><th>Normalizzato</th><th>N. Arrivo</th><th>DDT</th><th>Codice</th><th>Descrizione</th><th class="text-end">Colli</th><th></th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for r in problemi %}
                            <tr>
                                <td>{{ r.id }}</td>
                                <td>{{ r.cliente_raw }}</td>
                                <td>{{ r.cliente_letto }}</td>
                                <td><code>{{ r.normalizzato }}</code></td>
                                <td>{{ r.n_arrivo }}</td>
                                <td>{{ r.ddt }}</td>
                                <td>{{ r.codice }}</td>
                                <td>{{ r.descrizione }}</td>
                                <td class="text-end">{{ r.colli }}</td>
                                <td><a class="btn btn-sm btn-outline-primary" href="{{ url_for('giacenze', id=r.id) }}">Apri</a></td>
                            </tr>
                        {% else %}
                            <tr><td colspan="10" class="text-center text-muted py-3">Nessuna riga da verificare.</td></tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            {% endblock %}
            """
            return render_template_string(html, problemi=problemi)
        except Exception as e:
            try:
                scrivi_log_errore('Errore righe cliente da verificare dashboard', e)
            except Exception:
                pass
            return f"<h1>Errore</h1><p>{e}</p><a href='/home'>Torna alla dashboard</a>", 500
        finally:
            try:
                db.close()
            except Exception:
                pass

    @app_obj.route('/dashboard/cerca', endpoint='dashboard_ricerca_globale')
    @login_required
    def dashboard_ricerca_globale():
        query_value = (request.args.get('q') or '').strip()
        if not query_value:
            return redirect(url_for('home'))

        db = SessionLocal()
        try:
            like_value = f"%{query_value}%"
            filters = [
                or_(
                    Articolo.codice_articolo.ilike(like_value),
                    Articolo.lotto.ilike(like_value),
                    Articolo.n_arrivo.ilike(like_value),
                    Articolo.protocollo.ilike(like_value),
                    Articolo.serial_number.ilike(like_value),
                    Articolo.cliente.ilike(like_value),
                    Articolo.n_ddt_ingresso.ilike(like_value),
                    Articolo.n_ddt_uscita.ilike(like_value),
                    Articolo.buono_n.ilike(like_value),
                    Articolo.descrizione.ilike(like_value),
                )
            ]
            cliente_corrente = ''
            try:
                role_value = (session.get('role') or getattr(current_user, 'role', '') or '').strip().lower()
                if role_value == 'client':
                    cliente_corrente = (getattr(current_user, 'id', '') or session.get('user') or '').strip().upper()
            except Exception:
                cliente_corrente = ''
            if cliente_corrente:
                filters.append(func.upper(func.coalesce(Articolo.cliente, '')) == cliente_corrente)

            rows = (
                db.query(Articolo)
                .filter(*filters)
                .order_by(Articolo.id_articolo.desc())
                .limit(200)
                .all()
            )

            if len(rows) == 1:
                return redirect(url_for('giacenze', id=rows[0].id_articolo))

            html = """
            {% extends 'base.html' %}
            {% block content %}
            <div class="container-fluid py-3">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div>
                        <h4 class="mb-0"><i class="bi bi-search"></i> Ricerca globale</h4>
                        <div class="text-muted">Risultati per: <b>{{ query_value }}</b></div>
                    </div>
                    <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Dashboard</a>
                </div>
                <div class="table-responsive">
                    <table class="table table-sm table-striped align-middle">
                        <thead>
                            <tr>
                                <th>ID</th><th>Cliente</th><th>Codice</th><th>Descrizione</th>
                                <th>Lotto</th><th>N. Arrivo</th><th>Protocollo</th><th>Seriale</th><th>Buono</th><th></th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for r in rows %}
                            <tr>
                                <td>{{ r.id_articolo }}</td>
                                <td>{{ r.cliente or '-' }}</td>
                                <td>{{ r.codice_articolo or '-' }}</td>
                                <td>{{ (r.descrizione or '-')[:100] }}</td>
                                <td>{{ r.lotto or '-' }}</td>
                                <td>{{ r.n_arrivo or '-' }}</td>
                                <td>{{ r.protocollo or '-' }}</td>
                                <td>{{ r.serial_number or '-' }}</td>
                                <td>{{ r.buono_n or '-' }}</td>
                                <td><a class="btn btn-sm btn-outline-primary" href="{{ url_for('giacenze', id=r.id_articolo) }}">Apri</a></td>
                            </tr>
                        {% else %}
                            <tr><td colspan="10" class="text-center text-muted py-4">Nessun risultato.</td></tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            {% endblock %}
            """
            return render_template_string(html, rows=rows, query_value=query_value)
        finally:
            db.close()


    @app_obj.route('/home', endpoint='home')
    @login_required
    def home():
        db = SessionLocal()
        try:
            today_obj = date.today()
            today_iso = today_obj.strftime('%Y-%m-%d')
            today_it = today_obj.strftime('%d/%m/%Y')
            cutoff_90_iso = (today_obj - timedelta(days=90)).strftime('%Y-%m-%d')
            cliente_corrente = current_cliente()

            def _cliente_filter(model=Articolo):
                if cliente_corrente:
                    return [_cliente_key_expr(model.cliente) == cliente_corrente.upper()]
                return []

            active_filter = [_is_active_expr()] + _cliente_filter(Articolo)
            all_filter = _cliente_filter(Articolo)

            def _scalar(query, default=0):
                try:
                    v = query.scalar()
                    return default if v is None else v
                except Exception:
                    return default

            def _count_articoli(extra_filters=None):
                q = db.query(func.count(Articolo.id_articolo))
                filters = list(extra_filters or [])
                if filters:
                    q = q.filter(*filters)
                return int(_scalar(q, 0) or 0)

            def _sum_articoli(column, extra_filters=None):
                q = db.query(func.coalesce(func.sum(column), 0))
                filters = list(extra_filters or [])
                if filters:
                    q = q.filter(*filters)
                try:
                    return float(q.scalar() or 0)
                except Exception:
                    return 0.0

            def _examples(extra_filters, attr, max_items=5):
                try:
                    col = getattr(Articolo, attr)
                    rows_ex = (
                        db.query(col)
                        .filter(*(extra_filters or []))
                        .filter(col != None, col != '')
                        .limit(max_items)
                        .all()
                    )
                    out = []
                    for (val,) in rows_ex:
                        val = (str(val or '')).strip()
                        if val and val not in out:
                            out.append(val)
                    return out[:max_items]
                except Exception:
                    return []

            def _add_alert(alerts, level, title, count, message, examples=None, url=None):
                try:
                    count = int(count or 0)
                except Exception:
                    count = 0
                if count > 0:
                    alerts.append({
                        'level': level,
                        'title': title,
                        'count': count,
                        'message': message,
                        'examples': examples or [],
                        'url': url or url_for('giacenze')
                    })

            dashboard = {
                'tot_giacenza': _count_articoli(active_filter),
                'tot_m2': round(_sum_articoli(Articolo.m2, active_filter), 2),
                'tot_peso': round(_sum_articoli(Articolo.peso, active_filter), 2),
                'tot_colli': int(_sum_articoli(Articolo.n_colli, active_filter)),
                'entrate_oggi': _count_articoli(all_filter + [
                    or_(Articolo.data_ingresso == today_iso, Articolo.data_ingresso == today_it)
                ]),
                'uscite_oggi': _count_articoli(all_filter + [
                    or_(Articolo.data_uscita == today_iso, Articolo.data_uscita == today_it)
                ]),
                'doganali': _count_articoli(active_filter + [
                    func.upper(func.coalesce(Articolo.stato, '')).like('%DOGANA%')
                ]),
                'buoni_aperti': 0,
                'buoni_creati': 0,
                'buoni_usciti': 0,
            }

            def _norm_buono_prelievo(value):
                """Normalizza N. Buono di Prelievo per conteggi distinti."""
                s = (value or '').strip()
                if not s or s.upper() in ('NONE', 'NULL', 'NAT', 'NAN', '-'):
                    return ''
                return s.upper()

            def _has_uscita_buono(data_uscita, n_ddt_uscita):
                du = (str(data_uscita or '').strip()).upper()
                nd = (str(n_ddt_uscita or '').strip()).upper()
                return bool((du and du not in ('NONE', 'NULL', 'NAT', 'NAN')) or (nd and nd not in ('NONE', 'NULL', 'NAT', 'NAN', '-')))

            def _calcola_buoni_prelievo_dashboard():
                """Conta i Buoni di Prelievo dalla tabella Articoli, non dai Buoni QR di carico.

                Creati = buono_n distinto valorizzato.
                Usciti = buono_n distinto con DDT/Data uscita valorizzati.
                Aperti = creati - usciti.
                """
                stats = {}
                try:
                    q = db.query(
                        Articolo.cliente,
                        Articolo.codice_entrata,
                        Articolo.buono_n,
                        Articolo.data_uscita,
                        Articolo.n_ddt_uscita,
                    ).filter(*(all_filter + [Articolo.buono_n != None, Articolo.buono_n != '']))
                    for cli_raw, cod_ent, buono_raw, data_usc, ddt_usc in q.all():
                        bkey = _norm_buono_prelievo(buono_raw)
                        if not bkey:
                            continue
                        try:
                            nome_cli = _cliente_dashboard(cli_raw, cod_ent)
                        except Exception:
                            nome_cli = (cli_raw or 'CLIENTE DA VERIFICARE').strip().upper()
                        rec = stats.setdefault(nome_cli, {})
                        item = rec.setdefault(bkey, {'uscito': False})
                        if _has_uscita_buono(data_usc, ddt_usc):
                            item['uscito'] = True
                except Exception:
                    return {}, {'buoni_creati': 0, 'buoni_usciti': 0, 'buoni_aperti': 0}

                by_cliente = {}
                totale_creati = totale_usciti = 0
                for nome_cli, buoni in stats.items():
                    creati = len(buoni)
                    usciti = sum(1 for v in buoni.values() if v.get('uscito'))
                    aperti = max(0, creati - usciti)
                    by_cliente[nome_cli] = {
                        'buoni_creati': creati,
                        'buoni_usciti': usciti,
                        'buoni_aperti': aperti,
                    }
                    totale_creati += creati
                    totale_usciti += usciti

                totale = {
                    'buoni_creati': totale_creati,
                    'buoni_usciti': totale_usciti,
                    'buoni_aperti': max(0, totale_creati - totale_usciti),
                }
                return by_cliente, totale

            buoni_by_cliente_global = {}
            try:
                # Conteggio corretto dei Buoni di Prelievo creati dalla schermata Buono.
                buoni_by_cliente_global, buoni_totali = _calcola_buoni_prelievo_dashboard()
                dashboard['buoni_creati'] = int(buoni_totali.get('buoni_creati', 0) or 0)
                dashboard['buoni_usciti'] = int(buoni_totali.get('buoni_usciti', 0) or 0)
                dashboard['buoni_aperti'] = int(buoni_totali.get('buoni_aperti', 0) or 0)
            except Exception:
                pass

            movimenti = []

            def _add_movimenti_ingresso():
                q = db.query(
                    Articolo.data_ingresso, Articolo.cliente, Articolo.codice_articolo,
                    Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_ingresso,
                    Articolo.created_by, Articolo.updated_by
                ).filter(*(all_filter + [Articolo.data_ingresso != None, Articolo.data_ingresso != '']))
                q = q.order_by(Articolo.id_articolo.desc()).limit(20)
                for d_in_raw, cli, cod, desc, arr, ddt, created_by, updated_by in q.all():
                    d_in = to_date_db(d_in_raw)
                    if not d_in:
                        continue
                    movimenti.append({
                        'data_sort': d_in,
                        'data': d_in.strftime('%d/%m/%Y'),
                        'tipo': 'Entrata',
                        'cliente': cli or '',
                        'codice': cod or '',
                        'descrizione': (desc or '')[:60],
                        'n_arrivo': arr or '',
                        'ddt': ddt or '',
                        'operatore': created_by or updated_by or '',
                    })

            def _add_movimenti_uscita():
                q = db.query(
                    Articolo.data_uscita, Articolo.cliente, Articolo.codice_articolo,
                    Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_uscita,
                    Articolo.updated_by, Articolo.created_by
                ).filter(*(all_filter + [Articolo.data_uscita != None, Articolo.data_uscita != '']))
                q = q.order_by(Articolo.id_articolo.desc()).limit(20)
                for d_out_raw, cli, cod, desc, arr, ddt, updated_by, created_by in q.all():
                    d_out = to_date_db(d_out_raw)
                    if not d_out:
                        continue
                    movimenti.append({
                        'data_sort': d_out,
                        'data': d_out.strftime('%d/%m/%Y'),
                        'tipo': 'Uscita',
                        'cliente': cli or '',
                        'codice': cod or '',
                        'descrizione': (desc or '')[:60],
                        'n_arrivo': arr or '',
                        'ddt': ddt or '',
                        'operatore': updated_by or created_by or '',
                    })

            try:
                _add_movimenti_ingresso()
                _add_movimenti_uscita()
            except Exception:
                movimenti = []

            ultimi_movimenti = sorted(
                movimenti,
                key=lambda x: x.get('data_sort') or date.min,
                reverse=True
            )[:10]

            dashboard_alerts = []

            uscite_candidate_filter = all_filter + [
                Articolo.data_uscita != None,
                Articolo.data_uscita != '',
                or_(Articolo.mezzi_in_uscita == None, Articolo.mezzi_in_uscita == ''),
                Articolo.n_ddt_uscita != None,
                Articolo.n_ddt_uscita != '',
            ]
            uscite_senza_mezzo_count = 0
            uscite_senza_mezzo_examples = []
            try:
                candidate_ddt = db.query(Articolo.n_ddt_uscita).filter(*uscite_candidate_filter).limit(500).all()
                seen = set()
                for (n_ddt,) in candidate_ddt:
                    n = (n_ddt or '').strip()
                    if re.match(r'^\d{1,5}/\d{2}$', n):
                        uscite_senza_mezzo_count += 1
                        if n not in seen and len(uscite_senza_mezzo_examples) < 5:
                            seen.add(n)
                            uscite_senza_mezzo_examples.append(n)
            except Exception:
                pass
            _add_alert(
                dashboard_alerts, 'danger', 'DDT gestionale senza mezzo',
                uscite_senza_mezzo_count,
                'DDT creati dal gestionale senza Motrice / Bilico / Furgone compilato.',
                uscite_senza_mezzo_examples,
                url_for('giacenze', solo_uscite='1', mezzo_uscita='')
            )

            # Alert operativi essenziali: nessun controllo sulle posizioni.
            try:
                negativi_filter = active_filter + [Articolo.n_colli < 0]
                _add_alert(
                    dashboard_alerts, 'danger', 'Colli negativi',
                    _count_articoli(negativi_filter),
                    'Righe in giacenza con numero colli negativo.',
                    _examples(negativi_filter, 'id_articolo'),
                    url_for('dashboard_ricerca_globale', q='-')
                )
            except Exception:
                pass

            try:
                ddt_attivo_filter = active_filter + [
                    Articolo.n_ddt_uscita != None,
                    Articolo.n_ddt_uscita != ''
                ]
                _add_alert(
                    dashboard_alerts, 'danger', 'Articoli attivi con DDT uscita',
                    _count_articoli(ddt_attivo_filter),
                    'Righe ancora considerate in giacenza ma con DDT di uscita compilato.',
                    _examples(ddt_attivo_filter, 'n_ddt_uscita'),
                    url_for('giacenze', solo_in_giacenza='1')
                )
            except Exception:
                pass

            if int(dashboard.get('buoni_aperti') or 0) > 0:
                _add_alert(
                    dashboard_alerts, 'warning', 'Buoni aperti',
                    dashboard.get('buoni_aperti'),
                    'Buoni di prelievo creati ma non ancora completati con uscita.',
                    [],
                    url_for('giacenze', buono_n='')
                )

            level_order = {'danger': 0, 'warning': 1, 'info': 2}
            dashboard_alerts = sorted(dashboard_alerts, key=lambda x: (level_order.get(x.get('level'), 9), -int(x.get('count') or 0)))

            # Riepilogo giacenze diviso per cliente.
            # Query semplice e indipendente dall'anagrafica utenti:
            # mostra tutti i clienti realmente presenti nelle righe attive.
            dashboard_clienti = []
            try:
                cliente_expr = func.upper(
                    func.trim(
                        func.coalesce(Articolo.cliente, '')
                    )
                )

                rows_clienti = (
                    db.query(
                        cliente_expr.label('cliente'),
                        func.count(Articolo.id_articolo).label('righe'),
                        func.coalesce(func.sum(Articolo.n_colli), 0).label('colli'),
                        func.coalesce(func.sum(Articolo.m2), 0).label('m2'),
                        func.coalesce(func.sum(Articolo.peso), 0).label('peso'),
                    )
                    .filter(*active_filter)
                    .group_by(cliente_expr)
                    .order_by(cliente_expr.asc())
                    .all()
                )

                for cliente_val, righe_val, colli_val, m2_val, peso_val in rows_clienti:
                    nome_cliente = str(cliente_val or '').strip().upper()
                    if not nome_cliente or nome_cliente in ('NONE', 'NULL', 'NAT', 'NAN'):
                        nome_cliente = 'CLIENTE DA VERIFICARE'

                    dati_buoni = {}
                    try:
                        # Ricerca tollerante alle differenze di maiuscole/spazi.
                        for key_buono, value_buono in (buoni_by_cliente_global or {}).items():
                            if str(key_buono or '').strip().upper() == nome_cliente:
                                dati_buoni = value_buono or {}
                                break
                    except Exception:
                        dati_buoni = {}

                    dashboard_clienti.append({
                        'cliente': nome_cliente,
                        'righe': int(righe_val or 0),
                        'colli': int(colli_val or 0),
                        'm2': round(float(m2_val or 0), 2),
                        'peso': round(float(peso_val or 0), 2),
                        'buoni_aperti': int(dati_buoni.get('buoni_aperti', 0) or 0),
                        'buoni_creati': int(dati_buoni.get('buoni_creati', 0) or 0),
                        'buoni_usciti': int(dati_buoni.get('buoni_usciti', 0) or 0),
                        'da_verificare': nome_cliente == 'CLIENTE DA VERIFICARE',
                    })

                # Ordine alfabetico, lasciando l'eventuale voce da verificare in fondo.
                dashboard_clienti.sort(
                    key=lambda row: (
                        row.get('cliente') == 'CLIENTE DA VERIFICARE',
                        row.get('cliente') or ''
                    )
                )

                # Mantiene il totale colli coerente con la tabella per cliente.
                dashboard['tot_colli'] = int(
                    sum(int(row.get('colli') or 0) for row in dashboard_clienti)
                )

            except Exception as clienti_error:
                try:
                    app_obj.logger.error(
                        f"[DASHBOARD] errore riepilogo giacenze per cliente: {clienti_error}"
                    )
                except Exception:
                    pass
                dashboard_clienti = []

            backup_status = {
                'exists': False,
                'today': False,
                'date': '',
                'time': '',
                'size_mb': 0,
                'filename': '',
            }
            try:
                backup_dir = Path(MEDIA_DIR) / 'backups'
                files_backup = sorted(
                    backup_dir.glob('backup_camar_*.zip'),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if files_backup:
                    latest = files_backup[0]
                    dt_backup = datetime.fromtimestamp(latest.stat().st_mtime)
                    backup_status.update({
                        'exists': True,
                        'today': dt_backup.date() == today_obj,
                        'date': dt_backup.strftime('%d/%m/%Y'),
                        'time': dt_backup.strftime('%H:%M'),
                        'size_mb': round(latest.stat().st_size / (1024 * 1024), 2),
                        'filename': latest.name,
                    })
            except Exception:
                pass

            return render_template(
                'dashboard_home.html',
                dashboard=dashboard,
                dashboard_clienti=dashboard_clienti,
                dashboard_alerts=dashboard_alerts,
                ultimi_movimenti=ultimi_movimenti,
                backup_status=backup_status,
                today=today_obj,
                tot_articoli=dashboard['tot_giacenza'],
                tot_m2=dashboard['tot_m2'],
                logo_url=logo_url() if 'logo_url' in globals() else ''
            )
        except Exception as e:
            try:
                scrivi_log_errore('Errore caricamento Home dashboard', e)
            except Exception:
                pass
            return f"<h1>Errore Caricamento Home</h1><p>{e}</p><a href='/logout'>Logout</a>", 500
        finally:
            try:
                db.close()
            except Exception:
                pass
