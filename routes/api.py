# -*- coding: utf-8 -*-
"""
Modulo API clienti del Gestionale Camar.

Endpoint mantenuti:
- /api/v1/health
- /api/v1/giacenze
- /api/v1/inventario
- /api/v1/movimenti

Ogni API key è associata a un solo cliente. Il cliente NON viene passato nei parametri.
"""

import os
from datetime import datetime

from flask import request, jsonify
from sqlalchemy import or_, func


def register_api_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    def _load_api_clients_from_env() -> dict:
        """Carica mappa API_KEY -> CLIENTE.

        Priorità:
        1) API_KEYS_JSON='{"key1":"GALVANO TECNICA","key2":"DUFERCO"}'
        2) CORES_API_KEY + CORES_API_CLIENTE, per setup semplice a un cliente
        """
        clients = {}

        raw = (os.environ.get("API_KEYS_JSON") or "").strip()
        if raw:
            try:
                import json
                data = json.loads(raw)
                if isinstance(data, dict):
                    for k, v in data.items():
                        kk = (str(k) or "").strip()
                        vv = (str(v) or "").strip().upper()
                        if kk and vv:
                            clients[kk] = vv
            except Exception as e:
                print(f"[WARN] API_KEYS_JSON non valido: {e}")

        if not clients:
            k = (os.environ.get("CORES_API_KEY") or "").strip()
            c = (os.environ.get("CORES_API_CLIENTE") or "").strip().upper()
            if k and c:
                clients[k] = c

        return clients

    API_CLIENTS = _load_api_clients_from_env()

    def _api_get_cliente_from_key():
        key = (request.headers.get("X-API-KEY") or "").strip()
        if not key:
            return None
        return API_CLIENTS.get(key)

    def _api_unauthorized():
        return jsonify({"error": "unauthorized"}), 401

    def _api_bad_request(msg="bad request"):
        return jsonify({"error": "bad_request", "message": msg}), 400

    def _safe_limit(default=500, max_value=2000):
        try:
            limit = int(request.args.get("limit") or default)
        except Exception:
            limit = default
        return max(1, min(limit, max_value))

    def _safe_offset():
        try:
            offset = int(request.args.get("offset") or 0)
        except Exception:
            offset = 0
        return max(0, offset)

    @app.route("/api/v1/health", methods=["GET"])
    def api_health():
        cliente = _api_get_cliente_from_key()
        out = {"status": "ok", "time": datetime.utcnow().isoformat() + "Z"}
        if cliente:
            out["cliente"] = cliente
        return jsonify(out)

    @app.route("/api/v1/giacenze", methods=["GET"])
    def api_giacenze():
        cliente = _api_get_cliente_from_key()
        if not cliente:
            return _api_unauthorized()

        q = (request.args.get("q") or "").strip()
        lotto = (request.args.get("lotto") or "").strip()
        stato = (request.args.get("stato") or "").strip()
        limit = _safe_limit(default=500, max_value=2000)
        offset = _safe_offset()

        db = SessionLocal()
        try:
            qry = db.query(Articolo).filter(func.upper(Articolo.cliente) == cliente)
            qry = qry.filter((Articolo.data_uscita == None) | (Articolo.data_uscita == ""))

            if lotto:
                qry = qry.filter(Articolo.lotto == lotto)
            if stato:
                qry = qry.filter(func.upper(Articolo.stato) == stato.upper())
            if q:
                like = f"%{q}%"
                qry = qry.filter(or_(
                    Articolo.codice_articolo.ilike(like),
                    Articolo.descrizione.ilike(like),
                    Articolo.lotto.ilike(like),
                    Articolo.serial_number.ilike(like),
                    Articolo.ns_rif.ilike(like),
                    Articolo.codice_entrata.ilike(like),
                ))

            total = qry.count()
            rows = qry.order_by(Articolo.id_articolo.desc()).offset(offset).limit(limit).all()

            items = []
            for a in rows:
                items.append({
                    "id": a.id_articolo,
                    "codice": a.codice_articolo,
                    "descrizione": a.descrizione,
                    "cliente": (a.cliente or ""),
                    "lotto": (a.lotto or ""),
                    "serial_number": (a.serial_number or ""),
                    "colli": a.n_colli,
                    "peso": a.peso,
                    "m2": a.m2,
                    "m3": a.m3,
                    "magazzino": a.magazzino,
                    "posizione": a.posizione,
                    "stato": a.stato,
                    "data_ingresso": a.data_ingresso,
                    "ddt_ingresso": a.n_ddt_ingresso,
                    "codice_entrata": (getattr(a, "codice_entrata", "") or ""),
                })

            return jsonify({
                "cliente": cliente,
                "count": len(items),
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": items,
            })
        finally:
            db.close()

    @app.route("/api/v1/inventario", methods=["GET"])
    def api_inventario():
        """Inventario attuale del cliente.

        Versione alleggerita: usa raggruppamenti SQL invece di caricare tutte le righe in Python.
        """
        cliente = _api_get_cliente_from_key()
        if not cliente:
            return _api_unauthorized()

        raggruppa = (request.args.get("raggruppa") or "lotto").strip().lower()
        if raggruppa not in ("lotto", "codice", "serial"):
            return _api_bad_request("raggruppa deve essere lotto|codice|serial")

        if raggruppa == "serial":
            key_col = Articolo.serial_number
        elif raggruppa == "codice":
            key_col = Articolo.codice_articolo
        else:
            key_col = Articolo.lotto

        db = SessionLocal()
        try:
            rows = (
                db.query(
                    func.coalesce(key_col, "").label("key"),
                    func.min(Articolo.codice_articolo).label("codice"),
                    func.min(Articolo.descrizione).label("descrizione"),
                    func.min(Articolo.lotto).label("lotto"),
                    func.min(Articolo.serial_number).label("serial_number"),
                    func.count(Articolo.id_articolo).label("righe"),
                    func.coalesce(func.sum(Articolo.n_colli), 0).label("colli"),
                    func.coalesce(func.sum(Articolo.peso), 0).label("peso"),
                    func.coalesce(func.sum(Articolo.m2), 0).label("m2"),
                    func.coalesce(func.sum(Articolo.m3), 0).label("m3"),
                )
                .filter(
                    func.upper(Articolo.cliente) == cliente,
                    (Articolo.data_uscita == None) | (Articolo.data_uscita == ""),
                )
                .group_by(key_col)
                .order_by(func.min(Articolo.codice_articolo), func.min(Articolo.lotto), func.min(Articolo.serial_number))
                .all()
            )

            items = []
            for r in rows:
                key = (r.key or "").strip() or "(vuoto)"
                items.append({
                    "key": key,
                    "codice": r.codice,
                    "descrizione": r.descrizione,
                    "lotto": r.lotto,
                    "serial_number": r.serial_number if raggruppa == "serial" else "",
                    "righe": int(r.righe or 0),
                    "colli": int(r.colli or 0),
                    "peso": float(r.peso or 0.0),
                    "m2": float(r.m2 or 0.0),
                    "m3": float(r.m3 or 0.0),
                })

            return jsonify({
                "cliente": cliente,
                "raggruppa": raggruppa,
                "count": len(items),
                "items": items,
            })
        finally:
            db.close()

    @app.route("/api/v1/movimenti", methods=["GET"])
    def api_movimenti():
        """Movimenti ingresso/uscita ricostruiti dai campi articolo.

        Versione alleggerita: legge solo le colonne necessarie e applica un limite di sicurezza.
        """
        cliente = _api_get_cliente_from_key()
        if not cliente:
            return _api_unauthorized()

        lotto = (request.args.get("lotto") or "").strip()
        tipo = (request.args.get("tipo") or "tutti").strip().lower()
        if tipo not in ("ingresso", "uscita", "tutti"):
            return _api_bad_request("tipo deve essere ingresso|uscita|tutti")

        da = to_date_db(request.args.get("da"))
        a = to_date_db(request.args.get("a"))
        limit = _safe_limit(default=1000, max_value=5000)

        db = SessionLocal()
        try:
            qry = db.query(Articolo).filter(func.upper(Articolo.cliente) == cliente)
            if lotto:
                qry = qry.filter(Articolo.lotto == lotto)

            rows = qry.order_by(Articolo.id_articolo.desc()).limit(limit).all()

            out = []
            for art in rows:
                d_in = to_date_db(art.data_ingresso)
                if d_in and tipo in ("ingresso", "tutti"):
                    if (not da or d_in >= da) and (not a or d_in <= a):
                        out.append({
                            "data": d_in.isoformat(),
                            "tipo": "ingresso",
                            "id": art.id_articolo,
                            "codice": art.codice_articolo,
                            "descrizione": art.descrizione,
                            "lotto": art.lotto,
                            "serial_number": art.serial_number,
                            "colli": art.n_colli,
                            "peso": art.peso,
                            "m2": art.m2,
                            "m3": art.m3,
                            "ddt": art.n_ddt_ingresso,
                            "magazzino": art.magazzino,
                            "posizione": art.posizione,
                        })

                d_out = to_date_db(art.data_uscita)
                if d_out and tipo in ("uscita", "tutti"):
                    if (not da or d_out >= da) and (not a or d_out <= a):
                        out.append({
                            "data": d_out.isoformat(),
                            "tipo": "uscita",
                            "id": art.id_articolo,
                            "codice": art.codice_articolo,
                            "descrizione": art.descrizione,
                            "lotto": art.lotto,
                            "serial_number": art.serial_number,
                            "colli": art.n_colli,
                            "peso": art.peso,
                            "m2": art.m2,
                            "m3": art.m3,
                            "ddt": art.n_ddt_uscita,
                            "magazzino": art.magazzino,
                            "posizione": art.posizione,
                        })

            out.sort(key=lambda r: r.get("data") or "", reverse=True)
            if len(out) > limit:
                out = out[:limit]

            return jsonify({
                "cliente": cliente,
                "count": len(out),
                "limit": limit,
                "items": out,
            })
        finally:
            db.close()
