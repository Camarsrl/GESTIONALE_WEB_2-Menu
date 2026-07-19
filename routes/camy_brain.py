# -*- coding: utf-8 -*-
"""
CAMY BRAIN - Cervello operativo del gestionale Camar.

Questo modulo NON modifica il database.
Serve a capire l'intento della frase dell'utente e a restituire una decisione
che camy_ai.py userà per chiamare le funzioni operative già sicure.
"""

import re
from datetime import date


def _norm(text):
    return re.sub(r"[^a-z0-9àèéìòù]+", " ", (text or "").lower()).strip()


def _has_any(text, words):
    return any(w in text for w in words)


def _extract_reference(message):
    """Estrae un riferimento operativo: buono, DDT, arrivo, codice, seriale."""
    s = message or ""
    patterns = [
        r"\bbuono\s+(?:di\s+prelievo\s+)?([A-Z0-9][A-Z0-9./_\-]{1,50})",
        r"\bpicking\s+([A-Z0-9][A-Z0-9./_\-]{1,50})",
        r"\blavorazione\s+([A-Z0-9][A-Z0-9./_\-]{1,50})",
        r"\b(?:n\.?\s*)?arrivo\s+([A-Z0-9][A-Z0-9./_\-]{1,50})",
        r"\bddt\s+([A-Z0-9][A-Z0-9./_\-]{1,50})",
        r"\b(?:marca\s*[- ]?pezzo|codice(?:\s+articolo)?)\s+([A-Z0-9][A-Z0-9./_*_\-]{1,50})",
        r"\bseriale?\s+([A-Z0-9][A-Z0-9./_\-]{1,50})",
    ]
    stop = {"CREA", "CREARE", "PREPARA", "PREPARARE", "VEDERE", "VEDI", "APRI", "MOSTRA", "CERCA"}
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if m:
            val = (m.group(1) or "").strip().strip(".,;:")
            if val and val.upper() not in stop:
                return val
    # fallback per codici tipo 586-ZETA scritti da soli nella frase
    m = re.search(r"\b([0-9]{2,6}[A-Z0-9./_\-]*[A-Z][A-Z0-9./_\-]*)\b", s, re.I)
    return (m.group(1).strip() if m else "")



def _is_procedure_question(message):
    """Riconosce richieste di manuale/procedura.

    Esempi:
    - Come faccio un'entrata?
    - Non mi ricordo come si crea un buono
    - Procedura DDT
    - Come mando la mail al cliente?
    """
    low = _norm(message)
    if not low:
        return False

    trigger = [
        "come faccio", "come si fa", "come fare", "procedura", "passaggi",
        "istruzioni", "manuale", "spiegami", "mi spieghi", "non ricordo",
        "non mi ricordo", "mi sono dimenticato", "mi sono dimenticata"
    ]
    oggetti = [
        "entrata", "accettazione", "buono", "prelievo", "ddt", "trasporto",
        "trasporti", "picking", "lavorazione", "etichette", "etichetta",
        "cartello", "cartelli", "bancali", "pallet", "email", "mail",
        "inventario", "scarico parziale", "modifica multipla"
    ]

    if any(t in low for t in trigger) and any(o in low for o in oggetti):
        return True
    # Frasi brevi tipo "procedura buono", "manuale entrata"
    if len(low.split()) <= 5 and any(t in low for t in ["procedura", "manuale", "istruzioni"]) and any(o in low for o in oggetti):
        return True
    return False


def _is_smalltalk(message):
    """Riconosce frasi umane/generiche che NON devono avviare ricerche sul magazzino."""
    low = _norm(message)
    if not low:
        return False
    # Frasi brevi di saluto o cortesia
    exact_or_short = {
        "ciao", "buongiorno", "buonasera", "buonanotte", "salve", "hey", "hei",
        "ciao camy", "buongiorno camy", "come stai", "ciao come stai",
        "grazie", "grazie camy", "ok", "va bene", "perfetto", "ottimo", "brava", "bravissima",
        "ci sei", "sei pronta", "sei operativa"
    }
    if low in exact_or_short:
        return True
    if len(low.split()) <= 5 and any(x in low for x in ["come stai", "ciao", "buongiorno", "buonasera", "grazie", "ci sei"]):
        return True
    return False


