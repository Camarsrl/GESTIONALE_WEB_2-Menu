# -*- coding: utf-8 -*-
"""
CAMY Procedure - Manuale operativo intelligente CAMAR.

Modulo sicuro: NON modifica il database.
Serve a CAMY per spiegare al collega le procedure del gestionale passo passo.

Installazione:
1) Salvare questo file in: routes/camy_procedure.py
2) In routes/camy_ai.py aggiungere l'import e il richiamo indicati sotto.
"""

import re
from html import escape


def module_status():
    return "camy_procedure attivo - manuale operativo CAMAR"


def _norm(text):
    return re.sub(r"[^a-z0-9àèéìòù]+", " ", str(text or "").lower()).strip()


def _btn(label, href, color="primary"):
    return f"<a class='btn btn-sm btn-outline-{color} mt-2 me-1' href='{escape(href)}'>{escape(label)}</a>"


PROCEDURE = {
    "accettazione_entrata": {
        "title": "📥 Procedura - Accettazione Entrata",
        "keywords": [
            "accettazione entrata", "entrata", "nuovo arrivo", "registrare arrivo",
            "caricare arrivo", "documento entrata", "ddt ingresso", "come faccio entrata"
        ],
        "html": """
<b>📥 Procedura - Accettazione Entrata</b><br><br>
1. Apri <b>Accettazione Entrata</b> dalla Home.<br>
2. Carica il <b>PDF</b>, una <b>foto</b> del documento oppure inserisci i dati manualmente.<br>
3. Controlla i dati estratti da CAMY/OCR.<br>
4. Compila tutti i campi richiesti:<br>
&nbsp;&nbsp;• Cliente<br>
&nbsp;&nbsp;• Fornitore<br>
&nbsp;&nbsp;• Commessa<br>
&nbsp;&nbsp;• Ordine<br>
&nbsp;&nbsp;• Protocollo, se richiesto dal cliente<br>
&nbsp;&nbsp;• N. Arrivo<br>
&nbsp;&nbsp;• N. DDT ingresso<br>
&nbsp;&nbsp;• Magazzino e posizione<br>
&nbsp;&nbsp;• Codice articolo / marca pezzo<br>
&nbsp;&nbsp;• Descrizione<br>
&nbsp;&nbsp;• Quantità, colli, peso e misure se presenti<br>
5. Verifica bene che cliente, arrivo, codice e quantità siano corretti.<br>
6. Premi <b>Salva Entrata</b> oppure <b>Etichetta + Entrata automatica</b> se previsto.<br>
7. Stampa le <b>etichette</b> da applicare ai colli/bancali.<br>
8. Dopo aver compilato e salvato tutto, <b>invia l'e-mail al cliente</b> con il riepilogo dell'entrata e gli eventuali allegati/foto.<br>
9. Controlla in <b>Visualizza Giacenze</b> che il materiale sia presente e corretto.<br><br>
<b>Promemoria importante:</b><br>
• Per FINCANTIERI / ARMATORE / SCOPERTO controllare sempre il protocollo.<br>
• Per RF-DE WAVE controllare sempre le foto.<br>
""",
        "buttons": [("📥 Apri Accettazione Entrata", "/accettazione_entrata", "success"), ("📦 Apri Giacenze", "/giacenze", "primary")]
    },

    "buono": {
        "title": "📦 Procedura - Buono di Prelievo",
        "keywords": [
            "buono", "buono di prelievo", "creare buono", "come faccio buono",
            "prelievo", "scarico parziale", "cartelli bancali", "picking da buono"
        ],
        "html": """
<b>📦 Procedura - Buono di Prelievo</b><br><br>
1. Apri <b>Visualizza Giacenze</b>.<br>
2. Cerca il materiale con i filtri: cliente, arrivo, codice, ordine, commessa o protocollo.<br>
3. Seleziona tutte le righe da prelevare. Puoi selezionare anche righe su più pagine.<br>
4. Premi il pulsante <b>Buono</b>.<br>
5. Nella schermata del buono controlla:<br>
&nbsp;&nbsp;• N. Buono automatico o manuale<br>
&nbsp;&nbsp;• Data<br>
&nbsp;&nbsp;• Ordine / Commessa / Fornitore / Protocollo<br>
&nbsp;&nbsp;• Codice da mettere nel buono<br>
&nbsp;&nbsp;• Descrizione<br>
&nbsp;&nbsp;• Quantità<br>
&nbsp;&nbsp;• Note<br>
6. Se una riga contiene più codici, lascia nel campo solo il codice da prelevare: CAMY farà lo <b>scarico parziale</b> mantenendo il residuo in giacenza.<br>
7. Se serve, lascia attiva la spunta <b>Crea Picking al salvataggio</b>.<br>
8. Se serve stampare i cartelli, lascia spuntata la colonna <b>Cartello?</b> e compila <b>N. Pallet</b> per ogni riga.<br>
9. Premi <b>Anteprima PDF</b> per controllare.<br>
10. Premi <b>Genera e Salva</b> per salvare il buono e scaricare il PDF.<br>
11. Se devi stampare i cartelli, premi <b>Cartello Bancali</b>: verrà creato un cartello per ogni riga spuntata.<br>
12. Se il materiale deve uscire, crea il <b>DDT dal Buono</b>.<br><br>
<b>Controlli da fare prima di salvare:</b><br>
• Verificare che il materiale non sia già uscito.<br>
• Verificare quantità e descrizione.<br>
• Verificare che il cartello sia spuntato solo per i pallet da stampare.<br>
""",
        "buttons": [("📦 Apri Giacenze", "/giacenze", "primary"), ("📧 Buono da Email", "/camy-email-buono", "success")]
    },

    "ddt": {
        "title": "🚛 Procedura - DDT",
        "keywords": ["ddt", "creare ddt", "ddt da buono", "documento trasporto", "finalizza ddt"],
        "html": """
<b>🚛 Procedura - DDT</b><br><br>
1. Parti sempre dal <b>Buono di Prelievo</b> già creato.<br>
2. Apri la funzione <b>Crea DDT dal Buono</b> oppure chiedi a CAMY: <i>Crea DDT dal buono ...</i><br>
3. Controlla le righe inserite nel DDT.<br>
4. Compila destinatario, indirizzo, data, targa/mezzo e trasportatore se richiesti.<br>
5. Controlla i totali: colli, peso e materiale.<br>
6. Premi <b>Anteprima</b> per verificare il PDF.<br>
7. Premi <b>Finalizza</b> solo quando è tutto corretto.<br>
8. Invia il PDF al responsabile/cliente se richiesto.<br>
9. Registra il trasporto nella sezione <b>Trasporti</b> se necessario.<br><br>
<b>Attenzione:</b> il progressivo DDT deve essere salvato solo quando finalizzi.
""",
        "buttons": [("📦 Apri Giacenze", "/giacenze", "primary"), ("🚚 Apri Trasporti", "/trasporti", "success")]
    },

    "cartelli": {
        "title": "📋 Procedura - Cartelli Bancali",
        "keywords": ["cartelli", "cartello", "cartelli bancali", "cartello bancale", "pallet", "bancali"],
        "html": """
<b>📋 Procedura - Cartelli Bancali</b><br><br>
1. Crea o apri il <b>Buono di Prelievo</b>.<br>
2. Nella tabella del buono controlla la colonna <b>Cartello?</b>.<br>
3. Lascia la spunta solo sulle righe per cui vuoi stampare il cartello.<br>
4. Compila <b>N. Pallet</b> per ogni riga/pallet.<br>
5. Premi <b>Cartello Bancali</b>.<br>
6. Il gestionale genera un PDF con <b>un cartello per ogni riga spuntata</b>.<br>
7. Stampa il PDF e applica ogni cartello al pallet corretto.<br><br>
<b>Controllo:</b> in basso al cartello deve comparire <b>CARTELLO 1 DI X</b>, <b>CARTELLO 2 DI X</b>, ecc.
""",
        "buttons": [("📦 Apri Giacenze", "/giacenze", "primary")]
    },

    "picking": {
        "title": "📋 Procedura - Picking / Lavorazioni",
        "keywords": ["picking", "lavorazioni", "palletizzazione", "filmatura", "ore blue", "ore white"],
        "html": """
<b>📋 Procedura - Picking / Lavorazioni</b><br><br>
1. Il Picking può essere creato direttamente dal Buono se la spunta <b>Crea Picking al salvataggio</b> è attiva.<br>
2. Controlla o compila:<br>
&nbsp;&nbsp;• Data<br>
&nbsp;&nbsp;• Cliente<br>
&nbsp;&nbsp;• Descrizione lavorazione<br>
&nbsp;&nbsp;• Richiesta di<br>
&nbsp;&nbsp;• Seriali / N. Buono<br>
&nbsp;&nbsp;• N. Arrivo<br>
&nbsp;&nbsp;• Colli<br>
&nbsp;&nbsp;• Pallet entrati / usciti<br>
&nbsp;&nbsp;• Ore Blue / Ore White<br>
3. Salva il Buono: il Picking viene registrato automaticamente.<br>
4. In alternativa apri la sezione <b>Picking/Lavorazioni</b> e inserisci manualmente i dati.<br>
""",
        "buttons": [("📋 Apri Picking", "/lavorazioni", "success")]
    },

    "trasporti": {
        "title": "🚚 Procedura - Trasporti",
        "keywords": ["trasporto", "trasporti", "trasportatore", "costo trasporto", "excel trasporti"],
        "html": """
<b>🚚 Procedura - Trasporti</b><br><br>
1. Apri la sezione <b>Trasporti</b>.<br>
2. Compila data, tipo mezzo, cliente, trasportatore, DDT uscita, magazzino e costo se disponibile.<br>
3. Salva il trasporto.<br>
4. Se richiesto, stampa il report o crea l'export Excel.<br>
5. Controlla che il DDT sia collegato correttamente al trasporto.<br>
""",
        "buttons": [("🚚 Apri Trasporti", "/trasporti", "success")]
    },

    "etichette": {
        "title": "🏷️ Procedura - Etichette",
        "keywords": ["etichette", "etichetta", "stampare etichette", "ql 800", "barcode", "qr"],
        "html": """
<b>🏷️ Procedura - Etichette</b><br><br>
1. Seleziona gli articoli da <b>Visualizza Giacenze</b> oppure stampa dopo l'Accettazione Entrata.<br>
2. Premi <b>Etichette</b>.<br>
3. Controlla formato e quantità.<br>
4. Stampa con la stampante etichette corretta.<br>
5. Applica l'etichetta al collo/pallet corrispondente.<br>
""",
        "buttons": [("🏷️ Apri Etichette", "/labels", "success"), ("📦 Apri Giacenze", "/giacenze", "primary")]
    },

    "email": {
        "title": "📧 Procedura - Invio Email Cliente",
        "keywords": ["email", "e-mail", "mail", "inviare email", "mandare mail", "cliente"],
        "html": """
<b>📧 Procedura - Invio Email Cliente</b><br><br>
1. Apri la funzione <b>Invia Email</b> dalla giacenza o dalla procedura interessata.<br>
2. Seleziona o scrivi il destinatario.<br>
3. Controlla l'oggetto e il testo dell'e-mail.<br>
4. Verifica il riepilogo del materiale: cliente, arrivo, codice, colli, peso e descrizione.<br>
5. Aggiungi allegati se servono: foto, documenti, DDT o buono.<br>
6. Premi <b>Invia</b>.<br>
7. Controlla che non compaiano errori di invio.<br><br>
<b>Per Accettazione Entrata:</b> dopo aver compilato tutti i campi e salvato l'entrata, inviare sempre l'e-mail al cliente con il riepilogo.
""",
        "buttons": [("📦 Apri Giacenze", "/giacenze", "primary")]
    },

    "inventario": {
        "title": "📦 Procedura - Inventario",
        "keywords": ["inventario", "confronta inventario", "correggere giacenze", "export inventario"],
        "html": """
<b>📦 Procedura - Inventario</b><br><br>
1. Apri <b>Visualizza Giacenze</b> e filtra il cliente.<br>
2. Usa <b>Inventario Excel</b> per esportare il materiale.<br>
3. Se hai un file inventario cliente, usa la funzione di confronto inventario se disponibile.<br>
4. Controlla differenze di codice, colli, peso, lotto o serial number in base al cliente.<br>
5. Eventuali correzioni devono essere fatte solo dopo verifica fisica del materiale.<br>
""",
        "buttons": [("📦 Apri Giacenze", "/giacenze", "primary")]
    }
}


