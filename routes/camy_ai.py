# -*- coding: utf-8 -*-
"""
Modulo CAMY AI - Assistente intelligente collegato al gestionale.

Prima versione SICURA:
- route separata /camy-ai
- nessuna modifica al database
- ricerca giacenze in linguaggio naturale
- totali giacenze / colli / peso / M2 / M3
- rispetto permessi utente:
  CLIENTI -> solo il proprio cliente
  MAGAZZINO / ADMIN -> tutti i clienti
- OpenAI opzionale tramite variabile ambiente OPENAI_API_KEY
- se OPENAI_API_KEY manca, funziona comunque con parser locale base

Installazione:
1) Salvare questo file in routes/camy_ai.py
2) Nel file principale aggiungere la registrazione del modulo:

try:
    from routes.camy_ai import register_camy_ai_routes
    register_camy_ai_routes(app, globals())
except Exception as e:
    scrivi_log_errore("Modulo CAMY AI non registrato", e)
    print(f"[WARN] modulo CAMY AI non registrato: {e}")

3) Su Render aggiungere Environment Variable:
   OPENAI_API_KEY = la_tua_chiave_api

Nota sicurezza:
Questa versione può anche preparare alcune operazioni guidate.
Le modifiche al database avvengono solo dopo conferma esplicita dell'utente.
Non cancella righe e non esegue scarichi definitivi automatici.
"""


