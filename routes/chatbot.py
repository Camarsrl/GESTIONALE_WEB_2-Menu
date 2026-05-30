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
            <h5 class="mb-0">🤖 CAMY - Assistente gestionale</h5>
            <small class="text-muted">Puoi chiedere giacenze, arrivi, DDT, colli, peso, M2 e guide operative.</small>
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
            <button class="btn btn-sm btn-outline-primary" onclick="fillQuick('Cerca ARRIVO ')">Cerca N. arrivo</button>
            <button type="button" class="btn btn-sm btn-outline-warning" onclick="showPreparaBuonoForm()">Prepara Buono</button>
            <button class="btn btn-sm btn-outline-success" onclick="askQuick('Come creo un DDT?')">Guida DDT</button>
            <button class="btn btn-sm btn-outline-success" onclick="askQuick('Come faccio un buono QR?')">Guida Buono QR</button>
            <button class="btn btn-sm btn-outline-success" onclick="askQuick('Come stampo una etichetta?')">Guida Etichette</button>
          </div>

          <div id="camyBuonoForm" class="border border-warning rounded p-3 mb-2" style="display:none; background:#fffdf2;">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <b>Prepara Buono di Prelievo guidato</b>
              <button type="button" class="btn btn-sm btn-outline-secondary" onclick="hidePreparaBuonoForm()">Chiudi</button>
            </div>
            <div class="row g-2 align-items-end">
              <div class="col-md-2">
                <label class="form-label small mb-1">Cliente</label>
                <input id="camyCliente" class="form-control form-control-sm" placeholder="FINCANTIERI">
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-1">Codice articolo</label>
                <input id="camyCodice" class="form-control form-control-sm" placeholder="CB050CF">
              </div>
              <div class="col-md-3">
                <label class="form-label small mb-1">Descrizione</label>
                <input id="camyDescrizione" class="form-control form-control-sm" placeholder="Descrizione corretta">
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-1">N. arrivo</label>
                <input id="camyArrivo" class="form-control form-control-sm" placeholder="200/26">
              </div>
              <div class="col-md-1">
                <label class="form-label small mb-1">Pezzi</label>
                <input id="camyPezzi" class="form-control form-control-sm" type="number" min="1" value="1">
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-1">N. buono</label>
                <input id="camyBuono" class="form-control form-control-sm" placeholder="073-FADEM">
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-1">Package/Cassa</label>
                <input id="camyPackage" class="form-control form-control-sm" placeholder="1">
              </div>
              <div class="col-md-1 d-grid">
                <button type="button" class="btn btn-warning btn-sm" onclick="submitPreparaBuonoForm()">Prepara</button>
              </div>
            </div>
            <small class="text-muted">CAMY prepara una proposta per Buono di Prelievo. I colli non vengono divisi.</small>
          </div>

          <div id="chatBox" class="chat-box mb-3">
            <div class="msg bot"><div class="bubble">Ciao, sono CAMY, l’assistente del gestionale. Scrivimi ad esempio:<br>• quante giacenze DE WAVE SAMA<br>• totale colli e peso in giacenza<br>• entrate oggi<br>• uscite oggi<br>• cerca ARRIVO seguito dal numero<br>• dove si trova il codice ABC123<br>• come creo un DDT?<br>• come faccio un buono QR?<br>• come stampo una etichetta?</div></div>
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

      function showPreparaBuonoForm(){
        const form = document.getElementById('camyBuonoForm');
        if(form){ form.style.display = 'block'; }
        const cliente = document.getElementById('camyCliente');
        if(cliente){ cliente.focus(); }
      }
      function hidePreparaBuonoForm(){
        const form = document.getElementById('camyBuonoForm');
        if(form){ form.style.display = 'none'; }
      }
      function _camyVal(id){
        const el = document.getElementById(id);
        return el ? el.value.trim() : '';
      }
      function submitPreparaBuonoForm(){
        const cliente = _camyVal('camyCliente');
        const codice = _camyVal('camyCodice');
        const descrizione = _camyVal('camyDescrizione');
        const arrivo = _camyVal('camyArrivo');
        const pezzi = _camyVal('camyPezzi') || '1';
        const buono = _camyVal('camyBuono');
        const pack = _camyVal('camyPackage');
        if(!codice || !arrivo){
          addMsg('Per preparare il buono devi inserire almeno Codice articolo e N. arrivo.', 'bot');
          return;
        }
        let msg = `CAMY prepara buono codice ${codice}`;
        if(descrizione) msg += ` descrizione ${descrizione}`;
        msg += ` arrivo ${arrivo} pezzi ${pezzi}`;
        if(cliente) msg += ` cliente ${cliente}`;
        if(buono) msg += ` buono ${buono}`;
        if(pack) msg += ` package ${pack}`;
        document.getElementById('chatInput').value = msg;
        hidePreparaBuonoForm();
        sendMsg();
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
      async function confirmCamyBuono(token){
        if(!token) return;
        const loading = addMsg('Confermo e aggiorno il buono...', 'bot');
        try{
          const res = await fetch('{{ url_for('chatbot_buono_conferma') }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: token})
          });
          const data = await res.json();
          loading.remove();
          addMsg(data.answer || 'Operazione completata.', 'bot', !!data.html);
        }catch(e){
          loading.remove();
          addMsg('CAMY non è riuscita a confermare il buono. Controlla i log admin.', 'bot');
        }
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
          addMsg('CAMY ha avuto un errore durante la ricerca. Riprova o controlla i log admin.', 'bot');
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

    def _strip_cliente_from_term(term, cliente):
        """Toglie dal testo di ricerca il nome cliente già riconosciuto.
        Esempio: '24/26 FINCANTIERI' diventa '24/26', così il filtro cliente
        e il filtro N. arrivo lavorano separati.
        """
        s = (term or "").strip()
        if not s or not cliente:
            return s
        variants = set(_cliente_aliases(cliente))
        variants.add(cliente)
        for v in list(variants):
            nv = _norm_txt(v)
            if nv:
                variants.add(nv)
        for v in sorted(variants, key=len, reverse=True):
            if not v:
                continue
            s = re.sub(re.escape(v), " ", s, flags=re.I)
        s = re.sub(r"\s+", " ", s).strip(" -")
        return s

    def _is_arrivo_request(msg):
        low = (msg or "").lower()
        return bool(re.search(r"\b(n\.?\s*)?arrivo\b", low))

    def _apply_arrivo_filter(q, term):
        """Filtro robusto per N. arrivo: confronta sia testo normale sia testo normalizzato."""
        raw = (term or "").strip()
        if not raw:
            return q
        norm = _norm_txt(raw)
        col_norm = _sql_norm_col(Articolo.n_arrivo)
        conditions = [Articolo.n_arrivo.ilike(f"%{raw}%")]
        if norm:
            conditions.append(col_norm.ilike(f"%{norm}%"))
        return q.filter(or_(*conditions))

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
        q_base, cliente = _apply_cliente_if_present(_base_query(db), msg)
        term = _extract_search_text(msg)
        term = _strip_cliente_from_term(term, cliente)

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

        if _is_arrivo_request(msg):
            q = _apply_arrivo_filter(q_base, term)
            rows = q.order_by(Articolo.id_articolo.desc()).limit(5).all()
            if not rows:
                dettaglio = f"{term}"
                if cliente:
                    dettaglio += f" - {cliente}"
                return f"Non ho trovato arrivi per: {_esc(dettaglio)}"
            titolo = f"<b>Arrivo {_esc(term)}</b>"
            if cliente:
                titolo += f" - {_esc(cliente)}"
            out = [titolo + " (mostro massimo 5):"]
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


    def _answer_guida_operativa(msg):
        """Risposte guida passo-passo per usare il gestionale."""
        low = (msg or "").lower()

        if any(w in low for w in ["ddt", "documento di trasporto", "uscita merce", "scaricare merce", "scarico merce"]):
            return (
                "<b>Guida DDT / uscita merce</b><br>"
                "1. Vai in <b>Giacenze</b>.<br>"
                "2. Cerca il cliente, il codice articolo, il N. arrivo oppure il DDT ingresso.<br>"
                "3. Seleziona la riga o le righe da scaricare.<br>"
                "4. Clicca su <b>Crea DDT</b> o <b>Finalizza DDT</b>, in base alla procedura disponibile.<br>"
                "5. Controlla destinatario, colli, peso, data uscita, mezzo e numero DDT.<br>"
                "6. Conferma/finalizza solo dopo aver verificato i dati.<br><br>"
                "Per sicurezza, CAMY può guidarti, ma la finalizzazione deve sempre essere controllata da un operatore."
            )

        if any(w in low for w in ["buono qr", "buoni qr", "buono di carico", "qr"]):
            return (
                "<b>Guida Buono QR</b><br>"
                "1. Vai nella sezione <b>Buoni QR</b>.<br>"
                "2. Crea un nuovo buono oppure apri un buono esistente.<br>"
                "3. Aggiungi gli articoli/arrivi da caricare.<br>"
                "4. Durante il carico, scansiona il QR dei pallet.<br>"
                "5. Il gestionale ti avvisa se un pallet non appartiene al buono selezionato.<br>"
                "6. Alla fine controlla il riepilogo: scansionati, mancanti e non validi."
            )

        if any(w in low for w in ["verifica entrata", "verifico entrata", "entrata", "barcode", "codice entrata"]):
            return (
                "<b>Guida Verifica Entrata / Barcode</b><br>"
                "1. Scansiona o apri il codice entrata/QR.<br>"
                "2. Controlla che le righe collegate siano corrette.<br>"
                "3. Verifica cliente, N. arrivo, DDT ingresso, colli e descrizione.<br>"
                "4. Se ci sono dati provvisori, completa la riga senza modificare il codice entrata.<br>"
                "5. Non cancellare il barcode/QR se devi solo correggere dati descrittivi."
            )

        if any(w in low for w in ["etichetta", "etichette", "stampa", "stampare"]):
            return (
                "<b>Guida Etichette</b><br>"
                "1. Vai nella funzione <b>Etichette</b> o nella sezione collegata all’entrata.<br>"
                "2. Inserisci cliente, fornitore, N. arrivo, data ingresso e colli.<br>"
                "3. Controlla il formato etichetta selezionato.<br>"
                "4. Genera l’anteprima PDF se attiva.<br>"
                "5. Stampa una pagina per collo e verifica che il progressivo sia corretto."
            )

        if any(w in low for w in ["import", "importo", "pdf", "ocr", "excel", "file"]):
            return (
                "<b>Guida Import PDF / Excel</b><br>"
                "1. Vai nella sezione di importazione.<br>"
                "2. Carica il file PDF o Excel del cliente.<br>"
                "3. Controlla l’anteprima dei dati letti dal gestionale.<br>"
                "4. Correggi eventuali campi mancanti prima di confermare.<br>"
                "5. Importa solo dopo aver verificato cliente, codice articolo, colli, peso, DDT e data ingresso."
            )

        if any(w in low for w in ["backup", "salvataggio", "ripristino", "restore"]):
            return (
                "<b>Guida Backup</b><br>"
                "1. Il backup automatico leggero viene controllato dal gestionale in automatico.<br>"
                "2. Dalla pagina admin puoi anche creare un backup manuale.<br>"
                "3. Il backup leggero salva dati/configurazioni senza appesantire con tutti i media.<br>"
                "4. Prima di modifiche importanti è sempre meglio creare un backup manuale."
            )

        if any(w in low for w in ["filtro", "filtri", "cercare", "cerco", "giacenze"]):
            return (
                "<b>Guida ricerca giacenze</b><br>"
                "Puoi cercare per cliente, codice articolo, N. arrivo, DDT, seriale, lotto, fornitore o posizione.<br>"
                "Per vedere solo ciò che è ancora presente, usa il filtro delle giacenze attive o chiedimi: "
                "<i>quante giacenze ha RF-DE WAVE</i>."
            )

        return (
            "<b>Guida gestionale</b><br>"
            "Posso spiegarti come usare le funzioni principali. Prova a chiedere:<br>"
            "• come creo un DDT?<br>"
            "• come faccio un buono QR?<br>"
            "• come verifico un’entrata?<br>"
            "• come stampo un’etichetta?<br>"
            "• come importo un PDF?<br>"
            "• come faccio un backup?"
        )

    def _is_guida_request(msg):
        low = (msg or "").lower()
        parole_guida = [
            "come ", "spiegami", "guida", "istruzioni", "procedura", "cosa devo fare",
            "come faccio", "come creo", "come si fa", "aiutami a", "mi spieghi"
        ]
        argomenti = [
            "ddt", "buono", "qr", "entrata", "etichetta", "etichette", "backup",
            "import", "pdf", "excel", "barcode", "filtro", "giacenze", "stampa"
        ]
        return any(p in low for p in parole_guida) and any(a in low for a in argomenti)


    # ============================================================
    # CAMY OPERATIVA - BUONO CON CONFERMA
    # ============================================================
    def _is_buono_operativo_request(msg):
        low = (msg or "").lower()
        return any(x in low for x in ["prepara buono", "crea buono", "aggiungi al buono", "metti nel buono", "buono per"])

    def _parse_buono_operativo(msg):
        """Estrae i dati principali dal comando CAMY.
        Formato consigliato:
        CAMY prepara buono codice ABC123 descrizione VALVOLA INOX arrivo 87/26 pezzi 1 cliente RF-DE WAVE buono 073/26
        """
        text = (msg or "").strip()

        def rx(pattern):
            m = re.search(pattern, text, flags=re.I)
            return (m.group(1).strip() if m else "")

        codice = rx(r"\bcodice(?:\s+articolo)?\s+(.+?)(?=\s+descrizione\b|\s+descr\b|\s+arrivo\b|\s+n\.\s*arrivo\b|\s+cliente\b|\s+pezzi\b|\s+colli\b|\s+buono\b|\s+package\b|\s+cassa\b|$)")
        descrizione = rx(r"\b(?:descrizione|descr)\s+(.+?)(?=\s+arrivo\b|\s+n\.\s*arrivo\b|\s+codice\b|\s+cliente\b|\s+pezzi\b|\s+colli\b|\s+buono\b|\s+package\b|\s+cassa\b|$)")
        arrivo = rx(r"\b(?:n\.\s*)?arrivo\s+(.+?)(?=\s+codice\b|\s+descrizione\b|\s+descr\b|\s+cliente\b|\s+pezzi\b|\s+colli\b|\s+buono\b|\s+package\b|\s+cassa\b|$)")
        cliente = _detect_cliente(text) or rx(r"\bcliente\s+(.+?)(?=\s+codice\b|\s+descrizione\b|\s+descr\b|\s+arrivo\b|\s+pezzi\b|\s+colli\b|\s+buono\b|$)")
        buono = rx(r"\bbuono\s+((?:BC-)?\d{4}-\d+|BC[-\w]+|\d+)\b")
        package = rx(r"\b(?:package|pkg|cassa)\s+([A-Z0-9\-_/\.]+)")

        pezzi = 1
        m = re.search(r"\bpezzi\s+(\d+)\b", text, flags=re.I)
        if not m:
            m = re.search(r"\bcolli\s+(\d+)\b", text, flags=re.I)
        if m:
            try:
                pezzi = max(1, int(m.group(1)))
            except Exception:
                pezzi = 1

        return {
            "codice": codice.strip(" ,;"),
            "descrizione": descrizione.strip(" ,;"),
            "arrivo": arrivo.strip(" ,;"),
            "cliente": (cliente or "").strip().upper(),
            "buono": buono.strip(),
            "package": package.strip(),
            "pezzi": pezzi,
        }

    def _as_int_safe(v, default=0):
        try:
            s = str(v or "").strip().replace(",", ".")
            if not s:
                return default
            return int(float(s))
        except Exception:
            return default

    def _as_float_safe(v, default=0.0):
        try:
            s = str(v or "").strip().replace(",", ".")
            if not s:
                return default
            return float(s)
        except Exception:
            return default

    def _has_multiple_codes(value):
        txt = (value or "").strip()
        if not txt:
            return False
        # Più codici spesso sono separati da ; / + virgole o a capo.
        return bool(re.search(r"\s*(;|\+|\n|,|\s/\s)\s*", txt))

    def _remove_requested_code(original, requested):
        """Rimuove il codice richiesto lasciando gli altri codici leggibili."""
        original = (original or "").strip()
        requested = (requested or "").strip()
        if not original or not requested:
            return original
        parts = [p.strip() for p in re.split(r"\s*(?:;|\+|\n|,|\s/\s)\s*", original) if p.strip()]
        req_norm = _norm_txt(requested)
        kept = [p for p in parts if _norm_txt(p) != req_norm and req_norm not in _norm_txt(p)]
        if kept:
            return " ; ".join(kept)
        # fallback: rimuove solo il testo del codice
        cleaned = re.sub(re.escape(requested), "", original, flags=re.I)
        cleaned = re.sub(r"\s*(;|,|\+)\s*(;|,|\+)+", "; ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ;,+-/")
        return cleaned or original

    def _split_multi_parts(value):
        """Divide codici/descrizioni multiple mantenendo solo parti non vuote."""
        txt = (value or "").strip()
        if not txt:
            return []
        return [p.strip() for p in re.split(r"\s*(?:;|\+|\n|,|\s/\s)\s*", txt) if p and p.strip()]

    def _has_multiple_descriptions(value):
        return len(_split_multi_parts(value)) > 1

    def _remove_requested_description(original, requested):
        """Rimuove la descrizione richiesta lasciando la descrizione residua corretta.

        Regola di sicurezza:
        se non riesce a calcolare una descrizione residua attendibile, NON lascia il campo vuoto.
        In quel caso mantiene la descrizione originale, così la riga residua resta compilata
        e può essere corretta manualmente.
        """
        original = (original or "").strip()
        requested = (requested or "").strip()
        if not original:
            return ""
        if not requested:
            return original

        parts = _split_multi_parts(original)
        req_norm = _norm_txt(requested)

        # Prima prova: elemento separato uguale alla descrizione scelta.
        kept = [p for p in parts if _norm_txt(p) != req_norm]
        if parts and len(kept) != len(parts):
            residuo = " ; ".join(kept).strip()
            return residuo or original

        # Seconda prova: se la descrizione scelta è contenuta in un elemento multi-descrizione.
        kept = [p for p in parts if req_norm not in _norm_txt(p)]
        if parts and len(kept) != len(parts):
            residuo = " ; ".join(kept).strip()
            return residuo or original

        # Fallback: rimozione testuale semplice, senza distruggere tutta la descrizione.
        cleaned = re.sub(re.escape(requested), "", original, flags=re.I)
        cleaned = re.sub(r"\s*(;|,|\+)\s*(;|,|\+)+", "; ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ;,+-/")
        return cleaned or original

    def _descrizione_residua_da_codice(original_codici, original_descrizione, codice_richiesto, descrizione_richiesta):
        """Calcola la descrizione da lasciare sulla riga residua.

        1) Se la descrizione richiesta è indicata, la rimuove dalla descrizione originale.
        2) Se codice e descrizione hanno lo stesso numero di elementi, usa la stessa posizione
           del codice richiesto per togliere la descrizione corrispondente.
        3) Se il risultato sarebbe vuoto, mantiene la descrizione originale per evitare righe residue
           senza descrizione.
        """
        original_descrizione = (original_descrizione or "").strip()
        if not original_descrizione:
            return ""

        if descrizione_richiesta:
            residuo = _remove_requested_description(original_descrizione, descrizione_richiesta)
            return residuo or original_descrizione

        cod_parts = _split_multi_parts(original_codici)
        desc_parts = _split_multi_parts(original_descrizione)
        req_norm = _norm_txt(codice_richiesto)

        if req_norm and len(cod_parts) > 1 and len(cod_parts) == len(desc_parts):
            remove_idx = None
            for i, c in enumerate(cod_parts):
                cn = _norm_txt(c)
                if cn == req_norm or req_norm in cn:
                    remove_idx = i
                    break
            if remove_idx is not None:
                residuo_parts = [d for i, d in enumerate(desc_parts) if i != remove_idx and d.strip()]
                residuo = " ; ".join(residuo_parts).strip()
                return residuo or original_descrizione

        return original_descrizione

    def _detect_package_from_row(art, codice):
        text = " ".join([
            str(getattr(art, "codice_articolo", "") or ""),
            str(getattr(art, "descrizione", "") or ""),
            str(getattr(art, "note", "") or ""),
            str(getattr(art, "n_arrivo", "") or ""),
        ])
        patterns = [
            r"(?:PACKAGE|PKG|CASSA|CASE|COLLO)\s*[:#\-]?\s*([A-Z0-9\-_/\.]+)",
            r"\bN\.\s*([0-9]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.I)
            if m:
                return m.group(1).strip()
        return ""

    def _find_articolo_per_buono(db, data):
        codice = (data.get("codice") or "").strip()
        descrizione = (data.get("descrizione") or "").strip()
        arrivo = (data.get("arrivo") or "").strip()
        cliente = (data.get("cliente") or "").strip()
        if not codice or not arrivo:
            return [], "Per preparare il buono mi servono sempre <b>codice articolo</b> e <b>N. arrivo</b>."

        code_like = f"%{codice}%"
        descr_like = f"%{descrizione}%" if descrizione else ""

        def _apply_buono_common_filters(q):
            q = q.filter(or_(
                Articolo.codice_articolo.ilike(code_like),
                Articolo.descrizione.ilike(code_like),
                Articolo.note.ilike(code_like)
            ))
            if descrizione:
                q = q.filter(or_(
                    Articolo.descrizione.ilike(descr_like),
                    Articolo.note.ilike(descr_like)
                ))
            q = _apply_arrivo_filter(q, arrivo)
            if cliente and _user_role() != "client":
                alias_norms = sorted({_norm_txt(a) for a in _cliente_aliases(cliente) if _norm_txt(a)})
                if alias_norms:
                    col_norm = _sql_norm_col(Articolo.cliente)
                    q = q.filter(or_(*[col_norm == n for n in alias_norms]))
            return q

        # 1) Prima cerco solo righe ancora attive/in giacenza.
        q = _apply_buono_common_filters(_active_filter(_base_query(db)))
        rows = q.order_by(Articolo.id_articolo.asc()).limit(20).all()
        if rows:
            return rows, ""

        # 2) Se non trovo righe attive, controllo se il codice/arrivo è già uscito.
        #    Così CAMY non risponde più solo "non trovato", ma avvisa che la merce è già stata scaricata.
        q_usciti = _apply_buono_common_filters(_base_query(db)).filter(or_(
            Articolo.data_uscita != None,
            Articolo.data_uscita != "",
            Articolo.n_ddt_uscita != None,
            Articolo.n_ddt_uscita != ""
        ))
        usciti = q_usciti.order_by(Articolo.id_articolo.desc()).limit(5).all()
        if usciti:
            out = [
                f"⚠️ <b>Attenzione: il codice {_esc(codice)} con arrivo {_esc(arrivo)} risulta già uscito.</b><br>",
                "Non preparo il Buono di Prelievo per evitare doppio scarico.<br><br>",
                "<b>Righe trovate già uscite:</b>"
            ]
            for a in usciti:
                out.append(
                    "<div class='bot-result'>"
                    f"ID {_esc(a.id_articolo)} | Cliente: {_esc(a.cliente or '-')}<br>"
                    f"Codice: {_esc(a.codice_articolo or '-')}<br>"
                    f"N. arrivo: {_esc(a.n_arrivo or '-')}<br>"
                    f"Data uscita: {_esc(a.data_uscita or '-')} | DDT uscita: {_esc(a.n_ddt_uscita or '-')}"
                    "</div>"
                )
            return [], "<br>".join(out)

        return [], f"Non ho trovato righe attive con codice <b>{_esc(codice)}</b> e arrivo <b>{_esc(arrivo)}</b>."

    def _trova_buono_chat(db, valore):
        raw = str(valore or "").strip()
        if not raw:
            return None
        try:
            if raw.isdigit():
                b = db.query(BuonoCarico).filter(BuonoCarico.id == int(raw)).first()
                if b:
                    return b
            return db.query(BuonoCarico).filter(func.upper(BuonoCarico.codice_buono) == raw.upper()).first()
        except Exception:
            return None

    def _next_codice_buono_chat(db):
        anno = date.today().year
        prefix = f"BC-{anno}-"
        max_n = 0
        try:
            rows = db.query(BuonoCarico.codice_buono).filter(BuonoCarico.codice_buono.ilike(f"{prefix}%")).all()
            for row in rows:
                codice = row[0] if isinstance(row, (tuple, list)) else getattr(row, "codice_buono", "")
                m = re.search(r"(\d+)$", codice or "")
                if m:
                    max_n = max(max_n, int(m.group(1)))
        except Exception:
            max_n = 0
        return f"{prefix}{max_n + 1:04d}"

    def _add_summary_chat(current, value, sep="; ", limit=1500):
        value = (str(value or "")).strip()
        current = (str(current or "")).strip()
        if not value:
            return current
        parts = [p.strip() for p in current.split(sep) if p.strip()] if current else []
        if value not in parts:
            parts.append(value)
        return sep.join(parts)[:limit]


    def _next_buono_prelievo_chat(db):
        """Prossimo N. Buono di Prelievo per CAMY, coerente con il modulo buono."""
        yy = date.today().strftime("%y")
        max_current_year = 0
        max_any = 0
        try:
            rows = db.query(Articolo.buono_n).filter(Articolo.buono_n != None).all()
        except Exception:
            rows = []
        for row in rows:
            raw = row[0] if isinstance(row, (tuple, list)) else row
            txt = str(raw or "").strip()
            if not txt:
                continue
            m = re.search(r"(\d{1,6})", txt)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            max_any = max(max_any, n)
            if re.search(rf"(?:/|-|\b){re.escape(yy)}\b", txt):
                max_current_year = max(max_current_year, n)
        base = max_current_year or max_any
        return f"{base + 1:03d}/{yy}"

    def _answer_buono_operativo(db, msg):
        if _user_role() not in ("admin", "magazzino"):
            return "CAMY operativa sui buoni è disponibile solo per utenti admin o magazzino."

        data = _parse_buono_operativo(msg)
        rows, err = _find_articolo_per_buono(db, data)
        if err:
            return err
        if len(rows) > 1:
            out = ["Ho trovato più righe compatibili. Per sicurezza non preparo il buono finché non è univoca. Aggiungi anche cliente/package oppure controlla queste righe:"]
            out.extend(_fmt_row_html(r) for r in rows[:5])
            return "<br>".join(out)

        art = rows[0]
        pezzi_req = int(data.get("pezzi") or 1)
        total_pezzi = _as_int_safe(getattr(art, "pezzo", None), 0)
        if total_pezzi <= 0:
            total_pezzi = _as_int_safe(getattr(art, "n_colli", None), 1) or 1
        if pezzi_req > total_pezzi:
            return f"La riga ID {_esc(art.id_articolo)} ha solo {total_pezzi} pezzi/colli disponibili. Non posso prepararne {pezzi_req}."

        descrizione_buono = (data.get("descrizione") or "").strip() or (art.descrizione or "")
        multi_codice = _has_multiple_codes(getattr(art, "codice_articolo", "")) or (_norm_txt(data["codice"]) not in _norm_txt(getattr(art, "codice_articolo", "")))
        multi_descrizione = bool(data.get("descrizione")) and (
            _has_multiple_descriptions(getattr(art, "descrizione", ""))
            or _norm_txt(data.get("descrizione")) != _norm_txt(getattr(art, "descrizione", ""))
        )
        multi = multi_codice or multi_descrizione
        peso_tot = _as_float_safe(getattr(art, "peso", None), 0.0)
        peso_req = round((peso_tot * pezzi_req / total_pezzi), 3) if total_pezzi else peso_tot
        peso_residuo = round(max(0.0, peso_tot - peso_req), 3)
        package = data.get("package") or _detect_package_from_row(art, data.get("codice"))
        codice_buono = data.get("codice") or art.codice_articolo or ""
        if package and package not in codice_buono:
            codice_buono = f"{codice_buono} PACKAGE {package}"

        token = uuid.uuid4().hex
        pending = {
            "action": "buono_operativo_split",
            "articolo_id": int(art.id_articolo),
            "codice": data.get("codice"),
            "codice_buono": codice_buono,
            "descrizione": data.get("descrizione"),
            "descrizione_buono": descrizione_buono,
            "arrivo": data.get("arrivo"),
            "cliente": data.get("cliente") or (art.cliente or ""),
            "buono": data.get("buono"),
            "pezzi_req": pezzi_req,
            "total_pezzi": total_pezzi,
            "peso_req": peso_req,
            "peso_residuo": peso_residuo,
            "package": package,
            "multi": bool(multi),
        }
        session.setdefault("camy_pending", {})
        pend = dict(session.get("camy_pending") or {})
        pend[token] = pending
        session["camy_pending"] = pend
        session.modified = True

        tipo = "split riga" if multi or pezzi_req < total_pezzi else "aggiunta diretta al buono"
        buono_txt = data.get("buono") or "nuovo buono automatico"
        out = [
            f"<b>CAMY ha preparato una proposta buono ({_esc(tipo)})</b><br>",
            f"Cliente: <b>{_esc(pending['cliente'])}</b><br>",
            f"Riga origine: ID <b>{_esc(art.id_articolo)}</b><br>",
            f"Codice richiesto: <b>{_esc(codice_buono)}</b><br>",
            f"Descrizione richiesta: <b>{_esc(descrizione_buono)}</b><br>",
            f"N. arrivo: <b>{_esc(art.n_arrivo)}</b><br>",
            f"Pezzi richiesti: <b>{pezzi_req}</b> su {total_pezzi}<br>",
            f"Peso da assegnare al buono: <b>{_esc(_fmt_num(peso_req))} kg</b><br>",
            f"Peso residuo in giacenza: <b>{_esc(_fmt_num(peso_residuo))} kg</b><br>",
            f"Buono: <b>{_esc(buono_txt)}</b><br><br>",
        ]
        if multi or pezzi_req < total_pezzi:
            residuo_codice = _remove_requested_code(art.codice_articolo, data.get("codice"))
            residuo_descrizione = _descrizione_residua_da_codice(art.codice_articolo, art.descrizione, data.get("codice"), data.get("descrizione"))
            out.append("<b>Cosa farà dopo conferma:</b><br>")
            out.append("• creerà una riga per il buono con il codice e la descrizione richiesti, più il package/cassa se presente;<br>")
            out.append(f"• lascerà in giacenza la riga residua con codice: <b>{_esc(residuo_codice or '-')}</b>;<br>")
            out.append(f"• lascerà in giacenza la descrizione residua: <b>{_esc(residuo_descrizione or '-')}</b>;<br>")
            out.append("• varierà pezzi e peso in proporzione;<br>")
            out.append("• riporterà il numero buono sulla riga inserita nel buono.<br><br>")
        out.append(f"<button class='btn btn-warning btn-sm' onclick=\"confirmCamyBuono('{token}')\">Conferma proposta CAMY</button>")
        return "".join(out)

    def _conferma_buono_operativo(db, token):
        """Conferma CAMY per BUONO DI PRELIEVO.

        Importante:
        - NON crea BuonoCarico / Buono QR.
        - Prepara solo la riga corretta da mandare al normale Buono di Prelievo.
        - Nei parziali i colli NON vengono divisi: il pallet resta sempre 1 collo
          sia sulla riga nuova sia sulla riga residua.
        """
        if _user_role() not in ("admin", "magazzino"):
            return "Operazione non autorizzata."

        pend = dict(session.get("camy_pending") or {})
        data = pend.get(token)
        if not data:
            return "Proposta CAMY non trovata o già confermata. Ripeti il comando."

        art = db.query(Articolo).filter(Articolo.id_articolo == int(data["articolo_id"])).first()
        if not art:
            return "Riga origine non trovata."
        if (art.data_uscita or "").strip() or (art.n_ddt_uscita or "").strip():
            return "La riga risulta già uscita: operazione annullata."

        cliente = validate_cliente_or_raise(data.get("cliente") or art.cliente)
        pezzi_req = int(data.get("pezzi_req") or 1)
        total_pezzi = int(data.get("total_pezzi") or 1)
        peso_req = float(data.get("peso_req") or 0)
        peso_residuo = float(data.get("peso_residuo") or 0)
        codice_buono = data.get("codice_buono") or data.get("codice") or art.codice_articolo or ""
        descrizione_buono = (data.get("descrizione_buono") or data.get("descrizione") or art.descrizione or "").strip()
        n_buono = (data.get("buono") or "").strip() or _next_buono_prelievo_chat(db)
        n_arrivo_base = strip_arrivo_progressivo(art.n_arrivo)
        colli_originali = 1  # CAMY: pallet/collo non divisibile, entrambe le righe restano con colli = 1

        codice_entrata = ensure_codice_entrata(
            getattr(art, "codice_entrata", None),
            n_arrivo=n_arrivo_base or art.n_arrivo,
            n_ddt=art.n_ddt_ingresso,
            data_ingresso=art.data_ingresso,
            cliente=cliente
        )
        if not (getattr(art, "codice_entrata", "") or "").strip():
            art.codice_entrata = codice_entrata

        split_needed = bool(data.get("multi")) or pezzi_req < total_pezzi
        if split_needed:
            residuo_codice = _remove_requested_code(art.codice_articolo, data.get("codice"))
            residuo_descrizione = _descrizione_residua_da_codice(art.codice_articolo, art.descrizione, data.get("codice"), data.get("descrizione"))
            residuo_pezzi = max(0, total_pezzi - pezzi_req)

            # Riga nuova da inserire nel BUONO DI PRELIEVO.
            # NOTA: i colli NON si dividono. Il pallet resta 1 collo anche se si divide il materiale.
            nuova = Articolo(
                codice_articolo=codice_buono,
                descrizione=descrizione_buono,
                cliente=cliente,
                fornitore=art.fornitore,
                magazzino=art.magazzino,
                protocollo=art.protocollo,
                ordine=art.ordine,
                commessa=art.commessa,
                buono_n=n_buono,
                n_arrivo=art.n_arrivo,
                ns_rif=art.ns_rif,
                serial_number=art.serial_number,
                pezzo=str(pezzi_req),
                n_colli=colli_originali,
                peso=peso_req,
                larghezza=art.larghezza,
                lunghezza=art.lunghezza,
                altezza=art.altezza,
                m2=art.m2,
                m3=art.m3,
                posizione=art.posizione,
                stato=art.stato,
                note=((art.note or "") + "\nSplit creato da CAMY per Buono di Prelievo.").strip(),
                mezzi_in_uscita=art.mezzi_in_uscita,
                data_ingresso=art.data_ingresso,
                n_ddt_ingresso=art.n_ddt_ingresso,
                data_uscita="",
                n_ddt_uscita="",
                codice_entrata=codice_entrata,
                lotto=getattr(art, "lotto", None),
            )
            db.add(nuova)
            db.flush()

            # Riga origine: resta in giacenza come residuo, senza il codice richiesto.
            # Anche qui i colli NON si dividono.
            art.codice_articolo = residuo_codice
            art.descrizione = residuo_descrizione
            art.pezzo = str(residuo_pezzi) if residuo_pezzi else ""
            art.n_colli = colli_originali
            art.peso = peso_residuo
            id_articolo_prelievo = nuova.id_articolo
            art_prelievo = nuova
        else:
            # Riga intera: preparo la stessa riga per Buono di Prelievo.
            art.buono_n = n_buono
            if data.get("descrizione"):
                art.descrizione = descrizione_buono
            id_articolo_prelievo = art.id_articolo
            art_prelievo = art

        db.commit()
        pend.pop(token, None)
        session["camy_pending"] = pend
        session.modified = True

        try:
            link = url_for("chatbot_apri_buono_prelievo", art_id=id_articolo_prelievo)
        except Exception:
            link = f"/chatbot/buono_prelievo/apri/{id_articolo_prelievo}"

        return (
            f"<b>Operazione CAMY completata per Buono di Prelievo.</b><br>"
            f"Riga pronta: ID <b>{_esc(id_articolo_prelievo)}</b><br>"
            f"Codice: <b>{_esc(codice_buono)}</b><br>"
            f"Descrizione: <b>{_esc(descrizione_buono)}</b><br>"
            f"Pezzi: <b>{pezzi_req}</b><br>"
            f"Colli: <b>{_esc(getattr(art_prelievo, 'n_colli', '') or '')}</b> (non divisi)<br>"
            f"Peso: <b>{_esc(_fmt_num(peso_req))} kg</b><br>"
            f"<a class='btn btn-sm btn-primary mt-2' href='{_esc(link)}'>Apri Buono di Prelievo</a>"
        )

    @app.route("/chatbot/buono_prelievo/apri/<int:art_id>", methods=["GET"])
    @login_required
    def chatbot_apri_buono_prelievo(art_id):
        """Apre il normale Buono di Prelievo passando l'ID selezionato con POST automatico."""
        return render_template_string("""
        <!doctype html>
        <html lang="it">
        <head>
          <meta charset="utf-8">
          <title>Apro Buono di Prelievo...</title>
        </head>
        <body>
          <form id="f" method="post" action="{{ url_for('buono_preview') }}">
            <input type="hidden" name="ids" value="{{ art_id }}">
          </form>
          <script>document.getElementById('f').submit();</script>
          <p>Apro Buono di Prelievo...</p>
        </body>
        </html>
        """, art_id=art_id)

    def _answer_help():
        return (
            "Sono CAMY e posso aiutarti a cercare nel gestionale. Prova con:<br>"
            "• quante giacenze DE WAVE SAMA<br>"
            "• totale colli e peso in giacenza<br>"
            "• entrate oggi<br>"
            "• uscite oggi<br>"
            ""
            "• cerca ARRIVO seguito dal numero<br>"
            "• cerca DDT 123<br>"
            "• dove si trova ABC123"
        )

    @app.route("/chatbot", methods=["GET"])
    @login_required
    def chatbot():
        return render_template_string(CHATBOT_HTML)


    @app.route("/chatbot/buono/conferma", methods=["POST"])
    @login_required
    def chatbot_buono_conferma():
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        if not token:
            return jsonify({"answer": "Token conferma mancante.", "html": False}), 400
        db = SessionLocal()
        try:
            answer = _conferma_buono_operativo(db, token)
            return jsonify({"answer": answer, "html": True})
        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore conferma buono CAMY", e)
            except Exception:
                pass
            return jsonify({"answer": "Errore durante la conferma CAMY. Ho registrato l'errore nei log admin.", "html": False}), 500
        finally:
            db.close()

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

            if _is_buono_operativo_request(msg):
                answer = _answer_buono_operativo(db, msg)
            elif _is_guida_request(msg):
                answer = _answer_guida_operativa(msg)
            elif any(w in low for w in ["aiuto", "help", "cosa puoi fare"]):
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