def find_procedure_key(message):
    low = _norm(message)
    if not low:
        return ""

    # Attiva il manuale solo quando la frase è davvero una richiesta di procedura.
    procedure_words = [
        "come", "procedura", "non ricordo", "non mi ricordo", "spiegami",
        "aiuto", "manuale", "istruzioni", "come si fa", "come faccio",
        "passaggi", "fare", "creare", "registrare", "stampare", "inviare"
    ]
    if not any(w in low for w in procedure_words):
        return ""

    best_key = ""
    best_score = 0
    for key, proc in PROCEDURE.items():
        score = 0
        for kw in proc.get("keywords", []):
            nkw = _norm(kw)
            if nkw and nkw in low:
                score += max(1, len(nkw.split()))
        if score > best_score:
            best_key = key
            best_score = score
    return best_key


def is_procedure_request(message):
    return bool(find_procedure_key(message))


def render_procedure(message_or_key):
    key = message_or_key if message_or_key in PROCEDURE else find_procedure_key(message_or_key)
    if not key or key not in PROCEDURE:
        return render_procedure_index()

    proc = PROCEDURE[key]
    out = [proc.get("html", "")]
    buttons = proc.get("buttons", []) or []
    if buttons:
        out.append("<br><br>")
        for label, href, color in buttons:
            out.append(_btn(label, href, color))
    return "".join(out)


def render_procedure_index():
    out = ["<b>📚 Manuale procedure CAMY</b><br><br>"]
    out.append("Puoi chiedermi ad esempio:<br>")
    examples = [
        "Come faccio un Buono?",
        "Come faccio Accettazione Entrata?",
        "Come creo un DDT?",
        "Come stampo i cartelli bancali?",
        "Come registro un trasporto?",
        "Come mando email al cliente?",
    ]
    for ex in examples:
        out.append(f"• {escape(ex)}<br>")
    out.append("<br><b>Procedure disponibili:</b><br>")
    for key, proc in PROCEDURE.items():
        out.append(f"• <b>{escape(proc.get('title', key))}</b><br>")
    return "".join(out)
