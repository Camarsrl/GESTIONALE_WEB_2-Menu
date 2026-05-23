# -*- coding: utf-8 -*-
"""
Entrypoint del gestionale.
Per Render puoi usare: gunicorn app:app
Oppure continuare temporaneamente con: gunicorn gestionale_web_full:app
"""
from gestionale_web_full import app
