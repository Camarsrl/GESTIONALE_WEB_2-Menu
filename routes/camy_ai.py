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
    from sqlalchemy import or_, func, text

    try:
        from routes.camy_brain import decide_camy_intent, camy_brain_help, camy_smalltalk_answer
    except Exception:
        def decide_camy_intent(message):
            return {"action": "fallback", "target": "", "confidence": 0.0, "raw": message or ""}
        def camy_brain_help():
            return "Posso aiutarti con giacenze, buoni, DDT, picking, trasporti, entrate e report."
        def camy_smalltalk_answer(message):
            return "Ciao Alessia 😊 Sono pronta ad aiutarti con il gestionale."

    try:
        from routes.camy_reports import camy_daily_briefing
    except Exception:
        def camy_daily_briefing(db, deps, msg=""):
            return "Modulo report CAMY non disponibile."

    try:
        from routes.camy_procedure import is_procedure_request, render_procedure, render_procedure_index
    except Exception:
        def is_procedure_request(message):
            return False
        def render_procedure(message_or_key):
            return "Modulo procedure CAMY non disponibile."
        def render_procedure_index():
            return "Modulo procedure CAMY non disponibile."

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
      .camy-voice-btn.listening { animation: camyPulse 1s infinite; }
      @keyframes camyPulse { 0%{opacity:1;} 50%{opacity:.45;} 100%{opacity:1;} }
      .camy-speak-wrap { font-size:13px; color:#666; margin-top:6px; }
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
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Prepara%20buono%20del%20marca%20pezzo%20">Prepara Buono</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Scarico%20parziale%20ID%20">Scarico parziale</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Aggiungi%20al%20buono%20">Aggiungi a Buono</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Crea%20DDT%20arrivo%20">Crea DDT</a>
            <a class="btn btn-sm btn-outline-warning" href="/camy-ai?prefill=Confronta%20inventario%20cliente%20">Confronta Inventario</a>
            <a class="btn btn-sm btn-outline-success" href="/camy-ai?prefill=Crea%20report%20Excel%20giacenze%20cliente%20">Report Excel</a>
            <a class="btn btn-sm btn-outline-success" href="/accettazione_entrata">📄 Entrata da documento</a>
            <a class="btn btn-sm btn-outline-success" href="/camy-email-buono">📧 Buono da email</a>
            <a class="btn btn-sm btn-outline-success" href="/camy-ai?prefill=Genera%20registro%20giornaliero%20di%20oggi">📒 Registro oggi</a>
            <a class="btn btn-sm btn-outline-info" href="/camy-ai?prefill=Come%20siamo%20messi%20oggi%3F">📋 Situazione operativa</a>
            <a class="btn btn-sm btn-outline-info" href="/camy-ai?prefill=Cosa%20manca%20da%20fare%20oggi%3F">✅ Cosa manca?</a>
            <a class="btn btn-sm btn-outline-dark" href="/camy-ai?prefill=Apri%20accettazione%20entrata">🎤 Apri entrata</a>
            <button type="button" class="btn btn-sm btn-outline-dark" data-camy-fill="Cerca arrivo ">🎤 Cerca arrivo</button>
            <button type="button" class="btn btn-sm btn-outline-dark" data-camy-fill="Prepara buono del marca pezzo ">🎤 Prepara buono</button>
            <button type="button" class="btn btn-sm btn-outline-dark" data-camy-fill="Crea DDT dal buono ">🎤 Crea DDT</button>
            <button type="button" class="btn btn-sm btn-outline-dark" data-camy-fill="Fammi vedere la foto dell'arrivo ">🎤 Mostra foto</button>
            {% endif %}
            <a class="btn btn-sm btn-outline-success" href="/scan_qr_operativo">🔫 Scan QR</a>
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
            <input id="camyAiInput" name="q" type="text" class="form-control" placeholder="Scrivi o detta una domanda a CAMY AI..." value="{{ initial_input_value or '' }}">
            <button id="camyVoiceBtn" type="button" class="btn btn-outline-danger camy-voice-btn" title="Detta a CAMY" data-camy-voice="1">🎤</button>
            <button id="camyVoiceStopBtn" type="button" class="btn btn-outline-secondary" title="Ferma/Pausa vocale" data-camy-stopvoice="1">⏸ Pausa</button>
            <button type="submit" class="btn btn-primary" data-camy-send="1">Invia</button>
          </form>
          <div class="camy-speak-wrap">
            <label><input type="checkbox" id="camySpeakAnswer"> Leggi risposta ad alta voce</label>
            <span id="camyVoiceStatus" class="ms-2"></span>
          </div>
        </div>
      </div>
    </div>

    <script>
      (function(){
        function getBox(){ return document.getElementById('camyAiBox'); }
        function getInput(){ return document.getElementById('camyAiInput'); }
        function getVoiceBtn(){ return document.getElementById('camyVoiceBtn'); }
        function getVoiceStopBtn(){ return document.getElementById('camyVoiceStopBtn'); }
        function getVoiceStatus(){ return document.getElementById('camyVoiceStatus'); }
        function setVoiceStatus(txt){ var s=getVoiceStatus(); if(s) s.textContent = txt || ''; }
        window.camyAiRecognition = null;

        window.camyAiSpeak = function(text){
          try{
            var cb = document.getElementById('camySpeakAnswer');
            if(!cb || !cb.checked || !('speechSynthesis' in window)) return;
            var clean = (text || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
            if(!clean) return;
            window.speechSynthesis.cancel();
            var utter = new SpeechSynthesisUtterance(clean);
            utter.lang = 'it-IT';
            utter.rate = 1;
            window.speechSynthesis.speak(utter);
          }catch(e){}
        };

        window.camyAiStopVoice = function(){
          var btn = getVoiceBtn();
          try{
            if(window.camyAiRecognition){
              window.camyAiRecognition.onend = null;
              window.camyAiRecognition.stop();
              window.camyAiRecognition = null;
            }
          }catch(e){}
          try{
            if('speechSynthesis' in window){ window.speechSynthesis.cancel(); }
          }catch(e){}
          if(btn) btn.classList.remove('listening');
          setVoiceStatus('Vocale in pausa.');
        };

        window.camyAiStartVoice = function(){
          var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
          var input = getInput();
          var btn = getVoiceBtn();
          if(!SpeechRecognition){
            setVoiceStatus('Microfono non supportato da questo browser. Usa Chrome o Edge.');
            return;
          }
          try{
            window.camyAiStopVoice();
            var rec = new SpeechRecognition();
            window.camyAiRecognition = rec;
            rec.lang = 'it-IT';
            rec.interimResults = false;
            rec.maxAlternatives = 1;
            if(btn) btn.classList.add('listening');
            setVoiceStatus('Sto ascoltando... premi Pausa per fermare.');
            rec.onresult = function(event){
              var spoken = event.results && event.results[0] && event.results[0][0] ? event.results[0][0].transcript : '';
              if(input && spoken){
                input.value = spoken;
                input.focus();
              }
              setVoiceStatus('Testo inserito. Premi Invia oppure modifica la frase.');
            };
            rec.onerror = function(){ setVoiceStatus('Non sono riuscita a sentire bene. Riprova.'); };
            rec.onend = function(){
              if(btn) btn.classList.remove('listening');
              window.camyAiRecognition = null;
            };
            rec.start();
          }catch(e){
            if(btn) btn.classList.remove('listening');
            window.camyAiRecognition = null;
            setVoiceStatus('Microfono non avviato. Controlla i permessi del browser.');
          }
        };

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
            window.camyAiSpeak(data.answer || 'Non ho trovato una risposta.');
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

          noteBuono = prompt('Vuoi inserire una nota da salvare solo sulla riga del Buono? Lascia vuoto se non serve:', '');
          if(noteBuono === null) noteBuono = '';
          noteBuono = (noteBuono || '').trim();
          if(noteBuono){
            msg += String.fromCharCode(10,10) + 'Note del Buono: ' + noteBuono;
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
          var target = ev.target && ev.target.closest ? ev.target.closest('[data-camy-fill],[data-camy-send],[data-camy-confirm],[data-camy-voice],[data-camy-stopvoice]') : null;
          if(!target) return;
          ev.preventDefault();
          ev.stopPropagation();

          if(target.hasAttribute('data-camy-stopvoice')){
            window.camyAiStopVoice();
            return;
          }

          if(target.hasAttribute('data-camy-voice')){
            window.camyAiStartVoice();
            return;
          }

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
        m = re.search(r"\bcodice(?:\s+articolo)?\s+([A-Z0-9.*#/\\\-_]+)", msg or "", re.I)
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
            "• Fammi vedere la foto dell'arrivo 778/26 collo 1.<br>"
            "• Dove si trova il codice ABC123?<br>"
            "• Totale colli, peso, M2 e M3 di De Wave.<br>"
            "• Prepara buono arrivo 542/26: controllo uscito, Buono già presente e pezzi disponibili.<br>"
            "• Scarico parziale ID 12345.<br>"
            "• Crea DDT dal buono 025/26.<br>"
            "• Genera registro giornaliero di oggi.<br>"
            "• Cosa manca da fare oggi?<br>• Cosa devo spedire oggi?<br>• RF-DE WAVE senza foto<br>• Fincantieri / Armatore / Scoperto senza protocollo<br>• Fincantieri / Armatore / Scoperto senza mezzo<br>• Crea buono da email/PDF/foto<br>"
            "• Crea report Excel giacenze Fincantieri.<br>"
            "• Confronta inventario Galvano Tecnica.<br>"
            "• Come faccio un'entrata?<br>"
            "• Come preparo un buono?<br>"
            "• Come creo un DDT?<br>"
            "• Come mando email al cliente?<br><br>"
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
        return "-".join(parts)

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
        extra = "-".join(missing)
        return f"{value}-{extra}".strip("-") if value else extra

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

    def _extract_buono_line_items(msg):
        """Estrae marca-pezzi e quantità da una richiesta di Buono.

        Formati supportati:
        - CB051CF 4 pezzi
        - CB051CF pezzi 4
        - marca pezzo CB051CF pezzi 4
        - codice articolo CB051CF quantità 4
        - CB051CF: 4

        Le parole PEZZI, CLIENTE, PACKAGE, COMMESSA, ORDINE, NOTE ecc.
        non vengono mai interpretate come codici articolo.
        """
        text_msg = str(msg or "")
        items = []
        seen = set()

        stop_codes = {
            "BUONO", "COMMESSA", "ORDINE", "CLIENTE", "CLIENTI",
            "NOTE", "NOTA", "DDT", "ARRIVO", "ARRIVI",
            "PEZZI", "PEZZO", "PZ", "QTA", "QTÀ", "QUANTITA", "QUANTITÀ",
            "PACKAGE", "PKG", "PALLET", "CASSA", "CASE",
            "CODICE", "CODICI", "ARTICOLO", "ARTICOLI",
            "MARCA", "MARCAPEZZO", "MARCAPEZZI",
            "FORNITORE", "DESCRIZIONE", "DESC", "PROTOCOLLO",
            "MAGAZZINO", "POSIZIONE", "AUTOMATICO", "MANUALE",
            "CREA", "CREARE", "PREPARA", "PREPARARE", "DEL", "DELLA", "CON"
        }

        code_re = r"([A-Z0-9][A-Z0-9./_*\\-]{1,60})"
        qty_re = r"([0-9]+(?:[,.][0-9]+)?)"

        patterns = [
            rf"(?:marca\s*[- ]?pezzi?|codice(?:\s+articolo)?)\s*[:\-]?\s*{code_re}\s*(?:pezzi?|pz|qta|qtà|quantita|quantità)\s*[:=\-]?\s*{qty_re}",
            rf"\b{code_re}\b\s*(?:pezzi?|pz|qta|qtà|quantita|quantità)\s*[:=\-]?\s*{qty_re}",
            rf"\b{code_re}\b\s*[:=\-]?\s*{qty_re}\s*(?:pezzi?|pz)\b",
            rf"\b{code_re}\b\s*(?:q(?:uan)?t(?:it[aà])?)\s*[:=\-]?\s*{qty_re}",
            rf"\b{code_re}\b\s*[:=]\s*{qty_re}\b",
        ]

        chunks = re.split(r"[\n\r;]+", text_msg) or [text_msg]
        for chunk in chunks:
            line = str(chunk or "").strip()
            if not line:
                continue

            for pat in patterns:
                for m in re.finditer(pat, line, re.I):
                    code = (m.group(1) or "").strip().strip(".,;:")
                    qty = (m.group(2) or "").strip().replace(",", ".")
                    upper_code = re.sub(r"[^A-ZÀ-Ù0-9]+", "", code.upper())

                    if not re.search(r"[A-Z]", code, re.I) or not re.search(r"\d", code):
                        continue
                    if upper_code in stop_codes:
                        continue
                    if re.match(r"^(?:PACKAGE|PKG|PALLET|CASSA|CASE)(?:N|NO)?\d*$", upper_code):
                        continue

                    key = _norm_part(code)
                    if not key or key in seen:
                        continue

                    seen.add(key)
                    items.append({"codice": code, "pezzi": qty})

        return items

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
        # Stop anche se la parola successiva arriva dopo virgola/punto e virgola
        # Esempio: "codice SW*009VX, descrizione VALVE" deve restituire solo SW*009VX.
        pat = rf"\b(?:{kw})\b\s*[:\-]?\s*(.+?)(?=[\s,;]+(?:{stop_words})\b|$)"
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


    def _clean_piece_value(value):
        """Formatta quantità intere senza .0; mantiene gli eventuali decimali reali."""
        try:
            num = float(str(value or "0").strip().replace(",", "."))
            if abs(num - round(num)) < 0.000001:
                return str(int(round(num)))
            return str(round(num, 3)).rstrip("0").rstrip(".")
        except Exception:
            return str(value or "").strip()

    def _piece_value_for_db(value):
        """Restituisce un intero per 2, 8, 10 e un decimale solo quando reale."""
        try:
            num = float(str(value or "0").strip().replace(",", "."))
            if abs(num - round(num)) < 0.000001:
                return int(round(num))
            return float(_clean_piece_value(num))
        except Exception:
            return _clean_piece_value(value)

    def _parse_logistic_code(value):
        """Separa PACKAGE/PALLET/CASSA dai marca-pezzi senza duplicare il testo originale."""
        raw = re.sub(r"\s+", " ", str(value or "").strip())
        if not raw:
            return "", []

        # Riferimento logistico limitato al solo nome + identificativo.
        # Non cattura i marca-pezzi che seguono dopo il trattino.
        m = re.search(
            r"\b((?:PACKAGE|PKG|PALLET|CASSA|CASE)\s*"
            r"(?:(?:NO|N)\.?\s*)?[:#.]?\s*[A-Z0-9]+)\b",
            raw,
            flags=re.I,
        )
        logistic = re.sub(r"\s+", " ", m.group(1).strip()) if m else ""

        rest = raw
        if m:
            rest = (raw[:m.start()] + " " + raw[m.end():]).strip()

        # I codici articolo vengono separati con il trattino.
        rest = re.sub(r"^[\s\-/:;,|+]+|[\s\-/:;,|+]+$", "", rest)
        candidates = re.split(r"\s*(?:;|\||\+|,|\s/\s|\s*-\s*)\s*", rest)

        codes = []
        seen = set()
        for item in candidates:
            item = str(item or "").strip(" -/;,|+")
            if not item:
                continue
            # Evita di reinserire un secondo riferimento logistico.
            if re.match(r"^(?:PACKAGE|PKG|PALLET|CASSA|CASE)\b", item, re.I):
                continue
            key = _norm_part(item)
            if key and key not in seen:
                seen.add(key)
                codes.append(item)

        return logistic, codes

    def _build_logistic_code(logistic, codes):
        """Ricostruisce sempre: PACKAGE N.11-CODICE1-CODICE2."""
        parts = []
        if str(logistic or "").strip():
            parts.append(str(logistic).strip())
        seen = {_norm_part(parts[0])} if parts else set()
        for code in codes or []:
            code = str(code or "").strip(" -/")
            key = _norm_part(code)
            if not code or not key or key in seen:
                continue
            seen.add(key)
            parts.append(code)
        return "-".join(parts)

    def _prepare_partial_split_for_buono(
        row,
        buono,
        requested_code="",
        requested_descr="",
        requested_pezzi="",
        original_qty_override=None,
    ):
        """Crea la riga del Buono e lascia sulla riga originale solo il residuo.

        Regole:
        - PACKAGE/PALLET/CASSA compare una sola volta e sempre all'inizio;
        - i marca-pezzi sono separati esclusivamente con "-";
        - le quantità intere vengono salvate come 4 e non 4.0;
        - la riga residua non riceve le note del Buono.
        """
        original_code = str(getattr(row, "codice_articolo", "") or "").strip()
        original_desc = str(getattr(row, "descrizione", "") or "").strip()
        requested_code = str(requested_code or "").strip()
        requested_descr = str(requested_descr or "").strip()
        requested_pezzi = str(requested_pezzi or "").strip()

        logistic, original_codes = _parse_logistic_code(original_code)
        req_logistic, requested_codes = _parse_logistic_code(requested_code)

        # Se l'utente ha scritto soltanto il marca-pezzo, usa quello.
        if not requested_codes and requested_code and not req_logistic:
            requested_codes = [requested_code]

        # Il riferimento logistico deve provenire dalla riga originale.
        logistic = logistic or req_logistic

        original_qty = _safe_float_or_none(original_qty_override)
        if original_qty is None:
            original_qty = _safe_float_or_none(getattr(row, "pezzo", ""))
        selected_qty = _safe_float_or_none(requested_pezzi)

        # Se manca una quantità esplicita, usa tutta la disponibilità.
        if selected_qty is None:
            selected_qty = original_qty

        if original_qty is None or selected_qty is None or selected_qty <= 0:
            return None, {"reason": "invalid_quantity", "is_multi": len(original_codes) > 1}

        if selected_qty > original_qty:
            return None, {"reason": "quantity_exceeds", "is_multi": len(original_codes) > 1}

        original_norm_map = {_norm_part(c): c for c in original_codes if _norm_part(c)}
        selected_exact = []
        missing = []

        for code in requested_codes:
            key = _norm_part(code)
            if not key:
                continue
            if key in original_norm_map:
                selected_exact.append(original_norm_map[key])
            else:
                missing.append(code)

        # Con una riga semplice senza package il codice originale è il marca-pezzo.
        if not original_codes and original_code:
            original_codes = [original_code]
            original_norm_map = {_norm_part(original_code): original_code}
            if requested_codes:
                selected_exact = [
                    original_code for c in requested_codes
                    if _norm_part(c) == _norm_part(original_code)
                ]
            elif requested_code:
                selected_exact = [original_code]

        if missing:
            return None, {
                "reason": "requested_code_not_found",
                "is_multi": len(original_codes) > 1,
                "missing": missing,
            }

        if not selected_exact:
            # Se il codice non è stato specificato ma la riga ha un solo marca-pezzo,
            # considera selezionato quel codice.
            if len(original_codes) == 1:
                selected_exact = [original_codes[0]]
            else:
                return None, {"reason": "no_code_selected", "is_multi": len(original_codes) > 1}

        selected_norms = {_norm_part(c) for c in selected_exact}
        residual_codes = [c for c in original_codes if _norm_part(c) not in selected_norms]

        full_quantity = abs(selected_qty - original_qty) < 0.000001
        all_codes_selected = not residual_codes

        # Se esce tutta la quantità e tutti i codici, non serve creare una seconda riga.
        if full_quantity and all_codes_selected:
            row.codice_articolo = _build_logistic_code(logistic, selected_exact)
            row.pezzo = _piece_value_for_db(selected_qty)
            row.buono_n = buono
            row.n_colli = 1
            return None, {
                "reason": "full_selection",
                "is_multi": False,
                "selected_code": row.codice_articolo,
                "selected_pezzi": _clean_piece_value(selected_qty),
            }

        new_row = _copy_articolo_for_partial(row)
        new_row.codice_articolo = _build_logistic_code(logistic, selected_exact)
        new_row.descrizione = requested_descr or original_desc
        new_row.pezzo = _piece_value_for_db(selected_qty)
        new_row.buono_n = buono
        new_row.n_colli = 1

        residual_qty = max(0.0, original_qty - selected_qty)
        row.codice_articolo = _build_logistic_code(logistic, residual_codes)
        row.pezzo = _piece_value_for_db(residual_qty)
        row.buono_n = ""
        row.n_colli = 1

        # Ripartizione proporzionale di peso, M2 e M3.
        for field in ("peso", "m2", "m3"):
            try:
                original_value = float(getattr(row, field, 0) or 0)
                selected_value = original_value * (selected_qty / original_qty) if original_qty else 0
                setattr(new_row, field, round(selected_value, 6))
                setattr(row, field, round(max(0, original_value - selected_value), 6))
            except Exception:
                pass

        return new_row, {
            "reason": "split",
            "is_multi": len(original_codes) > 1,
            "selected_code": new_row.codice_articolo,
            "selected_desc": new_row.descrizione,
            "selected_pezzi": _clean_piece_value(selected_qty),
            "residue_codes": row.codice_articolo,
            "residue_desc": row.descrizione,
            "residue_pezzi": _clean_piece_value(residual_qty),
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

        # Regola di sicurezza importante:
        # se nel comando è presente un N. arrivo, CAMY deve restare BLOCCATA su quell'arrivo.
        # Esempio: "Prepara buono arrivo 140/25 codice SW*009VX" deve cercare:
        #     arrivo 140/25 AND codice SW*009VX
        # e non prendere lo stesso codice da altri arrivi.
        arrivo_presente = bool((filters.get("n_arrivo") or "").strip()) or bool(multi_arrivi)

        if multi_ids:
            q = _base_query(db).filter(Articolo.id_articolo.in_(multi_ids))
            q = _active_filter(q)
        elif arrivo_presente and (multi_codici or (filters.get("codice_articolo") or "").strip()):
            q = _base_query(db)
            if len(multi_arrivi) > 1:
                q = _build_multi_like_query(q, Articolo.n_arrivo, multi_arrivi)
            elif (filters.get("n_arrivo") or "").strip():
                q = _apply_norm_equals_or_like(q, Articolo.n_arrivo, filters.get("n_arrivo"))
            codici_da_filtrare = multi_codici if multi_codici else [filters.get("codice_articolo")]
            q = _build_multi_like_query(q, Articolo.codice_articolo, codici_da_filtrare)
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


    def _available_pezzi_for_request(row, requested_code=""):
        """Restituisce i pezzi disponibili sulla riga, se verificabili.
        Se la riga contiene più codici e il codice richiesto identifica una parte,
        usa i pezzi della stessa posizione; altrimenti usa il totale numerico della riga.
        """
        try:
            code_parts = _split_multi_values(getattr(row, "codice_articolo", ""), allow_dash=True)
            pezzi_parts = _split_multi_values(getattr(row, "pezzo", ""))
            requested_code = str(requested_code or "").strip()
            if requested_code and code_parts and pezzi_parts and len(pezzi_parts) == len(code_parts):
                idx = _find_requested_index(code_parts, requested_code)
                if idx >= 0 and idx < len(pezzi_parts):
                    return _safe_float_or_none(pezzi_parts[idx])
            val = _safe_float_or_none(getattr(row, "pezzo", ""))
            if val is not None:
                return val
            nums = [_safe_float_or_none(x) for x in pezzi_parts]
            nums = [x for x in nums if x is not None]
            if nums:
                return sum(nums)
        except Exception:
            pass
        return None

    def _validate_pezzi_richiesti(rows, requested_pezzi, requested_code=""):
        """Controlla che i pezzi richiesti non superino quelli disponibili."""
        req = _safe_float_or_none(requested_pezzi)
        if req is None:
            return []
        problemi = []
        for r in rows or []:
            disp = _available_pezzi_for_request(r, requested_code=requested_code)
            if disp is not None and req > disp:
                problemi.append((r, disp, req))
        return problemi


    def _answer_prepare_buono(db, msg):
        if not _can_operate():
            return _operation_denied()

        filters = _extract_intent(msg)
        filters["only_active"] = True

        # Evito modifiche troppo generiche: serve almeno un riferimento preciso.
        # Ora CAMY supporta anche un Buono unico con più ID, più codici o più arrivi.
        multi_ids = _extract_multi_ids(msg)
        line_items = _extract_buono_line_items(msg)
        multi_codici = [x.get("codice", "") for x in line_items] or _extract_multi_codici(msg)
        multi_arrivi = _extract_multi_arrivi(msg)

        has_key = any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto"))

        # Regola di sicurezza importante:
        # se nel comando è presente un N. arrivo, CAMY deve restare BLOCCATA su quell'arrivo.
        # Esempio: "Prepara buono arrivo 140/25 codice SW*009VX" deve cercare:
        #     arrivo 140/25 AND codice SW*009VX
        # e non prendere lo stesso codice da altri arrivi.
        arrivo_presente = bool((filters.get("n_arrivo") or "").strip()) or bool(multi_arrivi)

        if multi_ids:
            q = _base_query(db).filter(Articolo.id_articolo.in_(multi_ids))
            q = _active_filter(q)
        elif arrivo_presente and (multi_codici or (filters.get("codice_articolo") or "").strip()):
            q = _base_query(db)
            if len(multi_arrivi) > 1:
                q = _build_multi_like_query(q, Articolo.n_arrivo, multi_arrivi)
            elif (filters.get("n_arrivo") or "").strip():
                q = _apply_norm_equals_or_like(q, Articolo.n_arrivo, filters.get("n_arrivo"))
            codici_da_filtrare = multi_codici if multi_codici else [filters.get("codice_articolo")]
            q = _build_multi_like_query(q, Articolo.codice_articolo, codici_da_filtrare)
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
        rows_non_uscite = [r for r in rows_all if not _is_articolo_uscito(r)]
        rows_con_buono = [r for r in rows_non_uscite if str(getattr(r, "buono_n", "") or "").strip()]
        rows = [r for r in rows_non_uscite if not str(getattr(r, "buono_n", "") or "").strip()]

        if not rows and rows_uscite:
            dettagli = "<br>".join(_uscito_info(r) for r in rows_uscite[:10])
            return (
                "<b>Operazione annullata.</b><br>"
                "Le righe trovate risultano già uscite, quindi CAMY non può inserirle nel Buono di Prelievo.<br>"
                + dettagli
            )

        if not rows and rows_con_buono:
            dettagli = "<br>".join(
                f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')} | Buono già presente: <b>{_esc(r.buono_n or '-')}</b>"
                for r in rows_con_buono[:10]
            )
            return (
                "<b>Operazione annullata.</b><br>"
                "Le righe trovate hanno già un N. Buono assegnato. CAMY non crea un secondo Buono sulla stessa riga.<br>"
                + dettagli + "<br><br>Se devi aggiungerle a un Buono esistente usa: <b>Aggiungi al buono ...</b>"
            )

        if not rows:
            return "Non ho trovato righe attive compatibili per preparare il buono."

        total = len(rows)
        if total > 30:
            return (
                f"Ho trovato {total} righe. Per sicurezza non preparo un buono con più di 30 righe da CAMY AI.<br>"
                "Restringi la ricerca con N. arrivo, codice articolo, DDT o ID."
            )

        # Se la richiesta contiene più marca-pezzi con quantità, associa ogni codice
        # alla riga di giacenza corretta e prepara UN SOLO Buono con più righe.
        row_requests = {}
        if line_items:
            missing = []
            ambiguous = []
            for item in line_items:
                code = (item.get("codice") or "").strip()
                code_norm = _norm_part(code)
                candidates = []
                for r in rows:
                    original_norm = _norm_part(getattr(r, "codice_articolo", "") or "")
                    parts = _split_multi_values(getattr(r, "codice_articolo", ""), allow_dash=True)
                    part_norms = {_norm_part(x) for x in parts if _norm_part(x)}
                    if code_norm and (code_norm in part_norms or code_norm in original_norm):
                        candidates.append(r)
                if not candidates:
                    missing.append(code)
                    continue
                if len(candidates) > 1:
                    # Preferisce una corrispondenza esatta su una singola parte.
                    exact = [r for r in candidates if code_norm in {_norm_part(x) for x in _split_multi_values(getattr(r, "codice_articolo", ""), allow_dash=True)}]
                    if len(exact) == 1:
                        candidates = exact
                    else:
                        ambiguous.append((code, candidates))
                        continue
                r = candidates[0]
                rid = int(r.id_articolo)
                bucket = row_requests.setdefault(rid, {"codes": [], "qty": 0.0})
                bucket["codes"].append(code)
                try:
                    bucket["qty"] += float(item.get("pezzi") or 0)
                except Exception:
                    pass

            if missing:
                return "<b>Buono non preparato.</b><br>Marca-pezzi non trovati in giacenza: <b>" + _esc(", ".join(missing)) + "</b>."
            if ambiguous:
                details = []
                candidate_ids = []
                for code, candidates in ambiguous:
                    ids_code = []
                    for r in candidates[:12]:
                        try:
                            rid = int(getattr(r, "id_articolo", 0) or 0)
                        except Exception:
                            rid = 0
                        if rid and rid not in candidate_ids:
                            candidate_ids.append(rid)
                        if rid:
                            ids_code.append(f"ID {rid}")
                    details.append(_esc(code) + ": " + ", ".join(ids_code))

                _camy_dialog_save({
                    "state": "waiting_id",
                    "operation": "prepare_buono",
                    "original_message": msg,
                    "candidate_ids": candidate_ids,
                    "requested_codes": [code for code, _ in ambiguous],
                })

                return (
                    "<b>Buono non ancora preparato.</b><br>"
                    "Alcuni marca-pezzi sono presenti in più righe.<br>"
                    + "<br>".join(details)
                    + "<br><br><b>Quale ID devo usare?</b><br>"
                    "Rispondi semplicemente, per esempio: <b>ID "
                    + _esc(candidate_ids[0] if candidate_ids else "")
                    + "</b>, oppure scrivi <b>il primo</b>."
                )

            rows = [r for r in rows if int(r.id_articolo) in row_requests]
            for r in rows:
                req = row_requests[int(r.id_articolo)]
                disponibili = _available_pezzi_for_request(r, requested_code=" - ".join(req["codes"]))
                if disponibili is not None and req["qty"] > float(disponibili):
                    return (
                        "<b>Operazione bloccata.</b><br>"
                        f"ID {_esc(r.id_articolo)} | Marca-pezzi: <b>{_esc(' - '.join(req['codes']))}</b><br>"
                        f"Richiesti: <b>{_esc(req['qty'])}</b> | Disponibili: <b>{_esc(disponibili)}</b>"
                    )

        prossimo_auto = _peek_next_buono_number(db)
        manual_buono = _extract_manual_buono_number(msg)
        requested_code = (filters.get("codice_articolo") or "").strip()
        requested_descr = _extract_requested_descrizione(msg)
        requested_pezzi = _extract_requested_pezzi(msg)

        problemi_pezzi = _validate_pezzi_richiesti(rows, requested_pezzi, requested_code=requested_code)
        if problemi_pezzi:
            dettagli = "<br>".join(
                f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')} | Disponibili: <b>{_esc(disp)}</b> | Richiesti: <b>{_esc(req)}</b>"
                for r, disp, req in problemi_pezzi[:10]
            )
            return (
                "<b>Operazione bloccata.</b><br>"
                "I pezzi richiesti sono superiori ai pezzi disponibili in giacenza.<br>"
                + dettagli
            )

        note_buono = _extract_note_buono(msg)
        needs_partial_details = any(_row_needs_partial_details(r) for r in rows) and not (requested_code or requested_descr)

        token = _make_token()
        ids = [int(r.id_articolo) for r in rows]
        row_snapshots = {}
        for r in rows:
            rid_key = str(getattr(r, "id_articolo", "") or "")
            req_for_row = row_requests.get(int(r.id_articolo), {}) if row_requests else {}
            req_codes = "-".join(req_for_row.get("codes") or [])
            available_now = _available_pezzi_for_request(r, requested_code=req_codes or requested_code)
            row_snapshots[rid_key] = {
                "original_pezzi": available_now,
                "original_code": str(getattr(r, "codice_articolo", "") or ""),
            }

        _save_pending_op(token, {
            "type": "set_buono",
            "ids": ids,
            "manual_buono": manual_buono,
            "requested_code": requested_code,
            "requested_descr": requested_descr,
            "requested_pezzi": requested_pezzi,
            "note_buono": note_buono,
            "needs_partial_details": bool(needs_partial_details),
            "row_requests": {str(k): v for k, v in row_requests.items()},
            "row_snapshots": row_snapshots,
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

        dettagli_multi = ""
        if row_requests:
            lines = []
            for r in rows:
                req = row_requests.get(int(r.id_articolo), {})
                lines.append(
                    f"ID {_esc(r.id_articolo)} | Marca-pezzi: <b>{_esc(' - '.join(req.get('codes') or []))}</b> | "
                    f"Pezzi richiesti: <b>{_esc(req.get('qty') or 0)}</b> | Disponibili: {_esc(getattr(r, 'pezzo', 0) or 0)}"
                )
            dettagli_multi = "<br><b>Righe del Buono unico:</b><br>" + "<br>".join(lines) + "<br>"

        dettagli_usciti = ""
        if rows_uscite:
            dettagli_usciti = (
                "<br><b>Attenzione:</b> alcune righe sono già uscite e verranno escluse dal Buono:<br>"
                + "<br>".join(_uscito_info(r) for r in rows_uscite[:8])
                + "<br>"
            )

        dettagli_buoni_esistenti = ""
        if rows_con_buono:
            dettagli_buoni_esistenti = (
                "<br><b>Attenzione:</b> alcune righe hanno già un Buono e verranno escluse dalla nuova proposta:<br>"
                + "<br>".join(
                    f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')} | Buono: <b>{_esc(r.buono_n or '-')}</b>"
                    for r in rows_con_buono[:8]
                )
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
            f"Prossimo numero automatico previsto: <b>{_esc(prossimo_auto)}</b>{scelta_manual}{dettagli_multi}{dettagli_parziale}{dettagli_note}{dettagli_usciti}{dettagli_buoni_esistenti}<br>",
            "CAMY applicherà la modifica solo dopo conferma. Nessuno scarico definitivo verrà eseguito automaticamente.<br>"
        ]
        riepilogo.append(dettagli_multi)
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


    def _extract_picking_buono_target(msg):
        s = msg or ""
        patterns = [
            r"\b(?:crea|genera|prepara)\s+picking\s+(?:dal|del|da|per)?\s*buono\s+([A-Z0-9][A-Z0-9./\-_]{1,50})",
            r"\bpicking\s+buono\s+([A-Z0-9][A-Z0-9./\-_]{1,50})",
        ]
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                return (m.group(1) or "").strip().strip(".,;:")
        return ""

    def _unique_join(values):
        out, seen = [], set()
        for v in values or []:
            v = str(v or "").strip()
            if not v:
                continue
            k = v.upper()
            if k not in seen:
                seen.add(k)
                out.append(v)
        return " / ".join(out)

    def _crea_picking_da_buono(db, buono, descrizione_default="PICKING+FILMATURA+PALLETIZZAZIONE"):
        """Crea una riga Picking/Lavorazione partendo dalle righe del Buono di Prelievo.
        Non duplica se nella stessa giornata esiste già una lavorazione con stesso buono.
        """
        buono = str(buono or "").strip()
        if not buono:
            return {"created": False, "message": "N. Buono mancante."}

        LavorazioneModel = globals().get("Lavorazione")
        if LavorazioneModel is None:
            return {"created": False, "message": "Modello Lavorazione non disponibile."}

        rows = (
            _base_query(db)
            .filter(func.upper(func.trim(Articolo.buono_n)) == buono.upper())
            .order_by(Articolo.id_articolo.asc())
            .all()
        )
        if not rows:
            rows = (
                _base_query(db)
                .filter(Articolo.buono_n.ilike(f"%{buono}%"))
                .order_by(Articolo.id_articolo.asc())
                .all()
            )
        if not rows:
            return {"created": False, "message": f"Non ho trovato righe con Buono {buono}."}

        today = date.today()
        try:
            existing = (
                db.query(LavorazioneModel)
                .filter(LavorazioneModel.data == today)
                .filter(func.upper(func.coalesce(LavorazioneModel.seriali, "")).like(f"%{buono.upper()}%"))
                .first()
            )
            if existing:
                return {"created": False, "already": True, "message": f"Picking già presente oggi per il Buono {buono}."}
        except Exception:
            existing = None

        cliente = _unique_join([getattr(r, "cliente", "") for r in rows])
        n_arrivo = _unique_join([getattr(r, "n_arrivo", "") for r in rows])
        colli = 0
        for r in rows:
            try:
                colli += int(getattr(r, "n_colli", 0) or 0)
            except Exception:
                pass
        if colli <= 0:
            colli = len(rows)

        rec = LavorazioneModel()
        rec.data = today
        rec.cliente = cliente
        rec.descrizione = descrizione_default
        rec.richiesta_di = ""
        rec.seriali = buono
        if hasattr(rec, "n_arrivo"):
            rec.n_arrivo = n_arrivo
        rec.colli = colli
        rec.pallet_forniti = 0
        rec.pallet_uscita = 0
        rec.ore_blue_collar = 0
        rec.ore_white_collar = 0
        db.add(rec)
        db.commit()
        return {"created": True, "buono": buono, "cliente": cliente, "n_arrivo": n_arrivo, "colli": colli, "id": getattr(rec, "id", None)}

    def _answer_crea_picking_da_buono(db, msg):
        if not _can_operate():
            return _operation_denied()
        buono = _extract_picking_buono_target(msg)
        if not buono:
            return "Indicami il numero del Buono. Esempio: <b>Crea picking dal buono 073-FADEM</b>"
        res = _crea_picking_da_buono(db, buono)
        if res.get("created"):
            return (
                f"<b>Picking creato automaticamente dal Buono {_esc(buono)}.</b><br>"
                f"Cliente: {_esc(res.get('cliente') or '-')}<br>"
                f"N. Arrivo: {_esc(res.get('n_arrivo') or '-')}<br>"
                f"Colli: {_esc(res.get('colli') or 0)}<br>"
                "Descrizione: <b>PICKING+FILMATURA+PALLETIZZAZIONE</b><br>"
                f"<a class='btn btn-sm btn-outline-primary mt-2' href='{_esc(url_for('lavorazioni'))}'>Apri Picking</a>"
            )
        return _esc(res.get("message") or "Picking non creato.")

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

                row_requests = op.get("row_requests") or {}
                row_snapshots = op.get("row_snapshots") or {}
                for r in rows:
                    rid_key = str(getattr(r, "id_articolo", "") or "")
                    per_row = row_requests.get(rid_key) or {}
                    snapshot = row_snapshots.get(rid_key) or {}
                    row_requested_code = "-".join(per_row.get("codes") or []) or requested_code
                    row_requested_pezzi = _clean_piece_value(per_row.get("qty") or requested_pezzi)

                    original_qty_snapshot = _safe_float_or_none(snapshot.get("original_pezzi"))
                    current_qty = _safe_float_or_none(getattr(r, "pezzo", ""))

                    # Se la disponibilità è cambiata tra proposta e conferma, blocca:
                    # evita di calcolare un residuo su dati non più aggiornati.
                    if (
                        original_qty_snapshot is not None
                        and current_qty is not None
                        and abs(original_qty_snapshot - current_qty) > 0.000001
                    ):
                        db.rollback()
                        return jsonify({
                            "answer": (
                                f"La disponibilità della riga ID {_esc(rid_key)} è cambiata "
                                f"da {_esc(_clean_piece_value(original_qty_snapshot))} a "
                                f"{_esc(_clean_piece_value(current_qty))} pezzi.<br>"
                                "Aggiorna la richiesta prima di creare il Buono."
                            ),
                            "html": True
                        }), 409

                    new_row, info = _prepare_partial_split_for_buono(
                        r,
                        buono,
                        requested_code=row_requested_code,
                        requested_descr=requested_descr,
                        requested_pezzi=row_requested_pezzi,
                        original_qty_override=original_qty_snapshot,
                    )
                    if new_row is not None:
                        if note_buono:
                            # Le note del Buono vanno solo sulla nuova riga del Buono.
                            new_row.note = note_buono
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
                        # Se CAMY ha letto una quantità specifica, non deve ignorarla.
                        if row_requested_pezzi:
                            try:
                                req_num = float(str(row_requested_pezzi).replace(',', '.'))
                                disp_num = float(str(getattr(r, 'pezzo', 0) or 0).replace(',', '.'))
                                if req_num < disp_num:
                                    # Una quantità inferiore richiede lo split controllato del modulo Buono.
                                    db.rollback()
                                    return jsonify({
                                        "answer": "La quantità richiesta è inferiore alla disponibilità. Apri l’anteprima del Buono per completare lo scarico parziale in sicurezza.",
                                        "html": False
                                    }), 409
                            except Exception:
                                pass
                        r.buono_n = buono
                        r.pezzo = _piece_value_for_db(getattr(r, "pezzo", ""))
                        # In questo ramo la riga originale è interamente assegnata al Buono,
                        # quindi non è una riga residua e può ricevere la nota del Buono.
                        if note_buono:
                            r.note = note_buono
                        updated += 1

                db.commit()

                picking_msg = ""
                try:
                    pick = _crea_picking_da_buono(db, buono)
                    if pick.get("created"):
                        picking_msg = (
                            f"<br><b>Picking creato automaticamente.</b><br>"
                            f"Descrizione: PICKING+FILMATURA+PALLETIZZAZIONE<br>"
                            f"N. Arrivo: {_esc(pick.get('n_arrivo') or '-')}<br>"
                        )
                    elif pick.get("already"):
                        picking_msg = f"<br><b>Picking:</b> {_esc(pick.get('message') or 'già presente')}<br>"
                except Exception as pick_err:
                    try:
                        scrivi_log_errore("CAMY AI - creazione picking da buono", pick_err)
                    except Exception:
                        pass

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
                    extra += f"<br>Note salvate esclusivamente sulla riga del Buono: <b>{_esc(note_buono)}</b><br>"
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
                        f"{picking_msg}"
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


    def _filters_to_query_params(filters):
        """Converte i filtri CAMY nei parametri usati da Giacenze/Export Excel."""
        params = []
        mapping = {
            "cliente": "cliente",
            "codice_articolo": "codice_articolo",
            "descrizione": "descrizione",
            "n_arrivo": "n_arrivo",
            "ddt": "n_ddt_ingresso",
            "stato": "stato",
            "fornitore": "fornitore",
            "serial_number": "serial_number",
            "lotto": "lotto",
            "posizione": "posizione",
        }
        for k, dest in mapping.items():
            v = (filters.get(k) or "").strip() if isinstance(filters.get(k), str) else filters.get(k)
            if v:
                params.append((dest, str(v)))
        if filters.get("only_active"):
            params.append(("solo_giacenza", "1"))
        if filters.get("date_from"):
            if (filters.get("date_field") or "data_ingresso") == "data_uscita":
                params.append(("data_usc_da", filters.get("date_from")))
            else:
                params.append(("data_ing_da", filters.get("date_from")))
        if filters.get("date_to"):
            if (filters.get("date_field") or "data_ingresso") == "data_uscita":
                params.append(("data_usc_a", filters.get("date_to")))
            else:
                params.append(("data_ing_a", filters.get("date_to")))
        try:
            from urllib.parse import urlencode
            return urlencode(params)
        except Exception:
            return "&".join([str(a) + "=" + str(b) for a, b in params])

    def _extract_ddt_buono_target(msg):
        """Estrae il N. Buono quando CAMY deve aprire il DDT partendo da un Buono.
        Esempi validi:
        - Crea DDT buono 073-FADEM
        - Crea DDT dal buono 45/26
        - Apri DDT per buono BP-12/26
        """
        s = msg or ""
        patterns = [
            r"\b(?:crea|prepara|apri|genera)?\s*(?:ddt)?\s*(?:dal|del|da|per)?\s*buono\s+([A-Z0-9][A-Z0-9./\-_]{1,50})",
            r"\bbuono\s*(?:n\.?|numero)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9./\-_]{1,50})",
        ]
        stop = {"ARRIVO", "CODICE", "DDT", "CLIENTE", "ID", "IDS", "SCARICO", "PARZIALE"}
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                val = (m.group(1) or "").strip().strip(".,;:")
                if val and val.upper() not in stop:
                    return val
        return ""

    def _answer_prepare_ddt(db, msg):
        if not _can_operate():
            return _operation_denied()

        if 'ddt_preview' not in app.view_functions:
            return (
                "La schermata DDT non risulta registrata nel gestionale. "
                "Controlla che la route <b>/ddt/preview</b> sia attiva prima di usare CAMY per aprire il DDT."
            )

        buono_target = _extract_ddt_buono_target(msg)
        filters = _extract_intent(msg)
        filters["only_active"] = True

        if buono_target:
            q = _base_query(db)
            q = _active_filter(q)
            # Prima provo corrispondenza esatta, poi parziale.
            rows = (
                q.filter(func.upper(func.trim(Articolo.buono_n)) == buono_target.upper())
                 .order_by(Articolo.id_articolo.asc())
                 .limit(200)
                 .all()
            )
            if not rows:
                rows = (
                    q.filter(Articolo.buono_n.ilike(f"%{buono_target}%"))
                     .order_by(Articolo.id_articolo.asc())
                     .limit(200)
                     .all()
                )
            criterio = f"Buono <b>{_esc(buono_target)}</b>"
        else:
            if not any((filters.get(k) or "").strip() for k in ("n_arrivo", "codice_articolo", "ddt", "serial_number", "lotto", "cliente")):
                return (
                    "Per aprire la schermata DDT indicami almeno un riferimento.<br>"
                    "Esempi:<br>"
                    "• <b>Crea DDT buono 073-FADEM</b><br>"
                    "• <b>Crea DDT arrivo 38/26</b>"
                )
            rows = _apply_filters(_base_query(db), filters).order_by(Articolo.id_articolo.asc()).limit(200).all()
            criterio = "filtro richiesto"

        rows = [
            r for r in rows
            if not str(getattr(r, 'data_uscita', '') or '').strip()
            and not str(getattr(r, 'n_ddt_uscita', '') or '').strip()
        ]

        if not rows:
            if buono_target:
                return f"Non ho trovato righe attive col Buono <b>{_esc(buono_target)}</b> per aprire il DDT."
            return "Non ho trovato righe attive compatibili per aprire la schermata DDT."

        if len(rows) > 200:
            return "Ho trovato troppe righe per aprire il DDT da CAMY. Restringi la ricerca."

        # Importante: ddt_preview accetta una lista di campi ids, non un unico campo CSV.
        # Quindi creo un input hidden per ogni riga selezionata.
        hidden_ids = "".join(
            f"<input type='hidden' name='ids' value='{_esc(getattr(r, 'id_articolo', ''))}'>"
            for r in rows
        )

        riepilogo = [
            f"<b>DDT pronto da aprire</b><br>",
            f"Criterio: {criterio}<br>",
            f"Righe selezionate: <b>{len(rows)}</b><br>"
        ]
        for r in rows[:12]:
            riepilogo.append(
                f"ID {_esc(r.id_articolo)} | Codice: {_esc(r.codice_articolo or '-')} | "
                f"Descrizione: {_esc((r.descrizione or '-')[:80])} | Colli: {_esc(r.n_colli or 0)} | "
                f"N. arrivo: {_esc(r.n_arrivo or '-')} | Buono: {_esc(r.buono_n or '-')}<br>"
            )
        if len(rows) > 12:
            riepilogo.append(f"... altre {len(rows)-12} righe.<br>")

        try:
            giacenze_link = url_for('giacenze')
            if buono_target:
                from urllib.parse import urlencode
                giacenze_link += "?" + urlencode({"buono_n": buono_target, "solo_giacenza": "1"})
        except Exception:
            giacenze_link = "/giacenze"

        riepilogo.append(
            "<br><b>Conferma:</b> apro solo la schermata DDT già compilata. "
            "La finalizzazione resta manuale: scegli destinatario, mezzo uscita e poi confermi tu.<br>"
            f"<form method='POST' action='{url_for('ddt_preview')}' style='margin-top:8px; display:inline-block;'>"
            f"{hidden_ids}"
            "<button type='submit' class='btn btn-sm btn-success'>Apri schermata DDT</button>"
            "</form> "
            f"<a class='btn btn-sm btn-outline-primary' href='{_esc(giacenze_link)}'>Vedi righe in Giacenze</a>"
        )
        return "".join(riepilogo)

    def _answer_report_excel(db, msg):
        filters = _extract_intent(msg)
        qs = _filters_to_query_params(filters)
        export_url = url_for('export_excel') + (('?' + qs) if qs else '')
        giacenze_url = url_for('giacenze') + (('?' + qs) if qs else '')
        total = _apply_filters(_base_query(db), filters).with_entities(func.count(Articolo.id_articolo)).scalar() or 0
        return (
            f"<b>Report Excel pronto</b><br>Righe compatibili: <b>{int(total)}</b><br>"
            f"<a class='btn btn-sm btn-success mt-2' href='{export_url}'>Scarica Excel</a> "
            f"<a class='btn btn-sm btn-outline-primary mt-2' href='{giacenze_url}'>Vedi filtro in Giacenze</a>"
        )

    def _answer_confronta_inventario_camy(msg):
        if not _can_operate():
            return _operation_denied()
        return (
            "<b>Confronto inventario</b><br>"
            "Ti apro la funzione dedicata: carica il file inventario, scegli il cliente e CAMY ti mostrerà le differenze prima di applicare eventuali correzioni.<br>"
            f"<a class='btn btn-sm btn-primary mt-2' href='{url_for('confronta_inventario')}'>Apri Confronta Inventario</a>"
        )



    # ========================================================
    # FOTO ARRIVO / COLLO - risposta diretta da CAMY AI
    # ========================================================
    def _extract_photo_arrivo_collo_request(msg):
        """Riconosce frasi tipo:
        - fammi vedere la foto dell'arrivo 778/26 collo 1
        - ci sono foto arrivo 778/26?
        - mostra foto collo 2 arrivo 778/26
        """
        s = msg or ""
        low = s.lower()
        if not any(w in low for w in ["foto", "fotografie", "immagine", "immagini", "allegati"]):
            return None
        if "arrivo" not in low:
            return None

        arrivo = ""
        m = re.search(r"\b(?:n\.?\s*)?arrivo\s+([A-Z0-9./\-_]+(?:\s*/\s*[A-Z0-9]+)?)", s, re.I)
        if m:
            arrivo = (m.group(1) or "").strip()

        collo = ""
        m = re.search(r"\b(?:collo|colli|n\.?|numero)\s*[:\-]?\s*(\d{1,4})\b", s, re.I)
        if m:
            collo = (m.group(1) or "").strip()

        if not arrivo:
            return None
        return {"arrivo": arrivo, "collo": collo}

    def _is_photo_attachment(att):
        kind = (getattr(att, "kind", "") or "").strip().lower()
        fn = (getattr(att, "filename", "") or "").strip().lower()
        return kind in ("photo", "foto", "image", "img") or fn.endswith((".jpg", ".jpeg", ".png", ".webp"))

    def _photo_attachments(row):
        return [a for a in (getattr(row, "attachments", []) or []) if _is_photo_attachment(a) and getattr(a, "filename", None)]

    def _row_matches_collo(row, collo):
        if not collo:
            return True
        c = str(collo).strip()
        arr = str(getattr(row, "n_arrivo", "") or "")
        arr_norm = _norm_part(arr)
        patterns = [
            f"N{c}",
            f"COLLO{c}",
            f"COLLI{c}",
        ]
        return any(p in arr_norm for p in patterns)

    def _photo_link_html(att, row):
        try:
            href = url_for("serve_uploaded_file", filename=getattr(att, "filename", ""))
        except Exception:
            href = "/media/" + str(getattr(att, "filename", ""))
        filename = _esc(getattr(att, "filename", "") or "foto")
        return (
            "<div class='camy-ai-result'>"
            f"<b>Foto riga ID {_esc(getattr(row, 'id_articolo', '') or '')}</b><br>"
            f"Arrivo: {_esc(getattr(row, 'n_arrivo', '') or '-')} | "
            f"Codice: {_esc(getattr(row, 'codice_articolo', '') or '-')}<br>"
            f"<a href='{_esc(href)}' target='_blank'>📷 Apri foto: {filename}</a><br>"
            f"<a href='{_esc(href)}' target='_blank'><img src='{_esc(href)}' style='max-width:220px;max-height:160px;border:1px solid #ddd;border-radius:8px;margin-top:6px'></a>"
            "</div>"
        )

    def _answer_arrivo_photos(db, msg):
        req = _extract_photo_arrivo_collo_request(msg)
        if not req:
            return None

        arrivo = req.get("arrivo", "")
        collo = req.get("collo", "")
        arrivo_base = re.sub(r"\s+", "", arrivo)

        q = _base_query(db)
        q = _apply_norm_equals_or_like(q, Articolo.n_arrivo, arrivo_base)
        rows = q.order_by(Articolo.id_articolo.asc()).limit(200).all()

        if not rows:
            return f"Non ho trovato righe per l'arrivo <b>{_esc(arrivo)}</b>."

        # Prima provo a identificare il collo richiesto dal testo del N. arrivo.
        target_rows = [r for r in rows if _row_matches_collo(r, collo)] if collo else rows

        # Se il gestionale non salva 'N.1 / collo 1' nel campo arrivo, uso l'ordine delle righe come fallback.
        if collo and not target_rows:
            try:
                idx = int(collo) - 1
                if 0 <= idx < len(rows):
                    target_rows = [rows[idx]]
            except Exception:
                target_rows = []

        target_photos = []
        for r in target_rows:
            for a in _photo_attachments(r):
                target_photos.append((r, a))

        if target_photos:
            titolo = f"Ho trovato {len(target_photos)} foto per l'arrivo <b>{_esc(arrivo)}</b>"
            if collo:
                titolo += f", collo <b>{_esc(collo)}</b>"
            return titolo + ":<br>" + "".join(_photo_link_html(a, r) for r, a in target_photos[:12])

        all_photos = []
        for r in rows:
            for a in _photo_attachments(r):
                all_photos.append((r, a))

        if collo and all_photos:
            return (
                f"Nel collo <b>{_esc(collo)}</b> dell'arrivo <b>{_esc(arrivo)}</b> non ci sono foto.<br>"
                f"Però ho trovato <b>{len(all_photos)}</b> foto sull'arrivo completo. Vuoi vedere le foto di tutto l'arrivo?<br>"
                + "".join(_photo_link_html(a, r) for r, a in all_photos[:12])
            )

        return f"Non ho trovato foto collegate all'arrivo <b>{_esc(arrivo)}</b>."

    def _extract_arrivo_colli_for_accettazione(msg):
        """Estrae arrivo e colli da frasi tipo: crea entrata arrivo 770/26 con 20 colli."""
        s = (msg or '').strip()
        arrivo = ''
        colli = ''
        m = re.search(r'(?:arrivo|n\.\s*arrivo)\s+([0-9]{1,5}\s*/\s*[0-9]{2,4})', s, re.I)
        if not m:
            m = re.search(r'\b([0-9]{1,5}\s*/\s*[0-9]{2,4})\b', s, re.I)
        if m:
            arrivo = re.sub(r'\s+', '', m.group(1))
        m2 = re.search(r'(?:con|da)?\s*(\d{1,4})\s*(?:colli|collo|coll|pallet)\b', s, re.I)
        if m2:
            colli = m2.group(1)
        return arrivo, colli

    def _answer_accettazione_entrata(msg):
        arrivo, colli = _extract_arrivo_colli_for_accettazione(msg)
        params = []
        if arrivo:
            params.append('arrivo=' + arrivo.replace('/', '%2F'))
        if colli:
            params.append('colli=' + colli)
        url = '/accettazione_entrata' + (('?' + '&'.join(params)) if params else '')
        parti = ["Ho preparato la schermata <b>Accettazione Entrata</b>."]
        if arrivo:
            parti.append(f"N. arrivo precompilato: <b>{_esc(arrivo)}</b>.")
        if colli:
            parti.append(f"Colli precompilati: <b>{_esc(colli)}</b>.")
        parti.append("Carica il PDF OCR del DDT dell'autista, controlla i dati letti e conferma l'entrata.")
        parti.append(f'<br><a class="btn btn-sm btn-success mt-2" href="{url}">📄 Apri Accettazione Entrata</a>')
        return '<br>'.join(parti)


    def _today_date_from_message(msg):
        """Estrae la data per report giornaliero/quaderno.
        Supporta: oggi, ieri, gg/mm/aaaa, aaaa-mm-gg. Default: oggi.
        """
        s = (msg or '').strip().lower()
        if 'ieri' in s:
            from datetime import timedelta
            return date.today() - timedelta(days=1)
        m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b', s)
        if m:
            gg, mm, aa = m.groups()
            aa = ('20' + aa) if len(aa) == 2 else aa
            try:
                return datetime(int(aa), int(mm), int(gg)).date()
            except Exception:
                pass
        m = re.search(r'\b(20\d{2})-(\d{1,2})-(\d{1,2})\b', s)
        if m:
            aa, mm, gg = m.groups()
            try:
                return datetime(int(aa), int(mm), int(gg)).date()
            except Exception:
                pass
        return date.today()

    def _filter_date_equals(q, column, d):
        """Filtro data robusto per campi TEXT e DATE.
        Articolo.data_ingresso/data_uscita sono TEXT, mentre Trasporto.data e Lavorazione.data sono DATE.
        Evita l'errore Postgres TEXT = DATE che causava 500 nel Registro giornaliero.
        """
        if not d:
            return q
        try:
            from sqlalchemy import Date as SA_Date, DateTime as SA_DateTime
            col_type = getattr(column, 'type', None)
            if isinstance(col_type, (SA_Date, SA_DateTime)):
                return q.filter(column == d)
        except Exception:
            pass

        vals = []
        try:
            vals = [d.strftime('%Y-%m-%d'), d.strftime('%d/%m/%Y')]
        except Exception:
            vals = [str(d)]
        return q.filter(or_(*[column == v for v in vals]))

    def _safe_model(name):
        try:
            return globals().get(name)
        except Exception:
            return None

    def _as_date_for_registro(value):
        """Converte in date i valori data salvati come DATE, datetime o stringa.
        Serve perché Trasporti e Picking/Lavorazioni possono avere formati diversi nel DB.
        """
        try:
            if not value:
                return None
        except Exception:
            pass
        try:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
        except Exception:
            pass
        s = str(value or '').strip()
        if not s:
            return None
        # Se arriva una datetime come stringa, considero solo la parte data.
        s10 = s[:10]
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y'):
            try:
                return datetime.strptime(s10 if fmt == '%Y-%m-%d' else s, fmt).date()
            except Exception:
                pass
        try:
            return to_date_db(value)
        except Exception:
            return None

    def _rows_by_day_python(rows, date_attr, giorno):
        """Filtro data lato Python: evita problemi PostgreSQL TEXT/DATE e formati misti."""
        out = []
        for rec in rows or []:
            try:
                if _as_date_for_registro(getattr(rec, date_attr, None)) == giorno:
                    out.append(rec)
            except Exception:
                pass
        return out

    def _answer_registro_giornaliero(db, msg):
        """Genera il quaderno/registro giornaliero prendendo i dati già presenti nel gestionale."""
        if not _can_operate():
            return _operation_denied()

        giorno = _today_date_from_message(msg)
        data_it = giorno.strftime('%d/%m/%Y')

        # Entrate del giorno
        entrate_q = _base_query(db)
        entrate_q = _filter_date_equals(entrate_q, Articolo.data_ingresso, giorno)
        entrate_rows = entrate_q.order_by(Articolo.cliente.asc(), Articolo.n_arrivo.asc(), Articolo.id_articolo.asc()).limit(600).all()

        # Uscite/DDT del giorno
        uscite_q = _base_query(db)
        uscite_q = _filter_date_equals(uscite_q, Articolo.data_uscita, giorno)
        uscite_rows = uscite_q.order_by(Articolo.n_ddt_uscita.asc(), Articolo.cliente.asc(), Articolo.id_articolo.asc()).limit(600).all()

        # Raggruppo entrate per cliente + arrivo + DDT ingresso
        entrate = {}
        for r in entrate_rows:
            key = ((r.cliente or '-').strip(), (strip_arrivo_progressivo(r.n_arrivo) if 'strip_arrivo_progressivo' in globals() else (r.n_arrivo or '')).strip(), (r.n_ddt_ingresso or '').strip())
            rec = entrate.setdefault(key, {'colli':0, 'peso':0.0, 'righe':0})
            rec['righe'] += 1
            try: rec['colli'] += int(r.n_colli or 0)
            except Exception: pass
            try: rec['peso'] += float(r.peso or 0)
            except Exception: pass

        # Raggruppo uscite per DDT + cliente
        uscite = {}
        for r in uscite_rows:
            key = ((r.n_ddt_uscita or '-').strip(), (r.cliente or '-').strip())
            rec = uscite.setdefault(key, {'colli':0, 'peso':0.0, 'righe':0})
            rec['righe'] += 1
            try: rec['colli'] += int(r.n_colli or 0)
            except Exception: pass
            try: rec['peso'] += float(r.peso or 0)
            except Exception: pass

        # Trasporti del giorno.
        # Importante: li filtriamo in Python perché nel DB la data può essere DATE o TEXT
        # a seconda della versione del gestionale/deploy.
        trasporti_rows = []
        TrasportoModel = _safe_model('Trasporto')
        if TrasportoModel is not None:
            try:
                all_trasporti = db.query(TrasportoModel).order_by(TrasportoModel.id.desc()).limit(2000).all()
                trasporti_rows = _rows_by_day_python(all_trasporti, 'data', giorno)
                trasporti_rows.sort(key=lambda r: ((getattr(r, 'cliente', '') or ''), (getattr(r, 'ddt_uscita', '') or '')))
                trasporti_rows = trasporti_rows[:300]
            except Exception as e:
                try:
                    scrivi_log_errore('CAMY Registro - lettura trasporti', e)
                except Exception:
                    pass
                trasporti_rows = []

        # Lavorazioni/Picking del giorno.
        # Anche qui filtro in Python perché la pagina Picking usa conversioni robuste lato codice.
        lavorazioni_rows = []
        LavorazioneModel = _safe_model('Lavorazione')
        if LavorazioneModel is not None:
            try:
                all_lavorazioni = db.query(LavorazioneModel).order_by(LavorazioneModel.id.desc()).limit(2000).all()
                lavorazioni_rows = _rows_by_day_python(all_lavorazioni, 'data', giorno)
                lavorazioni_rows.sort(key=lambda r: ((getattr(r, 'cliente', '') or ''), (getattr(r, 'id', 0) or 0)))
                lavorazioni_rows = lavorazioni_rows[:300]
            except Exception as e:
                try:
                    scrivi_log_errore('CAMY Registro - lettura lavorazioni/picking', e)
                except Exception:
                    pass
                lavorazioni_rows = []

        tot_colli_in = sum(v['colli'] for v in entrate.values())
        tot_peso_in = sum(v['peso'] for v in entrate.values())
        tot_colli_out = sum(v['colli'] for v in uscite.values())
        tot_peso_out = sum(v['peso'] for v in uscite.values())
        tot_costo = 0.0
        for t in trasporti_rows:
            try: tot_costo += float(getattr(t, 'costo', 0) or 0)
            except Exception: pass

        out = []
        out.append(f"<b>📒 Registro giornaliero del {data_it}</b><br>")
        out.append("<b>ENTRATE</b><br>")
        if entrate:
            for (cliente, arrivo, ddt), rec in entrate.items():
                out.append(f"• {_esc(cliente)} - Arrivo {_esc(arrivo or '-')} - DDT ingresso {_esc(ddt or '-')} - Colli {int(rec['colli'] or rec['righe'])} - Peso {_esc(_fmt_num(rec['peso']))} kg<br>")
        else:
            out.append("• Nessuna entrata registrata.<br>")

        out.append("<br><b>USCITE / DDT</b><br>")
        if uscite:
            for (ddt, cliente), rec in uscite.items():
                out.append(f"• DDT {_esc(ddt)} - {_esc(cliente)} - Colli {int(rec['colli'] or rec['righe'])} - Peso {_esc(_fmt_num(rec['peso']))} kg<br>")
        else:
            out.append("• Nessun DDT registrato.<br>")

        out.append("<br><b>TRASPORTI</b><br>")
        if trasporti_rows:
            for t in trasporti_rows:
                costo = getattr(t, 'costo', None)
                costo_txt = f" - Costo € {_esc(_fmt_num(costo))}" if costo not in (None, '') else ""
                out.append(
                    f"• DDT {_esc(getattr(t, 'ddt_uscita', '') or '-')} - {_esc(getattr(t, 'cliente', '') or '-')} - "
                    f"Trasportatore {_esc(getattr(t, 'trasportatore', '') or '-')} - Mezzo {_esc(getattr(t, 'tipo_mezzo', '') or '-')}"
                    f"{costo_txt}<br>"
                )
        else:
            out.append("• Nessun trasporto registrato.<br>")

        out.append("<br><b>PICKING / LAVORAZIONI</b><br>")
        if lavorazioni_rows:
            for l in lavorazioni_rows:
                ore_b = getattr(l, 'ore_blue_collar', None) or 0
                ore_w = getattr(l, 'ore_white_collar', None) or 0
                out.append(
                    f"• {_esc(getattr(l, 'cliente', '') or '-')} - {_esc(getattr(l, 'descrizione', '') or '-')} - "
                    f"Colli {_esc(getattr(l, 'colli', '') or 0)} - Pallet IN {_esc(getattr(l, 'pallet_forniti', '') or 0)} - "
                    f"Pallet OUT {_esc(getattr(l, 'pallet_uscita', '') or 0)} - Ore { _esc(_fmt_num(float(ore_b or 0) + float(ore_w or 0))) }<br>"
                )
        else:
            out.append("• Nessuna lavorazione registrata.<br>")

        out.append("<br><b>TOTALI GIORNATA</b><br>")
        out.append(f"• Entrate: {len(entrate)} - Colli in entrata: {int(tot_colli_in)} - Peso: {_esc(_fmt_num(tot_peso_in))} kg<br>")
        out.append(f"• DDT uscita: {len(uscite)} - Colli in uscita: {int(tot_colli_out)} - Peso: {_esc(_fmt_num(tot_peso_out))} kg<br>")
        out.append(f"• Trasporti: {len(trasporti_rows)} - Costo totale: € {_esc(_fmt_num(tot_costo))}<br>")

        out.append("<br><div class='alert alert-light border small'><b>Testo pronto per WhatsApp / email:</b><br>")
        testo = []
        testo.append(f"Registro giornaliero {data_it}")
        testo.append(f"Entrate: {len(entrate)} - Colli {int(tot_colli_in)}")
        testo.append(f"DDT uscita: {len(uscite)} - Colli {int(tot_colli_out)}")
        testo.append(f"Trasporti: {len(trasporti_rows)} - Costo totale € {_fmt_num(tot_costo)}")
        testo.append(f"Lavorazioni/Picking: {len(lavorazioni_rows)}")
        out.append("<pre style='white-space:pre-wrap;margin-bottom:0'>" + _esc("\n".join(testo)) + "</pre></div>")
        return "".join(out)

    def _answer_cosa_manca_oggi(db, msg):
        """Controllo rapido delle attività aperte/incomplete per ridurre dimenticanze."""
        if not _can_operate():
            return _operation_denied()
        giorno = _today_date_from_message(msg)
        data_it = giorno.strftime('%d/%m/%Y')
        out = [f"<b>✅ Controllo attività aperte del {data_it}</b><br>"]

        # Arrivi di oggi incompleti: protocollo, codice, descrizione, posizione.
        q = _base_query(db)
        q = _filter_date_equals(q, Articolo.data_ingresso, giorno)
        rows = q.order_by(Articolo.cliente.asc(), Articolo.n_arrivo.asc()).limit(500).all()
        incompleti = []
        for r in rows:
            mancano = []
            if not (r.codice_articolo or '').strip(): mancano.append('codice')
            if not (r.descrizione or '').strip(): mancano.append('descrizione')
            if not (r.protocollo or '').strip(): mancano.append('protocollo')
            if not (r.posizione or '').strip(): mancano.append('posizione')
            if mancano:
                incompleti.append((r, mancano))

        out.append("<b>Arrivi da completare</b><br>")
        if incompleti:
            for r, mancano in incompleti[:20]:
                out.append(f"• ID {_esc(r.id_articolo)} - {_esc(r.cliente or '-')} - Arrivo {_esc(r.n_arrivo or '-')} - manca: {_esc(', '.join(mancano))}<br>")
            if len(incompleti) > 20:
                out.append(f"• ... altre {len(incompleti)-20} righe da verificare.<br>")
        else:
            out.append("• Nessun arrivo incompleto trovato per oggi.<br>")

        # Buoni presenti senza DDT uscita.
        q2 = _active_filter(_base_query(db)).filter(Articolo.buono_n != None).filter(Articolo.buono_n != '')
        buoni_aperti = q2.order_by(Articolo.buono_n.asc(), Articolo.cliente.asc()).limit(200).all()
        groups = {}
        for r in buoni_aperti:
            groups.setdefault((r.buono_n or '-', r.cliente or '-'), 0)
            groups[(r.buono_n or '-', r.cliente or '-')] += 1
        out.append("<br><b>Buoni aperti senza DDT</b><br>")
        if groups:
            for (buono, cliente), count in list(groups.items())[:20]:
                out.append(f"• Buono {_esc(buono)} - {_esc(cliente)} - {count} riga/e<br>")
            if len(groups) > 20:
                out.append(f"• ... altri {len(groups)-20} buoni aperti.<br>")
        else:
            out.append("• Nessun buono aperto senza DDT.<br>")

        # DDT di oggi senza trasporto.
        q3 = _base_query(db)
        q3 = _filter_date_equals(q3, Articolo.data_uscita, giorno)
        uscite = q3.filter(Articolo.n_ddt_uscita != None).filter(Articolo.n_ddt_uscita != '').all()
        ddt_set = sorted({(r.n_ddt_uscita or '').strip() for r in uscite if (r.n_ddt_uscita or '').strip()})
        trasporti_set = set()
        TrasportoModel = _safe_model('Trasporto')
        if TrasportoModel is not None:
            try:
                tq = db.query(TrasportoModel)
                tq = _filter_date_equals(tq, TrasportoModel.data, giorno)
                for t in tq.all():
                    if (getattr(t, 'ddt_uscita', '') or '').strip():
                        trasporti_set.add((getattr(t, 'ddt_uscita', '') or '').strip())
            except Exception:
                pass
        mancanti_trasporto = [d for d in ddt_set if d not in trasporti_set]
        out.append("<br><b>DDT senza trasporto registrato</b><br>")
        if mancanti_trasporto:
            for d in mancanti_trasporto[:20]:
                out.append(f"• DDT {_esc(d)}<br>")
        else:
            out.append("• Nessun DDT senza trasporto trovato per oggi.<br>")

        return "".join(out)



    def _answer_scan_qr_operativo(msg):
        return (
            "<b>Scan QR operativo pronto.</b><br>"
            "Puoi usare scanner <b>USB</b>, <b>Bluetooth</b> o <b>Wi-Fi</b>.<br>"
            "• USB/Bluetooth: apri la pagina, clicca nel campo e spara il QR.<br>"
            "• Wi-Fi/API: invia il codice a <code>/api/scan_qr_operativo</code>.<br><br>"
            "<a class='btn btn-success btn-sm' href='/scan_qr_operativo'>🔫 Apri Scan QR operativo</a>"
        )


    # ========================================================
    # CAMY OPERATIVA - ricerca libera su tutto il gestionale
    # ========================================================
    def _has_any(text_value, words):
        low_value = (text_value or "").lower()
        return any(w in low_value for w in words)

    def _extract_after_keywords(msg, keywords, max_len=60):
        """Estrae un riferimento dopo parole come buono, ddt, picking, trasporto."""
        s = msg or ""
        keys = sorted([k for k in keywords if k], key=len, reverse=True)
        kw = "|".join(re.escape(k) for k in keys)
        stop = r"(?:cliente|fornitore|arrivo|codice|descrizione|data|oggi|mese|anno|ddt|buono|picking|trasporto|lavorazione)"
        patterns = [
            rf"\b(?:{kw})\b\s*(?:n\.?|numero)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_\- ]{{1,{max_len}}}?)(?=\s+{stop}\b|$)",
            rf"\b(?:{kw})\b\s+([A-Z0-9][A-Z0-9./_\-]{{1,{max_len}}})\b",
        ]
        for pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                val = (m.group(1) or "").strip().strip(".,;:")
                # Evita parole generiche prese come riferimento.
                if val and val.upper() not in {"DA", "DAL", "DEL", "PER", "IL", "LA", "LO", "UN", "UNA", "PRELIEVO", "CARICO", "VEDERE", "MOSTRARE", "APRIRE"}:
                    return val
        return ""

    def _extract_generic_code(msg):
        """Ultima possibilità: prende codici tipo 586-ZETA, 2058377-ENTALPIA, 481/26."""
        s = msg or ""
        candidates = re.findall(r"\b[A-Z0-9]{2,}(?:[./_\-][A-Z0-9]{1,})+\b", s.upper())
        stop = {"CAMY-AI"}
        for c in candidates:
            if c not in stop:
                return c
        m = re.search(r"\b\d{1,5}\s*/\s*\d{2,4}\b", s)
        if m:
            return m.group(0).replace(" ", "")
        return ""

    def _current_month_range():
        import calendar as _calendar
        today = date.today()
        last = _calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), date(today.year, today.month, last)

    def _period_from_message(msg):
        low = (msg or "").lower()
        today = date.today()
        if "oggi" in low:
            return today, today
        if "ieri" in low:
            d = today.fromordinal(today.toordinal() - 1)
            return d, d
        if "mese" in low or "questo mese" in low:
            return _current_month_range()
        da, a = _month_range_from_message(msg)
        d1 = _parse_date_any(da) if da else None
        d2 = _parse_date_any(a) if a else None
        return d1, d2

    def _safe_url(endpoint, fallback, **kwargs):
        try:
            if endpoint in app.view_functions:
                return url_for(endpoint, **kwargs)
        except Exception:
            pass
        return fallback

    def _answer_open_buono_prelievo(db, msg):
        """Mostra un Buono di Prelievo già creato, cioè righe Articolo con buono_n."""
        target = _extract_after_keywords(msg, ["buono di prelievo", "buono prelievo", "buono", "prelievo"]) or _extract_generic_code(msg)
        if not target:
            return "Indicami il numero del Buono di Prelievo da vedere. Esempio: <b>Voglio vedere il buono 586-ZETA</b>."

        q = _base_query(db)
        rows = (
            q.filter(func.upper(func.trim(func.coalesce(Articolo.buono_n, ""))) == target.upper())
             .order_by(Articolo.id_articolo.asc())
             .limit(300)
             .all()
        )
        if not rows:
            rows = (
                q.filter(Articolo.buono_n.ilike(f"%{target}%"))
                 .order_by(Articolo.id_articolo.asc())
                 .limit(300)
                 .all()
            )
        if not rows:
            # Prima di dire che non esiste, controllo anche i buoni QR/carico.
            try:
                return _answer_open_buono_carico(db, msg)
            except Exception:
                pass
            return f"Non ho trovato nessun Buono di Prelievo con riferimento <b>{_esc(target)}</b>."

        buono = str(rows[0].buono_n or target).strip()
        colli = sum(int(getattr(r, "n_colli", 0) or 0) for r in rows)
        peso = sum(float(getattr(r, "peso", 0) or 0) for r in rows)
        cliente = rows[0].cliente or "-"
        fornitore = rows[0].fornitore or "-"
        ordine = rows[0].ordine or "-"
        commessa = rows[0].commessa or "-"
        protocollo = ", ".join([p for p in dict.fromkeys(str(getattr(r, "protocollo", "") or "").strip() for r in rows) if p]) or "-"

        out = [
            f"<b>Buono di Prelievo {_esc(buono)}</b><br>",
            f"Cliente: {_esc(cliente)}<br>",
            f"Fornitore: {_esc(fornitore)}<br>",
            f"Ordine: {_esc(ordine)} | Commessa: {_esc(commessa)} | Protocollo: {_esc(protocollo)}<br>",
            f"Righe: <b>{len(rows)}</b> | Colli: <b>{colli}</b> | Peso: <b>{_esc(_fmt_num(peso))} kg</b><br>",
        ]
        for r in rows[:12]:
            out.append(
                "<div class='camy-ai-result'>"
                f"ID {_esc(r.id_articolo)} | Codice: <b>{_esc(r.codice_articolo or '-')}</b><br>"
                f"Descrizione: {_esc((r.descrizione or '-')[:180])}<br>"
                f"N. arrivo: {_esc(r.n_arrivo or '-')} | Q.tà/Pezzi: {_esc(r.pezzo or r.n_colli or '-')} | Posizione: {_esc(r.posizione or '-')}<br>"
                f"DDT uscita: {_esc(r.n_ddt_uscita or '-')} | Data uscita: {_esc(r.data_uscita or '-')}"
                "</div>"
            )
        if len(rows) > 12:
            out.append(f"<br>Altre righe non mostrate: {len(rows) - 12}.")

        try:
            filename, pdf_path = _generate_buono_pdf(db, buono)
            if filename:
                out.append(f"<br><a class='btn btn-sm btn-success mt-2' href='{_esc(url_for('camy_ai_buono_pdf', filename=filename))}'>Scarica PDF Buono</a>")
        except Exception:
            pass
        if _can_operate():
            out.append(f" <button type='button' class='btn btn-sm btn-outline-primary mt-2' data-camy-fill='Crea DDT dal buono {_esc(buono)}'>Crea DDT da questo Buono</button>")
            out.append(f" <button type='button' class='btn btn-sm btn-outline-warning mt-2' data-camy-fill='Crea picking dal buono {_esc(buono)}'>Crea Picking</button>")
        return "".join(out)

    def _answer_open_buono_carico(db, msg):
        """Mostra un Buono QR/carico se il riferimento è un codice_buono."""
        target = _extract_after_keywords(msg, ["buono qr", "buono carico", "buono", "qr"]) or _extract_generic_code(msg)
        if not target or "BuonoCarico" not in globals():
            return "Indicami il codice del Buono da cercare."
        q = db.query(BuonoCarico)
        if _role() == "client":
            q = q.filter(func.upper(BuonoCarico.cliente) == _current_cliente())
        b = q.filter(func.upper(func.trim(BuonoCarico.codice_buono)) == target.upper()).first()
        if not b:
            b = q.filter(BuonoCarico.codice_buono.ilike(f"%{target}%")).first()
        if not b:
            return f"Non ho trovato nessun Buono QR/Carico con riferimento <b>{_esc(target)}</b>."
        link = _safe_url("dettaglio_buono_carico", f"/buoni_carico/{b.id}", buono_id=b.id)
        return (
            f"<b>Buono QR/Carico {_esc(b.codice_buono)}</b><br>"
            f"Cliente: {_esc(b.cliente or '-')}<br>"
            f"Fornitore: {_esc(b.fornitore or '-')}<br>"
            f"N. arrivo: {_esc(b.n_arrivo or '-')} | DDT: {_esc(b.n_ddt_ingresso or '-')}<br>"
            f"Stato: <b>{_esc(b.stato or '-')}</b><br>"
            f"<a class='btn btn-sm btn-primary mt-2' href='{_esc(link)}'>Apri Buono QR</a>"
        )

    def _answer_search_lavorazioni(db, msg):
        target = _extract_after_keywords(msg, ["picking", "lavorazione", "lavorazioni", "seriale", "seriali", "buono"]) or _extract_generic_code(msg)
        d1, d2 = _period_from_message(msg)
        q = db.query(Lavorazione)
        if _role() == "client":
            q = q.filter(func.upper(Lavorazione.cliente) == _current_cliente())
        if target:
            q = q.filter(or_(
                Lavorazione.seriali.ilike(f"%{target}%"),
                Lavorazione.n_arrivo.ilike(f"%{target}%"),
                Lavorazione.cliente.ilike(f"%{target}%"),
                Lavorazione.richiesta_di.ilike(f"%{target}%"),
                Lavorazione.descrizione.ilike(f"%{target}%"),
            ))
        if d1:
            q = q.filter(Lavorazione.data >= d1)
        if d2:
            q = q.filter(Lavorazione.data <= d2)
        rows = q.order_by(Lavorazione.data.desc(), Lavorazione.id.desc()).limit(30).all()
        if not rows:
            return "Non ho trovato lavorazioni/picking compatibili con la richiesta."
        tot_colli = sum(int(r.colli or 0) for r in rows)
        tot_blue = sum(float(r.ore_blue_collar or 0) for r in rows)
        tot_white = sum(float(r.ore_white_collar or 0) for r in rows)
        out = [f"<b>Picking/Lavorazioni trovate: {len(rows)}</b><br>Colli: {tot_colli} | Ore Blue: {_esc(_fmt_num(tot_blue))} | Ore White: {_esc(_fmt_num(tot_white))}<br>"]
        for r in rows[:15]:
            out.append(
                "<div class='camy-ai-result'>"
                f"Data: {_esc(r.data or '-')} | Cliente: <b>{_esc(r.cliente or '-')}</b><br>"
                f"Descrizione: {_esc(r.descrizione or '-')}<br>"
                f"Richiesta di: {_esc(r.richiesta_di or '-')} | Seriali/Buono: {_esc(r.seriali or '-')}<br>"
                f"N. arrivo: {_esc(r.n_arrivo or '-')} | Colli: {_esc(r.colli or 0)} | Pallet usciti: {_esc(r.pallet_uscita or 0)}"
                "</div>"
            )
        out.append("<br><a class='btn btn-sm btn-outline-primary' href='/lavorazioni'>Apri Picking/Lavorazioni</a>")
        return "".join(out)

    def _answer_search_trasporti(db, msg):
        target = _extract_after_keywords(msg, ["trasporto", "trasporti", "ddt", "trasportatore", "mezzo"]) or _extract_generic_code(msg)
        d1, d2 = _period_from_message(msg)
        q = db.query(Trasporto)
        if _role() == "client":
            q = q.filter(func.upper(Trasporto.cliente) == _current_cliente())
        if target:
            q = q.filter(or_(
                Trasporto.ddt_uscita.ilike(f"%{target}%"),
                Trasporto.cliente.ilike(f"%{target}%"),
                Trasporto.trasportatore.ilike(f"%{target}%"),
                Trasporto.tipo_mezzo.ilike(f"%{target}%"),
                Trasporto.magazzino.ilike(f"%{target}%"),
                Trasporto.consolidato.ilike(f"%{target}%"),
            ))
        if d1:
            q = q.filter(Trasporto.data >= d1)
        if d2:
            q = q.filter(Trasporto.data <= d2)
        rows = q.order_by(Trasporto.data.desc(), Trasporto.id.desc()).limit(30).all()
        if not rows:
            return "Non ho trovato trasporti compatibili con la richiesta."
        costo = sum(float(r.costo or 0) for r in rows)
        out = [f"<b>Trasporti trovati: {len(rows)}</b><br>Costo totale: € {_esc(_fmt_num(costo))}<br>"]
        for r in rows[:15]:
            out.append(
                "<div class='camy-ai-result'>"
                f"Data: {_esc(r.data or '-')} | Mezzo: <b>{_esc(r.tipo_mezzo or '-')}</b><br>"
                f"Cliente: {_esc(r.cliente or '-')} | Trasportatore: {_esc(r.trasportatore or '-')}<br>"
                f"DDT: {_esc(r.ddt_uscita or '-')} | Magazzino: {_esc(r.magazzino or '-')}<br>"
                f"Consolidato: {_esc(r.consolidato or '-')} | Costo: € {_esc(_fmt_num(r.costo))}"
                "</div>"
            )
        out.append("<br><a class='btn btn-sm btn-outline-primary' href='/trasporti'>Apri Trasporti</a>")
        return "".join(out)

    def _answer_global_operational_search(db, msg):
        """Fallback intelligente: cerca lo stesso riferimento in giacenze, buoni, picking e trasporti."""
        ref = _extract_generic_code(msg) or _extract_after_keywords(msg, ["cerca", "vedere", "mostra", "apri", "trova", "dimmi"])
        if not ref:
            return None
        blocks = []
        # Buoni di Prelievo
        rows_b = _base_query(db).filter(Articolo.buono_n.ilike(f"%{ref}%")).limit(5).all()
        if rows_b:
            blocks.append(f"<b>Buoni di Prelievo</b><br>{_answer_open_buono_prelievo(db, 'buono ' + ref)}")
        # Giacenze / DDT / arrivi / codice
        rows_g = _base_query(db).filter(or_(
            Articolo.n_arrivo.ilike(f"%{ref}%"),
            Articolo.codice_articolo.ilike(f"%{ref}%"),
            Articolo.n_ddt_ingresso.ilike(f"%{ref}%"),
            Articolo.n_ddt_uscita.ilike(f"%{ref}%"),
            Articolo.serial_number.ilike(f"%{ref}%"),
        )).order_by(Articolo.id_articolo.desc()).limit(5).all()
        if rows_g:
            blocks.append("<b>Giacenze / Articoli</b><br>" + "".join(_row_html(r) for r in rows_g))
        # Picking
        try:
            rows_l = db.query(Lavorazione).filter(or_(Lavorazione.seriali.ilike(f"%{ref}%"), Lavorazione.n_arrivo.ilike(f"%{ref}%"))).limit(5).all()
            if rows_l:
                blocks.append("<b>Picking/Lavorazioni</b><br>" + _answer_search_lavorazioni(db, "picking " + ref))
        except Exception:
            pass
        # Trasporti
        try:
            rows_t = db.query(Trasporto).filter(Trasporto.ddt_uscita.ilike(f"%{ref}%")).limit(5).all()
            if rows_t:
                blocks.append("<b>Trasporti</b><br>" + _answer_search_trasporti(db, "trasporto " + ref))
        except Exception:
            pass
        if blocks:
            return "<br><hr>".join(blocks)
        return None



    # ============================================================
    # MEMORIA DIALOGO CAMY
    # Conserva una domanda operativa incompleta (per esempio la scelta
    # dell'ID) e collega la risposta successiva alla richiesta originale.
    # ============================================================
    def _camy_dialog_get():
        try:
            data = session.get("camy_dialog") or {}
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _camy_dialog_save(data):
        try:
            payload = dict(data or {})
            payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session["camy_dialog"] = payload
            session.modified = True
        except Exception:
            pass

    def _camy_dialog_clear():
        try:
            session.pop("camy_dialog", None)
            session.modified = True
        except Exception:
            pass

    def _camy_dialog_extract_selected_id(message, candidates):
        """Legge ID 258521, 258521, 'il primo', 'il secondo'."""
        msg = str(message or "").strip()
        ids = []
        for value in candidates or []:
            try:
                ids.append(int(value))
            except Exception:
                pass

        low = msg.lower()
        ordinali = {
            "primo": 0, "prima": 0, "1": 0,
            "secondo": 1, "seconda": 1, "2": 1,
            "terzo": 2, "terza": 2, "3": 2,
            "quarto": 3, "quarta": 3, "4": 3,
            "quinto": 4, "quinta": 4, "5": 4,
        }
        for parola, pos in ordinali.items():
            if re.search(rf"\b(?:il|la)?\s*{re.escape(parola)}\b", low):
                if 0 <= pos < len(ids):
                    return ids[pos]

        m = re.search(r"\b(?:id\s*[:#\-]?\s*)?(\d{4,12})\b", msg, re.I)
        if m:
            try:
                selected = int(m.group(1))
                return selected if selected in ids else None
            except Exception:
                return None
        return None

    def _camy_resolve_open_dialog(message):
        """Completa la richiesta precedente quando CAMY attende una risposta."""
        dialog = _camy_dialog_get()
        if not dialog:
            return None, None

        msg = str(message or "").strip()
        low = msg.lower()

        if low in {"annulla", "annulla operazione", "cancella", "lascia perdere", "stop"}:
            _camy_dialog_clear()
            return "", (
                "Operazione annullata. Ho dimenticato la richiesta in sospeso."
            )

        state = str(dialog.get("state") or "")
        if state == "waiting_id" and dialog.get("operation") == "prepare_buono":
            candidates = dialog.get("candidate_ids") or []
            selected_id = _camy_dialog_extract_selected_id(msg, candidates)
            if selected_id is None:
                elenco = ", ".join(f"ID {x}" for x in candidates[:12])
                return "", (
                    "<b>Sto ancora aspettando la scelta della riga.</b><br>"
                    f"Scrivi uno degli ID proposti: {elenco}.<br>"
                    "Puoi anche scrivere <b>il primo</b>, <b>il secondo</b> oppure <b>annulla</b>."
                )

            original = str(dialog.get("original_message") or "").strip()
            _camy_dialog_clear()
            # L'ID viene aggiunto alla richiesta completa: cliente, codice,
            # quantità e note rimangono quindi disponibili.
            return f"{original} ID {selected_id}", None

        return None, None

    # ============================================================
    # MEMORIA OPERATIVA CAMY
    # Tiene traccia dell'ultimo riferimento usato nella chat, così CAMY
    # può capire frasi come "fammi il buono", "crea il DDT" o "mostrami la foto"
    # riferite all'ultimo arrivo/buono/codice cercato.
    # ============================================================
    def _camy_memory_get():
        try:
            mem = session.get("camy_memory") or {}
            if not isinstance(mem, dict):
                return {}
            return dict(mem)
        except Exception:
            return {}

    def _camy_memory_save(mem):
        try:
            mem = dict(mem or {})
            mem["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session["camy_memory"] = mem
            session.modified = True
        except Exception:
            pass

    def _camy_extract_context(msg):
        """Estrae riferimenti operativi dalla frase dell'utente."""
        ctx = {}
        s = msg or ""
        patterns = [
            ("last_buono", r"\b(?:n\.?\s*)?buono(?:\s+di\s+prelievo)?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9./_\-]{1,50})"),
            ("last_arrivo", r"\b(?:n\.?\s*)?arrivo\s*[:#\-]?\s*([A-Z0-9][A-Z0-9./_\-]{1,50})"),
            ("last_ddt", r"\bddt\s*[:#\-]?\s*([A-Z0-9][A-Z0-9./_\-]{1,50})"),
            ("last_codice", r"\b(?:codice|marca\s+pezzo)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9.*#/\\_\-]{1,60})"),
            ("last_protocollo", r"\b(?:protocollo|prot\.?)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9./_\-]{3,60})"),
            ("last_id", r"\bID\s*[:#\-]?\s*(\d{1,12})\b"),
        ]
        stop = {"ARRIVO", "CODICE", "BUONO", "DDT", "ID", "QUESTO", "QUESTA", "QUELLO", "QUELLA"}
        for key, pat in patterns:
            m = re.search(pat, s, re.I)
            if m:
                val = (m.group(1) or "").strip().strip(".,;:")
                if val and val.upper() not in stop:
                    ctx[key] = val
        try:
            clienti = get_clienti_utenti()
        except Exception:
            clienti = []
        msg_norm = _norm(s)
        for cli in sorted(clienti, key=lambda x: len(_norm(x)), reverse=True):
            if _norm(cli) and _norm(cli) in msg_norm:
                ctx["last_cliente"] = cli
                break
        return ctx

    def _camy_has_explicit_reference(msg):
        ctx = _camy_extract_context(msg)
        return any(ctx.get(k) for k in ("last_buono", "last_arrivo", "last_ddt", "last_codice", "last_protocollo", "last_id", "last_cliente"))

    def _camy_resolve_message_with_memory(msg):
        """Aggiunge il riferimento precedente quando la frase è contestuale."""
        original = msg or ""
        low = original.lower()
        mem = _camy_memory_get()
        if not mem or _camy_has_explicit_reference(original):
            return original, ""

        contextual_words = [
            "questo", "questa", "quello", "quella", "stesso", "stessa", "precedente",
            "ultimo", "ultima", "fallo", "falla", "fammi", "crealo", "creala", "preparalo", "preparala",
            "mandalo", "mandala", "da li", "da lì", "di quello", "di questa", "di questo"
        ]
        looks_contextual = any(w in low for w in contextual_words)

        # Frasi pratiche molto usate: "fammi il buono", "crea il ddt", "mostrami foto".
        if "buono" in low and any(w in low for w in ["fammi", "fai", "crea", "prepara", "genera"]):
            if mem.get("last_arrivo"):
                return original + f" arrivo {mem['last_arrivo']}", f"arrivo {mem['last_arrivo']}"
            if mem.get("last_codice"):
                return original + f" codice {mem['last_codice']}", f"codice {mem['last_codice']}"

        if "ddt" in low and any(w in low for w in ["fammi", "fai", "crea", "prepara", "genera"]):
            if mem.get("last_buono"):
                return original + f" dal buono {mem['last_buono']}", f"buono {mem['last_buono']}"
            if mem.get("last_arrivo"):
                return original + f" arrivo {mem['last_arrivo']}", f"arrivo {mem['last_arrivo']}"

        if ("foto" in low or "pdf" in low or "documento" in low) and mem.get("last_arrivo"):
            return original + f" arrivo {mem['last_arrivo']}", f"arrivo {mem['last_arrivo']}"

        if "scarico" in low and "parziale" in low and mem.get("last_id"):
            return original + f" ID {mem['last_id']}", f"ID {mem['last_id']}"

        if "picking" in low and mem.get("last_buono"):
            return original + f" buono {mem['last_buono']}", f"buono {mem['last_buono']}"

        if looks_contextual:
            if mem.get("last_arrivo"):
                return original + f" arrivo {mem['last_arrivo']}", f"arrivo {mem['last_arrivo']}"
            if mem.get("last_buono"):
                return original + f" buono {mem['last_buono']}", f"buono {mem['last_buono']}"
            if mem.get("last_codice"):
                return original + f" codice {mem['last_codice']}", f"codice {mem['last_codice']}"
        return original, ""

    def _camy_update_memory_from_message(msg, filters=None):
        mem = _camy_memory_get()
        ctx = _camy_extract_context(msg)
        filters = filters or {}
        if filters.get("cliente"):
            ctx["last_cliente"] = filters.get("cliente")
        if filters.get("n_arrivo"):
            ctx["last_arrivo"] = filters.get("n_arrivo")
        if filters.get("codice_articolo"):
            ctx["last_codice"] = filters.get("codice_articolo")
        if filters.get("ddt"):
            ctx["last_ddt"] = filters.get("ddt")
        if ctx:
            mem.update(ctx)
            mem["last_message"] = (msg or "")[:300]
            _camy_memory_save(mem)
        return mem

    def _camy_context_note(used_context):
        if not used_context:
            return ""
        return f"<div class='small text-muted mt-2'>🧠 Ho usato il riferimento precedente: <b>{_esc(used_context)}</b>.</div>"

    def _process_camy_message(db, msg):
        original_msg = msg or ""

        # Prima del parser normale, verifica se CAMY aveva fatto una domanda.
        # Esempio: richiesta Buono -> CAMY chiede ID -> utente risponde solo "258521".
        resolved_dialog_msg, dialog_answer = _camy_resolve_open_dialog(original_msg)
        if dialog_answer is not None:
            return dialog_answer, True, {"action": "dialogo_in_corso"}
        if resolved_dialog_msg:
            original_msg = resolved_dialog_msg

        msg, used_context = _camy_resolve_message_with_memory(original_msg)
        low = (msg or "").lower()
        _camy_update_memory_from_message(msg)

        # ============================================================
        # MANUALE PROCEDURE CAMY
        # Prima di qualunque ricerca/azione, intercetto domande tipo:
        # "come faccio un'entrata", "non ricordo il buono",
        # "procedura DDT", "come mando la mail al cliente".
        # ============================================================
        try:
            if is_procedure_request(original_msg) or is_procedure_request(msg):
                return render_procedure(original_msg or msg), True, {"action": "procedura", "raw": original_msg}
        except Exception as e_proc:
            try:
                scrivi_log_errore("Errore manuale procedure CAMY", e_proc)
            except Exception:
                pass

        # ============================================================
        # CAMY BRAIN - livello decisionale centrale
        # Serve a non trasformare ogni frase in una ricerca di giacenze.
        # Esempio: "ciao come stai" deve ricevere risposta umana,
        # non mostrare 15.000 risultati.
        # ============================================================
        try:
            brain = decide_camy_intent(msg) or {}
        except Exception:
            brain = {}
        brain_action = (brain.get("action") or "").strip().lower()

        if brain_action == "smalltalk":
            return camy_smalltalk_answer(msg), True, brain

        if brain_action == "help":
            return camy_brain_help(), True, brain

        if brain_action == "procedura":
            try:
                return render_procedure(msg), True, brain
            except Exception:
                return render_procedure_index(), True, brain

        if brain_action == "open_buono":
            return _answer_open_buono_prelievo(db, msg), True, brain

        if brain_action == "search_picking":
            return _answer_search_lavorazioni(db, msg), True, brain

        if brain_action == "search_trasporti":
            return _answer_search_trasporti(db, msg), True, brain

        if brain_action == "search_global":
            global_answer = _answer_global_operational_search(db, msg)
            if global_answer:
                return global_answer, True, brain
            return "Ho capito che vuoi cercare un riferimento operativo, ma non ho trovato risultati nel gestionale.", True, brain

        if brain_action == "scan_qr":
            return _answer_scan_qr_operativo(msg), True, brain

        if brain_action == "situazione_operativa":
            return camy_daily_briefing(db, globals(), msg), True, brain

        if brain_action == "registro_giornaliero":
            return _answer_registro_giornaliero(db, msg), True, brain

        if brain_action == "cosa_manca":
            return camy_daily_briefing(db, globals(), msg), True, brain

        if brain_action == "accettazione_entrata":
            return _answer_accettazione_entrata(msg), True, brain

        if brain_action == "prepare_ddt":
            return _answer_prepare_ddt(db, msg), True, brain

        if brain_action == "add_to_buono":
            return _answer_add_to_existing_buono(db, msg), True, brain

        if brain_action == "prepare_buono":
            return _answer_prepare_buono(db, msg), True, brain

        if brain_action == "scarico_parziale":
            return _answer_scarico_parziale(db, msg), True, brain

        # Se CAMY non capisce l'intento e non trova un riferimento operativo,
        # chiede chiarimento invece di lanciare una ricerca enorme.
        if brain_action in ("fallback", "") and not (brain.get("target") or "").strip():
            parole_operative = ["giacenza", "giacenze", "buono", "ddt", "picking", "lavorazione", "trasporto", "arrivo", "codice", "cliente", "foto", "pdf", "registro", "quaderno", "dogana"]
            if not any(p in low for p in parole_operative):
                return "Ho capito il messaggio, ma non è una richiesta operativa del gestionale. Dimmi se vuoi cercare giacenze, buoni, DDT, picking, trasporti, entrate o report.", True, brain

        view_words = ["vedere", "vedi", "mostra", "mostrami", "aprire", "apri", "visualizza", "fammi vedere", "voglio vedere", "cerca", "trova"]
        create_words = ["crea", "creare", "prepara", "preparare", "genera", "generare", "aggiungi", "scarico", "scarica"]

        # Prima distinzione fondamentale: vedere/aprire un buono già creato NON deve diventare crea/prepara buono.
        if "buono" in low and _has_any(low, view_words) and not _has_any(low, create_words):
            return _answer_open_buono_prelievo(db, msg), True, {"action":"apri_buono"}

        if ("picking" in low or "lavorazione" in low or "lavorazioni" in low) and (_has_any(low, view_words) or "oggi" in low or "mese" in low or _extract_generic_code(msg)):
            return _answer_search_lavorazioni(db, msg), True, {"action":"cerca_picking"}

        if ("trasporto" in low or "trasporti" in low or "trasportatore" in low) and (_has_any(low, view_words) or "oggi" in low or "mese" in low or _extract_generic_code(msg)):
            return _answer_search_trasporti(db, msg), True, {"action":"cerca_trasporti"}

        if _has_any(low, view_words) and _extract_generic_code(msg):
            global_answer = _answer_global_operational_search(db, msg)
            if global_answer:
                return global_answer, True, {"action":"ricerca_operativa_globale"}

        if any(x in low for x in ["scanner", "scan qr", "scansione qr", "pistola", "lettore qr", "prelievo qr", "wifi qr"]):
            return _answer_scan_qr_operativo(msg), True, {"action":"scan_qr_operativo"}

        photo_answer = _answer_arrivo_photos(db, msg)
        if photo_answer is not None:
            return photo_answer, True, {}

        if any(x in low for x in ["accettazione entrata", "apri entrata", "nuova entrata", "nuovo arrivo", "carica documento entrata", "documento entrata", "crea entrata"]):
            return _answer_accettazione_entrata(msg), True, {"action":"accettazione_entrata"}

        if any(x in low for x in ["come siamo messi", "situazione operativa", "situazione di oggi", "quadro giornata", "briefing", "punto della situazione", "dashboard operativa"]):
            return camy_daily_briefing(db, globals(), msg), True, {"action":"situazione_operativa"}

        if any(x in low for x in ["registro giornaliero", "registro di oggi", "quaderno", "aggiorna quaderno", "genera registro", "riepilogo giornata", "riepilogo di oggi"]):
            return _answer_registro_giornaliero(db, msg), True, {"action":"registro_giornaliero"}

        if any(x in low for x in ["cosa manca", "manca da fare", "attivita aperte", "attività aperte", "controlla aperti", "controlla anomalie", "cosa devo spedire", "spedire oggi", "senza foto", "foto mancanti", "senza mezzo", "mezzo mancante", "senza protocollo", "protocollo mancante", "oltre 180 giorni", "buoni aperti"]):
            return camy_daily_briefing(db, globals(), msg), True, {"action":"cosa_manca_oggi"}

        if any(x in low for x in ["aiuto", "help", "cosa puoi fare", "cosa sai fare"]):
            return _answer_help(), True, {}

        if any(x in low for x in ["confronta inventario", "inventario"]):
            return _answer_confronta_inventario_camy(msg), True, {}

        if any(x in low for x in ["report excel", "crea report", "scarica excel", "esporta excel", "excel giacenze"]):
            return _answer_report_excel(db, msg), True, {}

        if any(x in low for x in ["crea ddt", "prepara ddt", "genera ddt"]):
            return _answer_prepare_ddt(db, msg), True, {}

        if "picking" in low and "buono" in low:
            return _answer_crea_picking_da_buono(db, msg), True, {"action":"crea_picking_da_buono"}

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
                initial_answer, _, filters = _process_camy_message(db, q)
                try:
                    _camy_update_memory_from_message(q, filters if isinstance(filters, dict) else {})
                except Exception:
                    pass
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
            try:
                _camy_update_memory_from_message(msg, filters if isinstance(filters, dict) else {})
            except Exception:
                pass
            return jsonify({"answer": answer, "html": is_html, "filters": filters, "memory": _camy_memory_get()})
        except Exception as e:
            try:
                scrivi_log_errore("Errore CAMY AI", e)
            except Exception:
                pass
            return jsonify({"answer": "CAMY AI ha avuto un errore. Ho registrato il dettaglio nei log admin.", "html": False}), 500
        finally:
            db.close()