def register_camy_ai_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import os
    import re
    import json
    import html
    from datetime import date, datetime

    from flask import request, jsonify, render_template_string, session, url_for
    from flask_login import login_required, current_user
    from sqlalchemy import or_, func

    CAMY_AI_HTML = """
    {% extends "base.html" %}
    {% block content %}
    <style>
      .camy-ai-card { max-width: 1120px; margin: 20px auto; }
      .camy-ai-box { height: 62vh; overflow-y:auto; background:#f8f9fa; border:1px solid #ddd; border-radius:14px; padding:15px; scroll-behavior:smooth; }
      .camy-ai-msg { margin:8px 0; display:flex; }
      .camy-ai-msg.user { justify-content:flex-end; }
      .camy-ai-bubble { max-width:86%; padding:10px 13px; border-radius:15px; white-space:pre-wrap; line-height:1.38; }
      .camy-ai-msg.user .camy-ai-bubble { background:#0d6efd; color:#fff; border-bottom-right-radius:4px; }
      .camy-ai-msg.bot .camy-ai-bubble { background:#fff; border:1px solid #e1e1e1; border-bottom-left-radius:4px; }
      .camy-ai-quick { display:flex; flex-wrap:wrap; gap:6px; }
      .camy-ai-result { border-top:1px solid #eee; padding-top:8px; margin-top:8px; }
      .camy-ai-result:first-child { border-top:0; padding-top:0; margin-top:0; }
      .camy-ai-input { position:sticky; bottom:0; background:white; padding-top:8px; }
      @media (max-width:768px){
        .camy-ai-card { margin:0; border-radius:0; }
        .camy-ai-box { height:calc(100vh - 280px); min-height:360px; }
        .camy-ai-bubble { max-width:94%; font-size:14px; }
        .camy-ai-quick { overflow-x:auto; flex-wrap:nowrap; padding-bottom:4px; }
        .camy-ai-quick button { white-space:nowrap; min-height:42px; font-size:13px; }
        #camyAiInput { min-height:44px; font-size:16px; }
      }
    </style>

    <div class="container-fluid">
      <div class="card shadow-sm camy-ai-card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>
            <h5 class="mb-0">🧠 CAMY AI - Assistente intelligente</h5>
            <small class="text-muted">Versione operativa sicura: cerca, riepiloga e prepara operazioni con conferma.</small>
          </div>
          <div class="d-flex gap-2">
            <a href="{{ url_for('chatbot') if 'chatbot' in endpoints else '/chatbot' }}" class="btn btn-outline-primary btn-sm">CAMY classica</a>
            <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Home</a>
          </div>
        </div>
        <div class="card-body">
          <div class="alert alert-info py-2 mb-2">
            CAMY AI può cercare nelle giacenze, fare riepiloghi e preparare operazioni. Le modifiche vengono applicate solo dopo conferma.
          </div>

          <div class="camy-ai-quick mb-2">
            <button class="btn btn-sm btn-outline-primary" onclick="camyAiAsk('Quante giacenze attive ho?')">Giacenze attive</button>
            <button class="btn btn-sm btn-outline-primary" onclick="camyAiAsk('Totale colli peso M2 e M3 in giacenza')">Totali</button>
            <button class="btn btn-sm btn-outline-primary" onclick="camyAiFill('Cerca N. arrivo ')">Cerca arrivo</button>
            <button class="btn btn-sm btn-outline-primary" onclick="camyAiFill('Mostrami articoli DOGANALI cliente ')">Dogana</button>
            <button class="btn btn-sm btn-outline-primary" onclick="camyAiFill('Cerca DDT ')">Cerca DDT</button>
            <button class="btn btn-sm btn-outline-warning" onclick="camyAiFill('Prepara buono arrivo ')">Prepara Buono</button>
            <button class="btn btn-sm btn-outline-warning" onclick="camyAiFill('Scarico parziale ID ')">Scarico parziale</button>
            <button class="btn btn-sm btn-outline-success" onclick="camyAiAsk('Cosa puoi fare?')">Aiuto</button>
          </div>

          <div id="camyAiBox" class="camy-ai-box mb-3">
            <div class="camy-ai-msg bot"><div class="camy-ai-bubble">Ciao, sono CAMY AI. Puoi scrivermi ad esempio:<br>• mostrami le giacenze Fincantieri in dogana<br>• cerca N. arrivo 542/26<br>• totale colli e peso di De Wave<br>• dove si trova il codice ABC123<br>• articoli entrati a maggio<br><br>Posso preparare Buoni di Prelievo con conferma e aiutarti ad aprire lo Scarico Parziale.</div></div>
          </div>

          <div class="input-group camy-ai-input">
            <input id="camyAiInput" type="text" class="form-control" placeholder="Scrivi una domanda a CAMY AI..." onkeydown="if(event.key==='Enter'){camyAiSend();}">
            <button class="btn btn-primary" onclick="camyAiSend()">Invia</button>
          </div>
        </div>
      </div>
    </div>

    <script>
      function camyAiAdd(text, who, isHtml=false){
        const box = document.getElementById('camyAiBox');
        const row = document.createElement('div');
        row.className = 'camy-ai-msg ' + who;
        const bubble = document.createElement('div');
        bubble.className = 'camy-ai-bubble';
        if(isHtml && who === 'bot') bubble.innerHTML = text;
        else bubble.textContent = text;
        row.appendChild(bubble);
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
        return row;
      }
      function camyAiAsk(text){
        document.getElementById('camyAiInput').value = text;
        camyAiSend();
      }
      function camyAiFill(text){
        const input = document.getElementById('camyAiInput');
        input.value = text;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      async function camyAiSend(){
        const input = document.getElementById('camyAiInput');
        const text = input.value.trim();
        if(!text) return;
        input.value = '';
        camyAiAdd(text, 'user');
        const loading = camyAiAdd('CAMY AI sta analizzando...', 'bot');
        try{
          const res = await fetch('{{ url_for('camy_ai_api') }}', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({message:text})
          });
          const data = await res.json();
          loading.remove();
          camyAiAdd(data.answer || 'Non ho trovato una risposta.', 'bot', !!data.html);
        }catch(e){
          loading.remove();
          camyAiAdd('CAMY AI ha avuto un errore. Controlla i log admin.', 'bot');
        }
      }

      async function camyAiConfirm(token){
        if(!token) return;
        if(!confirm('Confermi l’operazione proposta da CAMY AI?')) return;
        const loading = camyAiAdd('Confermo l’operazione...', 'bot');
        try{
          const res = await fetch('{{ url_for('camy_ai_confirm') }}', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({token:token})
          });
          const data = await res.json();
          loading.remove();
          camyAiAdd(data.answer || 'Operazione completata.', 'bot', !!data.html);
        }catch(e){
          loading.remove();
          camyAiAdd('CAMY AI non è riuscita a confermare. Controlla i log admin.', 'bot');
        }
      }
    </script>
    {% endblock %}
    """

    def _esc(v):
        return html.escape(str(v or ""))

    def _role():
        try:
            return session.get("role") or getattr(current_user, "role", "") or ""
        except Exception:
            return ""

    def _current_cliente():
        try:
            if _role() == "client":
                return (getattr(current_user, "id", "") or session.get("user") or "").strip().upper()
        except Exception:
            pass
        return ""

    def _norm(value):
        return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())

    def _sql_norm_col(col):
        expr = func.upper(func.coalesce(col, ""))
        for ch in [" ", "-", "_", "/", "\\", ".", "'", "°"]:
            expr = func.replace(expr, ch, "")
        return expr

    def _base_query(db):
        q = db.query(Articolo)
        cliente = _current_cliente()
        if cliente:
            q = q.filter(func.upper(Articolo.cliente) == cliente)
        return q

    def _active_filter(q):
        return q.filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == ""))

    def _fmt_num(v, dec=2):
        try:
            return f"{float(v or 0):.{dec}f}".replace('.', ',')
        except Exception:
            return "0"

    def _parse_date_any(value):
        s = (value or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        return None

    def _month_range_from_message(msg):
        low = (msg or "").lower()
        mesi = {
            "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
            "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
            "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
        }
        year = date.today().year
        my = re.search(r"\b(20\d{2})\b", low)
        if my:
            year = int(my.group(1))
        for nome, num in mesi.items():
            if nome in low:
                import calendar
                last = calendar.monthrange(year, num)[1]
                return f"{year}-{num:02d}-01", f"{year}-{num:02d}-{last:02d}"
        return "", ""

    def _extract_json_from_text(text):
        s = (text or "").strip()
        if not s:
            return {}
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s)
            s = re.sub(r"\s*```$", "", s)
        try:
            return json.loads(s)
        except Exception:
            m = re.search(r"\{.*\}", s, flags=re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return {}
        return {}

    def _ai_extract_intent(msg):
        """Usa OpenAI solo per trasformare la domanda in filtri JSON.
        La query DB resta sempre eseguita dal nostro codice, non dal modello.
        """
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return {}
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            instructions = (
                "Sei un estrattore JSON per un gestionale magazzino italiano. "
                "Devi restituire SOLO JSON valido, senza markdown. "
                "Non inventare dati. Campi ammessi: "
                "action ('search'|'totals'|'help'), cliente, codice_articolo, descrizione, n_arrivo, ddt, stato, "
                "fornitore, serial_number, lotto, posizione, only_active (boolean), date_field ('data_ingresso'|'data_uscita'), "
                "date_from, date_to, limit. Usa stringhe vuote se non presenti. "
                "Se chiede quante/totale/somma, action='totals'. Se chiede cerca/mostra/dove, action='search'."
            )
            response = client.responses.create(
                model=os.environ.get("CAMY_AI_MODEL", "gpt-5.5"),
                instructions=instructions,
                input=msg,
            )
            return _extract_json_from_text(getattr(response, "output_text", "") or "")
        except Exception as e:
            try:
                scrivi_log_errore("CAMY AI - errore chiamata OpenAI", e)
            except Exception:
                pass
            return {}

    def _local_extract_intent(msg):
        low = (msg or "").lower()
        out = {
            "action": "totals" if any(w in low for w in ["quanti", "quante", "quanto", "totale", "somma", "m2", "m3", "peso", "colli"]) else "search",
            "cliente": "", "codice_articolo": "", "descrizione": "", "n_arrivo": "", "ddt": "", "stato": "",
            "fornitore": "", "serial_number": "", "lotto": "", "posizione": "",
            "only_active": any(w in low for w in ["giacenza", "giacenze", "attive", "attivi", "ancora", "presenti", "magazzino"]),
            "date_field": "data_ingresso", "date_from": "", "date_to": "", "limit": 10,
        }
        if "dogan" in low:
            out["stato"] = "DOGANALE"
        elif "nazional" in low:
            out["stato"] = "NAZIONALE"

        m = re.search(r"(?:n\.?\s*)?arrivo\s+([A-Z0-9./\-_ ]+?)(?=\s+(?:cliente|codice|ddt|dogan|nazional|stato|fornitore|posizione)\b|$)", msg or "", re.I)
        if m:
            out["n_arrivo"] = m.group(1).strip()
        m = re.search(r"\bddt\s+([A-Z0-9./\-_]+)", msg or "", re.I)
        if m:
            out["ddt"] = m.group(1).strip()
        m = re.search(r"\bcodice(?:\s+articolo)?\s+([A-Z0-9./\-_]+)", msg or "", re.I)
        if m:
            out["codice_articolo"] = m.group(1).strip()
        m = re.search(r"\bserial(?:e| number)?\s+([A-Z0-9./\-_]+)", msg or "", re.I)
        if m:
            out["serial_number"] = m.group(1).strip()
        m = re.search(r"\blotto\s+([A-Z0-9./\-_]+)", msg or "", re.I)
        if m:
            out["lotto"] = m.group(1).strip()

        # Riconoscimento cliente dai clienti validi già presenti nel gestionale.
        try:
            clienti = get_clienti_utenti()
        except Exception:
            clienti = []
        msg_norm = _norm(msg)
        for cli in sorted(clienti, key=lambda x: len(_norm(x)), reverse=True):
            if _norm(cli) and _norm(cli) in msg_norm:
                out["cliente"] = cli
                break

        da, a = _month_range_from_message(msg)
        if da and a:
            out["date_from"] = da
            out["date_to"] = a

        if "uscit" in low:
            out["date_field"] = "data_uscita"
            if out["action"] == "totals":
                out["only_active"] = False
        return out

    def _extract_intent(msg):
        data = _ai_extract_intent(msg)
        if not data:
            data = _local_extract_intent(msg)
        local = _local_extract_intent(msg)
        # integrazione sicura: se AI non ha preso mese o stato, uso parser locale.
        for k in ("date_from", "date_to", "stato", "cliente", "n_arrivo", "ddt", "codice_articolo"):
            if not data.get(k) and local.get(k):
                data[k] = local[k]
        data.setdefault("action", local.get("action", "search"))
        data.setdefault("only_active", local.get("only_active", True))
        data.setdefault("limit", 10)
        return data

    def _apply_norm_equals_or_like(q, column, value):
        s = (value or "").strip()
        if not s:
            return q
        n = _norm(s)
        col_norm = _sql_norm_col(column)
        conditions = [column.ilike(f"%{s}%")]
        if n:
            conditions.append(col_norm.ilike(f"%{n}%"))
        return q.filter(or_(*conditions))

    def _apply_filters(q, filters):
        if filters.get("only_active"):
            q = _active_filter(q)

        if _role() != "client" and filters.get("cliente"):
            q = _apply_norm_equals_or_like(q, Articolo.cliente, filters.get("cliente"))

        if filters.get("codice_articolo"):
            q = _apply_norm_equals_or_like(q, Articolo.codice_articolo, filters.get("codice_articolo"))
        if filters.get("descrizione"):
            q = _apply_norm_equals_or_like(q, Articolo.descrizione, filters.get("descrizione"))
        if filters.get("n_arrivo"):
            q = _apply_norm_equals_or_like(q, Articolo.n_arrivo, filters.get("n_arrivo"))
        if filters.get("ddt"):
            ddt = filters.get("ddt")
            q = q.filter(or_(Articolo.n_ddt_ingresso.ilike(f"%{ddt}%"), Articolo.n_ddt_uscita.ilike(f"%{ddt}%")))
        if filters.get("stato"):
            q = _apply_norm_equals_or_like(q, Articolo.stato, filters.get("stato"))
        if filters.get("fornitore"):
            q = _apply_norm_equals_or_like(q, Articolo.fornitore, filters.get("fornitore"))
        if filters.get("serial_number"):
            q = _apply_norm_equals_or_like(q, Articolo.serial_number, filters.get("serial_number"))
        if filters.get("lotto"):
            q = _apply_norm_equals_or_like(q, Articolo.lotto, filters.get("lotto"))
        if filters.get("posizione"):
            q = _apply_norm_equals_or_like(q, Articolo.posizione, filters.get("posizione"))

        date_field = filters.get("date_field") or "data_ingresso"
        col = Articolo.data_uscita if date_field == "data_uscita" else Articolo.data_ingresso
        date_from = _parse_date_any(filters.get("date_from") or "")
        date_to = _parse_date_any(filters.get("date_to") or "")
        if date_from:
            q = q.filter(col >= date_from.strftime("%Y-%m-%d"))
        if date_to:
            q = q.filter(col <= date_to.strftime("%Y-%m-%d"))
        return q

    def _row_html(a):
        stato = "USCITO" if (getattr(a, "data_uscita", "") or "").strip() else "IN GIACENZA"
        try:
            link = url_for("giacenze", id=str(a.id_articolo))
        except Exception:
            link = "/giacenze"
        return (
            "<div class='camy-ai-result'>"
            f"<b>ID {_esc(a.id_articolo)} | {_esc(stato)}</b><br>"
            f"Cliente: {_esc(a.cliente or '-')}<br>"
            f"Fornitore: {_esc(a.fornitore or '-')}<br>"
            f"Codice: {_esc(a.codice_articolo or '-')}<br>"
            f"Descrizione: {_esc((a.descrizione or '-')[:180])}<br>"
            f"N. arrivo: {_esc(a.n_arrivo or '-')} | DDT ingresso: {_esc(a.n_ddt_ingresso or '-')} | DDT uscita: {_esc(a.n_ddt_uscita or '-')}<br>"
            f"Colli: {_esc(a.n_colli or 0)} | Peso: {_esc(_fmt_num(a.peso))} kg | M2: {_esc(_fmt_num(a.m2))} | M3: {_esc(_fmt_num(a.m3))}<br>"
            f"Magazzino: {_esc(a.magazzino or '-')} | Posizione: {_esc(a.posizione or '-')} | Stato: {_esc(a.stato or '-')}"
            f"<br><a class='btn btn-sm btn-outline-primary mt-1' href='{_esc(link)}'>Apri in Giacenze</a>"
            + (
                f" <a class='btn btn-sm btn-outline-warning mt-1' href='{_esc(url_for('scarico_parziale', id_articolo=a.id_articolo))}'>Scarico parziale</a>"
                if (_role() == 'admin' and not (getattr(a, 'data_uscita', '') or '').strip()) else ""
            )
            + "</div>"
        )

    def _answer_help():
        return (
            "<b>CAMY AI può aiutarti a interrogare il gestionale.</b><br>"
            "Esempi:<br>"
            "• Quante giacenze attive ha Fincantieri?<br>"
            "• Mostrami gli articoli DOGANALI entrati a maggio.<br>"
            "• Cerca N. arrivo 542/26.<br>"
            "• Dove si trova il codice ABC123?<br>"
            "• Totale colli, peso, M2 e M3 di De Wave.<br>"
            "• Prepara buono arrivo 542/26 buono 45/26.<br>"
            "• Scarico parziale ID 12345.<br><br>"
            "Le operazioni che modificano dati richiedono sempre conferma."
        )

    def _answer_totals(db, filters):
        q = _apply_filters(_base_query(db), filters)
        rec = q.with_entities(
            func.count(Articolo.id_articolo),
            func.coalesce(func.sum(Articolo.n_colli), 0),
            func.coalesce(func.sum(Articolo.peso), 0),
            func.coalesce(func.sum(Articolo.m2), 0),
            func.coalesce(func.sum(Articolo.m3), 0),
        ).first()
        righe, colli, peso, m2, m3 = rec or (0, 0, 0, 0, 0)
        scope = ""
        if _current_cliente():
            scope = f" - {_current_cliente()}"
        elif filters.get("cliente"):
            scope = f" - {filters.get('cliente')}"
        return (
            f"<b>Totali CAMY AI{_esc(scope)}</b><br>"
            f"• Righe: {int(righe or 0)}<br>"
            f"• Colli: {int(colli or 0)}<br>"
            f"• Peso totale: {_esc(_fmt_num(peso))} kg<br>"
            f"• M2 totali: {_esc(_fmt_num(m2))}<br>"
            f"• M3 totali: {_esc(_fmt_num(m3))}"
        )

    def _answer_search(db, filters):
        q = _apply_filters(_base_query(db), filters)
        try:
            limit = int(filters.get("limit") or 10)
        except Exception:
            limit = 10
        limit = max(1, min(limit, 20))
        total = q.with_entities(func.count(Articolo.id_articolo)).scalar() or 0
        rows = q.order_by(Articolo.id_articolo.desc()).limit(limit).all()
        if not rows:
            return "Non ho trovato righe compatibili con la richiesta."
        out = [f"<b>CAMY AI ha trovato {int(total)} risultato/i.</b><br>Mostro massimo {limit} righe:"]
        out.extend(_row_html(a) for a in rows)
        return "<br>".join(out)


    def _can_operate():
        return _role() in ("admin", "magazzino")

    def _operation_denied():
        return "Operazione non consentita: solo admin/magazzino possono preparare modifiche operative."

    def _extract_manual_buono_number(msg):
        """Estrae solo un numero buono scritto davvero dall'utente.
        Evita l'errore classico: 'Prepara buono arrivo 3578' non deve diventare buono='arrivo'.
        Formati accettati:
        - n buono 45/26
        - buono n 45/26
        - numero buono 45/26
        - buono 45/26
        """
        s = msg or ""
        patterns = [
            r"\b(?:n\.?\s*buono|buono\s*n\.?|numero\s+buono)\s*[:\-]?\s*([A-Z0-9][A-Z0-9./\-_]{1,30})",
            r"\bbuono\s+((?:BP[-_/]?)?\d{1,6}\s*/\s*\d{2,4})\b",
        ]
        for pat in patterns:
            for m in re.finditer(pat, s, re.I):
                val = (m.group(1) or "").strip().replace(" ", "")
                if val and val.lower() not in ("arrivo", "codice", "id", "ddt", "prelievo"):
                    return val
        return ""

    def _ensure_progressivi_buoni_table(db):
        """Crea la tabella dei progressivi Buoni di Prelievo se manca."""
        try:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS progressivi_buoni_prelievo (
                    anno VARCHAR(4) PRIMARY KEY,
                    last_num INTEGER NOT NULL
                )
            """))
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    def _max_buono_num_from_articoli(db, anno):
        """Legge i buoni già presenti e ricava il massimo numero dell'anno.
        Serve per non ripartire da 1 su database già popolati.
        """
        max_n = 0
        try:
            rows = (
                db.query(Articolo.buono_n)
                .filter(Articolo.buono_n != None)
                .filter(Articolo.buono_n != "")
                .all()
            )
            # accetta 45/26, BP-45/26, B45/26 ecc.
            pat = re.compile(r"(?:^|[^0-9])(\d{1,6})\s*/\s*" + re.escape(str(anno)) + r"(?:\D|$)", re.I)
            for (val,) in rows:
                s = str(val or "")
                for m in pat.finditer(s):
                    try:
                        max_n = max(max_n, int(m.group(1)))
                    except Exception:
                        pass
        except Exception:
            pass
        return max_n

    def _peek_next_buono_number(db):
        """Anteprima del prossimo N. Buono senza incrementare il progressivo."""
        anno = str(date.today().year)[-2:]
        _ensure_progressivi_buoni_table(db)
        try:
            row = db.execute(text("SELECT last_num FROM progressivi_buoni_prelievo WHERE anno=:anno"), {"anno": anno}).fetchone()
            last_num = int(row[0]) if row and row[0] is not None else 0
        except Exception:
            last_num = 0
        if last_num <= 0:
            last_num = _max_buono_num_from_articoli(db, anno)
        return f"{last_num + 1:02d}/{anno}"

    def _next_buono_number(db):
        """Incrementa e salva il prossimo progressivo Buono di Prelievo."""
        anno = str(date.today().year)[-2:]
        _ensure_progressivi_buoni_table(db)
        try:
            row = db.execute(text("SELECT last_num FROM progressivi_buoni_prelievo WHERE anno=:anno"), {"anno": anno}).fetchone()
            last_num = int(row[0]) if row and row[0] is not None else 0
            if last_num <= 0:
                last_num = _max_buono_num_from_articoli(db, anno)
            new_num = last_num + 1
            if row:
                db.execute(text("UPDATE progressivi_buoni_prelievo SET last_num=:n WHERE anno=:anno"), {"n": new_num, "anno": anno})
            else:
                db.execute(text("INSERT INTO progressivi_buoni_prelievo (anno, last_num) VALUES (:anno, :n)"), {"anno": anno, "n": new_num})
            db.commit()
            return f"{new_num:02d}/{anno}"
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            # Fallback sicuro: usa il massimo già presente + 1, senza bloccare CAMY.
            last_num = _max_buono_num_from_articoli(db, anno)
            return f"{last_num + 1:02d}/{anno}"

    def _extract_buono_number(msg, db=None, consume=False):
        manual = _extract_manual_buono_number(msg)
        if manual:
            return manual
        if db is not None:
            return _next_buono_number(db) if consume else _peek_next_buono_number(db)
        return "AUTOMATICO"

    def _make_token():
        import uuid
        return uuid.uuid4().hex

    def _get_pending_ops():
        data = session.get("camy_ai_pending_ops")
        if not isinstance(data, dict):
            data = {}
        return data

    def _save_pending_op(token, payload):
        data = _get_pending_ops()
        # Tengo poche operazioni in sessione per evitare accumuli.
        if len(data) > 15:
            for k in list(data.keys())[:5]:
                data.pop(k, None)
        data[token] = payload
        session["camy_ai_pending_ops"] = data
        session.modified = True

    def _apply_confirm_button(label, token):
        return (
            f"<button type='button' class='btn btn-sm btn-success mt-2' "
            f"onclick=\"camyAiConfirm('{_esc(token)}')\">{_esc(label)}</button>"
        )

    def _answer_prepare_buono(db, msg):
        if not _can_operate():
            return _operation_denied()

        filters = _extract_intent(msg)
        filters["only_active"] = True

        # Evito modifiche troppo generiche: serve almeno un riferimento preciso.
        has_key = any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto"))
        mid = re.search(r"\bID\s*(\d+)\b", msg or "", re.I)
        if mid:
            ids = [int(mid.group(1))]
            q = _base_query(db).filter(Articolo.id_articolo.in_(ids))
            q = _active_filter(q)
        elif has_key:
            q = _apply_filters(_base_query(db), filters)
        else:
            return (
                "Per preparare un Buono di Prelievo mi serve un riferimento preciso.<br>"
                "Esempi:<br>"
                "• Prepara buono arrivo 3578 buono 45/26<br>"
                "• Prepara buono codice ABC123 buono 45/26<br>"
                "• Prepara buono ID 256498 buono 45/26"
            )

        rows = q.order_by(Articolo.id_articolo.asc()).limit(30).all()
        if not rows:
            return "Non ho trovato righe attive compatibili per preparare il buono."

        total = len(rows)
        if total > 20:
            return (
                f"Ho trovato {total} righe. Per sicurezza non preparo un buono con più di 20 righe da CAMY AI.<br>"
                "Restringi la ricerca con N. arrivo, codice articolo, DDT o ID."
            )

        buono = _extract_buono_number(msg, db=db, consume=False)
        manual_buono = _extract_manual_buono_number(msg)
        token = _make_token()
        ids = [int(r.id_articolo) for r in rows]
        _save_pending_op(token, {
            "type": "set_buono",
            "ids": ids,
            "buono": buono,
            "manual_buono": manual_buono,
        })

        riepilogo = [
            f"<b>Proposta Buono di Prelievo</b><br>",
            f"N. buono proposto: <b>{_esc(buono)}</b><br>",
            f"Righe selezionate: <b>{len(ids)}</b><br>",
            "Alla conferma CAMY assegnerà il progressivo definitivo e lo imposterà sulle righe indicate. Nessuno scarico definitivo verrà eseguito automaticamente.<br>"
        ]
        for r in rows[:8]:
            riepilogo.append(
                f"<div class='camy-ai-result'>"
                f"ID {_esc(r.id_articolo)} | Cliente: {_esc(r.cliente or '-')} | Codice: {_esc(r.codice_articolo or '-')}<br>"
                f"Descrizione: {_esc((r.descrizione or '-')[:120])}<br>"
                f"N. arrivo: {_esc(r.n_arrivo or '-')} | Colli: {_esc(r.n_colli or 0)} | Posizione: {_esc(r.posizione or '-')}"
                f"</div>"
            )
        if len(rows) > 8:
            riepilogo.append(f"<br>Altre righe non mostrate: {len(rows) - 8}.")
        riepilogo.append(_apply_confirm_button("Conferma Buono", token))
        return "".join(riepilogo)

    def _answer_scarico_parziale(db, msg):
        if not _can_operate():
            return _operation_denied()

        mid = re.search(r"\bID\s*(\d+)\b", msg or "", re.I)
        if mid:
            art = _active_filter(_base_query(db)).filter(Articolo.id_articolo == int(mid.group(1))).first()
            if not art:
                return "Non ho trovato una riga attiva con questo ID."
            return (
                f"Ho trovato la riga ID <b>{_esc(art.id_articolo)}</b>.<br>"
                f"Codice: {_esc(art.codice_articolo or '-')}<br>"
                f"Descrizione: {_esc((art.descrizione or '-')[:150])}<br>"
                f"<a class='btn btn-sm btn-warning mt-2' href='{_esc(url_for('scarico_parziale', id_articolo=art.id_articolo))}'>Apri Scarico Parziale</a>"
            )

        filters = _extract_intent(msg)
        filters["only_active"] = True
        if not any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto")):
            return "Per aprire lo scarico parziale indicami un ID o un riferimento preciso. Esempio: Scarico parziale ID 256498."

        rows = _apply_filters(_base_query(db), filters).order_by(Articolo.id_articolo.asc()).limit(10).all()
        if not rows:
            return "Non ho trovato righe attive compatibili."
        if len(rows) == 1:
            art = rows[0]
            return (
                f"Ho trovato una sola riga compatibile.<br>"
                f"ID: <b>{_esc(art.id_articolo)}</b> | Codice: {_esc(art.codice_articolo or '-')}<br>"
                f"<a class='btn btn-sm btn-warning mt-2' href='{_esc(url_for('scarico_parziale', id_articolo=art.id_articolo))}'>Apri Scarico Parziale</a>"
            )
        out = ["Ho trovato più righe. Scegli quella corretta per lo scarico parziale:"]
        out.extend(_row_html(r) for r in rows)
        return "<br>".join(out)

    @app.route("/camy-ai/confirm", methods=["POST"])
    @login_required
    def camy_ai_confirm():
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        if not token:
            return jsonify({"answer": "Token mancante.", "html": False}), 400
        if not _can_operate():
            return jsonify({"answer": _operation_denied(), "html": False}), 403

        pending = _get_pending_ops()
        op = pending.get(token)
        if not op:
            return jsonify({"answer": "Operazione scaduta o non trovata. Ripeti la richiesta.", "html": False}), 404

        db = SessionLocal()
        try:
            if op.get("type") == "set_buono":
                ids = [int(x) for x in op.get("ids") or [] if str(x).isdigit()]
                manual_buono = (op.get("manual_buono") or "").strip()
                buono = manual_buono or _next_buono_number(db)
                if not ids or not buono:
                    return jsonify({"answer": "Dati operazione incompleti.", "html": False}), 400

                q = _base_query(db).filter(Articolo.id_articolo.in_(ids))
                rows = q.all()
                if not rows:
                    return jsonify({"answer": "Nessuna riga trovata da aggiornare.", "html": False}), 404

                for r in rows:
                    r.buono_n = buono
                db.commit()

                pending.pop(token, None)
                session["camy_ai_pending_ops"] = pending
                session.modified = True

                return jsonify({
                    "answer": (
                        f"<b>Buono aggiornato.</b><br>"
                        f"N. buono: <b>{_esc(buono)}</b><br>"
                        f"Righe aggiornate: {len(rows)}<br>"
                        "Ora puoi aprire le giacenze e generare/stampare il Buono di Prelievo."
                    ),
                    "html": True
                })

            return jsonify({"answer": "Tipo operazione non gestito.", "html": False}), 400
        except Exception as e:
            try:
                db.rollback()
                scrivi_log_errore("Errore conferma CAMY AI", e)
            except Exception:
                pass
            return jsonify({"answer": "Errore durante la conferma. Ho registrato il dettaglio nei log admin.", "html": False}), 500
        finally:
            db.close()

    @app.route("/camy-ai", methods=["GET"])
    @login_required
    def camy_ai():
        endpoints = set(app.view_functions.keys())
        return render_template_string(CAMY_AI_HTML, endpoints=endpoints)

    @app.route("/camy-ai/api", methods=["POST"])
    @login_required
    def camy_ai_api():
        data = request.get_json(silent=True) or {}
        msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"answer": "Scrivi una domanda.", "html": False})

        db = SessionLocal()
        try:
            low = msg.lower()
            if any(x in low for x in ["aiuto", "help", "cosa puoi fare", "cosa sai fare"]):
                return jsonify({"answer": _answer_help(), "html": True})

            if any(x in low for x in ["prepara buono", "crea buono", "buono di prelievo"]):
                return jsonify({"answer": _answer_prepare_buono(db, msg), "html": True})

            if "scarico parziale" in low or "scarica parziale" in low:
                return jsonify({"answer": _answer_scarico_parziale(db, msg), "html": True})

            filters = _extract_intent(msg)
            action = (filters.get("action") or "search").lower()
            if action == "totals":
                answer = _answer_totals(db, filters)
            else:
                answer = _answer_search(db, filters)
            return jsonify({"answer": answer, "html": True, "filters": filters})
        except Exception as e:
            try:
                scrivi_log_errore("Errore CAMY AI", e)
            except Exception:
                pass
            return jsonify({"answer": "CAMY AI ha avuto un errore. Ho registrato il dettaglio nei log admin.", "html": False}), 500
        finally:
            db.close()