def camy_smalltalk_answer(message):
    low = _norm(message)
    if "grazie" in low:
        return "Prego Alessia 😊 Sono qui per aiutarti con il gestionale."
    if "come stai" in low:
        return "Ciao Alessia 😊 Sto bene e sono pronta ad aiutarti con giacenze, buoni, DDT, picking, trasporti, entrate e report."
    if "ci sei" in low or "pronta" in low or "operativa" in low:
        return "Sì, ci sono 😊 Dimmi cosa vuoi controllare o preparare nel gestionale."
    return "Ciao Alessia 😊 Sono pronta. Puoi chiedermi giacenze, buoni, DDT, picking, trasporti, entrate o report."

def decide_camy_intent(message):
    """Ritorna una decisione stabile.

    Campi principali:
    - action: azione interna che camy_ai.py deve eseguire
    - target: riferimento estratto, se presente
    - confidence: valore indicativo
    """
    raw = message or ""
    low = _norm(raw)
    target = _extract_reference(raw)

    # Prima regola: le frasi di saluto/cortesia non devono diventare ricerche su tutte le giacenze.
    if _is_smalltalk(raw):
        return {"action": "smalltalk", "target": target, "confidence": 0.99, "raw": raw}

    # Manuale procedure: deve prevalere sulle azioni operative.
    # Esempio: "Come faccio un buono?" deve spiegare, non creare un buono.
    if _is_procedure_question(raw):
        return {"action": "procedura", "target": target, "confidence": 0.99, "raw": raw}

    view_words = ["vedere", "vedi", "mostra", "mostrami", "aprire", "apri", "visualizza", "fammi vedere", "voglio vedere", "cerca", "trova", "dove"]
    create_words = ["crea", "creare", "prepara", "preparare", "genera", "generare", "aggiungi", "scarico", "scarica", "salva"]

    # Aiuto / capacità
    if _has_any(low, ["aiuto", "help", "cosa puoi fare", "cosa sai fare", "come funzioni"]):
        return {"action": "help", "target": target, "confidence": 0.99, "raw": raw}

    # Scanner QR
    if _has_any(low, ["scanner", "scan qr", "scansione qr", "pistola", "lettore qr", "prelievo qr", "wifi qr", "bluetooth qr", "usb qr"]):
        return {"action": "scan_qr", "target": target, "confidence": 0.98, "raw": raw}

    # Registro / quaderno / lavoro giornaliero
    if _has_any(low, ["registro giornaliero", "registro di oggi", "quaderno", "riepilogo giornata", "riepilogo di oggi", "lavoro di oggi", "lavori di oggi"]):
        return {"action": "registro_giornaliero", "target": target, "confidence": 0.98, "raw": raw}

    # Cosa manca / alert operativi
    if _has_any(low, [
        "cosa manca", "manca da fare", "attivita aperte", "attività aperte",
        "controlla aperti", "anomalie", "da fare oggi",
        "protocollo mancante", "protocolli mancanti", "senza protocollo",
        "mancano protocollo", "mancano protocolli",
        "foto mancanti", "senza foto",
        "mezzo mancante", "senza mezzo", "ddt senza mezzo",
        "quali protocolli", "quali protocollo", "quali protocolli mancano", "protocolli mancanti", "fincantieri armatore senza protocollo", "fincantieri scoperto senza protocollo", "protocolli mancanti fincantieri armatore", "protocolli mancanti fincantieri scoperto"
    ]):
        return {"action": "cosa_manca", "target": target, "confidence": 0.98, "raw": raw}

    # Situazione operativa / briefing intelligente
    if _has_any(low, ["come siamo messi", "situazione operativa", "situazione di oggi", "quadro giornata", "briefing", "briefing operativo", "punto della situazione", "resoconto operativo", "stato giornata", "dashboard operativa"]):
        return {"action": "situazione_operativa", "target": target, "confidence": 0.99, "raw": raw}

    # Accettazione entrata
    if _has_any(low, ["accettazione entrata", "apri entrata", "nuova entrata", "nuovo arrivo", "documento entrata", "carica documento"]):
        return {"action": "accettazione_entrata", "target": target, "confidence": 0.96, "raw": raw}

    # DDT: CAMY prepara il documento dal Buono e chiede sempre conferma.
    if "ddt" in low and _has_any(low, ["crea", "prepara", "genera", "fammi", "fai", "fallo"]):
        return {"action": "prepare_ddt", "target": target, "confidence": 0.99, "raw": raw}

    # Buoni: distingue apertura da creazione
    if "buono" in low:
        if _has_any(low, ["aggiungi", "metti", "inserisci"]) and _has_any(low, ["al buono", "nel buono", "a buono"]):
            return {"action": "add_to_buono", "target": target, "confidence": 0.97, "raw": raw}
        if _has_any(low, ["prepara", "crea", "genera", "assegna", "fammi", "fai", "fallo"]) and not _has_any(low, ["vedi", "vedere", "mostra", "apri", "aprire"]):
            return {"action": "prepare_buono", "target": target, "confidence": 0.97, "raw": raw}
        if _has_any(low, view_words) or target:
            return {"action": "open_buono", "target": target, "confidence": 0.98, "raw": raw}

    # Picking / lavorazioni
    if _has_any(low, ["picking", "lavorazione", "lavorazioni", "filmat", "palletizz"]):
        return {"action": "search_picking", "target": target, "confidence": 0.95, "raw": raw}

    # Trasporti
    if _has_any(low, ["trasporto", "trasporti", "trasportatore", "motrice", "bilico", "donato", "camion"]):
        return {"action": "search_trasporti", "target": target, "confidence": 0.95, "raw": raw}

    # Scarico parziale
    if _has_any(low, ["scarico parziale", "scarica parziale"]):
        return {"action": "scarico_parziale", "target": target, "confidence": 0.96, "raw": raw}


    # Comandi contestuali: CAMY AI aggiungerà il riferimento precedente dalla memoria operativa.
    if _has_any(low, ["fallo", "falla", "fammi", "fai", "preparalo", "crealo", "creala"]):
        if "buono" in low:
            return {"action": "prepare_buono", "target": target, "confidence": 0.88, "raw": raw}
        if "ddt" in low:
            return {"action": "prepare_ddt", "target": target, "confidence": 0.88, "raw": raw}
        if "scarico" in low:
            return {"action": "scarico_parziale", "target": target, "confidence": 0.86, "raw": raw}

    # Ricerca globale se c'è un riferimento operativo e parole generiche
    if target and (_has_any(low, view_words) or _has_any(low, ["dove", "quale", "quali", "trova", "cerca"])):
        return {"action": "search_global", "target": target, "confidence": 0.90, "raw": raw}

    return {"action": "fallback", "target": target, "confidence": 0.50, "raw": raw}


