# -*- coding: utf-8 -*-
"""CAMY Reports - report giornalieri, briefing operativo e controlli intelligenti.

Modulo sicuro: legge il database e restituisce HTML. Non modifica dati.

Regole operative Camar:
- FOTO obbligatoria SOLO per cliente RF-DE WAVE.
- MEZZO/trasporto obbligatorio SOLO per cliente FINCANTIERI.
- PROTOCOLLO obbligatorio SOLO per cliente FINCANTIERI.
"""

import re
from datetime import date, datetime, timedelta
from html import escape
from sqlalchemy import or_, func


RF_DE_WAVE_KEYS = {"RFDEWAVE"}
FINCANTIERI_KEYS = {"FINCANTIERI"}


def module_status():
    return "camy_reports attivo"


def _esc(v):
    return escape(str(v or ""))


def _fmt_num(v, dec=2):
    try:
        return f"{float(v or 0):.{dec}f}".replace('.', ',')
    except Exception:
        return "0"


def _client_key(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _is_rf_de_wave(value):
    return _client_key(value) in RF_DE_WAVE_KEYS


def _is_fincantieri(value):
    return _client_key(value) in FINCANTIERI_KEYS


def _as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    # Supporta anche timestamp tipo "2026-06-18 15:24:31"
    s10 = s[:10]
    for fmt, val in [
        ("%Y-%m-%d", s10),
        ("%d/%m/%Y", s),
        ("%d-%m-%Y", s),
        ("%d.%m.%Y", s),
    ]:
        try:
            return datetime.strptime(val, fmt).date()
        except Exception:
            pass
    return None


def _date_from_message(msg):
    low = (msg or "").lower()
    today = date.today()
    if "ieri" in low:
        return today - timedelta(days=1)
    if "domani" in low:
        return today + timedelta(days=1)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low)
    if m:
        d = int(m.group(1)); mo = int(m.group(2)); y = int(m.group(3) or today.year)
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except Exception:
            return today
    return today


def _rows_for_day(rows, attr, giorno):
    out = []
    for r in rows or []:
        try:
            if _as_date(getattr(r, attr, None)) == giorno:
                out.append(r)
        except Exception:
            pass
    return out


def _safe_query(db, model, limit=3000):
    try:
        order_col = getattr(model, 'id', None) or getattr(model, 'id_articolo', None)
        if order_col is not None:
            return db.query(model).order_by(order_col.desc()).limit(limit).all()
        return db.query(model).limit(limit).all()
    except Exception:
        try:
            return db.query(model).limit(limit).all()
        except Exception:
            return []


def _has_text(value):
    return bool(str(value or "").strip())


def _is_active_articolo(r):
    return not _has_text(getattr(r, 'data_uscita', None)) and not _has_text(getattr(r, 'n_ddt_uscita', None))


