is_marine_interiors_riga = _cliente_marine_interiors(cliente_riga)
peso_originale = _num_float(getattr(r, "peso", None))
peso_scelto = peso_originale
                colli_scelti = 1
                colli_originali_db = getattr(r, "n_colli", None)
                colli_scelti = colli_originali_db

if is_galvano_riga:
lotto_originale = str(getattr(r, "lotto", "") or "").strip()
@@ -1179,17 +1180,19 @@ class BuonoValidationError(Exception):
f"GALVANO TECNICA - Pezzi insufficienti per il lotto {lotto}: "
f"richiesti {_fmt_num_clean(pezzi_scelti)}, disponibili {_fmt_num_clean(pezzi_originali)}."
)
                    # Galvano Tecnica: ogni riga deve avere almeno 1 collo.
                    # Se il campo viene lasciato vuoto, usa automaticamente 1
                    # invece di bloccare il salvataggio del Buono.
                    default_colli = "1"
                    colli_raw = (req_data.get(f"colli_buono_{rid}") or default_colli).strip()
                    try:
                        colli_scelti = int(colli_raw)
                    except (TypeError, ValueError):
                        raise BuonoValidationError(f"Inserisci un numero di colli valido per il lotto {lotto}.")
                    if colli_scelti <= 0:
                        raise BuonoValidationError(f"I colli per il lotto {lotto} devono essere almeno 1.")
                    # Galvano Tecnica: i colli sono facoltativi.
                    # Se in Giacenze il campo è vuoto e l'operatore lo lascia vuoto,
                    # anche il Buono e il database devono restare vuoti.
                    colli_raw = str(req_data.get(f"colli_buono_{rid}") or "").strip()
                    if colli_raw:
                        try:
                            colli_scelti = int(float(colli_raw.replace(",", ".")))
                        except (TypeError, ValueError):
                            raise BuonoValidationError(f"Inserisci un numero di colli valido per il lotto {lotto}, oppure lascia il campo vuoto.")
                        if colli_scelti <= 0:
                            raise BuonoValidationError(f"I colli per il lotto {lotto} devono essere maggiori di zero, oppure il campo deve restare vuoto.")
                    else:
                        colli_scelti = None

peso_raw = (req_data.get(f"peso_buono_{rid}") or "").strip()
if not peso_raw:
@@ -1332,6 +1335,7 @@ class BuonoValidationError(Exception):
'peso_scelto': peso_scelto,
'peso_residuo': max(0.0, peso_originale - peso_scelto),
'colli_scelti': colli_scelti,
                    'colli_originali_db': colli_originali_db,
})

scarico_parziale_eseguito = False
@@ -1357,7 +1361,8 @@ class BuonoValidationError(Exception):
peso_originale = item.get('peso_originale', _num_float(getattr(r, 'peso', None)))
peso_scelto = item.get('peso_scelto', peso_originale)
peso_residuo = item.get('peso_residuo', max(0.0, peso_originale - peso_scelto))
                colli_scelti = item.get('colli_scelti', 1)
                colli_scelti = item.get('colli_scelti')
                colli_originali_db = item.get('colli_originali_db', getattr(r, 'n_colli', None))

cod_parziale = bool(_norm_for_match(codice_scelto) != _norm_for_match(old_cod))
desc_parziale = bool(descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc))
@@ -1393,11 +1398,10 @@ class BuonoValidationError(Exception):
)
setattr(riga_buono, campo, _round_db_number(scelto_val))
setattr(r, campo, _round_db_number(residuo_val))
                        # Regola Galvano: ogni riga del Buono vale di default 1 collo,
                        # modificabile manualmente dall'operatore in anteprima.
                        # Galvano: il Buono usa il valore digitato; se vuoto resta vuoto.
                        # La riga residua conserva esattamente i colli originari della Giacenza.
riga_buono.n_colli = colli_scelti
                        # Se resta materiale in giacenza, la riga residua continua a rappresentare 1 collo.
                        r.n_colli = 1
                        r.n_colli = colli_originali_db
else:
for campo in ('peso', 'm2', 'm3'):
residuo_val, scelto_val = _split_quantita(
