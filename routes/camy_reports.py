# -*- coding: utf-8 -*-
"""CAMY Reports - report giornalieri, briefing operativo e controlli intelligenti.

Modulo sicuro: legge il database e restituisce HTML. Non modifica dati.
"""

import re
from datetime import date, datetime, timedelta
from html import escape
from sqlalchemy import or_, func


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


def _safe_count(query):
    try:
        return int(query.count() or 0)
    except Exception:
        return 0


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
        user = session.get('user') or session.get('username') or '' if session is not None else ''
        if role == 'client':
            cliente_bloccato = str(user or '').strip().upper()
    except Exception:
        cliente_bloccato = ""

    def base_articoli():
        q = db.query(Articolo)
        if cliente_bloccato:
            q = q.filter(func.upper(Articolo.cliente) == cliente_bloccato)
        return q

    # Scarico query giornaliere lato Python per reggere date salvate come TEXT o DATE.
    try:
        recent_art = base_articoli().order_by(Articolo.id_articolo.desc()).limit(5000).all()
    except Exception:
        recent_art = []

    entrate = [r for r in recent_art if _as_date(getattr(r, 'data_ingresso', None)) == giorno]
    uscite = [r for r in recent_art if _as_date(getattr(r, 'data_uscita', None)) == giorno]

    trasporti = []
    if Trasporto is not None:
        trasporti = _rows_for_day(_safe_query(db, Trasporto), 'data', giorno)

    lavorazioni = []
    if Lavorazione is not None:
        lavorazioni = _rows_for_day(_safe_query(db, Lavorazione), 'data', giorno)

    # Buoni di prelievo creati oggi: non c'è sempre una data buono dedicata, quindi stimiamo dai record aggiornati/usciti/ingressi di oggi con buono_n.
    buoni_oggi = set()
    buoni_attivi = set()
    for r in recent_art:
        buono = (getattr(r, 'buono_n', '') or '').strip()
        if not buono:
            continue
        if not (getattr(r, 'data_uscita', '') or '').strip():
            buoni_attivi.add(buono)
        updated = _as_date(getattr(r, 'updated_at', None))
        if updated == giorno or _as_date(getattr(r, 'data_ingresso', None)) == giorno or _as_date(getattr(r, 'data_uscita', None)) == giorno:
            buoni_oggi.add(buono)

    # DDT uscita del giorno
    ddt_oggi = sorted({(getattr(r, 'n_ddt_uscita', '') or '').strip() for r in uscite if (getattr(r, 'n_ddt_uscita', '') or '').strip()})
    ddt_trasporti = {(getattr(t, 'ddt_uscita', '') or '').strip() for t in trasporti if (getattr(t, 'ddt_uscita', '') or '').strip()}
    ddt_senza_trasporto = [d for d in ddt_oggi if d and d not in ddt_trasporti]

    # Foto/PDF mancanti sugli arrivi recenti/attivi. Limito per non appesantire.
    arrivi_senza_foto = []
    arrivi_senza_doc = []
    try:
        att_map = {}
        if Attachment is not None:
            ids = [getattr(r, 'id_articolo', None) for r in recent_art[:1500] if getattr(r, 'id_articolo', None)]
            if ids:
                for a in db.query(Attachment).filter(Attachment.articolo_id.in_(ids)).limit(5000).all():
                    att_map.setdefault(a.articolo_id, set()).add((a.kind or '').lower())
        for r in recent_art[:1500]:
            if (getattr(r, 'data_uscita', '') or '').strip():
                continue
            cli = (getattr(r, 'cliente', '') or '').strip().upper()
            arr = (getattr(r, 'n_arrivo', '') or '').strip()
            if not arr:
                continue
            kinds = att_map.get(getattr(r, 'id_articolo', None), set())
            # RF-DE WAVE: controllo foto richiesto nel tuo flusso operativo.
            if cli == 'RF-DE WAVE' and 'photo' not in kinds and len(arrivi_senza_foto) < 10:
                arrivi_senza_foto.append((arr, cli, getattr(r, 'id_articolo', '')))
            if 'doc' not in kinds and len(arrivi_senza_doc) < 10:
                arrivi_senza_doc.append((arr, cli, getattr(r, 'id_articolo', '')))
    except Exception:
        pass

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

    out.append("<br><b>⚠️ Controlli da completare</b><br>")
    any_alert = False
    if ddt_senza_trasporto:
        any_alert = True
        out.append(f"• DDT senza trasporto registrato: {', '.join(_esc(x) for x in ddt_senza_trasporto[:10])}<br>")
    if arrivi_senza_foto:
        any_alert = True
        out.append("• Arrivi RF-DE WAVE senza foto:<br>")
        for arr, cli, rid in arrivi_senza_foto[:10]:
            out.append(f"  - {_esc(arr)} | ID {_esc(rid)}<br>")
    if arrivi_senza_doc:
        any_alert = True
        out.append(f"• Prime righe attive senza documento allegato: {len(arrivi_senza_doc)} mostrate<br>")
    if buoni_attivi:
        any_alert = True
        out.append(f"• Buoni ancora associati a giacenze attive: {len(buoni_attivi)}<br>")
    if not any_alert:
        out.append("• Nessuna anomalia principale trovata per oggi.<br>")

    out.append("<br><b>Azioni rapide consigliate</b><br>")
    out.append("• Se vuoi il testo da inviare: scrivi <i>genera registro giornaliero di oggi</i>.<br>")
    out.append("• Se vuoi le anomalie: scrivi <i>cosa manca oggi</i>.<br>")
    out.append("• Se vuoi aprire un dettaglio: scrivi <i>apri buono...</i>, <i>apri picking...</i> o <i>cerca DDT...</i>.")
    return "".join(out)
