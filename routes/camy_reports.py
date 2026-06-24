# -*- coding: utf-8 -*-
"""CAMY Reports - report giornalieri, briefing operativo e controlli intelligenti.

Modulo sicuro: legge il database e restituisce HTML. Non modifica dati.
Regole operative:
- Protocollo obbligatorio solo per FINCANTIERI.
- Foto obbligatoria solo per RF-DE WAVE.
- Mezzo/trasporto obbligatorio solo per FINCANTIERI, FINCANTIERI ARMATORE, FINCANTIERI SCOPERTO.
"""

import re
from datetime import date, datetime, timedelta
from html import escape
from sqlalchemy import or_, func

CLIENTE_PROTOCOLLO_OBBLIGATORIO = {"FINCANTIERI"}
CLIENTI_MEZZO_OBBLIGATORIO = {"FINCANTIERI", "FINCANTIERI ARMATORE", "FINCANTIERI SCOPERTO"}
CLIENTI_FOTO_OBBLIGATORIA = {"RF-DE WAVE"}


def module_status():
    return "camy_reports attivo"


def _esc(v):
    return escape(str(v or ""))


def _fmt_num(v, dec=2):
    try:
        return f"{float(v or 0):.{dec}f}".replace('.', ',')
    except Exception:
        return "0"


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
    s10 = s[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s10 if fmt == "%Y-%m-%d" else s, fmt).date()
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


def _norm_cli(v):
    return re.sub(r"\s+", " ", str(v or "").strip().upper())


def _is_blank(v):
    return not str(v or "").strip()


def _active(row):
    return _is_blank(getattr(row, 'data_uscita', None))


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
        return db.query(model).order_by(getattr(model, 'id', getattr(model, 'id_articolo', None)).desc()).limit(limit).all()
    except Exception:
        try:
            return db.query(model).limit(limit).all()
        except Exception:
            return []


def _att_map_for_rows(db, Attachment, rows, limit=5000):
    att_map = {}
    if Attachment is None:
        return att_map
    try:
        ids = [getattr(r, 'id_articolo', None) for r in rows if getattr(r, 'id_articolo', None)]
        if not ids:
            return att_map
        for a in db.query(Attachment).filter(Attachment.articolo_id.in_(ids[:2000])).limit(limit).all():
            att_map.setdefault(a.articolo_id, set()).add((a.kind or '').lower())
    except Exception:
        pass
    return att_map


def _riga_link(row):
    rid = _esc(getattr(row, 'id_articolo', ''))
    arr = _esc(getattr(row, 'n_arrivo', '') or '-')
    cod = _esc(getattr(row, 'codice_articolo', '') or '-')
    pos = _esc(getattr(row, 'posizione', '') or '-')
    proto = _esc(getattr(row, 'protocollo', '') or '-')
    return f"ID <b>{rid}</b> | Arrivo {arr} | Codice {cod} | Pos. {pos} | Protocollo {proto}"


def _filtered_rows_for_client_scope(db, Articolo, session, limit=5000):
    cliente_bloccato = ""
    try:
        role = session.get('role') if session is not None else ''
        user = (session.get('user') or session.get('username') or '') if session is not None else ''
        if role == 'client':
            cliente_bloccato = str(user or '').strip().upper()
    except Exception:
        cliente_bloccato = ""

    q = db.query(Articolo)
    if cliente_bloccato:
        q = q.filter(func.upper(Articolo.cliente) == cliente_bloccato)
    try:
        return q.order_by(Articolo.id_articolo.desc()).limit(limit).all()
    except Exception:
        return q.limit(limit).all()


def _protocollo_mancante_rows(rows):
    return [r for r in rows if _active(r) and _norm_cli(getattr(r, 'cliente', '')) in CLIENTE_PROTOCOLLO_OBBLIGATORIO and _is_blank(getattr(r, 'protocollo', None))]


def _foto_mancante_rows(rows, att_map):
    out = []
    for r in rows:
        if not _active(r):
            continue
        if _norm_cli(getattr(r, 'cliente', '')) not in CLIENTI_FOTO_OBBLIGATORIA:
            continue
        if 'photo' not in att_map.get(getattr(r, 'id_articolo', None), set()):
            out.append(r)
    return out


def _mezzo_mancante_rows(rows):
    out = []
    for r in rows:
        if _norm_cli(getattr(r, 'cliente', '')) not in CLIENTI_MEZZO_OBBLIGATORIO:
            continue
        if _is_blank(getattr(r, 'n_ddt_uscita', None)):
            continue
        if _is_blank(getattr(r, 'mezzi_in_uscita', None)):
            out.append(r)
    return out


