# -*- coding: utf-8 -*-
"""
Modulo Dashboard/Home Gestionale Camar.

Correzioni:
- riepilogo colli/M2/peso per cliente
- buoni QR creati/aperti/usciti
- conteggio giacenze attive più robusto su data_uscita vuota/None/NaT
"""

HOME_HTML = '\n{% extends \'base.html\' %}\n{% block content %}\n<style>\n.home-kpi-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n    height:100%;\n}\n.home-kpi-icon{\n    width:42px;\n    height:42px;\n    border-radius:12px;\n    display:flex;\n    align-items:center;\n    justify-content:center;\n    background:#eef5ff;\n    color:#0d6efd;\n    font-size:20px;\n}\n.home-kpi-value{\n    font-size:26px;\n    font-weight:700;\n    line-height:1.1;\n}\n.home-section-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n}\n.home-movement-table td,\n.home-movement-table th{\n    vertical-align:middle;\n    font-size:13px;\n}\n\n.home-alert-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n}\n.home-alert-item{\n    border-left:5px solid #ffc107;\n    background:#fff8e1;\n    border-radius:10px;\n    padding:10px 12px;\n    margin-bottom:8px;\n}\n.home-alert-item.danger{\n    border-left-color:#dc3545;\n    background:#fff1f1;\n}\n.home-alert-item.warning{\n    border-left-color:#ffc107;\n    background:#fff8e1;\n}\n.home-alert-item.info{\n    border-left-color:#0d6efd;\n    background:#eef5ff;\n}\n.home-client-table th,\n.home-client-table td{\n    font-size:13px;\n    vertical-align:middle;\n}\n.home-client-table tfoot td{\n    font-weight:700;\n    background:#f8f9fa;\n}\n</style>\n\n<div class="container-fluid py-3">\n    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">\n        <div class="d-flex align-items-center gap-3">\n            {% if logo_url %}<img src="{{ logo_url }}" style="height:50px;width:auto;">{% endif %}\n            <div>\n                <h3 class="m-0">Dashboard Gestionale</h3>\n                <div class="text-muted small">Riepilogo operativo aggiornato al {{ today.strftime(\'%d/%m/%Y\') if today else \'\' }}</div>\n            </div>\n        </div>\n        <div class="d-flex flex-wrap gap-2">\n            <a class="btn btn-primary btn-sm" href="{{ url_for(\'giacenze\') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Giacenze</a>\n            {% if session.get(\'role\') == \'admin\' %}\n            <a class="btn btn-success btn-sm" href="{{ url_for(\'nuovo_articolo\') }}"><i class="bi bi-plus-circle"></i> Nuovo articolo</a>\n            {% endif %}\n            {% if can_use_buoni_qr() %}\n            <a class="btn btn-outline-primary btn-sm" href="{{ url_for(\'scan_entrata\') }}"><i class="bi bi-upc-scan"></i> Scan entrata</a>\n            {% endif %}\n        </div>\n    </div>\n\n    <div class="row g-3 mb-3">\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Articoli in giacenza</div>\n                        <div class="home-kpi-value">{{ dashboard.tot_giacenza }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-box-seam"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">M² occupati</div>\n                        <div class="home-kpi-value">{{ dashboard.tot_m2|it_num(2) }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-rulers"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Entrate oggi</div>\n                        <div class="home-kpi-value">{{ dashboard.entrate_oggi }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-arrow-down-circle"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Uscite oggi</div>\n                        <div class="home-kpi-value">{{ dashboard.uscite_oggi }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-arrow-up-circle"></i></div>\n                </div>\n            </div>\n        </div>\n    </div>\n\n    <div class="row g-3 mb-3">\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Articoli doganali</div>\n                <div class="home-kpi-value">{{ dashboard.doganali }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni QR aperti</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_aperti }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni creati</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_creati }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni usciti</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_usciti }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Peso in giacenza</div>\n                <div class="home-kpi-value">{{ dashboard.tot_peso|it_num(2) }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Colli in giacenza</div>\n                <div class="home-kpi-value">{{ dashboard.tot_colli }}</div>\n            </div>\n        </div>\n    </div>\n\n    {% if dashboard_alerts %}\n    <div class="card home-alert-card p-3 mb-3">\n        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">\n            <h5 class="m-0"><i class="bi bi-bell-fill text-warning"></i> Alert automatici</h5>\n            <span class="badge bg-warning text-dark">{{ dashboard_alerts|length }} segnalazioni</span>\n        </div>\n        <div class="row g-2">\n            {% for alert in dashboard_alerts %}\n            <div class="col-lg-6 col-xxl-4">\n                <div class="home-alert-item {{ alert.level }}">\n                    <div class="d-flex justify-content-between gap-2">\n                        <strong>{{ alert.title }}</strong>\n                        <span class="badge {% if alert.level == \'danger\' %}bg-danger{% elif alert.level == \'warning\' %}bg-warning text-dark{% else %}bg-primary{% endif %}">{{ alert.count }}</span>\n                    </div>\n                    <div class="small text-muted mt-1">{{ alert.message }}</div>\n                    {% if alert.examples %}\n                    <div class="small mt-1"><strong>Esempi:</strong> {{ alert.examples|join(\', \') }}</div>\n                    {% endif %}\n                </div>\n            </div>\n            {% endfor %}\n        </div>\n    </div>\n    {% endif %}\n\n    <div class="card home-section-card p-3 mb-3">\n        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">\n            <h5 class="m-0"><i class="bi bi-people-fill text-primary"></i> Giacenza per cliente</h5>\n            <span class="badge bg-primary">{{ dashboard_clienti|length }} clienti</span>\n        </div>\n        <div class="table-responsive">\n            <table class="table table-sm table-striped home-client-table mb-0">\n                <thead>\n                    <tr>\n                        <th>Cliente</th>\n                        <th class="text-end">Righe</th>\n                        <th class="text-end">Colli</th>\n                        <th class="text-end">M²</th>\n                        <th class="text-end">Peso kg</th>\n                        <th class="text-end">Buoni aperti</th>\n                        <th class="text-end">Buoni creati</th>\n                        <th class="text-end">Buoni usciti</th>\n                    </tr>\n                </thead>\n                <tbody>\n                    {% for r in dashboard_clienti %}\n                    <tr>\n                        <td>{{ r.cliente }}</td>\n                        <td class="text-end">{{ r.righe }}</td>\n                        <td class="text-end">{{ r.colli }}</td>\n                        <td class="text-end">{{ r.m2|it_num(2) }}</td>\n                        <td class="text-end">{{ r.peso|it_num(2) }}</td>\n                        <td class="text-end">{{ r.buoni_aperti }}</td>\n                        <td class="text-end">{{ r.buoni_creati }}</td>\n                        <td class="text-end">{{ r.buoni_usciti }}</td>\n                    </tr>\n                    {% else %}\n                    <tr><td colspan="8" class="text-muted text-center py-3">Nessuna giacenza attiva.</td></tr>\n                    {% endfor %}\n                </tbody>\n                <tfoot>\n                    <tr>\n                        <td>Totale</td>\n                        <td class="text-end">{{ dashboard.tot_giacenza }}</td>\n                        <td class="text-end">{{ dashboard.tot_colli }}</td>\n                        <td class="text-end">{{ dashboard.tot_m2|it_num(2) }}</td>\n                        <td class="text-end">{{ dashboard.tot_peso|it_num(2) }}</td>\n                        <td class="text-end">{{ dashboard.buoni_aperti }}</td>\n                        <td class="text-end">{{ dashboard.buoni_creati }}</td>\n                        <td class="text-end">{{ dashboard.buoni_usciti }}</td>\n                    </tr>\n                </tfoot>\n            </table>\n        </div>\n        <div class="text-muted small mt-2">\n            I colli sono calcolati solo sulle righe ancora in giacenza. Se un articolo ha colli vuoti o pari a 0, viene conteggiato come 0.\n        </div>\n    </div>\n\n    <div class="row g-3">\n        <div class="col-xl-3">\n            <div class="card home-section-card p-3 mb-3">\n                <h6 class="mb-3">Menu rapido</h6>\n                <div class="d-grid gap-2">\n                    <a class="btn btn-primary" href="{{ url_for(\'giacenze\') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Visualizza Giacenze</a>\n                    {% if session.get(\'role\') == \'admin\' %}\n                    <a class="btn btn-success" href="{{ url_for(\'nuovo_articolo\') }}"><i class="bi bi-plus-circle"></i> Nuovo Articolo</a>\n                    <a class="btn btn-outline-secondary" href="{{ url_for(\'labels_form\') }}"><i class="bi bi-tag"></i> Stampa Etichette</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'import_excel\') }}"><i class="bi bi-file-earmark-arrow-up"></i> Import Excel</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'export_excel\') }}"><i class="bi bi-file-earmark-arrow-down"></i> Export Excel Totale</a>\n                    {% endif %}\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'export_client\') }}"><i class="bi bi-people"></i> Export per Cliente</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'calcola_costi\') }}"><i class="bi bi-calculator"></i> Calcola Giacenze Mensili</a>\n                    {% if can_use_buoni_qr() %}\n                    <a class="btn btn-outline-primary btn-sm" href="{{ url_for(\'scan_entrata\') }}"><i class="bi bi-upc-scan"></i> Scan / Ricerca Entrata</a>\n                    {% endif %}\n                </div>\n            </div>\n\n            <div class="card home-section-card p-3">\n                <h6 class="mb-2"><i class="bi bi-upc-scan"></i> Ricerca veloce entrata</h6>\n                <form action="{{ url_for(\'go_scan_entrata\') }}" method="post" class="d-flex gap-2">\n                    <input name="codice_entrata" class="form-control" placeholder="Scansiona o incolla codice..." autocomplete="off">\n                    <button class="btn btn-primary">Apri</button>\n                </form>\n            </div>\n        </div>\n\n        <div class="col-xl-9">\n            <div class="card home-section-card p-3">\n                <div class="d-flex justify-content-between align-items-center mb-2">\n                    <h5 class="m-0">Ultimi movimenti</h5>\n                    <a href="{{ url_for(\'giacenze\') }}" class="btn btn-outline-secondary btn-sm">Apri giacenze</a>\n                </div>\n                <div class="table-responsive">\n                    <table class="table table-sm table-striped home-movement-table">\n                        <thead>\n                            <tr>\n                                <th>Data</th>\n                                <th>Tipo</th>\n                                <th>Cliente</th>\n                                <th>Codice</th>\n                                <th>Descrizione</th>\n                                <th>N. Arrivo</th>\n                                <th>DDT</th>\n                            </tr>\n                        </thead>\n                        <tbody>\n                            {% for m in ultimi_movimenti %}\n                            <tr>\n                                <td>{{ m.data }}</td>\n                                <td>\n                                    {% if m.tipo == \'Entrata\' %}\n                                    <span class="badge bg-success">Entrata</span>\n                                    {% else %}\n                                    <span class="badge bg-danger">Uscita</span>\n                                    {% endif %}\n                                </td>\n                                <td>{{ m.cliente }}</td>\n                                <td>{{ m.codice }}</td>\n                                <td>{{ m.descrizione }}</td>\n                                <td>{{ m.n_arrivo }}</td>\n                                <td>{{ m.ddt }}</td>\n                            </tr>\n                            {% else %}\n                            <tr><td colspan="7" class="text-muted text-center py-3">Nessun movimento recente.</td></tr>\n                            {% endfor %}\n                        </tbody>\n                    </table>\n                </div>\n            </div>\n        </div>\n    </div>\n</div>\n{% endblock %}\n'


