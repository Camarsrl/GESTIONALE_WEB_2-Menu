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
            {% if can_operate %}
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Prepara%20buono%20arrivo%20">Prepara Buono</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Scarico%20parziale%20ID%20">Scarico parziale</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Aggiungi%20al%20buono%20">Aggiungi a Buono</a>
            {% endif %}
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
          var noteBuono = '';
          var msg = 'Confermi l’operazione proposta da CAMY AI?';

          if(mode === 'existing'){
            msg = "Confermi l'aggiunta delle righe al Buono esistente?";
          } else if(mode === 'manual'){
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

          noteBuono = prompt('Vuoi inserire una nota da salvare nella tabella Giacenze? Lascia vuoto se non serve:', '');
          if(noteBuono === null) noteBuono = '';
          noteBuono = (noteBuono || '').trim();
          if(noteBuono){
            msg += String.fromCharCode(10,10) + 'Note giacenza: ' + noteBuono;
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
                requested_pezzi:requestedPezzi,
                note_buono:noteBuono
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


    def _apply_add_existing_buono_button(token, ask_partial=False):
        partial_flag = "true" if ask_partial else "false"
        safe_token = _esc(token)
        return (
            "<div class='mt-2 d-flex flex-wrap gap-2'>"
            f"<button type='button' class='btn btn-sm btn-success' "
            f"data-camy-confirm='1' data-camy-token='{safe_token}' data-camy-mode='existing' data-camy-partial='{partial_flag}'>Conferma aggiunta al Buono</button>"
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

    def _extract_logistic_refs(value):
        """Estrae riferimenti logistici da conservare sia sulla riga Buono sia sulla residua.

        Esempi riconosciuti: N. PACKAGE 12, PACKAGE 12, PKG 12, CASSA 3, PALLET A1, CASE 4.
        """
        txt = str(value or "")
        if not txt.strip():
            return []
        patterns = [
            r"\b(?:N\.?\s*)?(?:PACKAGE|PKG|CASSA|PALLET|CASE)\s*[:#\.\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
        ]
        out, seen = [], set()
        for pat in patterns:
            for m in re.finditer(pat, txt, flags=re.I):
                label = re.sub(r"\s+", " ", m.group(0).strip())
                key = _norm_part(label)
                if key and key not in seen:
                    seen.add(key)
                    out.append(label)
        return out

    def _append_refs_if_missing(value, refs):
        """Aggiunge PACKAGE/CASSA/PALLET se non già presenti nel testo."""
        value = str(value or "").strip()
        refs = [str(r or "").strip() for r in (refs or []) if str(r or "").strip()]
        if not refs:
            return value
        current_norm = _norm_part(value)
        missing = [r for r in refs if _norm_part(r) and _norm_part(r) not in current_norm]
        if not missing:
            return value
        extra = " / ".join(missing)
        return f"{value} / {extra}".strip(" /") if value else extra

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


    def _extract_note_buono(msg):
        """Estrae eventuali note scritte direttamente nel messaggio CAMY.
        Esempi:
        - Prepara buono arrivo 123 note materiale urgente
        - Crea buono ID 10 note: ritirare domani
        """
        s = msg or ""
        patterns = [
            r"\b(?:note|nota)\s*[:\-]?\s*(.+?)(?=\s+(?:buono|automatico|manuale|codice|descrizione|pezzi|pezzo|pz|qta|qtà|quantita|quantità)\b|$)",
        ]
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                return (m.group(1) or "").strip(" ;,.-")
        return ""

    def _merge_note(existing, new_note):
        """Aggiunge una nota senza cancellare eventuali note già presenti."""
        existing = str(existing or "").strip()
        new_note = str(new_note or "").strip()
        if not new_note:
            return existing
        if not existing:
            return new_note
        if _norm_part(new_note) in _norm_part(existing):
            return existing
        return existing + "\n" + new_note

    def _is_articolo_uscito(row):
        """True se la riga risulta già uscita e non deve essere inserita in un Buono."""
        try:
            data_uscita = str(getattr(row, "data_uscita", "") or "").strip()
            ddt_uscita = str(getattr(row, "n_ddt_uscita", "") or "").strip()
            return bool(data_uscita or ddt_uscita)
        except Exception:
            return False

    def _uscito_info(row):
        return (
            f"ID {_esc(getattr(row, 'id_articolo', '') or '')} | "
            f"Codice: {_esc(getattr(row, 'codice_articolo', '') or '-')} | "
            f"DDT uscita: {_esc(getattr(row, 'n_ddt_uscita', '') or '-')} | "
            f"Data uscita: {_esc(getattr(row, 'data_uscita', '') or '-')}"
        )


    def _extract_multi_ids(msg):
        """Estrae più ID scritti nello stesso comando CAMY.
        Esempi:
        - Prepara buono ID 256505 256890 257120
        - Prepara buono ids: 256505, 256890, 257120
        """
        s = msg or ""
        out = []
        # Cerca blocchi dopo ID/IDS fino a una parola operativa successiva.
        for m in re.finditer(r"\bIDS?\b\s*[:\-]?\s*([0-9\s,;./\-]+)", s, re.I):
            block = m.group(1) or ""
            for n in re.findall(r"\b\d{2,}\b", block):
                try:
                    val = int(n)
                    if val not in out:
                        out.append(val)
                except Exception:
                    pass
        # Compatibilità con il vecchio comando singolo: "ID 123".
        if not out:
            m = re.search(r"\bID\s*(\d+)\b", s or "", re.I)
            if m:
                out.append(int(m.group(1)))
        return out

    def _extract_multi_values_after_keywords(msg, keywords):
        """Estrae valori multipli dopo parole chiave come codici/arrivi.
        Versione robusta: ordina le parole chiave dalla più lunga alla più corta
        e si ferma prima di campi come CLIENTE, DESCRIZIONE, PEZZI, NOTE.
        """
        s = msg or ""
        # Importante: prima le keyword più lunghe, così "codici articolo" non diventa "codici" + "articolo".
        keywords = sorted([str(k or "").strip() for k in keywords if str(k or "").strip()], key=len, reverse=True)
        kw = "|".join(re.escape(k) for k in keywords)
        stop_words = (
            "con\\s+note|note|nota|buono|automatico|manuale|cliente|fornitore|descrizione|desc|"
            "pezzi|pezzo|pz|qta|qtà|quantita|quantità|ordine|commessa|protocollo|ddt|stato|magazzino|posizione"
        )
        pat = rf"\b(?:{kw})\b\s*[:\-]?\s*(.+?)(?=\s+\b(?:{stop_words})\b|$)"
        m = re.search(pat, s, re.I | re.S)
        if not m:
            return []
        block = (m.group(1) or "").strip()

        # Se il blocco contiene codici uniti da trattino, non spezziamo solo per spazi.
        # Dividiamo su virgola, punto e virgola, a capo; poi ogni elemento può contenere trattini/slash.
        raw = re.split(r"[,;\n\r]+", block)
        if len(raw) == 1:
            raw = re.split(r"\s+", block)

        stop = {"CON", "NOTE", "NOTA", "BUONO", "AUTOMATICO", "MANUALE", "PEZZI", "PEZZO", "PZ", "QTA", "QTÀ", "QUANTITA", "QUANTITÀ", "DESCRIZIONE", "DESC", "CLIENTE", "FORNITORE", "ARTICOLO", "ARTICOLI", "CODICE", "CODICI"}
        out, seen = [], set()
        for x in raw:
            val = x.strip().strip(".,;:")
            if not val:
                continue
            up = val.upper()
            if up in stop:
                continue
            if len(val) < 2:
                continue
            key = _norm_part(val)
            if key and key not in seen:
                seen.add(key)
                out.append(val)
        return out

    def _extract_multi_codici(msg):
        """Estrae più codici articolo da un comando esplicito.
        Esempio: Prepara buono codici ABC123 DEF456 GHI789
        """
        return _extract_multi_values_after_keywords(msg, ["codici", "codice articoli", "codice articolo", "codice"])

    def _extract_multi_arrivi(msg):
        """Estrae più N. arrivo da un comando esplicito.
        Esempio: Prepara buono arrivi 3578 4120 3987
        """
        return _extract_multi_values_after_keywords(msg, ["arrivi", "n arrivi", "n. arrivi", "n arrivo", "n. arrivo", "arrivo"])

    def _build_multi_like_query(q, column, values):
        """Applica un filtro OR per più valori sullo stesso campo."""
        values = [str(v or "").strip() for v in (values or []) if str(v or "").strip()]
        if not values:
            return q
        conds = []
        col_norm = _sql_norm_col(column)
        for v in values:
            n = _norm(v)
            conds.append(column.ilike(f"%{v}%"))
            if n:
                conds.append(col_norm.ilike(f"%{n}%"))
        return q.filter(or_(*conds))

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

        Versione corretta: se nella richiesta sono presenti più codici da prelevare,
        CAMY li mette tutti nella riga del Buono e lascia sulla riga originale solo i codici residui.
        Ritorna (new_row, info_dict) se fa split, altrimenti (None, info_dict).
        """
        original_code_value = getattr(row, "codice_articolo", "") or ""
        original_desc_value = getattr(row, "descrizione", "") or ""
        code_parts = _split_multi_values(original_code_value, allow_dash=True)
        desc_parts = _split_multi_values(original_desc_value, allow_dash=True)
        pezzi_parts = _split_multi_values(getattr(row, "pezzo", ""))
        code_logistic_refs = _extract_logistic_refs(original_code_value)
        desc_logistic_refs = _extract_logistic_refs(original_desc_value)

        requested_code = (requested_code or "").strip()
        requested_descr = (requested_descr or "").strip()
        requested_pezzi = (requested_pezzi or "").strip()

        is_multi = len(code_parts) > 1 or len(desc_parts) > 1 or len(pezzi_parts) > 1

        # Codici richiesti: possono essere uno o più, separati da trattino, slash, virgola, ecc.
        requested_code_parts = _split_multi_values(requested_code, allow_dash=True) if requested_code else []
        # Tolgo eventuali parole generiche finite nel parser.
        requested_code_parts = [p for p in requested_code_parts if _norm_part(p) not in {"CODICE", "CODICI", "ARTICOLO", "ARTICOLI"}]

        selected_indices = []
        for rc in requested_code_parts:
            idx = _find_requested_index(code_parts, rc)
            if idx >= 0 and idx not in selected_indices:
                selected_indices.append(idx)

        # Compatibilità con il vecchio caso singolo.
        if not selected_indices and requested_code:
            idx = _find_requested_index(code_parts, requested_code)
            if idx >= 0:
                selected_indices.append(idx)

        # Se non trovo il codice ma trovo la descrizione, uso la descrizione per individuare la parte.
        desc_selected_indices = []
        if requested_descr:
            d_idx = _find_requested_index(desc_parts, requested_descr)
            if d_idx >= 0:
                desc_selected_indices.append(d_idx)
                if not selected_indices and d_idx < len(code_parts):
                    selected_indices.append(d_idx)

        if not selected_indices or not is_multi:
            return None, {"reason": "no_split", "is_multi": is_multi, "idx": selected_indices[0] if selected_indices else -1}

        selected_indices = sorted(set(selected_indices))

        # Codici in uscita: tutti quelli richiesti.
        selected_code_parts = [code_parts[i] for i in selected_indices if i < len(code_parts)]
        selected_code = _join_multi_values(selected_code_parts) or requested_code

        # Descrizione in uscita: se l'utente l'ha indicata, ha priorità.
        if requested_descr:
            selected_desc = requested_descr
        else:
            selected_desc_parts = [desc_parts[i] for i in selected_indices if i < len(desc_parts)]
            selected_desc = _join_multi_values(selected_desc_parts) or (getattr(row, "descrizione", "") or "")

        # Pezzi in uscita.
        if requested_pezzi:
            selected_pezzi = requested_pezzi
        else:
            selected_pezzi_parts = [pezzi_parts[i] for i in selected_indices if i < len(pezzi_parts)]
            selected_pezzi = _join_multi_values(selected_pezzi_parts)

        original_pezzo_num = _safe_float_or_none(getattr(row, "pezzo", ""))
        selected_pezzo_num = _safe_float_or_none(selected_pezzi)

        # Residuo codici: elimino tutti gli indici usciti.
        resid_code_parts = [p for i, p in enumerate(code_parts) if i not in selected_indices]

        # Residuo descrizioni:
        # - se l'utente ha indicato una descrizione precisa, tolgo quella descrizione;
        # - altrimenti tolgo le descrizioni con gli stessi indici dei codici usciti.
        if desc_parts:
            if desc_selected_indices:
                resid_desc_parts = [p for i, p in enumerate(desc_parts) if i not in set(desc_selected_indices)]
            else:
                resid_desc_parts = [p for i, p in enumerate(desc_parts) if i not in selected_indices]
        else:
            resid_desc_parts = []

        # Residuo pezzi.
        resid_pezzi_parts = [p for i, p in enumerate(pezzi_parts) if i not in selected_indices] if pezzi_parts else []
        if not resid_pezzi_parts and original_pezzo_num is not None and selected_pezzo_num is not None:
            resid = max(0, original_pezzo_num - selected_pezzo_num)
            resid_pezzi_parts = [str(int(resid)) if abs(resid - int(resid)) < 0.0001 else str(round(resid, 3))]

        new_row = _copy_articolo_for_partial(row)
        # PACKAGE / CASSA / PALLET restano sia sulla riga Buono sia sulla residua.
        new_row.codice_articolo = _append_refs_if_missing(selected_code, code_logistic_refs)
        new_row.descrizione = _append_refs_if_missing(selected_desc, desc_logistic_refs)
        new_row.pezzo = selected_pezzi
        new_row.buono_n = buono
        new_row.n_colli = 1

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

        row.codice_articolo = _append_refs_if_missing(_join_multi_values(resid_code_parts), code_logistic_refs)
        if desc_parts:
            row.descrizione = _append_refs_if_missing(_join_multi_values(resid_desc_parts), desc_logistic_refs)
        else:
            row.descrizione = _append_refs_if_missing(getattr(row, "descrizione", ""), desc_logistic_refs)
        if resid_pezzi_parts:
            row.pezzo = _join_multi_values(resid_pezzi_parts)

        row.n_colli = 1
        row.buono_n = ""

        return new_row, {
            "reason": "split",
            "idx": selected_indices,
            "selected_code": selected_code,
            "selected_desc": selected_desc,
            "selected_pezzi": selected_pezzi,
            "residue_codes": row.codice_articolo,
            "residue_desc": row.descrizione,
            "residue_pezzi": row.pezzo,
        }



    def _extract_existing_buono_target(msg):
        """Estrae il N. Buono esistente per comandi tipo:
        - Aggiungi al buono 073-FADEM il codice ABC123
        - Aggiungi righe al buono 45/26 ID 123 456
        """
        s = msg or ""
        patterns = [
            r"\baggiung\w*\s+(?:righe?\s+)?(?:al|nel|a)\s+buono\s+([A-Z0-9][A-Z0-9./\-_]{1,40})",
            r"\bbuono\s+(?:esistente\s+)?([A-Z0-9][A-Z0-9./\-_]{1,40})",
        ]
        stop = {"ID", "IDS", "CODICE", "CODICI", "ARRIVO", "ARRIVI", "CLIENTE", "NOTE", "NOTA"}
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                val = (m.group(1) or "").strip().strip(".,;:")
                if val and val.upper() not in stop:
                    return val
        return ""

    def _message_without_existing_buono_target(msg, buono):
        """Rimuove dal testo il riferimento al buono per non confonderlo con ID/codici/arrivi."""
        s = msg or ""
        if not buono:
            return s
        s = re.sub(r"\baggiung\w*\s+(?:righe?\s+)?(?:al|nel|a)\s+buono\s+" + re.escape(buono), "Aggiungi ", s, flags=re.I)
        s = re.sub(r"\bbuono\s+(?:esistente\s+)?" + re.escape(buono), " ", s, flags=re.I)
        return s

    def _answer_add_to_existing_buono(db, msg):
        if not _can_operate():
            return _operation_denied()

        buono_target = _extract_existing_buono_target(msg)
        if not buono_target:
            return (
                "Per aggiungere righe a un Buono esistente indicami il N. Buono.<br>"
                "Esempi:<br>"
                "• Aggiungi al buono 073-FADEM ID 256505 256506<br>"
                "• Aggiungi al buono 073-FADEM codice CB051CF<br>"
                "• Aggiungi al buono 073-FADEM arrivo 200/26"
            )

        clean_msg = _message_without_existing_buono_target(msg, buono_target)
        filters = _extract_intent(clean_msg)
        filters["only_active"] = True

        multi_ids = _extract_multi_ids(clean_msg)
        multi_codici = _extract_multi_codici(clean_msg)
        multi_arrivi = _extract_multi_arrivi(clean_msg)
        has_key = any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto"))

        if multi_ids:
            q = _base_query(db).filter(Articolo.id_articolo.in_(multi_ids))
            q = _active_filter(q)
        elif len(multi_codici) > 1:
            q = _build_multi_like_query(_base_query(db), Articolo.codice_articolo, multi_codici)
            q = _active_filter(q)
        elif len(multi_arrivi) > 1:
            q = _build_multi_like_query(_base_query(db), Articolo.n_arrivo, multi_arrivi)
            q = _active_filter(q)
        elif has_key:
            q = _apply_filters(_base_query(db), filters)
        else:
            return (
                f"Ho riconosciuto il Buono <b>{_esc(buono_target)}</b>, ma manca il riferimento delle righe da aggiungere.<br>"
                "Puoi indicare ID, codice, arrivo, DDT, seriale o lotto."
            )

        rows_all = q.order_by(Articolo.id_articolo.asc()).limit(50).all()
        rows_uscite = [r for r in rows_all if _is_articolo_uscito(r)]
        rows_non_uscite = [r for r in rows_all if not _is_articolo_uscito(r)]
        rows_gia_buono = [r for r in rows_non_uscite if str(getattr(r, "buono_n", "") or "").strip() == buono_target]
        rows = [r for r in rows_non_uscite if str(getattr(r, "buono_n", "") or "").strip() != buono_target]

        if not rows and (rows_uscite or rows_gia_buono):
            out = ["<b>Nessuna nuova riga da aggiungere.</b>"]
            if rows_gia_buono:
                out.append("<br><b>Righe già presenti nel Buono:</b><br>" + "<br>".join(f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')}" for r in rows_gia_buono[:10]))
            if rows_uscite:
                out.append("<br><b>Righe escluse perché già uscite:</b><br>" + "<br>".join(_uscito_info(r) for r in rows_uscite[:10]))
            return "".join(out)

        if not rows:
            return "Non ho trovato righe attive compatibili da aggiungere al Buono."

        if len(rows) > 30:
            return (
                f"Ho trovato {len(rows)} righe. Per sicurezza non aggiungo più di 30 righe da CAMY AI.<br>"
                "Restringi la ricerca con N. arrivo, codice articolo, DDT o ID."
            )

        requested_code = (filters.get("codice_articolo") or "").strip()
        requested_descr = _extract_requested_descrizione(clean_msg)
        requested_pezzi = _extract_requested_pezzi(clean_msg)
        note_buono = _extract_note_buono(clean_msg)
        needs_partial_details = any(_row_needs_partial_details(r) for r in rows) and not (requested_code or requested_descr)

        token = _make_token()
        ids = [int(r.id_articolo) for r in rows]
        _save_pending_op(token, {
            "type": "set_buono",
            "ids": ids,
            "manual_buono": buono_target,
            "requested_code": requested_code,
            "requested_descr": requested_descr,
            "requested_pezzi": requested_pezzi,
            "note_buono": note_buono,
            "needs_partial_details": bool(needs_partial_details),
        })

        riepilogo = [
            f"<b>Aggiunta a Buono esistente</b><br>",
            f"N. Buono: <b>{_esc(buono_target)}</b><br>",
            f"Righe da aggiungere: <b>{len(ids)}</b><br>",
        ]
        if rows_gia_buono:
            riepilogo.append("<br><b>Già presenti nel Buono e quindi non duplicate:</b><br>" + "<br>".join(f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')}" for r in rows_gia_buono[:8]) + "<br>")
        if rows_uscite:
            riepilogo.append("<br><b>Righe già uscite e quindi escluse:</b><br>" + "<br>".join(_uscito_info(r) for r in rows_uscite[:8]) + "<br>")
        if requested_code or requested_descr or requested_pezzi:
            riepilogo.append(
                "<br><b>Dati scarico parziale letti:</b> "
                f"Codice: <b>{_esc(requested_code or '-')}</b> | "
                f"Descrizione: <b>{_esc(requested_descr or '-')}</b> | "
                f"Pezzi: <b>{_esc(requested_pezzi or '-')}</b><br>"
            )
        elif needs_partial_details:
            riepilogo.append(
                "<br><b>Scarico parziale rilevato:</b> alla conferma CAMY ti chiederà codice, descrizione e pezzi da aggiungere al Buono.<br>"
            )
        if note_buono:
            riepilogo.append(f"<br><b>Nota da salvare in giacenze:</b> {_esc(note_buono)}<br>")

        for r in rows[:8]:
            riepilogo.append(
                f"<div class='camy-ai-result'>"
                f"ID {_esc(r.id_articolo)} | Cliente: {_esc(r.cliente or '-')} | Codice: {_esc(r.codice_articolo or '-')}<br>"
                f"Descrizione: {_esc((r.descrizione or '-')[:120])}<br>"
                f"N. arrivo: {_esc(r.n_arrivo or '-')} | Colli: {_esc(r.n_colli or 0)} | Buono attuale: {_esc(r.buono_n or '-')}"
                f"</div>"
            )
        if len(rows) > 8:
            riepilogo.append(f"<br>Altre righe non mostrate: {len(rows) - 8}.")
        riepilogo.append(_apply_add_existing_buono_button(token, ask_partial=needs_partial_details))
        return "".join(riepilogo)


    def _answer_prepare_buono(db, msg):
        if not _can_operate():
            return _operation_denied()

        filters = _extract_intent(msg)
        filters["only_active"] = True

        # Evito modifiche troppo generiche: serve almeno un riferimento preciso.
        # Ora CAMY supporta anche un Buono unico con più ID, più codici o più arrivi.
        multi_ids = _extract_multi_ids(msg)
        multi_codici = _extract_multi_codici(msg)
        multi_arrivi = _extract_multi_arrivi(msg)

        has_key = any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto"))

        if multi_ids:
            q = _base_query(db).filter(Articolo.id_articolo.in_(multi_ids))
            q = _active_filter(q)
        elif len(multi_codici) > 1:
            q = _build_multi_like_query(_base_query(db), Articolo.codice_articolo, multi_codici)
            q = _active_filter(q)
        elif len(multi_arrivi) > 1:
            q = _build_multi_like_query(_base_query(db), Articolo.n_arrivo, multi_arrivi)
            q = _active_filter(q)
        elif has_key:
            q = _apply_filters(_base_query(db), filters)
        else:
            return (
                "Per preparare un Buono di Prelievo mi serve un riferimento preciso.<br>"
                "Esempi:<br>"
                "• Prepara buono arrivo 3578 buono 45/26<br>"
                "• Prepara buono arrivi 3578 4120 3987<br>"
                "• Prepara buono codici ABC123 DEF456 GHI789<br>"
                "• Prepara buono ID 256498 256499 256500"
            )

        rows_all = q.order_by(Articolo.id_articolo.asc()).limit(50).all()
        rows_uscite = [r for r in rows_all if _is_articolo_uscito(r)]
        rows = [r for r in rows_all if not _is_articolo_uscito(r)]

        if not rows and rows_uscite:
            dettagli = "<br>".join(_uscito_info(r) for r in rows_uscite[:10])
            return (
                "<b>Operazione annullata.</b><br>"
                "Le righe trovate risultano già uscite, quindi CAMY non può inserirle nel Buono di Prelievo.<br>"
                + dettagli
            )

        if not rows:
            return "Non ho trovato righe attive compatibili per preparare il buono."

        total = len(rows)
        if total > 30:
            return (
                f"Ho trovato {total} righe. Per sicurezza non preparo un buono con più di 30 righe da CAMY AI.<br>"
                "Restringi la ricerca con N. arrivo, codice articolo, DDT o ID."
            )

        prossimo_auto = _peek_next_buono_number(db)
        manual_buono = _extract_manual_buono_number(msg)
        requested_code = (filters.get("codice_articolo") or "").strip()
        requested_descr = _extract_requested_descrizione(msg)
        requested_pezzi = _extract_requested_pezzi(msg)
        note_buono = _extract_note_buono(msg)
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
            "note_buono": note_buono,
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

        dettagli_usciti = ""
        if rows_uscite:
            dettagli_usciti = (
                "<br><b>Attenzione:</b> alcune righe sono già uscite e verranno escluse dal Buono:<br>"
                + "<br>".join(_uscito_info(r) for r in rows_uscite[:8])
                + "<br>"
            )

        dettagli_note = ""
        if note_buono:
            dettagli_note = f"<br><b>Nota da salvare in giacenze:</b> {_esc(note_buono)}<br>"

        dettagli_multi = ""
        if multi_ids or len(multi_codici) > 1 or len(multi_arrivi) > 1:
            parti = []
            if multi_ids:
                parti.append("ID: " + ", ".join(_esc(x) for x in multi_ids))
            if len(multi_codici) > 1:
                parti.append("Codici: " + ", ".join(_esc(x) for x in multi_codici))
            if len(multi_arrivi) > 1:
                parti.append("Arrivi: " + ", ".join(_esc(x) for x in multi_arrivi))
            dettagli_multi = "<br><b>Buono multiplo:</b> " + " | ".join(parti) + "<br>"

        riepilogo = [
            f"<b>Proposta Buono di Prelievo</b><br>",
            f"Righe selezionate: <b>{len(ids)}</b><br>",
            f"Vuoi inserire il N. Buono <b>automaticamente</b> o <b>manualmente</b>?<br>",
            f"Prossimo numero automatico previsto: <b>{_esc(prossimo_auto)}</b>{scelta_manual}{dettagli_multi}{dettagli_parziale}{dettagli_note}{dettagli_usciti}<br>",
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
        """Genera il PDF del Buono di Prelievo CAMY usando lo stesso layout standard del gestionale."""
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

        filename = f"Buono_{_safe_pdf_filename(buono)}.pdf"
        pdf_path = base_dir / filename

        try:
            from pathlib import Path as _Path
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from reportlab.lib.enums import TA_CENTER
        except Exception:
            return "", None

        def _h(value):
            return html.escape(str(value or ""))

        def _qta(row):
            val = getattr(row, "pezzo", None)
            if val is None or str(val).strip() == "":
                val = getattr(row, "n_colli", "")
            s = str(val or "").strip()
            if not s:
                return ""
            try:
                f = float(s.replace(".", "").replace(",", ".") if "," in s else s)
                if abs(f - int(f)) < 0.000001:
                    return str(int(f))
                return str(round(f, 3)).replace(".", ",")
            except Exception:
                return s

        def _first_attr(attr):
            for r in rows:
                v = getattr(r, attr, "")
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""

        styles = getSampleStyleSheet()
        s_norm = ParagraphStyle("camy_buono_norm", parent=styles["Normal"], fontSize=9, leading=11, textColor=colors.black)
        s_bold = ParagraphStyle("camy_buono_bold", parent=s_norm, fontName="Helvetica-Bold")
        s_title = ParagraphStyle("camy_buono_title", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=16, leading=18, spaceAfter=10, textColor=colors.black)
        s_note = ParagraphStyle("camy_buono_note", parent=s_norm, fontSize=9, textColor=colors.darkblue)

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=10 * mm,
            rightMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
        )
        story = []

        # Logo uguale al gestionale standard.
        try:
            if "LOGO_PATH" in globals() and LOGO_PATH and _Path(LOGO_PATH).exists():
                story.append(Image(str(LOGO_PATH), width=50 * mm, height=16 * mm, hAlign="CENTER"))
            else:
                story.append(Paragraph("<b>Ca.mar. srl</b>", s_title))
        except Exception:
            story.append(Paragraph("<b>Ca.mar. srl</b>", s_title))

        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("BUONO DI PRELIEVO", s_title))
        story.append(Spacer(1, 5 * mm))

        cliente = _first_attr("cliente")
        fornitore = _first_attr("fornitore")
        commessa = _first_attr("commessa")
        ordine = _first_attr("ordine")
        protocolli = []
        seen_prot = set()
        for r in rows:
            p = str(getattr(r, "protocollo", "") or "").strip()
            if p and p not in seen_prot:
                seen_prot.add(p)
                protocolli.append(p)
        protocollo = ", ".join(protocolli)

        meta_data = [
            [Paragraph("<b>Data Emissione:</b>", s_bold), Paragraph(datetime.today().strftime("%d/%m/%Y"), s_norm)],
            [Paragraph("<b>Cliente:</b>", s_bold), Paragraph(_h(cliente), s_norm)],
            [Paragraph("<b>Fornitore:</b>", s_bold), Paragraph(_h(fornitore), s_norm)],
            [Paragraph("<b>Commessa:</b>", s_bold), Paragraph(_h(commessa), s_norm)],
            [Paragraph("<b>Ordine:</b>", s_bold), Paragraph(_h(ordine), s_norm)],
            [Paragraph("<b>Protocollo:</b>", s_bold), Paragraph(_h(protocollo), s_norm)],
            [Paragraph("<b>N. Buono:</b>", s_bold), Paragraph(_h(buono), s_norm)],
        ]

        t_meta = Table(meta_data, colWidths=[40 * mm, 140 * mm])
        t_meta.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t_meta)
        story.append(Spacer(1, 8 * mm))

        table_data = [[
            Paragraph("<b>Codice</b>", s_bold),
            Paragraph("<b>Descrizione</b>", s_bold),
            Paragraph("<b>Q.tà</b>", s_bold),
            Paragraph("<b>N.Arr</b>", s_bold),
        ]]

        for r in rows:
            table_data.append([
                Paragraph(_h(getattr(r, "codice_articolo", "")), s_norm),
                Paragraph(_h(getattr(r, "descrizione", "")), s_norm),
                Paragraph(_h(_qta(r)), s_norm),
                Paragraph(_h(getattr(r, "n_arrivo", "")), s_norm),
            ])
            note_user = str(getattr(r, "note", "") or "").strip()
            if note_user:
                table_data.append(["", Paragraph(f"<i>Note: {_h(note_user)}</i>", s_note), "", ""])

        t = Table(table_data, colWidths=[40 * mm, 100 * mm, 15 * mm, 25 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

        story.append(Spacer(1, 20 * mm))
        sig_data = [[
            Paragraph("Firma Magazzino:<br/><br/>__________________", s_norm),
            Paragraph("Firma Cliente:<br/><br/>__________________", s_norm),
        ]]
        story.append(Table(sig_data, colWidths=[90 * mm, 90 * mm]))

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
                elif mode == "existing":
                    buono = manual_from_message or manual_from_request
                    if not buono:
                        return jsonify({"answer": "Numero buono esistente mancante.", "html": False}), 400
                else:
                    buono = _next_buono_number(db)

                if not ids or not buono:
                    return jsonify({"answer": "Dati operazione incompleti.", "html": False}), 400

                q = _base_query(db).filter(Articolo.id_articolo.in_(ids))
                rows_all = q.all()
                if not rows_all:
                    return jsonify({"answer": "Nessuna riga trovata da aggiornare.", "html": False}), 404

                rows_uscite = [r for r in rows_all if _is_articolo_uscito(r)]
                rows = [r for r in rows_all if not _is_articolo_uscito(r)]

                if not rows and rows_uscite:
                    return jsonify({
                        "answer": (
                            "<b>Operazione annullata.</b><br>"
                            "Tutte le righe selezionate risultano già uscite e non sono state inserite nel Buono.<br>"
                            + "<br>".join(_uscito_info(r) for r in rows_uscite[:10])
                        ),
                        "html": True
                    }), 400

                requested_code = (data.get("requested_code") or op.get("requested_code") or "").strip()
                requested_descr = (data.get("requested_descr") or op.get("requested_descr") or "").strip()
                requested_pezzi = (data.get("requested_pezzi") or op.get("requested_pezzi") or "").strip()
                note_buono = (data.get("note_buono") or op.get("note_buono") or "").strip()

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
                        if note_buono:
                            new_row.note = _merge_note(getattr(new_row, "note", ""), note_buono)
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
                        if note_buono:
                            r.note = _merge_note(getattr(r, "note", ""), note_buono)
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
                if rows_uscite:
                    extra += (
                        "<br><b>Righe escluse perché già uscite:</b><br>"
                        + "<br>".join(_uscito_info(r) for r in rows_uscite[:10])
                    )
                if note_buono:
                    extra += f"<br>Note salvate in giacenze: <b>{_esc(note_buono)}</b><br>"
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
                    extra += (
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

        if "aggiungi" in low and "buono" in low:
            return _answer_add_to_existing_buono(db, msg), True, {}

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
            initial_input_value=("" if q else prefill),
            can_operate=_can_operate()
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