def _safe_int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def _safe_float(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _unique_examples(items, limit=8):
    out, seen = [], set()
    for item in items or []:
        key = str(item)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
        if len(out) >= limit:
            break
    return out


def camy_daily_briefing(db, deps, msg=""):
    """Riepilogo operativo: 'come siamo messi oggi', 'situazione operativa', 'cosa manca'."""
    deps = deps or {}
    Articolo = deps.get("Articolo")
    Trasporto = deps.get("Trasporto")
    Lavorazione = deps.get("Lavorazione")
    Attachment = deps.get("Attachment")
    session = deps.get("session")
    giorno = _date_from_message(msg)
    data_it = giorno.strftime("%d/%m/%Y")

    if Articolo is None:
        return "CAMY non riesce a leggere le tabelle del gestionale."

    # Permesso cliente: se login cliente, filtra sul proprio nome.
    cliente_bloccato = ""
    try:
        role = session.get('role') if session is not None else ''
        user = (session.get('user') or session.get('username') or '') if session is not None else ''
        if role == 'client':
            cliente_bloccato = str(user or '').strip().upper()
    except Exception:
        cliente_bloccato = ""

    def base_articoli():
        q = db.query(Articolo)
        if cliente_bloccato:
            q = q.filter(func.upper(Articolo.cliente) == cliente_bloccato)
        return q

    try:
        recent_art = base_articoli().order_by(Articolo.id_articolo.desc()).limit(7000).all()
    except Exception:
        recent_art = []

    entrate = [r for r in recent_art if _as_date(getattr(r, 'data_ingresso', None)) == giorno]
    uscite = [r for r in recent_art if _as_date(getattr(r, 'data_uscita', None)) == giorno]

    trasporti = _rows_for_day(_safe_query(db, Trasporto), 'data', giorno) if Trasporto is not None else []
    lavorazioni = _rows_for_day(_safe_query(db, Lavorazione), 'data', giorno) if Lavorazione is not None else []

    # DDT uscita di oggi, con controllo mezzo SOLO FINCANTIERI.
    ddt_oggi = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in uscite if _has_text(getattr(r, 'n_ddt_uscita', ''))})
    uscite_fincantieri = [r for r in uscite if _is_fincantieri(getattr(r, 'cliente', '')) and _has_text(getattr(r, 'n_ddt_uscita', ''))]
    ddt_fincantieri_oggi = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in uscite_fincantieri if _has_text(getattr(r, 'n_ddt_uscita', ''))})
    ddt_trasporti = {(getattr(t, 'ddt_uscita', '') or '').strip() for t in trasporti if _has_text(getattr(t, 'ddt_uscita', ''))}
    ddt_fincantieri_senza_trasporto = [d for d in ddt_fincantieri_oggi if d and d not in ddt_trasporti]

    # Buoni
    buoni_oggi = set()
    buoni_attivi = {}
    for r in recent_art:
        buono = (getattr(r, 'buono_n', '') or '').strip()
        if not buono:
            continue
        if _is_active_articolo(r):
            key = (buono, (getattr(r, 'cliente', '') or '-').strip())
            buoni_attivi[key] = buoni_attivi.get(key, 0) + 1
        updated = _as_date(getattr(r, 'updated_at', None))
        if updated == giorno or _as_date(getattr(r, 'data_ingresso', None)) == giorno or _as_date(getattr(r, 'data_uscita', None)) == giorno:
            buoni_oggi.add(buono)

    # Allegati: mappa kind per riga.
    att_map = {}
    try:
        if Attachment is not None:
            ids = [getattr(r, 'id_articolo', None) for r in recent_art[:2500] if getattr(r, 'id_articolo', None)]
            if ids:
                for a in db.query(Attachment).filter(Attachment.articolo_id.in_(ids)).limit(8000).all():
                    att_map.setdefault(a.articolo_id, set()).add((a.kind or '').lower())
    except Exception:
        att_map = {}

    # FOTO obbligatoria SOLO RF-DE WAVE.
    rf_senza_foto = []
    # PROTOCOLLO obbligatorio SOLO FINCANTIERI.
    fin_senza_protocollo = []
    # Giacenze oltre 180 giorni.
    oltre_180 = []

    today = date.today()
    for r in recent_art:
        if not _is_active_articolo(r):
            continue
        cli = getattr(r, 'cliente', '') or ''
        arr = (getattr(r, 'n_arrivo', '') or '').strip()
        rid = getattr(r, 'id_articolo', '')
        kinds = att_map.get(rid, set())

        if _is_rf_de_wave(cli) and 'photo' not in kinds:
            rf_senza_foto.append((arr or '-', cli, rid))

        if _is_fincantieri(cli) and not _has_text(getattr(r, 'protocollo', None)):
            fin_senza_protocollo.append((arr or '-', cli, rid))

        data_in = _as_date(getattr(r, 'data_ingresso', None))
        if data_in and (today - data_in).days >= 180:
            oltre_180.append((arr or '-', cli, rid, (today - data_in).days))

    # Documenti PDF mancanti: lo tengo separato e non lo tratto come errore per tutti, ma come controllo generico.
    senza_doc = []
    for r in recent_art[:2500]:
        if not _is_active_articolo(r):
            continue
        rid = getattr(r, 'id_articolo', '')
        if 'doc' not in att_map.get(rid, set()):
            senza_doc.append(((getattr(r, 'n_arrivo', '') or '-').strip(), getattr(r, 'cliente', '') or '-', rid))

    tot_in_colli = sum(_safe_int(getattr(r, 'n_colli', 0)) for r in entrate)
    tot_out_colli = sum(_safe_int(getattr(r, 'n_colli', 0)) for r in uscite)
    costo_trasporti = sum(_safe_float(getattr(t, 'costo', 0)) for t in trasporti)

    out = []
    out.append(f"<b>📋 Situazione operativa del {data_it}</b><br>")
    out.append("<small>Regole applicate: foto obbligatorie solo RF-DE WAVE; mezzo e protocollo obbligatori solo FINCANTIERI.</small><br>")

    out.append("<br><b>Quadro giornata</b><br>")
    out.append(f"• Entrate registrate: <b>{len(entrate)}</b> righe - Colli {int(tot_in_colli)}<br>")
    out.append(f"• Uscite/DDT: <b>{len(ddt_oggi)}</b> DDT - Righe {len(uscite)} - Colli {int(tot_out_colli)}<br>")
    out.append(f"• DDT FINCANTIERI oggi: <b>{len(ddt_fincantieri_oggi)}</b><br>")
    out.append(f"• Buoni movimentati oggi: <b>{len(buoni_oggi)}</b><br>")
    out.append(f"• Picking/Lavorazioni: <b>{len(lavorazioni)}</b><br>")
    out.append(f"• Trasporti: <b>{len(trasporti)}</b> - Costo totale € {_fmt_num(costo_trasporti)}<br>")

    # Cosa spedire oggi: DDT usciti oggi e buoni aperti.
    out.append("<br><b>📦 Cosa risulta da spedire / controllare</b><br>")
    if ddt_oggi:
        out.append(f"• DDT usciti oggi: {', '.join(_esc(x) for x in ddt_oggi[:12])}")
        if len(ddt_oggi) > 12:
            out.append(f" ... +{len(ddt_oggi)-12}")
        out.append("<br>")
    else:
        out.append("• Nessun DDT uscita registrato oggi.<br>")
    if buoni_attivi:
        out.append(f"• Buoni ancora aperti su giacenze attive: <b>{len(buoni_attivi)}</b><br>")
    else:
        out.append("• Nessun buono aperto su giacenze attive.<br>")

    out.append("<br><b>⚠️ Controlli intelligenti</b><br>")
    any_alert = False

    if rf_senza_foto:
        any_alert = True
        out.append(f"• RF-DE WAVE senza foto obbligatoria: <b>{len(rf_senza_foto)}</b><br>")
        for arr, cli, rid in rf_senza_foto[:10]:
            out.append(f"  - Arrivo {_esc(arr)} | ID {_esc(rid)}<br>")

    if fin_senza_protocollo:
        any_alert = True
        out.append(f"• FINCANTIERI senza protocollo obbligatorio: <b>{len(fin_senza_protocollo)}</b><br>")
        for arr, cli, rid in fin_senza_protocollo[:10]:
            out.append(f"  - Arrivo {_esc(arr)} | ID {_esc(rid)}<br>")

    if ddt_fincantieri_senza_trasporto:
        any_alert = True
        out.append(f"• DDT FINCANTIERI senza mezzo/trasporto registrato: <b>{len(ddt_fincantieri_senza_trasporto)}</b><br>")
        out.append("  - " + ", ".join(_esc(x) for x in ddt_fincantieri_senza_trasporto[:12]))
        if len(ddt_fincantieri_senza_trasporto) > 12:
            out.append(f" ... +{len(ddt_fincantieri_senza_trasporto)-12}")
        out.append("<br>")

    if oltre_180:
        any_alert = True
        out.append(f"• Articoli in giacenza da oltre 180 giorni: <b>{len(oltre_180)}</b><br>")
        for arr, cli, rid, giorni in oltre_180[:8]:
            out.append(f"  - {_esc(cli)} | Arrivo {_esc(arr)} | ID {_esc(rid)} | {giorni} giorni<br>")

    if senza_doc:
        # Controllo generico, non segnalo come errore bloccante cliente-specifico.
        out.append(f"• Righe attive senza documento/PDF allegato: <b>{len(senza_doc)}</b> (controllo generale)<br>")

    if not any_alert:
        out.append("• Nessuna anomalia principale trovata con le regole cliente.<br>")

    if buoni_attivi:
        out.append("<br><b>Buoni aperti principali</b><br>")
        for (buono, cliente), count in list(buoni_attivi.items())[:12]:
            out.append(f"• Buono {_esc(buono)} - {_esc(cliente)} - {count} riga/e ancora attive<br>")

    out.append("<br><b>Azioni rapide consigliate</b><br>")
    out.append("• Per il testo da inviare: <i>genera registro giornaliero di oggi</i>.<br>")
    out.append("• Per gli alert: <i>cosa manca oggi</i>.<br>")
    out.append("• Per aprire dettagli: <i>apri buono...</i>, <i>apri picking...</i> o <i>cerca DDT...</i>.")
    return "".join(out)
