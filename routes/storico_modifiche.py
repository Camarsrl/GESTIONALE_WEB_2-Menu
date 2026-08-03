# -*- coding: utf-8 -*-
"""Compatibilità con il vecchio storico a una riga per campo.

Il modello principale e la visualizzazione sono ora definiti in gestionale_web_full.py.
Questa funzione resta disponibile per eventuali moduli esterni che la importano.
"""
from datetime import datetime
from sqlalchemy import text


def salva_storico(db, articolo_id, utente, campo, vecchio, nuovo, commit=False):
    """Salva una variazione nella tabella storico_modifiche.

    Per impostazione predefinita non esegue commit, così la registrazione resta nella
    stessa transazione dell'operazione principale. Impostare commit=True solo quando
    la funzione viene chiamata fuori da una transazione già gestita.
    """
    try:
        db.execute(text("""
            INSERT INTO storico_modifiche
            (articolo_id, utente, campo, valore_vecchio, valore_nuovo, data_modifica)
            VALUES
            (:articolo_id, :utente, :campo, :vecchio, :nuovo, :data_modifica)
        """), {
            'articolo_id': int(articolo_id),
            'utente': str(utente or 'SISTEMA'),
            'campo': str(campo or ''),
            'vecchio': '' if vecchio is None else str(vecchio),
            'nuovo': '' if nuovo is None else str(nuovo),
            'data_modifica': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        if commit:
            db.commit()
        return True
    except Exception:
        if commit:
            db.rollback()
        return False
