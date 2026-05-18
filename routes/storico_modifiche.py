# -*- coding: utf-8 -*-
from datetime import datetime
from sqlalchemy import Column, Integer, Text
from sqlalchemy.orm import declarative_base

BaseStorico = declarative_base()

class StoricoModifica(BaseStorico):
    __tablename__ = "storico_modifiche"

    id = Column(Integer, primary_key=True)
    articolo_id = Column(Integer)
    utente = Column(Text)
    campo = Column(Text)
    valore_vecchio = Column(Text)
    valore_nuovo = Column(Text)
    data_modifica = Column(Text)

def salva_storico(db, articolo_id, utente, campo, vecchio, nuovo):
    try:
        rec = StoricoModifica(
            articolo_id=articolo_id,
            utente=utente,
            campo=campo,
            valore_vecchio=str(vecchio or ""),
            valore_nuovo=str(nuovo or ""),
            data_modifica=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        db.add(rec)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
