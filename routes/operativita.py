# -*- coding: utf-8 -*-
"""Dashboard operativa, agenda, registro giornaliero e statistiche CAMAR."""

def register_operativita_routes(app, deps):
    globals().update(deps)
    from datetime import date, datetime, timedelta
    from flask import render_template, request, redirect, url_for, flash, send_file, session
    from flask_login import login_required
    from sqlalchemy import Column, Integer, String, Text, Date, func, or_
    from io import BytesIO

    class AgendaMagazzino(Base):
        __tablename__ = "agenda_magazzino"
        id = Column(Integer, primary_key=True)
        data = Column(Date, nullable=False, index=True)
        cliente = Column(String(255))
        attivita = Column(Text, nullable=False)
        urgenza = Column(String(20), default="NORMALE")
        stato = Column(String(20), default="DA FARE")
        riferimento = Column(String(255))
        note = Column(Text)
        creato_da = Column(String(64))
        creato_il = Column(String(32))

    Base.metadata.create_all(engine)
    globals()["AgendaMagazzino"] = AgendaMagazzino

    def _date_value(value, default=None):
        if isinstance(value, date):
            return value
        s = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        return default

    def _article_date_filter(column, giorno):
        return or_(column == giorno.strftime("%Y-%m-%d"), column == giorno.strftime("%d/%m/%Y"))

    def _safe_count(db, model, *filters):
        try:
            return int(db.query(func.count(model.id if hasattr(model, 'id') else model.id_articolo)).filter(*filters).scalar() or 0)
        except Exception:
            return 0

    def _safe_sum(db, column, *filters):
        try:
            return float(db.query(func.coalesce(func.sum(column), 0)).filter(*filters).scalar() or 0)
        except Exception:
            return 0.0

    def build_daily_data(db, giorno=None, cliente=None):
        giorno = giorno or date.today()
        art_filters = []
        if cliente:
            art_filters.append(func.upper(func.coalesce(Articolo.cliente, "")) == cliente.upper())

        entrata_f = art_filters + [_article_date_filter(Articolo.data_ingresso, giorno)]
        uscita_f = art_filters + [_article_date_filter(Articolo.data_uscita, giorno)]

        tras_q = db.query(Trasporto).filter(Trasporto.data == giorno)
        lav_q = db.query(Lavorazione).filter(Lavorazione.data == giorno)
        agenda_q = db.query(AgendaMagazzino).filter(AgendaMagazzino.data == giorno)
        if cliente:
            tras_q = tras_q.filter(func.upper(func.coalesce(Trasporto.cliente, "")) == cliente.upper())
            lav_q = lav_q.filter(func.upper(func.coalesce(Lavorazione.cliente, "")) == cliente.upper())
            agenda_q = agenda_q.filter(func.upper(func.coalesce(AgendaMagazzino.cliente, "")) == cliente.upper())

        trasporti = tras_q.order_by(Trasporto.id.desc()).all()
        lavorazioni = lav_q.order_by(Lavorazione.id.desc()).all()
        agenda = agenda_q.order_by(AgendaMagazzino.stato.asc(), AgendaMagazzino.id.desc()).all()

        ddt = 0
        try:
            ddt = int(db.query(func.count(func.distinct(Articolo.n_ddt_uscita))).filter(
                *(uscita_f + [Articolo.n_ddt_uscita != None, Articolo.n_ddt_uscita != ""])
            ).scalar() or 0)
        except Exception:
            pass

        buoni = 0
        try:
            # Il buono di prelievo è registrato sulle righe articolo: conteggio numeri distinti usciti nel giorno.
            buoni = int(db.query(func.count(func.distinct(Articolo.buono_n))).filter(
                *(uscita_f + [Articolo.buono_n != None, Articolo.buono_n != ""])
            ).scalar() or 0)
        except Exception:
            pass

        return {
            "giorno": giorno,
            "arrivi": _safe_count(db, Articolo, *entrata_f),
            "uscite": _safe_count(db, Articolo, *uscita_f),
            "buoni": buoni,
            "ddt": ddt,
            "trasporti": len(trasporti),
            "picking": len(lavorazioni),
            "colli_entrati": int(_safe_sum(db, Articolo.n_colli, *entrata_f)),
            "colli_usciti": int(_safe_sum(db, Articolo.n_colli, *uscita_f)),
            "pezzi_entrati": _safe_sum(db, Articolo.pezzo, *entrata_f),
            "peso_entrato": _safe_sum(db, Articolo.peso, *entrata_f),
            "peso_uscito": _safe_sum(db, Articolo.peso, *uscita_f),
            "trasporti_rows": trasporti,
            "lavorazioni_rows": lavorazioni,
            "agenda_rows": agenda,
            "agenda_da_fare": sum(1 for x in agenda if (x.stato or "").upper() != "COMPLETATO"),
            "agenda_urgenti": sum(1 for x in agenda if (x.urgenza or "").upper() == "URGENTE" and (x.stato or "").upper() != "COMPLETATO"),
        }

    globals()["build_daily_operativa"] = build_daily_data

    @app.route('/agenda-magazzino', methods=['GET', 'POST'])
    @login_required
    def agenda_magazzino():
        db = SessionLocal()
        try:
            if request.method == 'POST':
                action = (request.form.get('action') or 'add').strip()
                if action == 'add':
                    attivita = (request.form.get('attivita') or '').strip()
                    giorno = _date_value(request.form.get('data'), date.today())
                    if not attivita:
                        flash('Inserisci l’attività.', 'warning')
                    else:
                        db.add(AgendaMagazzino(
                            data=giorno,
                            cliente=(request.form.get('cliente') or '').strip(),
                            attivita=attivita,
                            urgenza=(request.form.get('urgenza') or 'NORMALE').upper(),
                            stato=(request.form.get('stato') or 'DA FARE').upper(),
                            riferimento=(request.form.get('riferimento') or '').strip(),
                            note=(request.form.get('note') or '').strip(),
                            creato_da=(session.get('user') or ''),
                            creato_il=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                        db.commit()
                        flash('Attività aggiunta all’agenda.', 'success')
                    return redirect(url_for('agenda_magazzino', data=giorno.isoformat()))
                if action in {'complete', 'reopen', 'delete'}:
                    rid = int(request.form.get('id') or 0)
                    row = db.query(AgendaMagazzino).filter(AgendaMagazzino.id == rid).first()
                    if row:
                        if action == 'delete': db.delete(row)
                        else: row.stato = 'COMPLETATO' if action == 'complete' else 'DA FARE'
                        db.commit()
                    return redirect(url_for('agenda_magazzino', data=request.args.get('data') or date.today().isoformat()))

            giorno = _date_value(request.args.get('data'), date.today())
            stato = (request.args.get('stato') or '').strip().upper()
            q = db.query(AgendaMagazzino)
            if request.args.get('tutte') != '1': q = q.filter(AgendaMagazzino.data == giorno)
            if stato: q = q.filter(func.upper(AgendaMagazzino.stato) == stato)
            rows = q.order_by(AgendaMagazzino.data.asc(), AgendaMagazzino.id.desc()).all()
            return render_template('agenda_magazzino.html', righe=rows, giorno=giorno, stato=stato)
        finally:
            db.close()

    @app.route('/registro-giornaliero')
    @login_required
    def registro_giornaliero():
        giorno = _date_value(request.args.get('data'), date.today())
        db = SessionLocal()
        try:
            dati = build_daily_data(db, giorno)
            return render_template('registro_giornaliero.html', dati=dati, giorno=giorno)
        finally:
            db.close()

    @app.route('/statistiche-magazzino')
    @login_required
    def statistiche_magazzino():
        anno = int(request.args.get('anno') or date.today().year)
        cliente = (request.args.get('cliente') or '').strip()
        db = SessionLocal()
        try:
            mesi = []
            for mese in range(1, 13):
                start = date(anno, mese, 1)
                end = date(anno + (mese == 12), 1 if mese == 12 else mese + 1, 1) - timedelta(days=1)
                totale = {"mese": mese, "nome": start.strftime('%b').capitalize(), "arrivi": 0, "uscite": 0, "trasporti": 0, "picking": 0, "colli": 0, "peso": 0}
                # Le date articolo sono stringhe: includiamo ISO, il formato corrente del gestionale.
                qin = db.query(Articolo).filter(Articolo.data_ingresso >= start.isoformat(), Articolo.data_ingresso <= end.isoformat())
                qout = db.query(Articolo).filter(Articolo.data_uscita >= start.isoformat(), Articolo.data_uscita <= end.isoformat())
                qt = db.query(Trasporto).filter(Trasporto.data >= start, Trasporto.data <= end)
                ql = db.query(Lavorazione).filter(Lavorazione.data >= start, Lavorazione.data <= end)
                if cliente:
                    cf = func.upper(func.coalesce(Articolo.cliente, '')) == cliente.upper()
                    qin, qout = qin.filter(cf), qout.filter(cf)
                    qt = qt.filter(func.upper(func.coalesce(Trasporto.cliente, '')) == cliente.upper())
                    ql = ql.filter(func.upper(func.coalesce(Lavorazione.cliente, '')) == cliente.upper())
                totale['arrivi'] = qin.count(); totale['uscite'] = qout.count(); totale['trasporti'] = qt.count(); totale['picking'] = ql.count()
                try: totale['colli'] = int(sum((r.n_colli or 0) for r in qin.all()))
                except Exception: pass
                try: totale['peso'] = round(sum((r.peso or 0) for r in qin.all()), 2)
                except Exception: pass
                mesi.append(totale)
            clienti = [x[0] for x in db.query(Articolo.cliente).filter(Articolo.cliente != None, Articolo.cliente != '').distinct().order_by(Articolo.cliente).all()]
            massimi = {k: max([m[k] for m in mesi] + [1]) for k in ('arrivi','uscite','trasporti','picking')}
            return render_template('statistiche_magazzino.html', mesi=mesi, anno=anno, cliente=cliente, clienti=clienti, massimi=massimi)
        finally:
            db.close()
