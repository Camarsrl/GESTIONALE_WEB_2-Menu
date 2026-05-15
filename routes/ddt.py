# -*- coding: utf-8 -*-
"""
Modulo DDT - preparazione Step 4.
Le route DDT restano ancora nel file principale; saranno spostate nel prossimo step.
"""
def register_ddt_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj
    return app_obj
