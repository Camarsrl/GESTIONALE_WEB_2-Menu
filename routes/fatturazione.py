# -*- coding: utf-8 -*-
"""
Modulo Fatturazione / Report - fix Galvano Tecnica.

Correzione applicata anche nel file principale:
- per Galvano Tecnica il conteggio pallet usa N° Colli;
- i colli vuoti valgono 0 e NON 1;
- gli articoli usciti entro la fine del mese selezionato vengono esclusi.
"""

def register_fatturazione_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj
    # Le route fatturazione sono già presenti nel file principale corretto.