def register_dashboard_home_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    from datetime import date, timedelta
    from flask import render_template_string
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

            def _add_alert(alerts, level, title, count, message, examples=None):
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
                        'examples': examples or []
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

            def _buoni_base_query():
                q = db.query(func.count(BuonoCarico.id))
                if cliente_corrente:
                    q = q.filter(_cliente_key_expr(BuonoCarico.cliente) == cliente_corrente.upper())
                return q

            try:
                stato_buono = func.upper(func.coalesce(BuonoCarico.stato, ''))
                dashboard['buoni_creati'] = int(_buoni_base_query().filter(~stato_buono.in_(['ELIMINATO'])).scalar() or 0)
                dashboard['buoni_aperti'] = int(_buoni_base_query().filter(
                    ~stato_buono.in_(['CARICATO', 'CHIUSO', 'COMPLETATO', 'ELIMINATO'])
                ).scalar() or 0)
                dashboard['buoni_usciti'] = int(_buoni_base_query().filter(
                    stato_buono.in_(['CARICATO', 'CHIUSO', 'COMPLETATO'])
                ).scalar() or 0)
            except Exception:
                pass

            movimenti = []

            def _add_movimenti_ingresso():
                q = db.query(
                    Articolo.data_ingresso, Articolo.cliente, Articolo.codice_articolo,
                    Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_ingresso
                ).filter(*(all_filter + [Articolo.data_ingresso != None, Articolo.data_ingresso != '']))
                q = q.order_by(Articolo.id_articolo.desc()).limit(20)
                for d_in_raw, cli, cod, desc, arr, ddt in q.all():
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
                    })

            def _add_movimenti_uscita():
                q = db.query(
                    Articolo.data_uscita, Articolo.cliente, Articolo.codice_articolo,
                    Articolo.descrizione, Articolo.n_arrivo, Articolo.n_ddt_uscita
                ).filter(*(all_filter + [Articolo.data_uscita != None, Articolo.data_uscita != '']))
                q = q.order_by(Articolo.id_articolo.desc()).limit(20)
                for d_out_raw, cli, cod, desc, arr, ddt in q.all():
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

            try:
                senza_foto_filter = active_filter + [~Articolo.attachments.any(Attachment.kind == 'photo')]
                senza_pdf_filter = active_filter + [~Articolo.attachments.any(Attachment.kind == 'doc')]
                _add_alert(dashboard_alerts, 'warning', 'Foto mancante', _count_articoli(senza_foto_filter), 'Articoli in giacenza senza foto arrivo.', _examples(senza_foto_filter, 'n_arrivo'))
                _add_alert(dashboard_alerts, 'warning', 'Documento PDF mancante', _count_articoli(senza_pdf_filter), 'Articoli in giacenza senza documento arrivo PDF.', _examples(senza_pdf_filter, 'n_arrivo'))
            except Exception:
                pass

            def _duplicate_summary(attr, extra_filters=None, exclude_clienti=None):
                exclude_clienti = {c.upper() for c in (exclude_clienti or [])}
                col = getattr(Articolo, attr)
                filters = list(extra_filters or [])
                filters += [col != None, col != '']
                if exclude_clienti:
                    filters.append(~_cliente_key_expr(Articolo.cliente).in_(list(exclude_clienti)))
                try:
                    rows_dup = (
                        db.query(col, func.count(Articolo.id_articolo).label('cnt'))
                        .filter(*filters)
                        .group_by(col)
                        .having(func.count(Articolo.id_articolo) > 1)
                        .order_by(func.count(Articolo.id_articolo).desc())
                        .limit(50)
                        .all()
                    )
                    total_groups = len(rows_dup)
                    examples = [str(v or '').strip() for v, c in rows_dup[:5] if str(v or '').strip()]
                    return total_groups, examples
                except Exception:
                    return 0, []

            dup_arrivi_count, dup_arrivi_examples = _duplicate_summary('n_arrivo', active_filter)
            _add_alert(dashboard_alerts, 'warning', 'N. arrivo duplicato', dup_arrivi_count, 'Ci sono numeri arrivo ripetuti tra gli articoli ancora in giacenza.', dup_arrivi_examples)

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
            _add_alert(dashboard_alerts, 'danger', 'DDT gestionale senza mezzo', uscite_senza_mezzo_count, 'DDT creati dal gestionale senza Motrice / Bilico / Furgone compilato.', uscite_senza_mezzo_examples)

            vecchie_filter = active_filter + [
                Articolo.data_ingresso != None,
                Articolo.data_ingresso != '',
                Articolo.data_ingresso <= cutoff_90_iso
            ]
            _add_alert(dashboard_alerts, 'info', 'Giacenze oltre 90 giorni', _count_articoli(vecchie_filter), 'Articoli ancora in giacenza da almeno 90 giorni.', _examples(vecchie_filter, 'n_arrivo'))

            level_order = {'danger': 0, 'warning': 1, 'info': 2}
            dashboard_alerts = sorted(dashboard_alerts, key=lambda x: (level_order.get(x.get('level'), 9), -int(x.get('count') or 0)))

            dashboard_clienti = []
            try:
                rows_clienti = (
                    db.query(
                        func.coalesce(Articolo.cliente, '').label('cliente'),
                        func.count(Articolo.id_articolo).label('righe'),
                        func.coalesce(func.sum(Articolo.n_colli), 0).label('colli'),
                        func.coalesce(func.sum(Articolo.m2), 0).label('m2'),
                        func.coalesce(func.sum(Articolo.peso), 0).label('peso'),
                    )
                    .filter(*active_filter)
                    .group_by(func.coalesce(Articolo.cliente, ''))
                    .order_by(func.coalesce(Articolo.cliente, '').asc())
                    .all()
                )

                buoni_by_cliente = {}
                try:
                    stato_b = func.upper(func.coalesce(BuonoCarico.stato, ''))
                    q_b = db.query(
                        func.coalesce(BuonoCarico.cliente, '').label('cliente'),
                        func.count(BuonoCarico.id).label('creati'),
                        func.sum(case((stato_b.in_(['CARICATO', 'CHIUSO', 'COMPLETATO']), 1), else_=0)).label('usciti'),
                        func.sum(case((~stato_b.in_(['CARICATO', 'CHIUSO', 'COMPLETATO', 'ELIMINATO']), 1), else_=0)).label('aperti'),
                    ).filter(~stato_b.in_(['ELIMINATO']))
                    if cliente_corrente:
                        q_b = q_b.filter(_cliente_key_expr(BuonoCarico.cliente) == cliente_corrente.upper())
                    for cli_b, creati, usciti, aperti in q_b.group_by(func.coalesce(BuonoCarico.cliente, '')).all():
                        buoni_by_cliente[(cli_b or '').strip().upper()] = {
                            'buoni_creati': int(creati or 0),
                            'buoni_usciti': int(usciti or 0),
                            'buoni_aperti': int(aperti or 0),
                        }
                except Exception:
                    buoni_by_cliente = {}

                for cli, righe, colli, m2_val, peso_val in rows_clienti:
                    nome_cli = (cli or 'SENZA CLIENTE').strip() or 'SENZA CLIENTE'
                    dati_b = buoni_by_cliente.get(nome_cli.upper(), {})
                    dashboard_clienti.append({
                        'cliente': nome_cli,
                        'righe': int(righe or 0),
                        'colli': int(colli or 0),
                        'm2': float(m2_val or 0),
                        'peso': float(peso_val or 0),
                        'buoni_aperti': int(dati_b.get('buoni_aperti', 0) or 0),
                        'buoni_creati': int(dati_b.get('buoni_creati', 0) or 0),
                        'buoni_usciti': int(dati_b.get('buoni_usciti', 0) or 0),
                    })
            except Exception:
                dashboard_clienti = []

            return render_template_string(
                HOME_HTML,
                dashboard=dashboard,
                dashboard_clienti=dashboard_clienti,
                dashboard_alerts=dashboard_alerts,
                ultimi_movimenti=ultimi_movimenti,
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
