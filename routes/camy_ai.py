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

    from flask import request, jsonify, render_template_string, session, url_for, send_file, abort
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
            <a class="btn btn-sm btn-outline-primary" href="/camy-ai?prefill=Quante%20giacenze%20attive%20ho%3F">Giacenze attive</a>
            <a class="btn btn-sm btn-outline-primary" href="/camy-ai?prefill=Totale%20colli%20peso%20M2%20e%20M3%20in%20giacenza">Totali</a>
            <a class="btn btn-sm btn-outline-primary" href="/camy-ai?prefill=Cerca%20N.%20arrivo%20">Cerca arrivo</a>
            <a class="btn btn-sm btn-outline-primary" href="/camy-ai?prefill=Mostrami%20articoli%20DOGANALI%20cliente%20">Dogana</a>
            <a class="btn btn-sm btn-outline-primary" href="/camy-ai?prefill=Cerca%20DDT%20">Cerca DDT</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Prepara%20buono%20arrivo%20">Prepara Buono</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Scarico%20parziale%20ID%20">Scarico parziale</a>
            <a class="btn btn-sm btn-outline-success" href="/camy-ai?prefill=Cosa%20puoi%20fare%3F">Aiuto</a>
          </div>

          <div id="camyAiBox" class="camy-ai-box mb-3">
            {% if initial_user_msg %}
              <div class="camy-ai-msg user"><div class="camy-ai-bubble">{{ initial_user_msg }}</div></div>
              <div class="camy-ai-msg bot"><div class="camy-ai-bubble">{{ initial_bot_answer|safe }}</div></div>
            {% else %}
              <div class="camy-ai-msg bot"><div class="camy-ai-bubble">Ciao, sono CAMY AI. Puoi scrivermi ad esempio:<br>• mostrami le giacenze Fincantieri in dogana<br>• cerca N. arrivo 542/26<br>• totale colli e peso di De Wave<br>• dove si trova il codice ABC123<br>• articoli entrati a maggio<br><br>Posso preparare Buoni di Prelievo con conferma e aiutarti ad aprire lo Scarico Parziale.</div></div>
            {% endif %}
          </div>

          <form class="input-group camy-ai-input" method="get" action="/camy-ai">
            <input id="camyAiInput" name="q" type="text" class="form-control" placeholder="Scrivi una domanda a CAMY AI..." value="{{ initial_input_value or '' }}">
            <button type="submit" class="btn btn-primary" data-camy-send="1">Invia</button>
          </form>
        </div>
      </div>
    </div>

    <script>
      (function(){
        function getBox(){ return document.getElementById('camyAiBox'); }
        function getInput(){ return document.getElementById('camyAiInput'); }

        window.camyAiAdd = function(text, who, isHtml){
          var box = getBox();
          if(!box){ return null; }
          var row = document.createElement('div');
          row.className = 'camy-ai-msg ' + (who || 'bot');
          var bubble = document.createElement('div');
          bubble.className = 'camy-ai-bubble';
          if(isHtml && who === 'bot') bubble.innerHTML = text || '';
          else bubble.textContent = text || '';
          row.appendChild(bubble);
          box.appendChild(row);
          box.scrollTop = box.scrollHeight;
          return row;
        };

        window.camyAiAsk = function(text){
          var input = getInput();
          if(!input) return;
          input.value = text || '';
          window.camyAiSend();
        };

        window.camyAiFill = function(text){
          var input = getInput();
          if(!input) return;
          input.value = text || '';
          input.focus();
          try { input.setSelectionRange(input.value.length, input.value.length); } catch(e){}
        };

        window.camyAiSend = async function(){
          var input = getInput();
          if(!input) return;
          var text = (input.value || '').trim();
          if(!text) return;
          input.value = '';
          window.camyAiAdd(text, 'user', false);
          var loading = window.camyAiAdd('CAMY AI sta analizzando...', 'bot', false);
          try{
            var res = await fetch('/camy-ai/api', {
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify({message:text})
            });
            var data = await res.json();
            if(loading) loading.remove();
            window.camyAiAdd(data.answer || 'Non ho trovato una risposta.', 'bot', !!data.html);
          }catch(e){
            if(loading) loading.remove();
            window.camyAiAdd('CAMY AI ha avuto un errore. Controlla i log admin.', 'bot', false);
          }
        };

        window.camyAiConfirm = async function(token, mode, askPartial){
          if(!token) return;
          mode = mode || 'auto';
          var manualBuono = '';
          var requestedCode = '';
          var requestedDescr = '';
          var requestedPezzi = '';
          var msg = 'Confermi l’operazione proposta da CAMY AI?';

          if(mode === 'manual'){
            manualBuono = prompt('Inserisci il N. Buono manuale, esempio 45/26:');
            if(manualBuono === null) return;
            manualBuono = (manualBuono || '').trim();
            if(!manualBuono){
              window.camyAiAdd('Numero buono manuale non inserito. Operazione annullata.', 'bot', false);
              return;
            }
            msg = 'Confermi l’assegnazione del Buono manuale ' + manualBuono + '?';
          } else {
            msg = 'Confermi l’assegnazione automatica del prossimo N. Buono?';
          }

          if(askPartial){
            requestedCode = prompt('La riga contiene più codici. Inserisci il CODICE che deve uscire nel Buono:');
            if(requestedCode === null) return;
            requestedCode = (requestedCode || '').trim();
            if(!requestedCode){
              window.camyAiAdd('Codice da prelevare non inserito. Operazione annullata.', 'bot', false);
              return;
            }

            requestedDescr = prompt('Inserisci la DESCRIZIONE corretta da mettere nella riga del Buono:');
            if(requestedDescr === null) return;
            requestedDescr = (requestedDescr || '').trim();

            requestedPezzi = prompt('Inserisci i PEZZI da mettere nella riga del Buono:');
            if(requestedPezzi === null) return;
            requestedPezzi = (requestedPezzi || '').trim();
            if(!requestedPezzi){
              window.camyAiAdd('Pezzi da prelevare non inseriti. Operazione annullata.', 'bot', false);
              return;
            }

            msg += String.fromCharCode(10,10) + 'Scarico parziale:' + String.fromCharCode(10) + 'Codice: ' + requestedCode + String.fromCharCode(10) + 'Descrizione: ' + (requestedDescr || '-') + String.fromCharCode(10) + 'Pezzi: ' + requestedPezzi;
          }

          if(!confirm(msg)) return;
          var loading = window.camyAiAdd('Confermo l’operazione...', 'bot', false);
          try{
            var res = await fetch('/camy-ai/confirm', {
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify({
                token:token,
                mode:mode,
                manual_buono:manualBuono,
                requested_code:requestedCode,
                requested_descr:requestedDescr,
                requested_pezzi:requestedPezzi
              })
            });
            var data = await res.json();
            if(loading) loading.remove();
            window.camyAiAdd(data.answer || 'Operazione completata.', 'bot', !!data.html);
          }catch(e){
            if(loading) loading.remove();
            window.camyAiAdd('CAMY AI non è riuscita a confermare. Controlla i log admin.', 'bot', false);
          }
        };

        // Gestione robusta dei bottoni:
        // - i pulsanti rapidi compilano solo il campo, senza inviare;
        // - i pulsanti Automatico/Manuale dentro la risposta funzionano anche se l'onclick inline viene bloccato.
        document.addEventListener('click', function(ev){
          var target = ev.target && ev.target.closest ? ev.target.closest('[data-camy-fill],[data-camy-send],[data-camy-confirm]') : null;
          if(!target) return;
          ev.preventDefault();
          ev.stopPropagation();

          if(target.hasAttribute('data-camy-confirm')){
            var token = target.getAttribute('data-camy-token') || '';
            var mode = target.getAttribute('data-camy-mode') || 'auto';
            var askPartial = (target.getAttribute('data-camy-partial') || '').toLowerCase() === 'true';
            window.camyAiConfirm(token, mode, askPartial);
            return;
          }

          if(target.hasAttribute('data-camy-fill')){
            window.camyAiFill(target.getAttribute('data-camy-fill') || '');
            return;
          }

          if(target.hasAttribute('data-camy-send')){
            window.camyAiSend();
          }
        });

        var input = getInput();
        if(input){
          input.addEventListener('keydown', function(ev){
            if(ev.key === 'Enter'){
              ev.preventDefault();
              window.camyAiSend();
            }
          });
        }

        window.camyAiReady = true;
      })();
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
            "• Prepara buono arrivo 542/26.<br>"
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

    def _apply_buono_choice_buttons(token, ask_partial=False):
        partial_flag = "true" if ask_partial else "false"
        safe_token = _esc(token)
        return (
            "<div class='mt-2 d-flex flex-wrap gap-2'>"
            f"<button type='button' class='btn btn-sm btn-success' "
            f"data-camy-confirm='1' data-camy-token='{safe_token}' data-camy-mode='auto' data-camy-partial='{partial_flag}'>Automatico</button>"
            f"<button type='button' class='btn btn-sm btn-outline-primary' "
            f"data-camy-confirm='1' data-camy-token='{safe_token}' data-camy-mode='manual' data-camy-partial='{partial_flag}'>Manuale</button>"
            "</div>"
        )


    def _split_multi_values(value, allow_dash=False):
        """Divide campi multipli mantenendo l'ordine: codice / descrizione / pezzi."""
        s = str(value or "").strip()
        if not s:
            return []

        # Separatori sicuri: slash anche senza spazi, punto e virgola, +, a capo, virgola.
        parts = re.split(r"\s*(?:;|\+|\n|\r|,|/)\s*", s)
        parts = [p.strip() for p in parts if p and p.strip()]

        # Caso frequente nel gestionale: codici o descrizioni uniti con trattino.
        # Non dividiamo codici numerici tipo 1691045-0025-1-000.
        if len(parts) == 1 and allow_dash and "-" in s:
            dash_parts = [p.strip() for p in re.split(r"\s*-\s*", s) if p.strip()]
            if len(dash_parts) > 1:
                alpha_parts = sum(1 for p in dash_parts if re.search(r"[A-Za-z]", p))
                long_parts = sum(1 for p in dash_parts if len(p) >= 3)
                if alpha_parts >= 2 and long_parts >= 2:
                    parts = dash_parts

        return parts if parts else ([s] if s else [])

    def _join_multi_values(parts):
        parts = [str(p or "").strip() for p in (parts or []) if str(p or "").strip()]
        return " / ".join(parts)

    def _row_needs_partial_details(row):
        """True se la riga sembra contenere più codici/descrizioni e quindi serve scegliere cosa prelevare."""
        try:
            code_parts = _split_multi_values(getattr(row, "codice_articolo", ""), allow_dash=True)
            desc_parts = _split_multi_values(getattr(row, "descrizione", ""), allow_dash=True)
            pezzi_parts = _split_multi_values(getattr(row, "pezzo", ""))
            return len(code_parts) > 1 or len(desc_parts) > 1 or len(pezzi_parts) > 1
        except Exception:
            return False

    def _norm_part(value):
        return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())

    def _find_requested_index(parts, requested):
        req = _norm_part(requested)
        if not parts or not req:
            return -1
        # 1) match esatto normalizzato
        for i, p in enumerate(parts):
            if _norm_part(p) == req:
                return i
        # 2) match contenuto, utile se il codice ha spazi o testo aggiuntivo
        for i, p in enumerate(parts):
            np = _norm_part(p)
            if req and (req in np or np in req):
                return i
        return -1

    def _extract_requested_pezzi(msg):
        s = msg or ""
        patterns = [
            r"\b(?:pezzi|pezzo|pz|qta|qtà|quantita|quantità)\s*[:\-]?\s*([0-9]+(?:[,.][0-9]+)?)",
            r"\b([0-9]+(?:[,.][0-9]+)?)\s*(?:pezzi|pezzo|pz)\b",
        ]
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                return (m.group(1) or "").strip().replace(",", ".")
        return ""

    def _extract_requested_descrizione(msg):
        s = msg or ""
        patterns = [
            r"\b(?:descrizione|desc)\s*[:\-]?\s*(.+?)(?=\s+(?:pezzi|pezzo|pz|qta|qtà|quantita|quantità|buono|n\.?\s*buono|automatico|manuale)\b|$)",
        ]
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                return (m.group(1) or "").strip(" ;,.-")
        return ""

    def _safe_int_or_none(value):
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    def _safe_float_or_none(value):
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    def _copy_articolo_for_partial(src):
        """Copia una riga Articolo senza id e senza allegati per creare la riga del prelievo."""
        new = Articolo()
        try:
            for col in Articolo.__table__.columns:
                name = col.name
                if name == "id_articolo":
                    continue
                if hasattr(src, name):
                    setattr(new, name, getattr(src, name))
        except Exception:
            # Fallback sui campi principali se l'introspezione non fosse disponibile.
            for name in [
                "codice_articolo", "descrizione", "cliente", "fornitore", "magazzino",
                "protocollo", "ordine", "commessa", "buono_n", "n_arrivo", "ns_rif",
                "serial_number", "pezzo", "n_colli", "peso", "larghezza", "lunghezza",
                "altezza", "m2", "m3", "posizione", "stato", "note", "mezzi_in_uscita",
                "data_ingresso", "n_ddt_ingresso", "data_uscita", "n_ddt_uscita",
                "codice_entrata", "lotto"
            ]:
                if hasattr(src, name):
                    setattr(new, name, getattr(src, name))
        return new

    def _prepare_partial_split_for_buono(row, buono, requested_code="", requested_descr="", requested_pezzi=""):
        """Crea la nuova riga per il Buono e aggiorna la riga originale con il residuo.

        Ritorna (new_row, info_dict) se fa split, altrimenti (None, info_dict).
        """
        code_parts = _split_multi_values(getattr(row, "codice_articolo", ""), allow_dash=True)
        desc_parts = _split_multi_values(getattr(row, "descrizione", ""), allow_dash=True)
        pezzi_parts = _split_multi_values(getattr(row, "pezzo", ""))

        requested_code = (requested_code or "").strip()
        requested_descr = (requested_descr or "").strip()
        requested_pezzi = (requested_pezzi or "").strip()

        idx = _find_requested_index(code_parts, requested_code)
        if idx < 0 and requested_descr:
            idx = _find_requested_index(desc_parts, requested_descr)

        # Se non ho un codice/descrizione richiesti o non c'è una riga multipla, non faccio split.
        is_multi = len(code_parts) > 1 or len(desc_parts) > 1 or len(pezzi_parts) > 1
        if idx < 0 or not is_multi:
            return None, {"reason": "no_split", "is_multi": is_multi, "idx": idx}

        selected_code = code_parts[idx] if idx < len(code_parts) else requested_code
        selected_desc = (
            requested_descr
            or (desc_parts[idx] if idx < len(desc_parts) else (getattr(row, "descrizione", "") or ""))
        )
        selected_pezzi = (
            requested_pezzi
            or (pezzi_parts[idx] if idx < len(pezzi_parts) else "")
        )

        # Se il campo pezzi non è multiplo ma l'utente indica i pezzi da prelevare,
        # calcolo il residuo numerico sulla riga originale.
        original_pezzo_num = _safe_float_or_none(getattr(row, "pezzo", ""))
        selected_pezzo_num = _safe_float_or_none(selected_pezzi)
        if not pezzi_parts and requested_pezzi:
            selected_pezzi = requested_pezzi

        # Residuo: tolgo gli elementi corrispondenti all'indice scelto.
        resid_code_parts = [p for i, p in enumerate(code_parts) if i != idx]
        resid_desc_parts = [p for i, p in enumerate(desc_parts) if i != idx] if desc_parts else []
        resid_pezzi_parts = [p for i, p in enumerate(pezzi_parts) if i != idx] if pezzi_parts else []
        if not resid_pezzi_parts and original_pezzo_num is not None and selected_pezzo_num is not None:
            resid = max(0, original_pezzo_num - selected_pezzo_num)
            resid_pezzi_parts = [str(int(resid)) if abs(resid - int(resid)) < 0.0001 else str(round(resid, 3))]

        new_row = _copy_articolo_for_partial(row)
        new_row.codice_articolo = selected_code
        new_row.descrizione = selected_desc
        new_row.pezzo = selected_pezzi
        new_row.buono_n = buono

        # Se l'utente indica pezzi numerici, provo a valorizzare n_colli della riga nuova
        # solo quando il campo n_colli originale sembra riferito ai pezzi totali.
        sel_int = _safe_int_or_none(selected_pezzi)
        if sel_int is not None:
            try:
                new_row.n_colli = sel_int
            except Exception:
                pass

        # Peso proporzionale, se possibile.
        try:
            original_peso = float(getattr(row, "peso", None) or 0)
            all_nums = [_safe_float_or_none(x) for x in pezzi_parts]
            if original_peso and all_nums and all(v is not None for v in all_nums):
                total_pz = sum(all_nums)
                sel_pz = _safe_float_or_none(selected_pezzi)
                if total_pz and sel_pz is not None:
                    new_row.peso = round(original_peso * sel_pz / total_pz, 3)
                    row.peso = round(original_peso - float(new_row.peso or 0), 3)
        except Exception:
            pass

        # Aggiorno la riga vecchia con solo il residuo non uscito.
        row.codice_articolo = _join_multi_values(resid_code_parts)
        if desc_parts:
            row.descrizione = _join_multi_values(resid_desc_parts)
        if resid_pezzi_parts:
            row.pezzo = _join_multi_values(resid_pezzi_parts)

        # Se i pezzi residui sono numerici, aggiorno anche n_colli.
        try:
            nums = [_safe_int_or_none(x) for x in resid_pezzi_parts]
            if nums and all(v is not None for v in nums):
                row.n_colli = sum(nums)
        except Exception:
            pass

        # La riga residua non deve avere il buono del materiale uscito.
        row.buono_n = ""

        return new_row, {
            "reason": "split",
            "idx": idx,
            "selected_code": selected_code,
            "selected_desc": selected_desc,
            "selected_pezzi": selected_pezzi,
            "residue_codes": row.codice_articolo,
            "residue_desc": row.descrizione,
            "residue_pezzi": row.pezzo,
        }


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

        prossimo_auto = _peek_next_buono_number(db)
        manual_buono = _extract_manual_buono_number(msg)
        requested_code = (filters.get("codice_articolo") or "").strip()
        requested_descr = _extract_requested_descrizione(msg)
        requested_pezzi = _extract_requested_pezzi(msg)
        needs_partial_details = any(_row_needs_partial_details(r) for r in rows) and not (requested_code or requested_descr)

        token = _make_token()
        ids = [int(r.id_articolo) for r in rows]
        _save_pending_op(token, {
            "type": "set_buono",
            "ids": ids,
            "manual_buono": manual_buono,
            "requested_code": requested_code,
            "requested_descr": requested_descr,
            "requested_pezzi": requested_pezzi,
            "needs_partial_details": bool(needs_partial_details),
        })

        scelta_manual = f"<br>Numero manuale letto dal messaggio: <b>{_esc(manual_buono)}</b>" if manual_buono else ""
        dettagli_parziale = ""
        if requested_code or requested_descr or requested_pezzi:
            dettagli_parziale = (
                "<br><b>Dati scarico parziale letti:</b> "
                f"Codice: <b>{_esc(requested_code or '-')}</b> | "
                f"Descrizione: <b>{_esc(requested_descr or '-')}</b> | "
                f"Pezzi: <b>{_esc(requested_pezzi or '-')}</b><br>"
                "Se la riga contiene più codici, CAMY creerà una nuova riga per il materiale in uscita "
                "e lascerà sulla riga originale solo codice, descrizione e pezzi residui."
            )
        elif needs_partial_details:
            dettagli_parziale = (
                "<br><b>Scarico parziale rilevato:</b> la riga contiene più codici/descrizioni.<br>"
                "Alla conferma CAMY ti chiederà <b>codice, descrizione e pezzi</b> da mettere nel Buono, "
                "poi creerà una nuova riga e lascerà sulla riga originale solo il residuo."
            )

        riepilogo = [
            f"<b>Proposta Buono di Prelievo</b><br>",
            f"Righe selezionate: <b>{len(ids)}</b><br>",
            f"Vuoi inserire il N. Buono <b>automaticamente</b> o <b>manualmente</b>?<br>",
            f"Prossimo numero automatico previsto: <b>{_esc(prossimo_auto)}</b>{scelta_manual}{dettagli_parziale}<br>",
            "CAMY applicherà la modifica solo dopo conferma. Nessuno scarico definitivo verrà eseguito automaticamente.<br>"
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
        riepilogo.append(_apply_buono_choice_buttons(token, ask_partial=needs_partial_details))
        return "".join(riepilogo)

    def _safe_pdf_filename(value):
        s = str(value or "").strip()
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        return s.strip("_") or "buono"

    def _fmt_date_pdf(value):
        s = str(value or "").strip()
        if not s:
            return ""
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return s

    def _generate_buono_pdf(db, buono):
        """Genera il PDF del Buono di Prelievo CAMY e restituisce (filename, path)."""
        buono = str(buono or "").strip()
        if not buono:
            return "", None

        rows = (
            db.query(Articolo)
            .filter(Articolo.buono_n == buono)
            .order_by(Articolo.id_articolo.asc())
            .all()
        )
        if not rows:
            return "", None

        try:
            base_dir = DOCS_DIR
        except Exception:
            base_dir = MEDIA_DIR / "docs"
        base_dir.mkdir(parents=True, exist_ok=True)

        filename = f"buono_prelievo_{_safe_pdf_filename(buono)}.pdf"
        pdf_path = base_dir / filename

        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        except Exception:
            # Se ReportLab non è disponibile, segnalo tramite log e non blocco il buono.
            return "", None

        styles = getSampleStyleSheet()
        normal = ParagraphStyle(
            "camy_normal",
            parent=styles["Normal"],
            fontSize=7,
            leading=8,
            wordWrap="CJK",
        )
        title_style = ParagraphStyle(
            "camy_title",
            parent=styles["Heading1"],
            fontSize=16,
            leading=18,
            alignment=1,
            spaceAfter=8,
        )
        small = ParagraphStyle(
            "camy_small",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
        )

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=landscape(A4),
            rightMargin=10 * mm,
            leftMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
        )

        story = []
        story.append(Paragraph(f"BUONO DI PRELIEVO N. {html.escape(buono)}", title_style))
        story.append(Paragraph(f"Generato da CAMY AI il {datetime.now().strftime('%d/%m/%Y %H:%M')}", small))
        story.append(Spacer(1, 6))

        clienti = sorted({(getattr(r, 'cliente', '') or '').strip() for r in rows if (getattr(r, 'cliente', '') or '').strip()})
        fornitori = sorted({(getattr(r, 'fornitore', '') or '').strip() for r in rows if (getattr(r, 'fornitore', '') or '').strip()})
        story.append(Paragraph(f"Cliente/i: {html.escape(', '.join(clienti) or '-')}", small))
        story.append(Paragraph(f"Fornitore/i: {html.escape(', '.join(fornitori) or '-')}", small))
        story.append(Spacer(1, 8))

        data = [[
            Paragraph("ID", normal),
            Paragraph("Codice", normal),
            Paragraph("Descrizione", normal),
            Paragraph("Pz", normal),
            Paragraph("Colli", normal),
            Paragraph("Peso", normal),
            Paragraph("N. Arrivo", normal),
            Paragraph("DDT Ing.", normal),
            Paragraph("Magazzino", normal),
            Paragraph("Posizione", normal),
            Paragraph("Data Ing.", normal),
        ]]

        tot_colli = 0
        tot_peso = 0.0
        for r in rows:
            try:
                tot_colli += int(getattr(r, "n_colli", 0) or 0)
            except Exception:
                pass
            try:
                tot_peso += float(getattr(r, "peso", 0) or 0)
            except Exception:
                pass
            data.append([
                Paragraph(str(getattr(r, "id_articolo", "") or ""), normal),
                Paragraph(html.escape(str(getattr(r, "codice_articolo", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "descrizione", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "pezzo", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "n_colli", "") or "")), normal),
                Paragraph(_fmt_num(getattr(r, "peso", 0)), normal),
                Paragraph(html.escape(str(getattr(r, "n_arrivo", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "n_ddt_ingresso", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "magazzino", "") or "")), normal),
                Paragraph(html.escape(str(getattr(r, "posizione", "") or "")), normal),
                Paragraph(html.escape(_fmt_date_pdf(getattr(r, "data_ingresso", "") or "")), normal),
            ])

        table = Table(
            data,
            repeatRows=1,
            colWidths=[13*mm, 38*mm, 65*mm, 14*mm, 15*mm, 20*mm, 30*mm, 25*mm, 25*mm, 25*mm, 22*mm],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(table)
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Totale righe: {len(rows)} - Totale colli: {tot_colli} - Totale peso: {_fmt_num(tot_peso)} kg", small))
        story.append(Spacer(1, 16))
        story.append(Paragraph("Firma magazzino: ________________________________", small))

        doc.build(story)
        return filename, pdf_path

    @app.route("/camy-ai/buono-pdf/<path:filename>", methods=["GET"])
    @login_required
    def camy_ai_buono_pdf(filename):
        if not _can_operate():
            abort(403)
        safe_name = _safe_pdf_filename(filename)
        if not safe_name.lower().endswith(".pdf"):
            abort(404)
        try:
            pdf_path = DOCS_DIR / safe_name
        except Exception:
            pdf_path = MEDIA_DIR / "docs" / safe_name
        if not pdf_path.exists():
            abort(404)
        return send_file(str(pdf_path), as_attachment=True, download_name=safe_name)

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
                mode = (data.get("mode") or "auto").strip().lower()
                manual_from_request = (data.get("manual_buono") or "").strip()
                manual_from_message = (op.get("manual_buono") or "").strip()

                if mode == "manual":
                    buono = manual_from_request or manual_from_message
                    if not buono:
                        return jsonify({"answer": "Numero buono manuale mancante.", "html": False}), 400
                else:
                    buono = _next_buono_number(db)

                if not ids or not buono:
                    return jsonify({"answer": "Dati operazione incompleti.", "html": False}), 400

                q = _base_query(db).filter(Articolo.id_articolo.in_(ids))
                rows = q.all()
                if not rows:
                    return jsonify({"answer": "Nessuna riga trovata da aggiornare.", "html": False}), 404

                requested_code = (data.get("requested_code") or op.get("requested_code") or "").strip()
                requested_descr = (data.get("requested_descr") or op.get("requested_descr") or "").strip()
                requested_pezzi = (data.get("requested_pezzi") or op.get("requested_pezzi") or "").strip()

                if op.get("needs_partial_details") and not (requested_code or requested_descr):
                    return jsonify({
                        "answer": "La riga contiene più codici: per creare il Buono parziale devi indicare almeno il codice o la descrizione da prelevare.",
                        "html": False
                    }), 400

                updated = 0
                created = 0
                split_infos = []

                for r in rows:
                    new_row, info = _prepare_partial_split_for_buono(
                        r,
                        buono,
                        requested_code=requested_code,
                        requested_descr=requested_descr,
                        requested_pezzi=requested_pezzi,
                    )
                    if new_row is not None:
                        db.add(new_row)
                        created += 1
                        updated += 1
                        split_infos.append(info)
                    else:
                        # Se la riga è multipla ma CAMY non ha trovato il codice da separare,
                        # non assegno il Buono alla riga originale per evitare giacenze errate.
                        if info.get("is_multi") and (requested_code or requested_descr):
                            db.rollback()
                            return jsonify({
                                "answer": (
                                    "Non sono riuscita a trovare nella riga il codice/descrizione indicato per lo scarico parziale.<br>"
                                    "Controlla che il codice sia scritto esattamente come in giacenza e ripeti l'operazione."
                                ),
                                "html": True
                            }), 400

                        # Caso normale: una riga singola viene assegnata direttamente al Buono.
                        r.buono_n = buono
                        updated += 1

                db.commit()

                pending.pop(token, None)
                session["camy_ai_pending_ops"] = pending
                session.modified = True

                pdf_link_html = ""
                try:
                    pdf_filename, pdf_path = _generate_buono_pdf(db, buono)
                    if pdf_filename and pdf_path:
                        pdf_url = url_for("camy_ai_buono_pdf", filename=pdf_filename)
                        pdf_link_html = (
                            f"<br><a class='btn btn-sm btn-danger mt-2' href='{_esc(pdf_url)}' target='_blank'>"
                            "Scarica PDF Buono di Prelievo</a>"
                        )
                except Exception as pdf_err:
                    try:
                        scrivi_log_errore("Errore generazione PDF Buono CAMY AI", pdf_err)
                    except Exception:
                        pass
                    pdf_link_html = "<br><span class='text-warning'>Buono aggiornato, ma PDF non generato. Controlla i log admin.</span>"

                extra = ""
                if created:
                    dettagli = []
                    for info in split_infos[:5]:
                        dettagli.append(
                            "<div class='camy-ai-result'>"
                            f"Uscito: <b>{_esc(info.get('selected_code') or '-')}</b> | "
                            f"Descrizione: {_esc(info.get('selected_desc') or '-')} | "
                            f"Pezzi: {_esc(info.get('selected_pezzi') or '-')}<br>"
                            f"Residuo riga originale: {_esc(info.get('residue_codes') or '-')} | "
                            f"{_esc(info.get('residue_desc') or '-')} | "
                            f"Pezzi residui: {_esc(info.get('residue_pezzi') or '-')}"
                            "</div>"
                        )
                    extra = (
                        f"<br>Righe nuove create per scarico parziale: <b>{created}</b><br>"
                        "La riga originale è rimasta in giacenza con solo il materiale residuo."
                        + "".join(dettagli)
                    )

                return jsonify({
                    "answer": (
                        f"<b>Buono aggiornato.</b><br>"
                        f"N. buono: <b>{_esc(buono)}</b><br>"
                        f"Righe elaborate: {updated}<br>"
                        f"{extra}"
                        f"{pdf_link_html}<br>"
                        "Il PDF del Buono di Prelievo è stato generato direttamente da CAMY."
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

    def _process_camy_message(db, msg):
        low = (msg or "").lower()
        if any(x in low for x in ["aiuto", "help", "cosa puoi fare", "cosa sai fare"]):
            return _answer_help(), True, {}

        if any(x in low for x in ["prepara buono", "crea buono", "buono di prelievo"]):
            return _answer_prepare_buono(db, msg), True, {}

        if "scarico parziale" in low or "scarica parziale" in low:
            return _answer_scarico_parziale(db, msg), True, {}

        filters = _extract_intent(msg)
        action = (filters.get("action") or "search").lower()
        if action == "totals":
            answer = _answer_totals(db, filters)
        else:
            answer = _answer_search(db, filters)
        return answer, True, filters

    @app.route("/camy-ai", methods=["GET"])
    @login_required
    def camy_ai():
        endpoints = set(app.view_functions.keys())
        q = (request.args.get("q") or "").strip()
        prefill = (request.args.get("prefill") or "").strip()
        initial_answer = ""
        if q:
            db = SessionLocal()
            try:
                initial_answer, _, _ = _process_camy_message(db, q)
            except Exception as e:
                try:
                    scrivi_log_errore("Errore CAMY AI GET", e)
                except Exception:
                    pass
                initial_answer = "CAMY AI ha avuto un errore. Ho registrato il dettaglio nei log admin."
            finally:
                db.close()
        return render_template_string(
            CAMY_AI_HTML,
            endpoints=endpoints,
            initial_user_msg=q,
            initial_bot_answer=initial_answer,
            initial_input_value=("" if q else prefill)
        )

    @app.route("/camy-ai/api", methods=["POST"])
    @login_required
    def camy_ai_api():
        data = request.get_json(silent=True) or {}
        msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"answer": "Scrivi una domanda.", "html": False})

        db = SessionLocal()
        try:
            answer, is_html, filters = _process_camy_message(db, msg)
            return jsonify({"answer": answer, "html": is_html, "filters": filters})
        except Exception as e:
            try:
                scrivi_log_errore("Errore CAMY AI", e)
            except Exception:
                pass
            return jsonify({"answer": "CAMY AI ha avuto un errore. Ho registrato il dettaglio nei log admin.", "html": False}), 500
        finally:
            db.close()
