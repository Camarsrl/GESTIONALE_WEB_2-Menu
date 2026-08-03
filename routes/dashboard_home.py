# -*- coding: utf-8 -*-
"""
Modulo Dashboard/Home Gestionale Camar.

Correzioni:
- riepilogo colli/M2/peso per cliente
- buoni QR creati/aperti/usciti
- conteggio giacenze attive più robusto su data_uscita vuota/None/NaT
"""

HOME_HTML = '\n{% extends \'base.html\' %}\n{% block content %}\n<style>\n.home-kpi-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n    height:100%;\n}\n.home-kpi-icon{\n    width:42px;\n    height:42px;\n    border-radius:12px;\n    display:flex;\n    align-items:center;\n    justify-content:center;\n    background:#eef5ff;\n    color:#0d6efd;\n    font-size:20px;\n}\n.home-kpi-value{\n    font-size:26px;\n    font-weight:700;\n    line-height:1.1;\n}\n.home-section-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n}\n.home-movement-table td,\n.home-movement-table th{\n    vertical-align:middle;\n    font-size:13px;\n}\n\n.home-alert-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n}\n.home-alert-item{\n    border-left:5px solid #ffc107;\n    background:#fff8e1;\n    border-radius:10px;\n    padding:10px 12px;\n    margin-bottom:8px;\n}\n.home-alert-item.danger{\n    border-left-color:#dc3545;\n    background:#fff1f1;\n}\n.home-alert-item.warning{\n    border-left-color:#ffc107;\n    background:#fff8e1;\n}\n.home-alert-item.info{\n    border-left-color:#0d6efd;\n    background:#eef5ff;\n}\n.home-client-table th,\n.home-client-table td{\n    font-size:13px;\n    vertical-align:middle;\n}\n.home-client-table tfoot td{\n    font-weight:700;\n    background:#f8f9fa;\n}\n\n.home-tools-card{\n    border:0;\n    border-radius:16px;\n    box-shadow:0 4px 14px rgba(0,0,0,.07);\n    height:100%;\n}\n.home-camy-box{\n    background:linear-gradient(135deg,#eef8ff,#f7fbff);\n    border:1px solid #cfe8ff;\n    border-radius:14px;\n    padding:14px;\n}\n.home-backup-ok{color:#198754;font-weight:700}\n.home-backup-warn{color:#dc3545;font-weight:700}\n.home-global-search{\n    border:1px solid #d8e7f7;\n    border-radius:16px;\n    background:#fff;\n    box-shadow:0 4px 14px rgba(0,0,0,.06);\n    padding:14px;\n}\n.home-alert-link{\n    color:inherit;\n    text-decoration:none;\n    display:block;\n    height:100%;\n}\n.home-alert-link:hover .home-alert-item{\n    transform:translateY(-1px);\n    box-shadow:0 5px 14px rgba(0,0,0,.08);\n}\n.home-alert-item{transition:.15s ease}\n</style>\n\n<div class="container-fluid py-3">\n    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">\n        <div class="d-flex align-items-center gap-3">\n            {% if logo_url %}<img src="{{ logo_url }}" style="height:50px;width:auto;">{% endif %}\n            <div>\n                <h3 class="m-0">Dashboard Gestionale</h3>\n                <div class="text-muted small">Riepilogo operativo aggiornato al {{ today.strftime(\'%d/%m/%Y\') if today else \'\' }}</div>\n            </div>\n        </div>\n        <div class="d-flex flex-wrap gap-2">\n            <a class="btn btn-primary btn-sm" href="{{ url_for(\'giacenze\') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Giacenze</a>\n            {% if session.get(\'role\') == \'admin\' %}\n            <a class="btn btn-success btn-sm" href="{{ url_for(\'nuovo_articolo\') }}"><i class="bi bi-plus-circle"></i> Nuovo articolo</a>\n            {% endif %}\n            {% if can_use_buoni_qr() %}\n            <a class="btn btn-outline-primary btn-sm" href="{{ url_for(\'scan_entrata\') }}"><i class="bi bi-upc-scan"></i> Scan entrata</a>\n            {% endif %}\n        </div>\n    </div>\n\n    <div class="home-global-search mb-3">\n        <form method="get" action="{{ url_for(\'dashboard_ricerca_globale\') }}" class="row g-2 align-items-center">\n            <div class="col-lg-9">\n                <div class="input-group">\n                    <span class="input-group-text"><i class="bi bi-search"></i></span>\n                    <input name="q" class="form-control" placeholder="Cerca codice, lotto, N. arrivo, protocollo, seriale, cliente o DDT..." autocomplete="off">\n                </div>\n            </div>\n            <div class="col-lg-3 d-grid">\n                <button class="btn btn-primary"><i class="bi bi-search"></i> Ricerca globale</button>\n            </div>\n        </form>\n    </div>\n\n    {% if session.get(\'role\') == \'admin\' %}\n    <div class="row g-3 mb-3">\n        <div class="col-lg-8">\n            <div class="card home-tools-card p-3">\n                <div class="home-camy-box">\n                    <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">\n                        <div>\n                            <h5 class="mb-1"><i class="bi bi-robot text-primary"></i> CAMY operativa</h5>\n                            <div class="small text-muted mb-2">Controlli rapidi senza modificare il database.</div>\n                            {% if dashboard.buoni_aperti %}\n                            <div>⚠️ Buoni aperti: <b>{{ dashboard.buoni_aperti }}</b></div>\n                            {% else %}\n                            <div>✅ Nessun Buono aperto.</div>\n                            {% endif %}\n                            {% if dashboard_alerts %}\n                            <div>⚠️ Segnalazioni operative: <b>{{ dashboard_alerts|length }}</b></div>\n                            {% else %}\n                            <div>✅ Nessuna anomalia operativa rilevata.</div>\n                            {% endif %}\n                        </div>\n                        <div class="d-grid gap-2">\n                            <a class="btn btn-primary btn-sm" href="/camy-ai?prefill=Trova%20anomalie%20nel%20magazzino">\n                                <i class="bi bi-shield-check"></i> Controlla magazzino\n                            </a>\n                            <a class="btn btn-outline-primary btn-sm" href="/camy-ai">\n                                Apri CAMY\n                            </a>\n                        </div>\n                    </div>\n                </div>\n            </div>\n        </div>\n        <div class="col-lg-4">\n            <div class="card home-tools-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <h5 class="mb-1"><i class="bi bi-database-check text-primary"></i> Ultimo backup</h5>\n                        {% if backup_status.exists %}\n                            <div class="{% if backup_status.today %}home-backup-ok{% else %}home-backup-warn{% endif %}">\n                                {% if backup_status.today %}● OK{% else %}● DA CONTROLLARE{% endif %}\n                            </div>\n                            <div class="mt-1">{{ backup_status.date }}</div>\n                            <div class="small text-muted">{{ backup_status.time }} · {{ backup_status.size_mb }} MB</div>\n                        {% else %}\n                            <div class="home-backup-warn">● NESSUN BACKUP TROVATO</div>\n                        {% endif %}\n                    </div>\n                    <a class="btn btn-outline-primary btn-sm" href="/admin/backups">Apri backup</a>\n                </div>\n            </div>\n        </div>\n    </div>\n    {% endif %}\n\n    <div class="row g-3 mb-3">\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Articoli in giacenza</div>\n                        <div class="home-kpi-value">{{ dashboard.tot_giacenza }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-box-seam"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">M² occupati</div>\n                        <div class="home-kpi-value">{{ dashboard.tot_m2|it_num(2) }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-rulers"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Entrate oggi</div>\n                        <div class="home-kpi-value">{{ dashboard.entrate_oggi }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-arrow-down-circle"></i></div>\n                </div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-3">\n            <div class="card home-kpi-card p-3">\n                <div class="d-flex justify-content-between align-items-start">\n                    <div>\n                        <div class="text-muted small">Uscite oggi</div>\n                        <div class="home-kpi-value">{{ dashboard.uscite_oggi }}</div>\n                    </div>\n                    <div class="home-kpi-icon"><i class="bi bi-arrow-up-circle"></i></div>\n                </div>\n            </div>\n        </div>\n    </div>\n\n    <div class="row g-3 mb-3">\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Articoli doganali</div>\n                <div class="home-kpi-value">{{ dashboard.doganali }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni aperti</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_aperti }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni creati</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_creati }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Buoni usciti</div>\n                <div class="home-kpi-value">{{ dashboard.buoni_usciti }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Peso in giacenza</div>\n                <div class="home-kpi-value">{{ dashboard.tot_peso|it_num(2) }}</div>\n            </div>\n        </div>\n        <div class="col-md-6 col-xl-2">\n            <div class="card home-kpi-card p-3">\n                <div class="text-muted small">Colli in giacenza</div>\n                <div class="home-kpi-value">{{ dashboard.tot_colli }}</div>\n            </div>\n        </div>\n    </div>\n\n    {% if dashboard_alerts %}\n    <div class="card home-alert-card p-3 mb-3">\n        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">\n            <h5 class="m-0"><i class="bi bi-bell-fill text-warning"></i> Alert automatici</h5>\n            <span class="badge bg-warning text-dark">{{ dashboard_alerts|length }} segnalazioni</span>\n        </div>\n        <div class="row g-2">\n            {% for alert in dashboard_alerts %}\n            <div class="col-lg-6 col-xxl-4">\n                <a class="home-alert-link" href="{{ alert.url or url_for(\'giacenze\') }}">\n                    <div class="home-alert-item {{ alert.level }}">\n                        <div class="d-flex justify-content-between gap-2">\n                            <strong>{{ alert.title }}</strong>\n                            <span class="badge {% if alert.level == \'danger\' %}bg-danger{% elif alert.level == \'warning\' %}bg-warning text-dark{% else %}bg-primary{% endif %}">{{ alert.count }}</span>\n                        </div>\n                        <div class="small text-muted mt-1">{{ alert.message }}</div>\n                        {% if alert.examples %}\n                        <div class="small mt-1"><strong>Esempi:</strong> {{ alert.examples|join(\', \') }}</div>\n                        {% endif %}\n                        <div class="small text-primary mt-1"><i class="bi bi-box-arrow-up-right"></i> Apri elenco</div>\n                    </div>\n                </a>\n            </div>\n            {% endfor %}\n        </div>\n    </div>\n    {% endif %}\n\n    <div class="card home-section-card p-3 mb-3">\n        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">\n            <h5 class="m-0"><i class="bi bi-people-fill text-primary"></i> Giacenza per cliente</h5>\n            <span class="badge bg-primary">{{ dashboard_clienti|length }} clienti</span>\n        </div>\n        <div class="table-responsive">\n            <table class="table table-sm table-striped home-client-table mb-0">\n                <thead>\n                    <tr>\n                        <th>Cliente</th>\n                        <th class="text-end">Righe</th>\n                        <th class="text-end">Colli</th>\n                        <th class="text-end">M²</th>\n                        <th class="text-end">Peso kg</th>\n                        <th class="text-end">Buoni aperti</th>\n                        <th class="text-end">Buoni creati</th>\n                        <th class="text-end">Buoni usciti</th>\n                    </tr>\n                </thead>\n                <tbody>\n                    {% for r in dashboard_clienti %}\n                    <tr>\n                        <td>{{ r.cliente }}</td>\n                        <td class="text-end">{{ r.righe }}</td>\n                        <td class="text-end">{{ r.colli }}</td>\n                        <td class="text-end">{{ r.m2|it_num(2) }}</td>\n                        <td class="text-end">{{ r.peso|it_num(2) }}</td>\n                        <td class="text-end">{{ r.buoni_aperti }}</td>\n                        <td class="text-end">{{ r.buoni_creati }}</td>\n                        <td class="text-end">{{ r.buoni_usciti }}</td>\n                    </tr>\n                    {% else %}\n                    <tr><td colspan="9" class="text-muted text-center py-3">Nessuna giacenza attiva.</td></tr>\n                    {% endfor %}\n                </tbody>\n                <tfoot>\n                    <tr>\n                        <td>Totale</td>\n                        <td class="text-end">{{ dashboard.tot_giacenza }}</td>\n                        <td class="text-end">{{ dashboard.tot_colli }}</td>\n                        <td class="text-end">{{ dashboard.tot_m2|it_num(2) }}</td>\n                        <td class="text-end">{{ dashboard.tot_peso|it_num(2) }}</td>\n                        <td class="text-end">{{ dashboard.buoni_aperti }}</td>\n                        <td class="text-end">{{ dashboard.buoni_creati }}</td>\n                        <td class="text-end">{{ dashboard.buoni_usciti }}</td>\n                    </tr>\n                </tfoot>\n            </table>\n        </div>\n        <div class="text-muted small mt-2">\n            I colli sono calcolati come nella tabella Giacenze: somma del campo Colli sulle righe ancora in giacenza. Per GALVANO TECNICA non viene contato 1 collo per ogni riga articolo.\n        </div>\n    </div>\n\n    <div class="row g-3">\n        <div class="col-xl-3">\n            <div class="card home-section-card p-3 mb-3">\n                <h6 class="mb-3">Menu rapido</h6>\n                <div class="d-grid gap-2">\n                    <a class="btn btn-primary" href="{{ url_for(\'giacenze\') }}"><i class="bi bi-grid-3x3-gap-fill"></i> Visualizza Giacenze</a>\n                    {% if session.get(\'role\') == \'admin\' %}\n                    <a class="btn btn-success" href="{{ url_for(\'nuovo_articolo\') }}"><i class="bi bi-plus-circle"></i> Nuovo Articolo</a>\n                    <a class="btn btn-outline-secondary" href="{{ url_for(\'labels_form\') }}"><i class="bi bi-tag"></i> Stampa Etichette</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'import_excel\') }}"><i class="bi bi-file-earmark-arrow-up"></i> Import Excel</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'export_excel\') }}"><i class="bi bi-file-earmark-arrow-down"></i> Export Excel Totale</a>\n                    {% endif %}\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'export_client\') }}"><i class="bi bi-people"></i> Export per Cliente</a>\n                    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for(\'calcola_costi\') }}"><i class="bi bi-calculator"></i> Calcola Giacenze Mensili</a>\n                    {% if can_use_buoni_qr() %}\n                    <a class="btn btn-outline-primary btn-sm" href="{{ url_for(\'scan_entrata\') }}"><i class="bi bi-upc-scan"></i> Scan / Ricerca Entrata</a>\n                    {% endif %}\n                </div>\n            </div>\n\n            <div class="card home-section-card p-3">\n                <h6 class="mb-2"><i class="bi bi-upc-scan"></i> Ricerca veloce entrata</h6>\n                <form action="{{ url_for(\'go_scan_entrata\') }}" method="post" class="d-flex gap-2">\n                    <input name="codice_entrata" class="form-control" placeholder="Scansiona o incolla codice..." autocomplete="off">\n                    <button class="btn btn-primary">Apri</button>\n                </form>\n            </div>\n        </div>\n\n        <div class="col-xl-9">\n            <div class="card home-section-card p-3">\n                <div class="d-flex justify-content-between align-items-center mb-2">\n                    <h5 class="m-0">Ultimi movimenti</h5>\n                    <a href="{{ url_for(\'giacenze\') }}" class="btn btn-outline-secondary btn-sm">Apri giacenze</a>\n                </div>\n                <div class="table-responsive">\n                    <table class="table table-sm table-striped home-movement-table">\n                        <thead>\n                            <tr>\n                                <th>Data</th>\n                                <th>Tipo</th>\n                                <th>Cliente</th>\n                                <th>Codice</th>\n                                <th>Descrizione</th>\n                                <th>N. Arrivo</th>\n                                <th>DDT</th>\n                                <th>Operatore</th>\n                            </tr>\n                        </thead>\n                        <tbody>\n                            {% for m in ultimi_movimenti %}\n                            <tr>\n                                <td>{{ m.data }}</td>\n                                <td>\n                                    {% if m.tipo == \'Entrata\' %}\n                                    <span class="badge bg-success">Entrata</span>\n                                    {% else %}\n                                    <span class="badge bg-danger">Uscita</span>\n                                    {% endif %}\n                                </td>\n                                <td>{{ m.cliente }}</td>\n                                <td>{{ m.codice }}</td>\n                                <td>{{ m.descrizione }}</td>\n                                <td>{{ m.n_arrivo }}</td>\n                                <td>{{ m.ddt }}</td>\n                                <td>{{ m.operatore or \'-\' }}</td>\n                            </tr>\n                            {% else %}\n                            <tr><td colspan="8" class="text-muted text-center py-3">Nessun movimento recente.</td></tr>\n                            {% endfor %}\n                        </tbody>\n                    </table>\n                </div>\n            </div>\n        </div>\n    </div>\n</div>\n{% endblock %}\n'


