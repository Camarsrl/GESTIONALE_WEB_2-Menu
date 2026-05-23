# -*- coding: utf-8 -*-
"""
Modulo Chatbot Gestionale Camar.

Prima versione sicura:
- risponde sui dati del database Articolo
- rispetta il ruolo dell'utente loggato
- i clienti vedono solo le proprie giacenze
- non usa servizi esterni: nessun costo API
"""


def register_chatbot_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    from datetime import datetime, date
    from flask import request, jsonify, render_template_string, session
    from flask_login import login_required, current_user
    from sqlalchemy import or_, func

    CHATBOT_HTML = """
    {% extends "base.html" %}
    {% block content %}
    <style>
      .chat-card { max-width: 980px; margin: 20px auto; }
      .chat-box { height: 58vh; overflow-y: auto; background: #f8f9fa; border: 1px solid #ddd; border-radius: 12px; padding: 15px; }
      .msg { margin: 8px 0; display: flex; }
      .msg.user { justify-content: flex-end; }
      .bubble { max-width: 78%; padding: 10px 12px; border-radius: 14px; white-space: pre-wrap; }
      .msg.user .bubble { background: #0d6efd; color: white; border-bottom-right-radius: 4px; }
      .msg.bot .bubble { background: white; border: 1px solid #e2e2e2; border-bottom-left-radius: 4px; }
      .quick button { margin: 3px; }
    </style>

    <div class="container-fluid">
      <div class="card shadow-sm chat-card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>
            <h5 class="mb-0">🤖 Chat gestionale</h5>
            <small class="text-muted">Puoi chiedere giacenze, arrivi, DDT, colli, peso, M2, posizione.</small>
          </div>
          <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Home</a>
        </div>

        <div class="card-body">
          <div class="quick mb-2">
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Quante giacenze ho ancora in magazzino?')">Giacenze attive</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Totale colli e peso in giacenza')">Totale colli/peso</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Cerca n arrivo')">Cerca N. arrivo</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Cerca codice articolo')">Cerca codice articolo</button>
          </div>

          <div id="chatBox" class="chat-box mb-3">
            <div class="msg bot"><div class="bubble">Ciao, sono il chatbot del gestionale. Scrivimi ad esempio:\n• cerca ARRIVO 24/25\n• cerca codice ABC123\n• quante giacenze Fincantieri\n• totale colli e peso in giacenza\n• dove si trova il codice ABC123</div></div>
          </div>

          <div class="input-group">
            <input id="chatInput" type="text" class="form-control" placeholder="Scrivi una domanda..." onkeydown="if(event.key==='Enter'){sendMsg();}">
            <button class="btn btn-primary" onclick="sendMsg()">Invia</button>
          </div>
        </div>
      </div>
    </div>

    <script>
      function addMsg(text, who){
        const box = document.getElementById('chatBox');
        const row = document.createElement('div');
        row.className = 'msg ' + who;
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.textContent = text;
        row.appendChild(bubble);
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
      }
      function askQuick(text){
        document.getElementById('chatInput').value = text;
        sendMsg();
      }
      async function sendMsg(){
        const input = document.getElementById('chatInput');
        const text = input.value.trim();
        if(!text) return;
        input.value = '';
        addMsg(text, 'user');
        addMsg('Sto cercando...', 'bot');
        const box = document.getElementById('chatBox');
        const loading = box.lastChild;
        try{
          const res = await fetch('{{ url_for('chatbot_api') }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text})
          });
          const data = await res.json();
          loading.remove();
          addMsg(data.answer || 'Non ho trovato una risposta.', 'bot');
        }catch(e){
          loading.remove();
          addMsg('Errore durante la ricerca. Riprova o controlla i log admin.', 'bot');
        }
      }
    </script>
    {% endblock %}
    """

    def _user_role():
        try:
            return session.get("role") or getattr(current_user, "role", "") or ""
        except Exception:
            return ""

    def _base_query(db):
        q = db.query(Articolo)
        # I clienti vedono solo i propri dati. Admin e magazzino vedono tutto.
        if _user_role() == "client":
            cliente = (getattr(current_user, "id", "") or "").strip().upper()
            q = q.filter(func.upper(Articolo.cliente) == cliente)
        return q

    def _active_filter(q):
        return q.filter((Articolo.data_uscita == None) | (Articolo.data_uscita == ""))

    def _extract_search_text(msg):
        s = (msg or "").strip()
        s = re.sub(r"\b(cerca|trova|dove si trova|dove|codice articolo|codice|n\.?\s*arrivo|arrivo|ddt|cliente|fornitore|posizione)\b", " ", s, flags=re.I)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _fmt_num(v, dec=2):
        try:
            return f"{float(v or 0):.{dec}f}".replace('.', ',')
        except Exception:
            return "0"

    def _fmt_row(a):
        stato = "USCITO" if (a.data_uscita or "").strip() else "IN GIACENZA"
        return (
            f"ID {a.id_articolo} | {stato}\n"
            f"Cliente: {a.cliente or '-'}\n"
            f"Fornitore: {a.fornitore or '-'}\n"
            f"Codice: {a.codice_articolo or '-'}\n"
            f"Descrizione: {(a.descrizione or '-')[:120]}\n"
            f"N. arrivo: {a.n_arrivo or '-'} | DDT ingresso: {a.n_ddt_ingresso or '-'}\n"
            f"Colli: {a.n_colli or 0} | Peso: {_fmt_num(a.peso)} | M2: {_fmt_num(a.m2)} | M3: {_fmt_num(a.m3)}\n"
            f"Magazzino: {a.magazzino or '-'} | Posizione: {a.posizione or '-'}"
        )

    def _answer_totals(db, msg):
        q = _active_filter(_base_query(db))
        msg_u = (msg or "").upper()

        # filtro cliente testuale per admin/magazzino, senza toccare client.
        if _user_role() != "client":
            for cli in get_clienti_utenti():
                if cli and cli.upper() in msg_u:
                    q = q.filter(func.upper(Articolo.cliente) == cli.upper())
                    break

        rec = q.with_entities(
            func.count(Articolo.id_articolo),
            func.coalesce(func.sum(Articolo.n_colli), 0),
            func.coalesce(func.sum(Articolo.peso), 0),
            func.coalesce(func.sum(Articolo.m2), 0),
            func.coalesce(func.sum(Articolo.m3), 0),
        ).first()
        righe, colli, peso, m2, m3 = rec or (0, 0, 0, 0, 0)
        return (
            f"Situazione giacenze attive:\n"
            f"• Righe: {int(righe or 0)}\n"
            f"• Colli: {int(colli or 0)}\n"
            f"• Peso totale: {_fmt_num(peso)} kg\n"
            f"• M2 totali: {_fmt_num(m2)}\n"
            f"• M3 totali: {_fmt_num(m3)}"
        )

    def _answer_search(db, msg):
        term = _extract_search_text(msg)
        if not term or len(term) < 2:
            return "Scrivimi cosa devo cercare, ad esempio: cerca ARRIVO 24/25 oppure cerca codice ABC123."

        like = f"%{term}%"
        q = _base_query(db).filter(or_(
            Articolo.codice_articolo.ilike(like),
            Articolo.descrizione.ilike(like),
            Articolo.n_arrivo.ilike(like),
            Articolo.n_ddt_ingresso.ilike(like),
            Articolo.n_ddt_uscita.ilike(like),
            Articolo.cliente.ilike(like),
            Articolo.fornitore.ilike(like),
            Articolo.serial_number.ilike(like),
            Articolo.lotto.ilike(like),
            Articolo.posizione.ilike(like),
            Articolo.codice_entrata.ilike(like),
        ))

        # Se chiede giacenza, preferisco righe ancora presenti.
        if any(w in (msg or "").lower() for w in ["giacenza", "magazzino", "present", "ancora"]):
            q = _active_filter(q)

        rows = q.order_by(Articolo.id_articolo.desc()).limit(8).all()
        if not rows:
            return f"Non ho trovato risultati per: {term}"
        out = [f"Ho trovato {len(rows)} risultato/i (mostro massimo 8):"]
        for a in rows:
            out.append(_fmt_row(a))
        return "\n\n".join(out)

    def _answer_help():
        return (
            "Posso aiutarti a cercare nel gestionale. Prova con:\n"
            "• cerca ARRIVO 24/25\n"
            "• cerca DDT 123\n"
            "• cerca codice ABC123\n"
            "• dove si trova ABC123\n"
            "• quante giacenze ho ancora in magazzino\n"
            "• totale colli e peso in giacenza"
        )

    @app.route("/chatbot", methods=["GET"])
    @login_required
    def chatbot():
        return render_template_string(CHATBOT_HTML)

    @app.route("/chatbot/api", methods=["POST"])
    @login_required
    def chatbot_api():
        data = request.get_json(silent=True) or {}
        msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"answer": "Scrivi una domanda."})

        db = SessionLocal()
        try:
            low = msg.lower()
            if any(w in low for w in ["aiuto", "help", "cosa puoi fare"]):
                answer = _answer_help()
            elif any(w in low for w in ["quanto", "quanti", "totale", "somma", "peso", "m2", "m3", "colli"]):
                answer = _answer_totals(db, msg)
            else:
                answer = _answer_search(db, msg)
            return jsonify({"answer": answer})
        except Exception as e:
            try:
                scrivi_log_errore("Errore chatbot", e)
            except Exception:
                pass
            return jsonify({"answer": "Si è verificato un errore nella ricerca. Ho registrato l'errore nei log admin."}), 500
        finally:
            db.close()