def _render_rows(title, rows, max_rows=20, empty="Nessuna riga trovata."):
    out = [f"<b>{_esc(title)}</b><br>"]
    if not rows:
        out.append(f"• {empty}<br>")
        return "".join(out)
    for r in rows[:max_rows]:
        out.append(f"• {_riga_link(r)}<br>")
    if len(rows) > max_rows:
        out.append(f"• ... altre {len(rows) - max_rows} righe.<br>")
    return "".join(out)


def _specific_alert_response(msg, rows, att_map):
    low = (msg or "").lower()
    wants_protocol = any(x in low for x in ["protocollo", "protocolli", "senza protocollo"])
    wants_photo = any(x in low for x in ["foto", "senza foto"])
    wants_mezzo = any(x in low for x in ["mezzo", "trasporto", "senza mezzo"])

    if wants_protocol and not (wants_photo or wants_mezzo):
        protocolli = _protocollo_mancante_rows(rows)
        out = [f"<b>📋 Protocolli mancanti FINCANTIERI</b><br>"]
        out.append(f"Ho trovato <b>{len(protocolli)}</b> articolo/i FINCANTIERI in giacenza senza protocollo.<br><br>")
        out.append(_render_rows("Dettaglio", protocolli, empty="Nessun protocollo mancante per FINCANTIERI."))
        return "".join(out)

    if wants_photo and not (wants_protocol or wants_mezzo):
        foto = _foto_mancante_rows(rows, att_map)
        out = [f"<b>📷 Foto mancanti RF-DE WAVE</b><br>"]
        out.append(f"Ho trovato <b>{len(foto)}</b> articolo/i RF-DE WAVE in giacenza senza foto.<br><br>")
        out.append(_render_rows("Dettaglio", foto, empty="Nessuna foto mancante per RF-DE WAVE."))
        return "".join(out)

    if wants_mezzo and not (wants_protocol or wants_photo):
        mezzi = _mezzo_mancante_rows(rows)
        ddt = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in mezzi if (getattr(r, 'n_ddt_uscita', '') or '').strip()})
        out = [f"<b>🚛 DDT senza mezzo obbligatorio</b><br>"]
        out.append("Controllo solo FINCANTIERI, FINCANTIERI ARMATORE e FINCANTIERI SCOPERTO.<br>")
        out.append(f"Ho trovato <b>{len(ddt)}</b> DDT con mezzo mancante.<br><br>")
        if ddt:
            for d in ddt[:30]:
                out.append(f"• DDT {_esc(d)}<br>")
            if len(ddt) > 30:
                out.append(f"• ... altri {len(ddt)-30} DDT.<br>")
        else:
            out.append("• Nessun DDT senza mezzo trovato.<br>")
        return "".join(out)

    return None


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

    recent_art = _filtered_rows_for_client_scope(db, Articolo, session, limit=5000)
    att_map = _att_map_for_rows(db, Attachment, recent_art[:2000])

    specific = _specific_alert_response(msg, recent_art, att_map)
    if specific:
        return specific

    entrate = [r for r in recent_art if _as_date(getattr(r, 'data_ingresso', None)) == giorno]
    uscite = [r for r in recent_art if _as_date(getattr(r, 'data_uscita', None)) == giorno]

    trasporti = _rows_for_day(_safe_query(db, Trasporto), 'data', giorno) if Trasporto is not None else []
    lavorazioni = _rows_for_day(_safe_query(db, Lavorazione), 'data', giorno) if Lavorazione is not None else []

    buoni_oggi = set()
    buoni_attivi = set()
    for r in recent_art:
        buono = (getattr(r, 'buono_n', '') or '').strip()
        if not buono:
            continue
        if _active(r):
            buoni_attivi.add(buono)
        updated = _as_date(getattr(r, 'updated_at', None))
        if updated == giorno or _as_date(getattr(r, 'data_ingresso', None)) == giorno or _as_date(getattr(r, 'data_uscita', None)) == giorno:
            buoni_oggi.add(buono)

    ddt_oggi = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in uscite if (getattr(r, 'n_ddt_uscita', '') or '').strip()})
    ddt_trasporti = {(getattr(t, 'ddt_uscita', '') or '').strip() for t in trasporti if (getattr(t, 'ddt_uscita', '') or '').strip()}
    # DDT senza trasporto solo se cliente è tra quelli con mezzo obbligatorio.
    ddt_oggi_finc = sorted({
        (getattr(r, 'n_ddt_uscita', '') or '').strip()
        for r in uscite
        if (getattr(r, 'n_ddt_uscita', '') or '').strip()
        and _norm_cli(getattr(r, 'cliente', '')) in CLIENTI_MEZZO_OBBLIGATORIO
    })
    ddt_senza_trasporto = [d for d in ddt_oggi_finc if d and d not in ddt_trasporti]

    protocolli_mancanti = _protocollo_mancante_rows(recent_art)
    foto_mancanti = _foto_mancante_rows(recent_art, att_map)
    mezzi_mancanti_rows = _mezzo_mancante_rows(recent_art)
    ddt_mezzo_mancante = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in mezzi_mancanti_rows if (getattr(r, 'n_ddt_uscita', '') or '').strip()})

    tot_in_colli = sum(int(getattr(r, 'n_colli', 0) or 0) for r in entrate)
    tot_out_colli = sum(int(getattr(r, 'n_colli', 0) or 0) for r in uscite)
    costo_trasporti = 0.0
    for t in trasporti:
        try:
            costo_trasporti += float(getattr(t, 'costo', 0) or 0)
        except Exception:
            pass

    out = []
    out.append(f"<b>📋 Situazione operativa del {data_it}</b><br>")
    out.append("<br><b>Quadro giornata</b><br>")
    out.append(f"• Entrate registrate: <b>{len(entrate)}</b> righe - Colli {int(tot_in_colli)}<br>")
    out.append(f"• Uscite/DDT: <b>{len(ddt_oggi)}</b> DDT - Righe {len(uscite)} - Colli {int(tot_out_colli)}<br>")
    out.append(f"• Buoni movimentati oggi: <b>{len(buoni_oggi)}</b><br>")
    out.append(f"• Picking/Lavorazioni: <b>{len(lavorazioni)}</b><br>")
    out.append(f"• Trasporti: <b>{len(trasporti)}</b> - Costo totale € {_fmt_num(costo_trasporti)}<br>")

    out.append("<br><b>⚠️ Controlli operativi da completare</b><br>")
    any_alert = False
    if protocolli_mancanti:
        any_alert = True
        out.append(f"• FINCANTIERI senza protocollo: <b>{len(protocolli_mancanti)}</b><br>")
        for r in protocolli_mancanti[:8]:
            out.append(f"  - {_riga_link(r)}<br>")
        if len(protocolli_mancanti) > 8:
            out.append(f"  - ... altre {len(protocolli_mancanti)-8} righe.<br>")
    if foto_mancanti:
        any_alert = True
        out.append(f"• RF-DE WAVE senza foto: <b>{len(foto_mancanti)}</b><br>")
        for r in foto_mancanti[:8]:
            out.append(f"  - {_riga_link(r)}<br>")
        if len(foto_mancanti) > 8:
            out.append(f"  - ... altre {len(foto_mancanti)-8} righe.<br>")
    if ddt_mezzo_mancante:
        any_alert = True
        out.append(f"• DDT FINCANTIERI/ARMATORE/SCOPERTO senza mezzo in Giacenze: <b>{len(ddt_mezzo_mancante)}</b><br>")
        out.append(f"  - {', '.join(_esc(x) for x in ddt_mezzo_mancante[:12])}<br>")
    if ddt_senza_trasporto:
        any_alert = True
        out.append(f"• DDT FINCANTIERI/ARMATORE/SCOPERTO senza trasporto registrato: {', '.join(_esc(x) for x in ddt_senza_trasporto[:12])}<br>")
    if buoni_attivi:
        any_alert = True
        out.append(f"• Buoni ancora associati a giacenze attive: <b>{len(buoni_attivi)}</b><br>")
    if not any_alert:
        out.append("• Nessuna anomalia principale trovata con le regole operative attuali.<br>")

    out.append("<br><b>Comandi utili</b><br>")
    out.append("• <i>Quali protocolli mancano di Fincantieri?</i><br>")
    out.append("• <i>Quali arrivi RF-DE WAVE sono senza foto?</i><br>")
    out.append("• <i>Quali DDT Fincantieri sono senza mezzo?</i><br>")
    out.append("• <i>Genera registro giornaliero di oggi</i>")
    return "".join(out)
