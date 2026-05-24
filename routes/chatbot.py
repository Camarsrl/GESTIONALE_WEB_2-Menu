# -*- coding: utf-8 -*-
"""
Modulo Chatbot Gestionale Camar.

Versione migliorata:
- risponde sui dati del database Articolo
- rispetta il ruolo dell'utente loggato
- i clienti vedono solo le proprie giacenze
- riconosce clienti con nomi simili (es. DE WAVE / DE WAVE SAMA)
- supporta statistiche, ricerche, entrate/uscite oggi, senza posizione
- non usa servizi esterni: nessun costo API
"""


def register_chatbot_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    import html
    from datetime import datetime, date, timedelta
    from flask import request, jsonify, render_template_string, session, url_for
    from flask_login import login_required, current_user
    from sqlalchemy import or_, func

    CHATBOT_HTML = """
    {% extends "base.html" %}
    {% block content %}
    <style>
      .chat-card { max-width: 1050px; margin: 20px auto; }
      .chat-box { height: 60vh; overflow-y: auto; background: #f8f9fa; border: 1px solid #ddd; border-radius: 12px; padding: 15px; scroll-behavior: smooth; }
      .msg { margin: 8px 0; display: flex; }
      .msg.user { justify-content: flex-end; }
      .bubble { max-width: 82%; padding: 10px 12px; border-radius: 14px; white-space: pre-wrap; line-height: 1.35; }
      .msg.user .bubble { background: #0d6efd; color: white; border-bottom-right-radius: 4px; }
      .msg.bot .bubble { background: white; border: 1px solid #e2e2e2; border-bottom-left-radius: 4px; }
      .quick { display:flex; flex-wrap:wrap; gap:6px; }
      .quick button { margin: 0; min-height: 36px; }
      .bot-result { border-top: 1px solid #eee; padding-top: 8px; margin-top: 8px; }
      .bot-result:first-child { border-top: 0; padding-top: 0; margin-top: 0; }
      .bot-link { display:inline-block; margin-top:5px; font-size: 12px; }
      .chat-input-mobile { position: sticky; bottom: 0; background: #fff; padding-top: 8px; }
      @media (max-width: 768px) {
        body { background: #fff; }
        .chat-card { margin: 0; border-radius: 0; min-height: calc(100vh - 56px); }
        .chat-card .card-header { position: sticky; top: 0; z-index: 3; background: #fff; }
        .chat-card .card-body { padding: 10px; display: flex; flex-direction: column; min-height: calc(100vh - 120px); }
        .chat-box { height: calc(100vh - 285px); min-height: 360px; border-radius: 10px; padding: 10px; }
        .bubble { max-width: 92%; font-size: 14px; }
        .quick { overflow-x: auto; flex-wrap: nowrap; padding-bottom: 4px; }
        .quick button { white-space: nowrap; min-height: 42px; font-size: 13px; }
        #chatInput { min-height: 44px; font-size: 16px; }
        .input-group .btn { min-height: 44px; }
      }
    </style>

    <div class="container-fluid">
      <div class="card shadow-sm chat-card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>
            <h5 class="mb-0">🤖 Chat gestionale</h5>
            <small class="text-muted">Puoi chiedere giacenze, arrivi, DDT, colli, peso, M2, posizione.</small>
          </div>
          <div class="d-flex gap-2">
            <button id="installPwaBtn" class="btn btn-outline-primary btn-sm" style="display:none;">Installa</button>
            <a href="{{ url_for('home') }}" class="btn btn-outline-secondary btn-sm">Home</a>
          </div>
        </div>

        <div class="card-body">
          <div class="quick mb-2">
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Quante giacenze ho ancora in magazzino?')">Giacenze attive</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Totale colli e peso in giacenza')">Totale colli/peso</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Entrate oggi')">Entrate oggi</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Uscite oggi')">Uscite oggi</button>
            <button class="btn btn-sm btn-outline-primary" onclick="askQuick('Giacenze senza posizione')">Senza posizione</button>
            <button class="btn btn-sm btn-outline-primary" onclick="fillQuick('Cerca ARRIVO ')">Cerca N. arrivo</button>
          </div>

          <div id="chatBox" class="chat-box mb-3">
            <div class="msg bot"><div class="bubble">Ciao, sono il chatbot del gestionale. Scrivimi ad esempio:<br>• quante giacenze DE WAVE SAMA<br>• totale colli e peso in giacenza<br>• entrate oggi<br>• uscite oggi<br>• giacenze senza posizione<br>• cerca ARRIVO seguito dal numero<br>• dove si trova il codice ABC123</div></div>
          </div>

          <div class="input-group chat-input-mobile">
            <input id="chatInput" type="text" class="form-control" placeholder="Scrivi una domanda..." onkeydown="if(event.key==='Enter'){sendMsg();}">
            <button class="btn btn-primary" onclick="sendMsg()">Invia</button>
          </div>
        </div>
      </div>
    </div>

    <script>

      // Installazione PWA su smartphone/desktop compatibili
      let deferredInstallPrompt = null;
      window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredInstallPrompt = e;
        const btn = document.getElementById('installPwaBtn');
        if (btn) btn.style.display = 'inline-block';
      });
      document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('installPwaBtn');
        if (btn) {
          btn.addEventListener('click', async () => {
            if (!deferredInstallPrompt) return;
            deferredInstallPrompt.prompt();
            await deferredInstallPrompt.userChoice;
            deferredInstallPrompt = null;
            btn.style.display = 'none';
          });
        }
      });
      if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
          navigator.serviceWorker.register('/service-worker.js').catch(() => {});
        });
      }

      function addMsg(text, who, isHtml=false){
        const box = document.getElementById('chatBox');
        const row = document.createElement('div');
        row.className = 'msg ' + who;
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        if(isHtml && who === 'bot'){
          bubble.innerHTML = text;
        } else {
          bubble.textContent = text;
        }
        row.appendChild(bubble);
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
        return row;
      }
      function askQuick(text){
        document.getElementById('chatInput').value = text;
        sendMsg();
      }
      function fillQuick(text){
        const input = document.getElementById('chatInput');
        input.value = text;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      async function sendMsg(){
        const input = document.getElementById('chatInput');
        const text = input.value.trim();
        if(!text) return;
        input.value = '';
        addMsg(text, 'user');
        const loading = addMsg('Sto cercando...', 'bot');
        try{
          const res = await fetch('{{ url_for('chatbot_api') }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text})
          });
          const data = await res.json();
          loading.remove();
          addMsg(data.answer || 'Non ho trovato una risposta.', 'bot', !!data.html);
        }catch(e){
          loading.remove();
          addMsg('Errore durante la ricerca. Riprova o controlla i log admin.', 'bot');
        }
      }
    </script>
    {% endblock %}
    """

    def _esc(v):
        return html.escape(str(v or ""))

    def _user_role():
        try:
            return session.get("role") or getattr(current_user, "role", "") or ""
        except Exception:
            return ""

    def _norm_txt(value):
        s = (value or "").strip().upper()
        return re.sub(r"[^A-Z0-9]+", "", s)

    def _base_query(db):
        q = db.query(Articolo)
        # I clienti vedono solo i propri dati. Admin e magazzino vedono tutto.
        if _user_role() == "client":
            cliente = (getattr(current_user, "id", "") or "").strip().upper()
            q = q.filter(func.upper(Articolo.cliente) == cliente)
        return q

    def _active_filter(q):
        return q.filter((Articolo.data_uscita == None) | (Articolo.data_uscita == ""))

    def _date_values_today():
        today = date.today()
        return [
            today.strftime("%Y-%m-%d"),
            today.strftime("%d/%m/%Y"),
            today.strftime("%d-%m-%Y"),
        ]

    def _cliente_aliases(cliente):
        """Alias per clienti con nomi scritti in modi diversi nel DB o nella domanda."""
        cli = (cliente or "").strip().upper()
        aliases = {cli}
        n = _norm_txt(cli)

        # RF-DE WAVE può comparire scritto anche come RF DE WAVE, RFDEWAVE o DE WAVE RF.
        if n in {"RFDEWAVE", "DEWAVERF"} or ("RF" in n and "DEWAVE" in n):
            aliases.update({
                "RF-DE WAVE", "RF DE WAVE", "RFDEWAVE",
                "DE WAVE RF", "DE-WAVE RF", "DEWAVERF"
            })

        # DE WAVE SAMA deve restare distinto da DE WAVE.
        if n == "DEWAVESAMA":
            aliases.update({"DE WAVE SAMA", "DE-WAVE SAMA", "DEWAVESAMA"})

        # DE WAVE base, ma senza includere SAMA/RF.
        if n == "DEWAVE":
            aliases.update({"DE WAVE", "DE-WAVE", "DEWAVE"})

        return [a for a in aliases if a]

    def _sql_norm_col(col):
        """Normalizza una colonna SQL come _norm_txt: maiuscolo e senza spazi/punteggiatura."""
        expr = func.upper(func.coalesce(col, ""))
        for ch in [" ", "-", "_", "/", "\\", ".", "'"]:
            expr = func.replace(expr, ch, "")
        return expr

    def _detect_cliente(msg):
        """Riconosce il cliente dando priorità ai nomi più lunghi e agli alias.
        Evita confusione tra DE WAVE, DE WAVE SAMA e RF-DE WAVE.
        """
        if _user_role() == "client":
            return (getattr(current_user, "id", "") or "").strip().upper()

        msg_norm = _norm_txt(msg)
        try:
            clienti = list(get_clienti_utenti())
        except Exception:
            clienti = []

        # Aggiungo RF-DE WAVE se per qualche motivo non compare negli utenti.
        if not any(_norm_txt(c) in {"RFDEWAVE", "DEWAVERF"} for c in clienti):
            clienti.append("RF-DE WAVE")

        candidates = []
        for cli in clienti:
            for alias in _cliente_aliases(cli):
                an = _norm_txt(alias)
                if an:
                    candidates.append((len(an), cli.upper(), an))

        candidates.sort(reverse=True)
        for _, cli, alias_norm in candidates:
            if alias_norm and alias_norm in msg_norm:
                return cli
        return ""

    def _apply_cliente_if_present(q, msg):
        cli = _detect_cliente(msg)
        if cli and _user_role() != "client":
            alias_norms = sorted({_norm_txt(a) for a in _cliente_aliases(cli) if _norm_txt(a)})
            if alias_norms:
                col_norm = _sql_norm_col(Articolo.cliente)
                q = q.filter(or_(*[col_norm == n for n in alias_norms]))
            else:
                q = q.filter(func.upper(Articolo.cliente) == cli.upper())
        return q, cli

    def _extract_search_text(msg):
        s = (msg or "").strip()

        # Rimuovo parole di comando, ma lascio il valore cercato.
        patterns = [
            r"\bcerca\b", r"\btrova\b", r"\bdove si trova\b", r"\bdove\b",
            r"\bcodice articolo\b", r"\bcodice\b",
            r"\bn\.?\s*arrivo\b", r"\barrivo\b",
            r"\bddt\b", r"\bcliente\b", r"\bfornitore\b", r"\bposizione\b",
            r"\bmagazzino\b", r"\bgiacenza\b", r"\bgiacenze\b"
        ]
        for pat in patterns:
            s = re.sub(pat, " ", s, flags=re.I)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _fmt_num(v, dec=2):
        try:
            return f"{float(v or 0):.{dec}f}".replace('.', ',')
        except Exception:
            return "0"

    def _fmt_row_html(a):
        stato = "USCITO" if (a.data_uscita or "").strip() else "IN GIACENZA"
        try:
            link = url_for("giacenze", id=str(a.id_articolo))
        except Exception:
            link = "/giacenze"
        return (
            "<div class='bot-result'>"
            f"<b>ID {_esc(a.id_articolo)} | {_esc(stato)}</b><br>"
            f"Cliente: {_esc(a.cliente or '-')}<br>"
            f"Fornitore: {_esc(a.fornitore or '-')}<br>"
            f"Codice: {_esc(a.codice_articolo or '-')}<br>"
            f"Descrizione: {_esc((a.descrizione or '-')[:140])}<br>"
            f"N. arrivo: {_esc(a.n_arrivo or '-')} | DDT ingresso: {_esc(a.n_ddt_ingresso or '-')}<br>"
            f"Colli: {_esc(a.n_colli or 0)} | Peso: {_esc(_fmt_num(a.peso))} kg | M2: {_esc(_fmt_num(a.m2))} | M3: {_esc(_fmt_num(a.m3))}<br>"
            f"Magazzino: {_esc(a.magazzino or '-')} | Posizione: {_esc(a.posizione or '-')}"
            f"<br><a class='bot-link' href='{_esc(link)}'>Apri in Giacenze</a>"
            "</div>"
        )

    def _answer_totals(db, msg):
        q = _active_filter(_base_query(db))
        q, cliente = _apply_cliente_if_present(q, msg)

        rec = q.with_entities(
            func.count(Articolo.id_articolo),
            func.coalesce(func.sum(Articolo.n_colli), 0),
            func.coalesce(func.sum(Articolo.peso), 0),
            func.coalesce(func.sum(Articolo.m2), 0),
            func.coalesce(func.sum(Articolo.m3), 0),
        ).first()
        righe, colli, peso, m2, m3 = rec or (0, 0, 0, 0, 0)

        titolo = "Situazione giacenze attive"
        if cliente:
            titolo += f" - {cliente}"

        return (
            f"<b>{_esc(titolo)}:</b><br>"
            f"• Righe: {int(righe or 0)}<br>"
            f"• Colli: {int(colli or 0)}<br>"
            f"• Peso totale: {_esc(_fmt_num(peso))} kg<br>"
            f"• M2 totali: {_esc(_fmt_num(m2))}<br>"
            f"• M3 totali: {_esc(_fmt_num(m3))}"
        )

    def _answer_today(db, msg, uscita=False):
        q = _base_query(db)
        q, cliente = _apply_cliente_if_present(q, msg)

        vals = _date_values_today()
        col = Articolo.data_uscita if uscita else Articolo.data_ingresso
        q = q.filter(or_(*[col == v for v in vals]))

        rec = q.with_entities(
            func.count(Articolo.id_articolo),
            func.coalesce(func.sum(Articolo.n_colli), 0),
            func.coalesce(func.sum(Articolo.peso), 0),
            func.coalesce(func.sum(Articolo.m2), 0),
            func.coalesce(func.sum(Articolo.m3), 0),
        ).first()
        righe, colli, peso, m2, m3 = rec or (0, 0, 0, 0, 0)
        tipo = "uscite oggi" if uscita else "entrate oggi"
        titolo = f"Merce {tipo}"
        if cliente:
            titolo += f" - {cliente}"

        return (
            f"<b>{_esc(titolo)}:</b><br>"
            f"• Righe: {int(righe or 0)}<br>"
            f"• Colli: {int(colli or 0)}<br>"
            f"• Peso: {_esc(_fmt_num(peso))} kg<br>"
            f"• M2: {_esc(_fmt_num(m2))}<br>"
            f"• M3: {_esc(_fmt_num(m3))}"
        )

    def _answer_senza_posizione(db, msg):
        q = _active_filter(_base_query(db))
        q, cliente = _apply_cliente_if_present(q, msg)
        q = q.filter((Articolo.posizione == None) | (Articolo.posizione == ""))
        rows = q.order_by(Articolo.id_articolo.desc()).limit(5).all()
        total = q.with_entities(func.count(Articolo.id_articolo)).scalar() or 0

        titolo = "Giacenze attive senza posizione"
        if cliente:
            titolo += f" - {cliente}"

        if not rows:
            return f"<b>{_esc(titolo)}:</b><br>Nessuna riga trovata."
        out = [f"<b>{_esc(titolo)}:</b><br>Totale righe: {int(total)}<br>Mostro massimo 5 risultati:"]
        out.extend(_fmt_row_html(a) for a in rows)
        return "<br>".join(out)

    def _answer_search(db, msg):
        term = _extract_search_text(msg)
        q_base, cliente = _apply_cliente_if_present(_base_query(db), msg)

        if not term or len(term) < 2:
            if cliente:
                q = _active_filter(q_base)
                rows = q.order_by(Articolo.id_articolo.desc()).limit(5).all()
                total = q.with_entities(func.count(Articolo.id_articolo)).scalar() or 0
                if not rows:
                    return f"<b>Nessuna giacenza attiva trovata per {_esc(cliente)}.</b>"
                out = [f"<b>Giacenze attive - {_esc(cliente)}</b><br>Totale righe: {int(total)}<br>Mostro massimo 5 risultati:"]
                out.extend(_fmt_row_html(a) for a in rows)
                return "<br>".join(out)
            return "Scrivimi cosa devo cercare, ad esempio: cerca ARRIVO 123/25 oppure cerca codice ABC123."

        term_norm = _norm_txt(term)
        if cliente and term_norm in {_norm_txt(a) for a in _cliente_aliases(cliente)}:
            q = _active_filter(q_base)
            rows = q.order_by(Articolo.id_articolo.desc()).limit(5).all()
            total = q.with_entities(func.count(Articolo.id_articolo)).scalar() or 0
            if not rows:
                return f"<b>Nessuna giacenza attiva trovata per {_esc(cliente)}.</b>"
            out = [f"<b>Giacenze attive - {_esc(cliente)}</b><br>Totale righe: {int(total)}<br>Mostro massimo 5 risultati:"]
            out.extend(_fmt_row_html(a) for a in rows)
            return "<br>".join(out)

        like = f"%{term}%"
        q = q_base.filter(or_(
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

        # Se chiede giacenza/magazzino/presente, preferisco righe ancora presenti.
        if any(w in (msg or "").lower() for w in ["giacenza", "giacenze", "magazzino", "presente", "presenti", "ancora"]):
            q = _active_filter(q)

        rows = q.order_by(Articolo.id_articolo.desc()).limit(5).all()
        if not rows:
            return f"Non ho trovato risultati per: {_esc(term)}"

        out = [f"<b>Ho trovato {len(rows)} risultato/i</b> (mostro massimo 5):"]
        out.extend(_fmt_row_html(a) for a in rows)
        return "<br>".join(out)

    def _answer_help():
        return (
            "Posso aiutarti a cercare nel gestionale. Prova con:<br>"
            "• quante giacenze DE WAVE SAMA<br>"
            "• totale colli e peso in giacenza<br>"
            "• entrate oggi<br>"
            "• uscite oggi<br>"
            "• giacenze senza posizione<br>"
            "• cerca ARRIVO seguito dal numero<br>"
            "• cerca DDT 123<br>"
            "• dove si trova ABC123"
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
            return jsonify({"answer": "Scrivi una domanda.", "html": False})

        db = SessionLocal()
        try:
            low = msg.lower()

            parole_totali = [
                "quanto", "quanti", "quante", "totale", "somma",
                "peso", "m2", "m3", "colli", "pallet", "righe",
                "giacenze", "giacenza", "magazzino", "ancora", "presenti", "attive",
                "cosa ho", "merce in giacenza"
            ]

            if any(w in low for w in ["aiuto", "help", "cosa puoi fare"]):
                answer = _answer_help()
            elif any(w in low for w in ["senza posizione", "manca posizione", "non hanno posizione", "non ha posizione"]):
                answer = _answer_senza_posizione(db, msg)
            elif any(w in low for w in ["uscite oggi", "uscita oggi", "merce uscita oggi"]):
                answer = _answer_today(db, msg, uscita=True)
            elif any(w in low for w in ["entrate oggi", "entrata oggi", "merce entrata oggi", "arrivi oggi"]):
                answer = _answer_today(db, msg, uscita=False)
            elif any(w in low for w in parole_totali):
                answer = _answer_totals(db, msg)
            else:
                answer = _answer_search(db, msg)

            return jsonify({"answer": answer, "html": True})
        except Exception as e:
            try:
                scrivi_log_errore("Errore chatbot", e)
            except Exception:
                pass
            return jsonify({"answer": "Si è verificato un errore nella ricerca. Ho registrato l'errore nei log admin.", "html": False}), 500
        finally:
            db.close()
