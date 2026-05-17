# -*- coding: utf-8 -*-
"""
Modulo Fatturazione / Report - Step 1.
File preparato per routes/fatturazione.py.
"""

def register_fatturazione_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj
    # Step sicuro: registrazione modulo fatturazione pronta.
