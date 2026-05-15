# -*- coding: utf-8 -*-
"""
Modulo Buoni di Carico QR - Step 1 modularizzazione.

Questo file è stato creato per iniziare a separare la funzione Buoni QR
dal file principale gestionale_web_full.py.

NOTA IMPORTANTE:
Per sicurezza, in questo primo step il gestionale continua a usare le route
presenti nel file principale. Nel prossimo step possiamo spostare qui
le route definitive e registrare il Blueprint in app.py/gestionale_web_full.py.
"""

from flask import Blueprint

buoni_qr_bp = Blueprint("buoni_qr", __name__)

# Qui verranno spostate progressivamente:
# - elenco buoni carico
# - dettaglio buono
# - creazione buono
# - aggiunta arrivi
# - scansione QR
# - stampa PDF buono
# - eliminazione buono
#
# La divisione graduale evita internal error dovuti a spostamenti troppo grandi.