def register_dashboard_home_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    from pathlib import Path
    from datetime import date, timedelta, datetime
    from flask import render_template_string, request, redirect, url_for
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
            cliente_corrente = current_cliente()
            if cliente_corrente:
                filters.append(_cliente_key_expr(Articolo.cliente) == cliente_corrente.upper())

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

            dashboard_clienti = []
            try:
                # Normalizzazione lato Python: evita gruppi falsi tipo "SENZA CLIENTE"
                # causati da spazi, valori NaT/None o vecchi record con cliente non compilato
                # ma codice_entrata contenente il cliente, es. ENT-20260522-RFDEWAVE-...
                try:
                    clienti_validi = list(get_clienti_utenti())
                except Exception:
                    clienti_validi = []

                alias_cliente = {}
                def _norm_cliente_token(v):
                    return re.sub(r'[^A-Z0-9]+', '', (v or '').upper())

                for c in clienti_validi:
                    cn = (c or '').strip().upper()
                    if not cn:
                        continue
                    alias_cliente[_norm_cliente_token(cn)] = cn
                    # alias usati spesso nel gestionale
                    if _norm_cliente_token(cn) == 'RFDEWAVE':
                        alias_cliente['DEWAVERF'] = cn
                    if _norm_cliente_token(cn) == 'DEWAVERF':
                        alias_cliente['RFDEWAVE'] = cn

                def _cliente_dashboard(raw_cliente, codice_entrata=None):
                    raw = (raw_cliente or '').strip()
                    if raw and raw.upper() not in ('NONE', 'NULL', 'NAT'):
                        nraw = _norm_cliente_token(raw)
                        return alias_cliente.get(nraw, raw.upper())

                    codice = (codice_entrata or '').strip().upper()
                    if codice.startswith('ENT-'):
                        parts = codice.split('-')
                        # ENT-YYYYMMDD-CLIENTE-ARRIVO...
                        if len(parts) >= 4:
                            token = _norm_cliente_token(parts[2])
                            if token in alias_cliente:
                                return alias_cliente[token]
                            # gestione RF-DE WAVE spezzato o scritto DEWAVERF
                            if token in ('RFDEWAVE', 'DEWAVERF') and 'RF-DE WAVE' in clienti_validi:
                                return 'RF-DE WAVE'
                    return 'CLIENTE DA VERIFICARE'

                def _is_galvano_cliente(nome_cliente):
                    return _norm_cliente_token(nome_cliente) == 'GALVANOTECNICA'

                def _pallet_key_galvano(codice_entrata=None, n_arrivo=None):
                    """Per GALVANO TECNICA più righe/articoli possono stare su un unico pallet.
                    La dashboard quindi conta 1 collo per ogni arrivo/codice entrata,
                    non 1 collo per ogni riga articolo.
                    """
                    cod = (codice_entrata or '').strip().upper()
                    if cod:
                        return 'CE|' + cod
                    arr = (n_arrivo or '').strip().upper()
                    if arr:
                        # rimuove progressivi tipo N.1 / N 1 / 1/3 / COLLO 1
                        arr = re.sub(r'\s+N\.?\s*\d+\s*$', '', arr, flags=re.I)
                        arr = re.sub(r'\s+COLLO\s*\d+\s*$', '', arr, flags=re.I)
                        arr = re.sub(r'\s+\d+\s*/\s*\d+\s*$', '', arr, flags=re.I)
                        arr = re.sub(r'\s{2,}', ' ', arr).strip(' -')
                        return 'ARR|' + arr if arr else ''
                    return ''

                gruppi_clienti = {}
                rows_art = (
                    db.query(
                        Articolo.cliente,
                        Articolo.codice_entrata,
                        Articolo.n_arrivo,
                        Articolo.n_colli,
                        Articolo.m2,
                        Articolo.peso,
                    )
                    .filter(*active_filter)
                    .all()
                )

                for cli_raw, cod_ent, n_arrivo_val, n_colli, m2_val, peso_val in rows_art:
                    nome_cli = _cliente_dashboard(cli_raw, cod_ent)
                    rec = gruppi_clienti.setdefault(nome_cli, {
                        'cliente': nome_cli,
                        'righe': 0,
                        'colli': 0,
                        'm2': 0.0,
                        'peso': 0.0,
                        'buoni_aperti': 0,
                        'buoni_creati': 0,
                        'buoni_usciti': 0,
                        'da_verificare': nome_cli in ('SENZA CLIENTE', 'CLIENTE DA VERIFICARE'),
                        '_galvano_pallet_keys': set(),
                        '_galvano_colli_fallback': 0,
                    })
                    if nome_cli in ('SENZA CLIENTE', 'CLIENTE DA VERIFICARE'):
                        rec['da_verificare'] = True
                    rec['righe'] += 1
                    # Colli: deve combaciare con la tabella Giacenze.
                    # Quindi sommiamo sempre il campo n_colli delle righe attive.
                    # Per GALVANO TECNICA non contiamo 1 collo per ogni riga articolo,
                    # ma usiamo comunque il valore reale presente nella colonna Colli.
                    try:
                        rec['colli'] += int(float(n_colli or 0))
                    except Exception:
                        pass
                    try:
                        rec['m2'] += float(m2_val or 0)
                    except Exception:
                        pass
                    try:
                        rec['peso'] += float(peso_val or 0)
                    except Exception:
                        pass

                # Usa i Buoni di Prelievo salvati in Articolo.buono_n.
                # Non usa BuonoCarico, perché quello riguarda i Buoni QR di carico.
                buoni_by_cliente = dict(buoni_by_cliente_global or {})

                for nome_cli, rec in sorted(gruppi_clienti.items(), key=lambda x: x[0]):
                    dati_b = buoni_by_cliente.get(nome_cli, {})
                    rec['buoni_aperti'] = int(dati_b.get('buoni_aperti', 0) or 0)
                    rec['buoni_creati'] = int(dati_b.get('buoni_creati', 0) or 0)
                    rec['buoni_usciti'] = int(dati_b.get('buoni_usciti', 0) or 0)
                    rec.pop('_galvano_pallet_keys', None)
                    rec.pop('_galvano_colli_fallback', None)
                    rec['m2'] = round(float(rec.get('m2') or 0), 2)
                    rec['peso'] = round(float(rec.get('peso') or 0), 2)
                    dashboard_clienti.append(rec)
                try:
                    dashboard['tot_colli'] = int(sum(int(r.get('colli') or 0) for r in dashboard_clienti))
                except Exception:
                    pass
            except Exception:
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

            return render_template_string(
                HOME_HTML,
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