def camy_brain_help():
    return (
        "<b>CAMY Centrale Operativa</b><br>"
        "Puoi chiedermi, anche con frasi naturali:<br>"
        "• Voglio vedere il buono 586-ZETA<br>"
        "• Apri picking 2058114-ENTALPIA<br>"
        "• Mostrami i trasporti di oggi<br>"
        "• Come siamo messi oggi?<br>"
        "• Cosa manca da fare oggi?<br>"
        "• Quali protocolli mancano di Fincantieri?<br>"
        "• Mostrami gli articoli Fincantieri senza protocollo<br>"
        "• Quali arrivi RF-DE WAVE sono senza foto?<br>"
        "• Quali DDT Fincantieri sono senza mezzo?<br>"
        "• Genera registro giornaliero di oggi<br>"
        "• Crea DDT dal buono 586-ZETA<br>"
        "• Prepara buono del marca pezzo CB051CF pezzi 4 cliente FINCANTIERI package N.11<br>"
        "• Prepara buono arrivo 200/26<br>"
        "• Cerca codice CB050CF<br>"
        "• Apri accettazione entrata<br>"
        "• Come faccio un'entrata?<br>"
        "• Come preparo un buono?<br>"
        "• Procedura DDT<br>"
        "• Come mando email al cliente?<br><br>"
        "Le modifiche operative restano sempre con conferma."
    )
