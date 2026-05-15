# -*- coding: utf-8 -*-
"""
Modulo Magazzino - preparazione Step 3.

In questo step prepariamo la separazione del Magazzino.
Per sicurezza la route principale delle giacenze resta ancora in gestionale_web_full.py.
"""

def register_magazzino_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj
    return app_obj
