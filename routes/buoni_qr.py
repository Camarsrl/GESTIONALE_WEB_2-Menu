# -*- coding: utf-8 -*-
"""
Modulo Buoni di Carico QR.

Questo modulo contiene:
- elenco buoni di carico QR
- creazione buono da righe magazzino
- aggiunta arrivi a buono esistente
- dettaglio buono
- scansione QR
- stampa PDF
- eliminazione buono
- QR immagine

Le route vengono registrate sull'app principale mantenendo gli stessi endpoint.
"""

def register_buoni_qr_routes(app_obj, deps):
    """Registra le route Buoni QR sull'app principale.

    deps = globals() del file principale, così il modulo usa gli stessi modelli,
    sessione DB, helper, template base e funzioni già presenti nel gestionale.
    """
    globals().update(deps)
    globals()["app"] = app_obj

    # Permessi Buoni QR:
    # ADMIN/OPS = role admin, MAGAZZINO = role magazzino, CLIENTI esclusi
    if "require_admin_or_magazzino" not in globals():
        def require_admin_or_magazzino(view_func):
            @wraps(view_func)
            def _wrapped(*args, **kwargs):
                if session.get("role") not in ("admin", "magazzino"):
                    flash("Accesso negato.", "danger")
                    return redirect(url_for("giacenze"))
                return view_func(*args, **kwargs)
            return _wrapped



    # ========================================================
    #  BUONI DI CARICO CON QR COLLEGATO ALL'ARRIVO
    # ========================================================

    BUONI_CARICO_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h3>📦 Buoni di carico QR</h3>
        <a href="{{ url_for('giacenze') }}" class="btn btn-secondary btn-sm">Magazzino</a>
      </div>

      <div class="card shadow-sm mb-3">
        <div class="card-header fw-bold">Nuovo buono di carico</div>
        <div class="card-body">
          <form method="POST" class="row g-2">
            <div class="col-md-3">
              <label class="form-label">Cliente</label>
              <select name="cliente" class="form-select" required>
                <option value="">-- seleziona --</option>
                {% for c in clienti %}
                <option value="{{ c }}">{{ c }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-3">
              <label class="form-label">Fornitore</label>
              <input type="text" name="fornitore" class="form-control">
            </div>
            <div class="col-md-2">
              <label class="form-label">N. arrivo</label>
              <input type="text" name="n_arrivo" class="form-control" required>
            </div>
            <div class="col-md-3">
              <label class="form-label">Codice articolo</label>
              <input type="text" name="codice_articolo" class="form-control">
            </div>
            <div class="col-md-5">
              <label class="form-label">Descrizione</label>
              <input type="text" name="descrizione" class="form-control">
            </div>
            <div class="col-md-2">
              <label class="form-label">DDT ingresso</label>
              <input type="text" name="n_ddt_ingresso" class="form-control">
            </div>
            <div class="col-md-2">
              <label class="form-label">Data ingresso</label>
              <input type="date" name="data_ingresso" value="{{ oggi }}" class="form-control" required>
            </div>
            <div class="col-md-2">
              <label class="form-label">Colli previsti</label>
              <input type="number" min="1" name="pallet_previsti" class="form-control" required>
            </div>
            <div class="col-md-2">
              <label class="form-label">Peso previsto kg</label>
              <input type="text" name="peso_previsto" class="form-control">
            </div>
            <div class="col-md-5">
              <label class="form-label">QR/Codice entrata già esistente</label>
              <input type="text" name="codice_entrata" class="form-control" placeholder="facoltativo ENT-...">
            </div>
            <div class="col-md-3">
              <label class="form-label">Note</label>
              <input type="text" name="note" class="form-control">
            </div>
            <div class="col-12 mt-3">
              <button class="btn btn-success">Crea buono di carico</button>
            </div>
          </form>
        </div>
      </div>

      <div class="card shadow-sm">
        <div class="card-header fw-bold">Buoni creati</div>
        <div class="table-responsive">
          <table class="table table-sm table-striped mb-0 align-middle">
            <thead>
              <tr>
                <th>Buono</th><th>Cliente</th><th>N. arrivo</th><th>DDT</th>
                <th>Previsti</th><th>Caricati</th><th>Mancanti</th><th>Stato</th><th>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {% for b in buoni %}
              <tr>
                <td><strong>{{ b.codice_buono }}</strong></td>
                <td>{{ b.cliente }}</td>
                <td>{{ b.n_arrivo }}</td>
                <td>{{ b.n_ddt_ingresso or '' }}</td>
                <td>{{ b.pallet_previsti or 0 }}</td>
                <td>{{ stats[b.id]['ok'] }}</td>
                <td>{{ stats[b.id]['mancanti'] }}</td>
                <td>
                  <span class="badge {% if b.stato == 'COMPLETATO' %}bg-success{% elif b.stato == 'PARZIALE' %}bg-warning text-dark{% elif b.stato == 'ERRORE' %}bg-danger{% else %}bg-secondary{% endif %}">
                    {{ b.stato or 'DA CARICARE' }}
                  </span>
                </td>
                <td>
                  <a class="btn btn-primary btn-sm" href="{{ url_for('dettaglio_buono_carico', buono_id=b.id) }}">Apri</a>
                  <form method="POST" action="{{ url_for('elimina_buono_carico', buono_id=b.id) }}" style="display:inline;" onsubmit="return confirm('Eliminare questo buono di carico? Assicurati di aver salvato/stampato il PDF.');">
                    <button type="submit" class="btn btn-danger btn-sm">Elimina</button>
                  </form>
                </td>
              </tr>
              {% else %}
              <tr><td colspan="9" class="text-muted">Nessun buono creato.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    {% endblock %}
    """

    BUONO_CARICO_DETTAGLIO_HTML = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="container-fluid py-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h3>📦 Buono di carico {{ buono.codice_buono }}</h3>
        <div>
          <a href="{{ url_for('buoni_carico') }}" class="btn btn-secondary btn-sm">Elenco buoni</a>
          <a href="{{ url_for('stampa_buono_carico_pdf', buono_id=buono.id) }}" class="btn btn-success btn-sm" target="_blank" rel="noopener">🖨️ Stampa buono</a>
          <a href="{{ url_for('giacenze', aggiungi_buono_carico=buono.id) }}" class="btn btn-primary btn-sm">➕ Aggiungi arrivi</a>
          <form method="POST" action="{{ url_for('elimina_buono_carico', buono_id=buono.id) }}" style="display:inline;" onsubmit="return confirm('Eliminare questo buono di carico? Assicurati di aver salvato/stampato il PDF.');">
            <button type="submit" class="btn btn-danger btn-sm">🗑️ Elimina buono</button>
          </form>
          <a href="{{ url_for('giacenze') }}" class="btn btn-outline-secondary btn-sm">Magazzino</a>
        </div>
      </div>

      <div class="row g-3 mb-3">
        <div class="col-md-8">
          <div class="card shadow-sm h-100">
            <div class="card-header fw-bold">Dati buono</div>
            <div class="card-body">
              <div class="row g-2">
                <div class="col-md-3"><strong>Cliente</strong><br>{{ buono.cliente }}</div>
                <div class="col-md-3"><strong class="buono-wrap-text">Fornitore</strong><br>{{ buono.fornitore or '-' }}</div>
                <div class="col-md-3"><span style="white-space:pre-wrap;word-break:break-word;"><strong>Codice articolo</strong><br>{{ buono.codice_articolo or '-' }}</span></div>
                <div class="col-md-3"><strong>Descrizione</strong><br>{{ buono.descrizione or '-' }}</div>
                <div class="col-md-2 mt-3"><strong>N. arrivo</strong><br>{{ buono.n_arrivo }}</div>
                <div class="col-md-2"><strong>DDT</strong><br>{{ buono.n_ddt_ingresso or '-' }}</div>
                <div class="col-md-2"><strong>Data</strong><br>{{ buono.data_ingresso or '-' }}</div>
                <div class="col-md-3 mt-3"><strong>Colli previsti</strong><br>{{ buono.pallet_previsti or 0 }}</div>
                <div class="col-md-3 mt-3"><strong>Colli caricati</strong><br>{{ caricati_ok }}</div>
                <div class="col-md-3 mt-3"><strong>Mancanti</strong><br>{{ mancanti }}</div>
                <div class="col-md-3 mt-3"><strong>Stato</strong><br>{{ buono.stato or 'DA CARICARE' }}</div>
              </div>
              <hr>
              <strong>QR/Codice entrata corretto:</strong><br>
              <code>{{ buono.codice_entrata }}</code>
              {% if mancanti > 0 %}
              <div class="alert alert-warning mt-3 mb-0">Mancano ancora <strong>{{ mancanti }}</strong> colli da caricare/scansionare.</div>
              {% else %}
              <div class="alert alert-success mt-3 mb-0">Tutti i colli previsti risultano caricati.</div>
              {% endif %}
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card shadow-sm h-100 text-center">
            <div class="card-header fw-bold">QR arrivo</div>
            <div class="card-body">
              <img src="{{ url_for('qr_buono_carico', buono_id=buono.id) }}" style="max-width:220px;width:100%;height:auto;">
              <div class="small text-muted mt-2">QR collegato all'arrivo corretto.</div>
            </div>
          </div>
        </div>
      </div>


  
      <div class="card shadow-sm mb-3">
        <div class="card-header fw-bold">Riepilogo controllo scansioni</div>
        <div class="card-body">
          <div class="row g-3">
            <div class="col-md-6">
              <div class="alert alert-warning mb-0">
                <strong>Arrivi non ancora scansionati:</strong>
                {% if riepilogo_scan.mancanti %}
                  <ul class="mb-0 mt-2">
                    {% for r in riepilogo_scan.mancanti %}
                    <li>
                      <strong>{{ r.n_arrivo or '-' }}</strong>
                      {% if r.codice_articolo %} - {{ r.codice_articolo }}{% endif %}
                      {% if r.descrizione %} - {{ r.descrizione }}{% endif %}
                      <br><small>QR: {{ r.codice_entrata }}</small>
                    </li>
                    {% endfor %}
                  </ul>
                {% else %}
                  <div class="mt-2">Nessun arrivo mancante.</div>
                {% endif %}
              </div>
            </div>

            <div class="col-md-6">
              <div class="alert {% if riepilogo_scan.sbagliati %}alert-danger{% else %}alert-success{% endif %} mb-0">
                <strong>Scansioni non presenti nel buono:</strong>
                {% if riepilogo_scan.sbagliati %}
                  <ul class="mb-0 mt-2">
                    {% for s in riepilogo_scan.sbagliati %}
                    <li>
                      <strong>{{ s.codice_scansionato }}</strong>
                      <br><small>{{ s.scanned_at }} - {{ s.messaggio }}</small>
                    </li>
                    {% endfor %}
                  </ul>
                {% else %}
                  <div class="mt-2">Nessuna scansione errata.</div>
                {% endif %}
              </div>
            </div>
          </div>
        </div>
      </div>

    <div class="card shadow-sm mb-3">
        <div class="card-header fw-bold d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>Arrivi collegati al buono</span>
          <small class="text-muted">Puoi spuntare manualmente gli arrivi caricati, come se avessi sparato il QR.</small>
        </div>
        <form method="POST" action="{{ url_for('segna_righe_buono_carico', buono_id=buono.id) }}" onsubmit="return confirm('Segnare gli arrivi selezionati come caricati?');">
        <div class="p-2 d-flex gap-2 flex-wrap align-items-center">
          <button type="submit" class="btn btn-success btn-sm">✅ Segna selezionati come caricati</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.querySelectorAll('.chk-arrivo-carico:not(:disabled)').forEach(c => c.checked = true);">Seleziona mancanti</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="document.querySelectorAll('.chk-arrivo-carico').forEach(c => c.checked = false);">Deseleziona</button>
          <span class="small text-muted">Utile se non riesci a leggere il QR con pistola/fotocamera.</span>
        </div>
        <div class="table-responsive">
          <table class="table table-sm table-striped mb-0">
            <thead>
              <tr>
                <th style="width:60px;">Spunta</th>
                <th>ID Art.</th><th>Cliente</th><th>Fornitore</th><th>Codice</th><th>Descrizione</th>
                <th>N. Arrivo</th><th>DDT Ing</th><th>Colli</th><th>Peso</th><th>QR/Codice entrata</th><th>Stato scansione</th>
              </tr>
            </thead>
            <tbody>
              {% for r in righe %}
              <tr>
                {% set stato_riga = (riepilogo_scan.row_status or {}).get(r.id|string, 'mancante') %}
                <td class="text-center">
                  <input type="checkbox"
                         class="form-check-input chk-arrivo-carico"
                         name="riga_ids"
                         value="{{ r.id }}"
                         {% if stato_riga == 'caricato' %}disabled{% endif %}>
                </td>
                <td>{{ r.id_articolo }}</td>
                <td>{{ r.cliente }}</td>
                <td>{{ r.fornitore or '' }}</td>
                <td>{{ r.codice_articolo or '' }}</td>
                <td>{{ r.descrizione or '' }}</td>
                <td>{{ r.n_arrivo or '' }}</td>
                <td>{{ r.n_ddt_ingresso or '' }}</td>
                <td>{{ r.colli_previsti or 0 }}</td>
                <td>{{ r.peso_previsto|it_num(2) }}</td>
                <td><code>{{ r.codice_entrata }}</code></td>
                <td>
                  {% if stato_riga == 'caricato' %}
                    <span class="badge bg-success">Caricato</span>
                  {% elif stato_riga == 'parziale' %}
                    <span class="badge bg-info text-dark">Parziale</span>
                  {% else %}
                    <span class="badge bg-warning text-dark">Mancante</span>
                  {% endif %}
                </td>
              </tr>
              {% else %}
              <tr><td colspan="12" class="text-muted">Vecchio buono senza righe dettagliate.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        </form>
      </div>

      <div class="card shadow-sm mb-3">
        <div class="card-header fw-bold">Scansiona pallet / arrivo</div>
        <div class="card-body">
          <form id="form_scansione_qr" method="POST" action="{{ url_for('scansiona_buono_carico', buono_id=buono.id) }}" class="row g-2">
            <div class="col-md-8">
              <input type="text" id="codice_scansionato" name="codice_scansionato" class="form-control form-control-lg" placeholder="Scansiona QR o incolla codice entrata ENT-..." autofocus required>
            </div>
            <div class="col-md-4">
              <button class="btn btn-success btn-sm w-100">Registra scansione</button>
            </div>
          </form>

        <div class="mt-3 d-flex gap-2 flex-wrap">
          <button type="button" class="btn btn-outline-primary btn-sm" onclick="avviaScannerQR()">
            📷 Apri fotocamera QR
          </button>
          <button type="button" class="btn btn-outline-danger btn-sm" onclick="fermaScannerQR()">
            ✖ Chiudi fotocamera
          </button>
        </div>

        <div id="qr_reader_box" class="mt-3" style="display:none;">
          <div id="reader" style="width:100%;max-width:420px;margin:auto;border:1px solid #ddd;border-radius:8px;padding:8px;background:#fff;"></div>
          <div class="small text-muted mt-2 text-center">
            Su smartphone autorizza l'uso della fotocamera. Se non si apre, verifica che il sito sia in HTTPS.
          </div>
        </div>

        </div>
      </div>

      <div class="card shadow-sm">
        <div class="card-header fw-bold">Storico scansioni</div>
        <div class="table-responsive">
          <table class="table table-sm table-striped mb-0">
            <thead><tr><th>Data/Ora</th><th>Utente</th><th>Codice scansionato</th><th>Esito</th><th>Messaggio</th></tr></thead>
            <tbody>
              {% for s in scansioni %}
              <tr>
                <td>{{ s.scanned_at }}</td>
                <td>{{ s.scanned_by or '-' }}</td>
                <td><code>{{ s.codice_scansionato }}</code></td>
                <td>{{ s.esito }}</td>
                <td>{{ s.messaggio }}</td>
              </tr>
              {% else %}
              <tr><td colspan="5" class="text-muted">Nessuna scansione registrata.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
    let qrScannerInstance = null;
    let qrScannerRunning = false;

    function setQrStatus(msg, type) {
        let el = document.getElementById("qr_status_msg");
        if (!el) {
            const box = document.getElementById("qr_reader_box");
            if (box) {
                el = document.createElement("div");
                el.id = "qr_status_msg";
                el.className = "alert mt-2";
                box.appendChild(el);
            }
        }
        if (el) {
            el.className = "alert mt-2 " + (type || "alert-info");
            el.innerText = msg;
        }
    }

    function caricaHtml5QrCodeSeServe(callback) {
        if (typeof Html5Qrcode !== "undefined") {
            callback();
            return;
        }

        const old = document.getElementById("html5-qrcode-dynamic");
        if (old) {
            old.addEventListener("load", callback);
            return;
        }

        const s = document.createElement("script");
        s.id = "html5-qrcode-dynamic";
        s.src = "https://unpkg.com/html5-qrcode";
        s.onload = callback;
        s.onerror = function() {
            setQrStatus("Impossibile caricare il lettore QR. Controlla la connessione internet del telefono.", "alert-danger");
        };
        document.head.appendChild(s);
    }

    async function avviaScannerQR() {
        const box = document.getElementById("qr_reader_box");
        const readerEl = document.getElementById("reader");
        const input = document.getElementById("codice_scansionato");

        if (!box || !readerEl || !input) {
            alert("Lettore QR non trovato nella pagina.");
            return;
        }

        box.style.display = "block";
        readerEl.innerHTML = "";

        if (!window.isSecureContext) {
            setQrStatus("La fotocamera dello smartphone funziona solo con sito HTTPS. Apri il gestionale dal link https://...", "alert-danger");
            return;
        }

        caricaHtml5QrCodeSeServe(async function() {
            try {
                if (qrScannerRunning && qrScannerInstance) {
                    await fermaScannerQR();
                }

                qrScannerInstance = new Html5Qrcode("reader");

                let config = {
                    fps: 10,
                    qrbox: function(viewfinderWidth, viewfinderHeight) {
                        const minEdge = Math.min(viewfinderWidth, viewfinderHeight);
                        const boxSize = Math.floor(minEdge * 0.75);
                        return { width: boxSize, height: boxSize };
                    },
                    aspectRatio: 1.0
                };

                // Su smartphone è più affidabile chiedere direttamente la camera posteriore
                await qrScannerInstance.start(
                    { facingMode: { exact: "environment" } },
                    config,
                    function(decodedText) {
                        input.value = decodedText;
                        setQrStatus("QR letto correttamente. Invio scansione...", "alert-success");

                        setTimeout(async function() {
                            try { await fermaScannerQR(); } catch(e) {}
                            const form = document.getElementById("form_scansione_qr") || input.closest("form");
                            if (form) form.submit();
                        }, 300);
                    },
                    function(errorMessage) {
                        // errori normali durante la ricerca del QR: non mostrare alert continui
                    }
                );

                qrScannerRunning = true;
                setQrStatus("Fotocamera attiva. Inquadra il QR dell'arrivo.", "alert-info");

            } catch (err1) {
                console.warn("Camera environment exact fallita, provo fallback", err1);

                try {
                    // Fallback per iPhone/Android che non accettano exact
                    if (qrScannerInstance) {
                        try { await qrScannerInstance.clear(); } catch(e) {}
                    }
                    qrScannerInstance = new Html5Qrcode("reader");

                    await qrScannerInstance.start(
                        { facingMode: "environment" },
                        {
                            fps: 10,
                            qrbox: { width: 250, height: 250 }
                        },
                        function(decodedText) {
                            input.value = decodedText;
                            setQrStatus("QR letto correttamente. Invio scansione...", "alert-success");

                            setTimeout(async function() {
                                try { await fermaScannerQR(); } catch(e) {}
                                const form = document.getElementById("form_scansione_qr") || input.closest("form");
                                if (form) form.submit();
                            }, 300);
                        },
                        function(errorMessage) {}
                    );

                    qrScannerRunning = true;
                    setQrStatus("Fotocamera attiva. Inquadra il QR dell'arrivo.", "alert-info");

                } catch (err2) {
                    console.error(err2);
                    setQrStatus(
                        "Non riesco ad aprire la fotocamera. Controlla i permessi del browser e che il sito sia aperto in HTTPS. Errore: " + err2,
                        "alert-danger"
                    );
                }
            }
        });
    }

    async function fermaScannerQR() {
        try {
            if (qrScannerInstance && qrScannerRunning) {
                await qrScannerInstance.stop();
            }
        } catch(e) {
            console.warn(e);
        }

        try {
            if (qrScannerInstance) {
                await qrScannerInstance.clear();
            }
        } catch(e) {}

        qrScannerRunning = false;

        const readerEl = document.getElementById("reader");
        if (readerEl) readerEl.innerHTML = "";

        const box = document.getElementById("qr_reader_box");
        if (box) box.style.display = "none";
    }
    </script>

    {% endblock %}
    """


    def _trova_buono_carico_da_input(db, valore):
        """Trova un buono carico da ID numerico oppure da codice tipo BC-2026-0001."""
        raw = (str(valore or "")).strip()
        if not raw:
            return None
        if raw.isdigit():
            b = db.query(BuonoCarico).filter(BuonoCarico.id == int(raw)).first()
            if b:
                return b
        return db.query(BuonoCarico).filter(func.upper(BuonoCarico.codice_buono) == raw.upper()).first()


    def _next_codice_buono_carico(db):
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

        for n in range(max_n + 1, max_n + 10000):
            candidate = f"{prefix}{n:04d}"
            if not db.query(BuonoCarico).filter(BuonoCarico.codice_buono == candidate).first():
                return candidate

        return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


    def _righe_buono_carico(db, buono):
        try:
            return db.query(BuonoCaricoRiga).filter(BuonoCaricoRiga.buono_id == buono.id).order_by(BuonoCaricoRiga.id.asc()).all()
        except Exception:
            return []

    def _codici_validi_buono_carico(db, buono):
        codici = []
        righe = _righe_buono_carico(db, buono)
        if righe:
            for r in righe:
                if (r.codice_entrata or "").strip():
                    codici.append((r.codice_entrata or "").strip())
        elif (buono.codice_entrata or "").strip():
            codici.append((buono.codice_entrata or "").strip())

        out = []
        seen = set()
        for c in codici:
            for v in _codice_entrata_varianti(c):
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
        return out


    def _key_codice_entrata_buono(codice):
        """Chiave normalizzata stabile per confrontare QR/codici entrata."""
        vars_ = _codice_entrata_varianti(codice)
        if vars_:
            # usa la variante più corta/vecchia se presente, così vecchio e nuovo barcode coincidono
            return normalize_text_key(sorted(vars_, key=lambda x: len(x))[0])
        return normalize_text_key(codice)


    def _conteggi_qr_buono_carico(db, buono):
        """Restituisce conteggi per QR del buono.

        expected_by_key = colli previsti per QR
        ok_by_key = scansioni OK registrate per QR
        canonical_by_key = codice originale da mostrare/salvare
        """
        righe = _righe_buono_carico(db, buono)

        expected_by_key = {}
        canonical_by_key = {}

        if righe:
            for r in righe:
                cod = (r.codice_entrata or "").strip()
                if not cod:
                    continue
                k = _key_codice_entrata_buono(cod)
                expected_by_key[k] = expected_by_key.get(k, 0) + int(r.colli_previsti or 0)
                canonical_by_key.setdefault(k, cod)
        else:
            cod = (buono.codice_entrata or "").strip()
            if cod:
                for c in [x.strip() for x in cod.split(";") if x.strip()]:
                    k = _key_codice_entrata_buono(c)
                    expected_by_key[k] = expected_by_key.get(k, 0) + int(buono.pallet_previsti or 0)
                    canonical_by_key.setdefault(k, c)

        ok_by_key = {}
        scansioni_ok = db.query(BuonoCaricoScan).filter(
            BuonoCaricoScan.buono_id == buono.id,
            BuonoCaricoScan.esito == "OK"
        ).all()

        for s in scansioni_ok:
            cod = (s.codice_scansionato or "").strip()
            if not cod:
                continue
            k = _key_codice_entrata_buono(cod)
            ok_by_key[k] = ok_by_key.get(k, 0) + 1

        return expected_by_key, ok_by_key, canonical_by_key


    def _match_key_qr_buono(db, buono, codice_scansionato):
        """Trova la chiave QR del buono compatibile con il codice scansionato."""
        expected_by_key, ok_by_key, canonical_by_key = _conteggi_qr_buono_carico(db, buono)

        scan_variants = {_key_codice_entrata_buono(v) for v in _codice_entrata_varianti(codice_scansionato)}
        scan_variants.add(_key_codice_entrata_buono(codice_scansionato))

        for k in expected_by_key.keys():
            if k in scan_variants:
                return k, canonical_by_key.get(k) or codice_scansionato

        # confronto extra tollerante sulle varianti testuali
        scan_norms = {normalize_text_key(v) for v in _codice_entrata_varianti(codice_scansionato)}
        scan_norms.add(normalize_text_key(codice_scansionato))
        for k, canon in canonical_by_key.items():
            vars_norm = {normalize_text_key(v) for v in _codice_entrata_varianti(canon)}
            if vars_norm.intersection(scan_norms):
                return k, canon

        return None, codice_scansionato


    def _stats_buono_carico(db, buono):
        """Statistiche buono carico: conta i colli reali per QR, non solo le righe."""
        righe = _righe_buono_carico(db, buono)

        if righe:
            previsti = sum(int(r.colli_previsti or 0) for r in righe)
        else:
            previsti = int(buono.pallet_previsti or 0)

        expected_by_key, ok_by_key, canonical_by_key = _conteggi_qr_buono_carico(db, buono)

        ok = 0
        for k, prev in expected_by_key.items():
            ok += min(int(ok_by_key.get(k, 0)), int(prev or 0))

        # fallback vecchi buoni senza righe/codici
        if not expected_by_key:
            ok = db.query(BuonoCaricoScan).filter(
                BuonoCaricoScan.buono_id == buono.id,
                BuonoCaricoScan.esito == "OK"
            ).count()

        return {
            "ok": ok,
            "mancanti": max(0, previsti - ok),
            "previsti": previsti
        }


    def _riepilogo_scansioni_buono_carico(db, buono):
        """Riepiloga arrivi caricati/mancanti e scansioni non presenti nel buono.

        Nota: se un QR ha 2 colli previsti, servono 2 scansioni OK dello stesso QR.
        """
        righe = _righe_buono_carico(db, buono)
        scansioni = db.query(BuonoCaricoScan).filter(
            BuonoCaricoScan.buono_id == buono.id
        ).order_by(BuonoCaricoScan.id.desc()).all()

        expected_by_key, ok_by_key, canonical_by_key = _conteggi_qr_buono_carico(db, buono)

        wrong_scans = []
        for s in scansioni:
            if s.esito in ("SBAGLIATO", "ERRORE"):
                wrong_scans.append(s)

        # Per lo stato riga: assegna le scansioni disponibili alle righe dello stesso QR in ordine.
        usate_by_key = {}
        mancanti = []
        caricati = []
        row_status = {}

        for r in righe:
            cod = (r.codice_entrata or "").strip()
            k = _key_codice_entrata_buono(cod)
            prev_riga = int(r.colli_previsti or 0)
            ok_disponibili = int(ok_by_key.get(k, 0))
            gia_usate = int(usate_by_key.get(k, 0))
            residuo_ok = max(0, ok_disponibili - gia_usate)

            if residuo_ok >= prev_riga and prev_riga > 0:
                row_status[str(r.id)] = "caricato"
                caricati.append(r)
                usate_by_key[k] = gia_usate + prev_riga
            elif residuo_ok > 0:
                row_status[str(r.id)] = "parziale"
                mancanti.append(r)
                usate_by_key[k] = gia_usate + residuo_ok
            else:
                row_status[str(r.id)] = "mancante"
                mancanti.append(r)

        ok_codes = set()
        for k, n_ok in ok_by_key.items():
            if int(n_ok or 0) > 0:
                ok_codes.add(k)

        return {
            "mancanti": mancanti,
            "caricati": caricati,
            "sbagliati": wrong_scans,
            "ok_codes": ok_codes,
            "row_status": row_status,
            "expected_by_key": expected_by_key,
            "ok_by_key": ok_by_key,
        }


    def _aggiorna_stato_buono_carico(db, buono):
        st = _stats_buono_carico(db, buono)
        errori = db.query(BuonoCaricoScan).filter(BuonoCaricoScan.buono_id == buono.id, BuonoCaricoScan.esito.in_(["ERRORE", "SBAGLIATO"])).count()
        if errori and st["ok"] < st["previsti"]:
            buono.stato = "ERRORE"
        elif st["ok"] >= st["previsti"] and st["previsti"] > 0:
            buono.stato = "COMPLETATO"
        elif st["ok"] > 0:
            buono.stato = "PARZIALE"
        else:
            buono.stato = "DA CARICARE"
        db.commit()


    @app.route("/buono_carico_da_riga", methods=["POST"])
    @login_required
    @require_admin_or_magazzino
    def buono_carico_da_riga():
        """Crea un buono di carico QR partendo da una o più righe selezionate in Magazzino."""
        ids = request.form.getlist("ids") or request.form.getlist("selected_ids") or request.form.getlist("selected") or []
        ids = [str(x).strip() for x in ids if str(x).strip().isdigit()]

        if len(ids) < 1:
            flash("Seleziona almeno una riga per creare il buono di carico QR.", "warning")
            return redirect(url_for("giacenze"))

        db = SessionLocal()
        try:
            Base.metadata.create_all(engine)

            articoli = (
                db.query(Articolo)
                .filter(Articolo.id_articolo.in_([int(x) for x in ids]))
                .order_by(Articolo.id_articolo.asc())
                .all()
            )

            if not articoli:
                flash("Nessuna riga selezionata trovata.", "danger")
                return redirect(url_for("giacenze"))

            usciti = [str(a.id_articolo) for a in articoli if (a.data_uscita or a.n_ddt_uscita)]
            if usciti:
                flash("Alcune righe selezionate risultano già uscite: " + ", ".join(usciti), "warning")
                return redirect(url_for("giacenze"))

            clienti = {validate_cliente_or_raise(a.cliente) for a in articoli}
            if len(clienti) > 1:
                flash("Per creare un buono di carico unico seleziona righe dello stesso cliente.", "warning")
                return redirect(url_for("giacenze"))

            cliente = list(clienti)[0]
            primo = articoli[0]

            buono = BuonoCarico(
                codice_buono=_next_codice_buono_carico(db),
                id_articolo_origine=primo.id_articolo,
                cliente=cliente,
                fornitore="",
                codice_articolo="",
                descrizione="",
                n_arrivo="",
                n_ddt_ingresso="",
                data_ingresso=primo.data_ingresso or date.today().strftime("%Y-%m-%d"),
                codice_entrata="",
                pallet_previsti=0,
                peso_previsto=0.0,
                stato="DA CARICARE",
                note=f"Creato da {len(articoli)} righe magazzino",
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                created_by=_current_username_for_audit()
            )
            db.add(buono)
            db.flush()

            totale_colli = 0
            totale_peso = 0.0
            codici_entrata = []
            codici_articolo = []
            descrizioni = []
            arrivi = []
            ddt_ing = []
            fornitori = []

            def _add_unique(lista, valore):
                valore = (str(valore or "")).strip()
                if valore and valore not in lista:
                    lista.append(valore)

            for art in articoli:
                n_arrivo_base = strip_arrivo_progressivo(art.n_arrivo)
                codice_entrata = ensure_codice_entrata(
                    getattr(art, "codice_entrata", None),
                    n_arrivo=n_arrivo_base or art.n_arrivo,
                    n_ddt=art.n_ddt_ingresso,
                    data_ingresso=art.data_ingresso,
                    cliente=cliente
                )

                if not (getattr(art, "codice_entrata", "") or "").strip():
                    art.codice_entrata = codice_entrata

                try:
                    colli = int(art.n_colli or 0)
                except Exception:
                    colli = 0
                if colli <= 0:
                    colli = 1

                try:
                    peso = float(art.peso or 0)
                except Exception:
                    peso = 0.0

                totale_colli += colli
                totale_peso += peso

                _add_unique(codici_entrata, codice_entrata)
                _add_unique(codici_articolo, art.codice_articolo)
                _add_unique(descrizioni, art.descrizione)
                _add_unique(arrivi, n_arrivo_base or art.n_arrivo)
                _add_unique(ddt_ing, art.n_ddt_ingresso)
                _add_unique(fornitori, art.fornitore)

                db.add(BuonoCaricoRiga(
                    buono_id=buono.id,
                    id_articolo=art.id_articolo,
                    cliente=cliente,
                    fornitore=art.fornitore or "",
                    codice_articolo=art.codice_articolo or "",
                    descrizione=art.descrizione or "",
                    n_arrivo=n_arrivo_base or (art.n_arrivo or ""),
                    n_ddt_ingresso=art.n_ddt_ingresso or "",
                    data_ingresso=art.data_ingresso or "",
                    codice_entrata=codice_entrata,
                    colli_previsti=colli,
                    peso_previsto=peso
                ))

            buono.fornitore = " / ".join(fornitori)[:500]
            buono.codice_articolo = "; ".join(codici_articolo)[:500]
            buono.descrizione = "; ".join(descrizioni)[:800]
            buono.n_arrivo = "; ".join(arrivi)[:500]
            buono.n_ddt_ingresso = "; ".join(ddt_ing)[:500]
            buono.codice_entrata = "; ".join(codici_entrata)[:1500]
            buono.pallet_previsti = totale_colli
            buono.peso_previsto = totale_peso

            db.commit()
            flash(f"Buono di carico QR creato con {len(articoli)} righe/arrivi selezionati.", "success")
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore buono_carico_da_riga multi", e)
            except Exception:
                pass
            flash(f"Errore creazione buono di carico: {e}", "danger")
            return redirect(url_for("giacenze"))
        finally:
            db.close()


    @app.route("/buoni_carico", methods=["GET", "POST"])
    @login_required
    @require_admin_or_magazzino
    def buoni_carico():
        db = SessionLocal()
        try:
            Base.metadata.create_all(engine)
            if request.method == "POST":
                cliente = validate_cliente_or_raise(request.form.get("cliente"))
                fornitore = (request.form.get("fornitore") or "").strip()
                codice_articolo = (request.form.get("codice_articolo") or "").strip()
                descrizione = (request.form.get("descrizione") or "").strip()
                n_arrivo = (request.form.get("n_arrivo") or "").strip()
                n_ddt_ingresso = (request.form.get("n_ddt_ingresso") or "").strip()
                data_ingresso = (request.form.get("data_ingresso") or date.today().strftime("%Y-%m-%d")).strip()
                codice_entrata = (request.form.get("codice_entrata") or "").strip()
                note = (request.form.get("note") or "").strip()

                try:
                    pallet_previsti = int(float((request.form.get("pallet_previsti") or "0").replace(",", ".")))
                except Exception:
                    pallet_previsti = 0
                try:
                    peso_previsto = float((request.form.get("peso_previsto") or "0").replace(".", "").replace(",", "."))
                except Exception:
                    peso_previsto = 0.0

                if pallet_previsti <= 0:
                    flash("Inserisci i pallet previsti.", "danger")
                    return redirect(url_for("buoni_carico"))

                if not codice_entrata:
                    codice_entrata = genera_codice_entrata(n_arrivo=n_arrivo, n_ddt=n_ddt_ingresso, data_ingresso=data_ingresso, cliente=cliente)

                buono = BuonoCarico(
                    codice_buono=_next_codice_buono_carico(db),
                    cliente=cliente,
                    fornitore=fornitore,
                    codice_articolo=codice_articolo,
                    descrizione=descrizione,
                    n_arrivo=n_arrivo,
                    n_ddt_ingresso=n_ddt_ingresso,
                    data_ingresso=data_ingresso,
                    codice_entrata=codice_entrata,
                    pallet_previsti=pallet_previsti,
                    peso_previsto=peso_previsto,
                    stato="DA CARICARE",
                    note=note,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    created_by=_current_username_for_audit()
                )
                db.add(buono)
                db.commit()
                flash("Buono di carico creato.", "success")
                return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

            buoni = db.query(BuonoCarico).order_by(BuonoCarico.id.desc()).limit(300).all()
            stats = {b.id: _stats_buono_carico(db, b) for b in buoni}
            return render_template_string(BUONI_CARICO_HTML, buoni=buoni, stats=stats, clienti=get_clienti_utenti(), oggi=date.today().strftime("%Y-%m-%d"))
        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore buoni_carico", e)
            except Exception:
                pass
            flash(f"Errore buoni di carico: {e}", "danger")
            return redirect(url_for("home"))
        finally:
            db.close()

    @app.route("/buoni_carico/<int:buono_id>", methods=["GET"])
    @login_required
    @require_admin_or_magazzino
    def dettaglio_buono_carico(buono_id):
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                flash("Buono di carico non trovato.", "danger")
                return redirect(url_for("buoni_carico"))
            _aggiorna_stato_buono_carico(db, buono)
            scansioni = db.query(BuonoCaricoScan).filter(BuonoCaricoScan.buono_id == buono.id).order_by(BuonoCaricoScan.id.desc()).all()
            st = _stats_buono_carico(db, buono)
            riepilogo_scan = _riepilogo_scansioni_buono_carico(db, buono)
            return render_template_string(
                BUONO_CARICO_DETTAGLIO_HTML,
                buono=buono,
                righe=_righe_buono_carico(db, buono),
                scansioni=scansioni,
                caricati_ok=st["ok"],
                mancanti=st["mancanti"],
                riepilogo_scan=riepilogo_scan
            )
        finally:
            db.close()

    @app.route("/buoni_carico/<int:buono_id>/scansiona", methods=["POST"])
    @login_required
    @require_admin_or_magazzino
    def scansiona_buono_carico(buono_id):
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                flash("Buono di carico non trovato.", "danger")
                return redirect(url_for("buoni_carico"))

            raw = (request.form.get("codice_scansionato") or "").strip()
            if not raw:
                flash("Scansiona o inserisci un codice QR.", "warning")
                return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

            codice = unquote(raw)
            m = re.search(r"/entrata/([^/?#]+)", codice, flags=re.I)
            if m:
                codice = unquote(m.group(1)).strip()

            expected_by_key, ok_by_key, canonical_by_key = _conteggi_qr_buono_carico(db, buono)
            key_qr, codice_salvato = _match_key_qr_buono(db, buono, codice)

            if not key_qr:
                esito = "SBAGLIATO"
                msg = "Arrivo sbagliato: questo QR non è collegato a questo buono di carico oppure non è da caricare."
            else:
                previsti_qr = int(expected_by_key.get(key_qr, 0))
                gia_ok_qr = int(ok_by_key.get(key_qr, 0))

                if gia_ok_qr >= previsti_qr and previsti_qr > 0:
                    esito = "DUPLICATO"
                    msg = "Questo arrivo/QR ha già raggiunto tutti i colli previsti su questo buono."
                else:
                    st = _stats_buono_carico(db, buono)
                    if st["ok"] >= st["previsti"]:
                        esito = "ERRORE"
                        msg = "Colli in più: hai già raggiunto il numero previsto per questo buono."
                    else:
                        esito = "OK"
                        msg = f"Arrivo/collo caricato correttamente ({gia_ok_qr + 1}/{previsti_qr})."

            scan = BuonoCaricoScan(
                buono_id=buono.id,
                codice_scansionato=codice_salvato,
                esito=esito,
                messaggio=msg,
                scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                scanned_by=_current_username_for_audit()
            )
            db.add(scan)
            db.commit()
            _aggiorna_stato_buono_carico(db, buono)

            flash(msg, "success" if esito == "OK" else ("warning" if esito == "DUPLICATO" else "danger"))
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))
        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore scansione buono carico multi", e)
            except Exception:
                pass
            flash(f"Errore scansione: {e}", "danger")
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono_id))
        finally:
            db.close()


    @app.route("/buoni_carico/<int:buono_id>/segna_righe", methods=["POST"])
    @login_required
    @require_admin_or_magazzino
    def segna_righe_buono_carico(buono_id):
        """Permette di spuntare manualmente gli arrivi collegati al buono.

        La spunta registra scansioni OK come se il QR fosse stato letto.
        Se una riga ha più colli previsti, vengono aggiunte solo le scansioni mancanti
        fino al totale previsto per quel codice entrata, senza duplicare colli già caricati.
        """
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                flash("Buono di carico non trovato.", "danger")
                return redirect(url_for("buoni_carico"))

            ids = request.form.getlist("riga_ids")
            ids = [int(x) for x in ids if str(x).strip().isdigit()]

            if not ids:
                flash("Seleziona almeno un arrivo da segnare come caricato.", "warning")
                return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

            righe = (
                db.query(BuonoCaricoRiga)
                .filter(BuonoCaricoRiga.buono_id == buono.id, BuonoCaricoRiga.id.in_(ids))
                .order_by(BuonoCaricoRiga.id.asc())
                .all()
            )

            if not righe:
                flash("Nessuna riga valida selezionata.", "warning")
                return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

            expected_by_key, ok_by_key, canonical_by_key = _conteggi_qr_buono_carico(db, buono)

            aggiunte = 0
            saltate = 0

            for r in righe:
                codice = (r.codice_entrata or "").strip()
                if not codice:
                    saltate += 1
                    continue

                k = _key_codice_entrata_buono(codice)
                previsti_totali = int(expected_by_key.get(k, 0))
                gia_ok = int(ok_by_key.get(k, 0))
                colli_riga = int(r.colli_previsti or 0)
                if colli_riga <= 0:
                    colli_riga = 1

                mancanti_qr = max(0, previsti_totali - gia_ok)
                da_aggiungere = min(colli_riga, mancanti_qr)

                if da_aggiungere <= 0:
                    saltate += 1
                    continue

                codice_salvato = canonical_by_key.get(k) or codice

                for i in range(da_aggiungere):
                    scan = BuonoCaricoScan(
                        buono_id=buono.id,
                        codice_scansionato=codice_salvato,
                        esito="OK",
                        messaggio=(
                            f"Arrivo segnato manualmente come caricato "
                            f"({gia_ok + i + 1}/{previsti_totali})."
                        ),
                        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        scanned_by=_current_username_for_audit()
                    )
                    db.add(scan)
                    aggiunte += 1

                ok_by_key[k] = gia_ok + da_aggiungere

            db.commit()
            _aggiorna_stato_buono_carico(db, buono)

            if aggiunte:
                msg = f"Spunta registrata: {aggiunte} collo/i segnati come caricati."
                if saltate:
                    msg += f" {saltate} riga/e erano già complete o senza QR."
                flash(msg, "success")
            else:
                flash("Nessuna scansione aggiunta: gli arrivi selezionati risultano già caricati o senza QR.", "warning")

            return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore spunta manuale buono carico", e)
            except Exception:
                pass
            flash(f"Errore spunta manuale: {e}", "danger")
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono_id))
        finally:
            db.close()






    @app.route("/buoni_carico/aggiungi_righe", methods=["POST"])
    @login_required
    @require_admin_or_magazzino
    def aggiungi_righe_a_buono_carico():
        """Aggiunge una o più righe selezionate dal Magazzino a un buono di carico esistente."""
        buono_input = (
            request.form.get("buono_carico_id_manual")
            or request.form.get("buono_carico_id")
            or request.form.get("aggiungi_buono_carico")
            or request.args.get("aggiungi_buono_carico")
            or session.get("aggiungi_buono_carico")
            or ""
        )
        buono_input = str(buono_input).strip()

        ids = request.form.getlist("ids") or request.form.getlist("selected_ids") or request.form.getlist("selected") or []
        ids = [str(x).strip() for x in ids if str(x).strip().isdigit()]

        if not buono_input:
            flash("Indica l'ID del buono oppure il codice buono, esempio BC-2026-0001.", "warning")
            return redirect(url_for("giacenze"))

        if not ids:
            flash("Seleziona almeno una riga da aggiungere al buono di carico.", "warning")
            return redirect(url_for("giacenze", aggiungi_buono_carico=buono_input))

        db = SessionLocal()
        try:
            Base.metadata.create_all(engine)

            buono = _trova_buono_carico_da_input(db, buono_input)
            if not buono:
                flash("Buono di carico non trovato. Inserisci l'ID numerico oppure il codice tipo BC-2026-0001.", "danger")
                return redirect(url_for("giacenze"))

            articoli = (
                db.query(Articolo)
                .filter(Articolo.id_articolo.in_([int(x) for x in ids]))
                .order_by(Articolo.id_articolo.asc())
                .all()
            )

            if not articoli:
                flash("Nessuna riga selezionata trovata.", "danger")
                return redirect(url_for("giacenze", aggiungi_buono_carico=buono.id))

            try:
                esistenti = {
                    int(r.id_articolo) for r in db.query(BuonoCaricoRiga)
                    .filter(BuonoCaricoRiga.buono_id == buono.id)
                    .all()
                    if r.id_articolo
                }
            except Exception:
                esistenti = set()

            aggiunte = 0
            totale_colli_add = 0
            totale_peso_add = 0.0

            def _add_summary(current, value, sep="; ", limit=1500):
                value = (str(value or "")).strip()
                current = (str(current or "")).strip()
                if not value:
                    return current
                parts = [p.strip() for p in current.split(sep) if p.strip()] if current else []
                if value not in parts:
                    parts.append(value)
                return sep.join(parts)[:limit]

            for art in articoli:
                if art.id_articolo in esistenti:
                    continue

                cliente_art = validate_cliente_or_raise(art.cliente)
                if normalize_text_key(cliente_art) != normalize_text_key(buono.cliente):
                    flash("Puoi aggiungere solo righe dello stesso cliente del buono.", "warning")
                    return redirect(url_for("giacenze", aggiungi_buono_carico=buono.id))

                if art.data_uscita or art.n_ddt_uscita:
                    flash(f"La riga ID {art.id_articolo} risulta già uscita e non può essere aggiunta.", "warning")
                    return redirect(url_for("giacenze", aggiungi_buono_carico=buono.id))

                n_arrivo_base = strip_arrivo_progressivo(art.n_arrivo)
                codice_entrata = ensure_codice_entrata(
                    getattr(art, "codice_entrata", None),
                    n_arrivo=n_arrivo_base or art.n_arrivo,
                    n_ddt=art.n_ddt_ingresso,
                    data_ingresso=art.data_ingresso,
                    cliente=buono.cliente
                )

                if not (getattr(art, "codice_entrata", "") or "").strip():
                    art.codice_entrata = codice_entrata

                try:
                    colli = int(art.n_colli or 0)
                except Exception:
                    colli = 0
                if colli <= 0:
                    colli = 1

                try:
                    peso = float(art.peso or 0)
                except Exception:
                    peso = 0.0

                db.add(BuonoCaricoRiga(
                    buono_id=buono.id,
                    id_articolo=art.id_articolo,
                    cliente=buono.cliente,
                    fornitore=art.fornitore or "",
                    codice_articolo=art.codice_articolo or "",
                    descrizione=art.descrizione or "",
                    n_arrivo=n_arrivo_base or (art.n_arrivo or ""),
                    n_ddt_ingresso=art.n_ddt_ingresso or "",
                    data_ingresso=art.data_ingresso or "",
                    codice_entrata=codice_entrata,
                    colli_previsti=colli,
                    peso_previsto=peso
                ))

                buono.fornitore = _add_summary(buono.fornitore, art.fornitore, sep=" / ", limit=500)
                buono.codice_articolo = _add_summary(getattr(buono, "codice_articolo", ""), art.codice_articolo, sep="; ", limit=500)
                buono.descrizione = _add_summary(getattr(buono, "descrizione", ""), art.descrizione, sep="; ", limit=800)
                buono.n_arrivo = _add_summary(buono.n_arrivo, n_arrivo_base or art.n_arrivo, sep="; ", limit=500)
                buono.n_ddt_ingresso = _add_summary(buono.n_ddt_ingresso, art.n_ddt_ingresso, sep="; ", limit=500)
                buono.codice_entrata = _add_summary(buono.codice_entrata, codice_entrata, sep="; ", limit=1500)

                totale_colli_add += colli
                totale_peso_add += peso
                aggiunte += 1

            buono.pallet_previsti = int(buono.pallet_previsti or 0) + totale_colli_add
            buono.peso_previsto = float(buono.peso_previsto or 0) + totale_peso_add

            _aggiorna_stato_buono_carico(db, buono)
            db.commit()

            if aggiunte:
                flash(f"Aggiunte {aggiunte} righe/arrivi al buono di carico {buono.codice_buono}.", "success")
            else:
                flash("Le righe selezionate erano già presenti nel buono.", "info")

            session["aggiungi_buono_carico"] = str(buono.id)
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono.id))

        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore aggiunta righe a buono carico", e)
            except Exception:
                pass
            flash(f"Errore aggiunta righe al buono: {e}", "danger")
            return redirect(url_for("giacenze", aggiungi_buono_carico=buono_input))
        finally:
            db.close()


    @app.route("/buoni_carico/<int:buono_id>/elimina", methods=["POST"])
    @login_required
    @require_admin_or_magazzino
    def elimina_buono_carico(buono_id):
        """Elimina un buono di carico e le relative righe/scansioni."""
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                flash("Buono di carico non trovato.", "danger")
                return redirect(url_for("buoni_carico"))

            codice = buono.codice_buono or str(buono.id)

            try:
                db.query(BuonoCaricoScan).filter(BuonoCaricoScan.buono_id == buono.id).delete(synchronize_session=False)
            except Exception:
                pass

            try:
                db.query(BuonoCaricoRiga).filter(BuonoCaricoRiga.buono_id == buono.id).delete(synchronize_session=False)
            except Exception:
                pass

            db.delete(buono)
            db.commit()
            flash(f"Buono di carico {codice} eliminato.", "success")
            return redirect(url_for("buoni_carico"))
        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore elimina buono carico", e)
            except Exception:
                pass
            flash(f"Errore eliminazione buono di carico: {e}", "danger")
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono_id))
        finally:
            db.close()


    @app.route("/buoni_carico/<int:buono_id>/stampa.pdf")
    @login_required
    @require_admin_or_magazzino
    def stampa_buono_carico_pdf(buono_id):
        """Genera la stampa PDF operativa del buono di carico."""
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                flash("Buono di carico non trovato.", "danger")
                return redirect(url_for("buoni_carico"))

            righe = _righe_buono_carico(db, buono)
            stats = _stats_buono_carico(db, buono)

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=12*mm,
                leftMargin=12*mm,
                topMargin=12*mm,
                bottomMargin=12*mm
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "TitoloBuonoCarico",
                parent=styles["Title"],
                fontSize=16,
                alignment=TA_CENTER,
                spaceAfter=8
            )
            normal = styles["Normal"]
            small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
            from xml.sax.saxutils import escape as _xml_escape

            def _pdf_text_cell(value, style=small):
                """Cella PDF con ritorno a capo automatico; separa anche liste con / o ;."""
                s = str(value or "").strip()
                s = _xml_escape(s)
                s = s.replace(" / ", "<br/>").replace("; ", "<br/>")
                return Paragraph(s or "-", style)


            story = []

            # Logo opzionale
            try:
                if LOGO_PATH and Path(LOGO_PATH).exists():
                    story.append(RLImage(LOGO_PATH, width=38*mm, height=14*mm))
                    story.append(Spacer(1, 4))
            except Exception:
                pass

            story.append(Paragraph(f"BUONO DI CARICO {buono.codice_buono or ''}", title_style))
            story.append(Spacer(1, 6))

            dati = [
                ["Cliente", _pdf_text_cell(buono.cliente), "Stato", _pdf_text_cell(buono.stato or "DA CARICARE")],
                ["Fornitore", _pdf_text_cell(buono.fornitore), "Data", _pdf_text_cell(buono.data_ingresso)],
                ["Colli previsti", str(stats.get("previsti", 0)), "Colli caricati", str(stats.get("ok", 0))],
                ["Colli mancanti", str(stats.get("mancanti", 0)), "Peso previsto", it_num(buono.peso_previsto or 0, 2) + " kg"],
            ]
            t = Table(dati, colWidths=[32*mm, 62*mm, 32*mm, 50*mm])
            t.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
                ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
                ("BACKGROUND", (2,0), (2,-1), colors.whitesmoke),
                ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 4),
                ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ]))
            story.append(t)
            story.append(Spacer(1, 10))

            story.append(Paragraph("Arrivi collegati", styles["Heading3"]))

            data = [[
                "ID", "Fornitore", "Codice", "Descrizione", "N. Arrivo", "DDT Ing", "Colli", "Peso", "QR/Codice entrata"
            ]]

            if righe:
                for r in righe:
                    data.append([
                        str(r.id_articolo or ""),
                        _pdf_text_cell(r.fornitore),
                        _pdf_text_cell(r.codice_articolo),
                        _pdf_text_cell(r.descrizione),
                        _pdf_text_cell(r.n_arrivo),
                        _pdf_text_cell(r.n_ddt_ingresso),
                        str(r.colli_previsti or 0),
                        it_num(r.peso_previsto or 0, 2),
                        _pdf_text_cell(r.codice_entrata),
                    ])
            else:
                data.append([
                    str(getattr(buono, "id_articolo_origine", "") or ""),
                    _pdf_text_cell(buono.fornitore),
                    _pdf_text_cell(getattr(buono, "codice_articolo", "")),
                    _pdf_text_cell(getattr(buono, "descrizione", "")),
                    _pdf_text_cell(buono.n_arrivo),
                    _pdf_text_cell(buono.n_ddt_ingresso),
                    str(buono.pallet_previsti or 0),
                    it_num(buono.peso_previsto or 0, 2),
                    _pdf_text_cell(buono.codice_entrata),
                ])

            tab = Table(data, repeatRows=1, colWidths=[10*mm, 22*mm, 25*mm, 38*mm, 20*mm, 18*mm, 10*mm, 15*mm, 42*mm])
            tab.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 7),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 3),
                ("RIGHTPADDING", (0,0), (-1,-1), 3),
            ]))
            story.append(tab)
            story.append(Spacer(1, 14))

            story.append(Paragraph("Controllo magazzino", styles["Heading3"]))
            controllo = [
                ["Firma magazzino", ""],
                ["Note controllo", ""],
                ["Data completamento", ""],
            ]
            t2 = Table(controllo, colWidths=[40*mm, 140*mm], rowHeights=[14*mm, 18*mm, 14*mm])
            t2.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.4, colors.grey),
                ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("FONTSIZE", (0,0), (-1,-1), 9),
            ]))
            story.append(t2)

            story.append(Spacer(1, 10))
            story.append(Paragraph(
                "Il buono deve essere verificato tramite scansione QR: se il QR non appartiene agli arrivi collegati, il gestionale segnala arrivo sbagliato / non da caricare.",
                small
            ))

            doc.build(story)
            buffer.seek(0)

            filename = f"buono_carico_{(buono.codice_buono or buono.id)}.pdf".replace("/", "_")
            return send_file(buffer, as_attachment=False, download_name=filename, mimetype="application/pdf")

        except Exception as e:
            try:
                scrivi_log_errore("Errore stampa buono carico PDF", e)
            except Exception:
                pass
            flash(f"Errore stampa buono di carico: {e}", "danger")
            return redirect(url_for("dettaglio_buono_carico", buono_id=buono_id))
        finally:
            db.close()


    @app.route("/buoni_carico/<int:buono_id>/qr.png")
    @login_required
    @require_admin_or_magazzino
    def qr_buono_carico(buono_id):
        db = SessionLocal()
        try:
            buono = db.query(BuonoCarico).filter(BuonoCarico.id == buono_id).first()
            if not buono:
                abort(404)
            payload = (_codici_validi_buono_carico(db, buono)[0] if _codici_validi_buono_carico(db, buono) else (buono.codice_entrata or buono.codice_buono))
            try:
                import qrcode
                img = qrcode.make(payload)
                bio = io.BytesIO()
                img.save(bio, format="PNG")
                bio.seek(0)
                return send_file(bio, mimetype="image/png")
            except Exception:
                from PIL import Image, ImageDraw
                img = Image.new("RGB", (420, 180), "white")
                d = ImageDraw.Draw(img)
                d.text((15, 30), "QR non disponibile", fill="black")
                d.text((15, 70), payload[:45], fill="black")
                bio = io.BytesIO()
                img.save(bio, format="PNG")
                bio.seek(0)
                return send_file(bio, mimetype="image/png")
        finally:
            db.close()
