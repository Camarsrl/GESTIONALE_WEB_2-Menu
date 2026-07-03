# -*- coding: utf-8 -*-
"""CAMY Queries - funzioni comuni di lettura e contesto per CAMY.

Modulo di supporto: centralizza piccole utilità di ricerca, normalizzazione
e riepilogo contesto. Non modifica il database.
"""

import re
from sqlalchemy import or_, func


def module_status():
    return "camy_queries attivo - query operative centralizzate"


def norm(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def text(value):
    return str(value or "").strip()


def is_active(row):
    return not text(getattr(row, "data_uscita", ""))


def safe_limit(value, default=20, max_limit=200):
    try:
        n = int(value or default)
    except Exception:
        n = default
    return max(1, min(n, max_limit))


def sql_norm_col(func_obj, col):
    expr = func_obj.upper(func_obj.coalesce(col, ""))
    for ch in [" ", "-", "_", "/", "\\", ".", "'", "°", ";", ","]:
        expr = func_obj.replace(expr, ch, "")
    return expr


def apply_text_filter(q, column, value):
    s = text(value)
    if not s:
        return q
    n = norm(s)
    conditions = [column.ilike(f"%{s}%")]
    try:
        col_norm = sql_norm_col(func, column)
        if n:
            conditions.append(col_norm.ilike(f"%{n}%"))
    except Exception:
        pass
    return q.filter(or_(*conditions))


def search_articoli_by_reference(db, Articolo, reference, only_active=True, limit=20):
    ref = text(reference)
    if not ref:
        return []
    q = db.query(Articolo)
    if only_active:
        q = q.filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == ""))
    conds = [
        Articolo.n_arrivo.ilike(f"%{ref}%"),
        Articolo.codice_articolo.ilike(f"%{ref}%"),
        Articolo.protocollo.ilike(f"%{ref}%"),
        Articolo.ordine.ilike(f"%{ref}%"),
        Articolo.n_ddt_ingresso.ilike(f"%{ref}%"),
        Articolo.n_ddt_uscita.ilike(f"%{ref}%"),
        Articolo.buono_n.ilike(f"%{ref}%"),
        Articolo.serial_number.ilike(f"%{ref}%"),
    ]
    return q.filter(or_(*conds)).order_by(Articolo.id_articolo.desc()).limit(safe_limit(limit)).all()


def build_memory_from_rows(rows):
    mem = {}
    rows = rows or []
    if not rows:
        return mem
    first = rows[0]
    for key, attr in [
        ("last_id", "id_articolo"),
        ("last_arrivo", "n_arrivo"),
        ("last_buono", "buono_n"),
        ("last_codice", "codice_articolo"),
        ("last_cliente", "cliente"),
        ("last_protocollo", "protocollo"),
        ("last_ddt", "n_ddt_uscita"),
    ]:
        v = text(getattr(first, attr, ""))
        if v:
            mem[key] = v
    return mem
