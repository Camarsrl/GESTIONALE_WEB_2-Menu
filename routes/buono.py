# -*- coding: utf-8 -*-
"""
Modulo Buono di Prelievo.

Gestisce:
- anteprima buono
- generazione/salvataggio buono
- scarico parziale da celle "codice articolo" e "descrizione"

Uso operativo:
se in una riga sono presenti più codici/descrizioni, nel preview del buono si lascia
solo il codice/descrizione da prelevare. Con lo scarico parziale viene creata una nuova riga con N. buono, note e pezzi prelevati;
la riga originale resta in giacenza con il residuo, senza note del buono e senza N. buono.
"""

def register_buono_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    def _split_multi_value(value):
        """Divide una cella multi-valore senza rompere gli slash/asterischi interni.

        Esempi gestiti:
        - Package No.305 -DR/018DF -DR/021DF
        - Package No.311-AP/060VR -VA/002VR -AV*002VD
        - NG/147VD / NG/146VD

        Il Package resta separato; i codici vengono poi ricostruiti con " - ".
        """
        s = str(value or "").strip()
        if not s:
            return []

        s = re.sub(r"[\r\n]+", " - ", s)
        s = re.sub(r"(?i)\bPackage\s+No\.?\s*", "Package No.", s)

        # Se il Package è scritto attaccato al primo marca-pezzo, lo separo.
        # Esempi:
        #   PACKAGE 11-CB052CB-CB...  -> PACKAGE 11 - CB052CB-CB...
        #   Package No.311-AP/060VR  -> Package No.311 - AP/060VR
        # In questo modo il Package resta sempre sulla riga residua mentre viene
        # eliminato soltanto il codice effettivamente prelevato.
        s = re.sub(
            r"(?i)\b((?:PACKAGE|PKG)\s*(?:(?:NO|N)\.?)?\s*[:#.]?\s*[A-Z0-9]+)\s*-\s*(?=[A-Z0-9])",
            r"\1 - ",
            s,
        )

        # Se il riferimento logistico e il primo marca-pezzo sono separati
        # soltanto da uno spazio, li divide comunque.
        # Esempi:
        #   Package No.311 UR/014VD
        #   Package No.311 VA/002VR
        #   PACKAGE N.11 CB051CF
        #   CASSA 12 AV*002VD
        s = re.sub(
            r"(?i)\b("
            r"(?:PACKAGE|PKG)\s*(?:(?:NO|N)\.?)?\s*[:#.]?\s*[A-Z0-9]+"
            r"|PALLET\s*[:#.]?\s*[A-Z0-9]+"
            r"|(?:CASSA|CASE)\s*[:#.]?\s*[A-Z0-9]+"
            r")\s+(?="
            r"(?:[A-Z0-9]{1,25}(?:/|\*)[A-Z0-9]+)"
            r"|(?:[A-Z]{1,12}\d[A-Z0-9]*)"
            r")",
            r"\1 - ",
            s,
        )

        # Se dopo un trattino inizia un marca-pezzo con / oppure *, separo.
        # Non rompe lo slash interno di SE/007VD e riconosce AV*002VD.
        s = re.sub(r"\s*-\s*(?=[A-Z0-9]{1,25}(?:/|\*)[A-Z0-9])", " - ", s, flags=re.I)

        # Se i marca-pezzi sono concatenati con trattini senza spazi, li separo.
        # Esempio operativo:
        #   PACKAGE N.11-CB051CF-CB052CF-CB053CF
        # diventa:
        #   PACKAGE N.11 - CB051CF - CB052CF - CB053CF
        #
        # Il controllo richiede che il token successivo inizi con lettere seguite
        # da almeno una cifra: in questo modo evitiamo di spezzare indiscriminatamente
        # normali descrizioni con trattino.
        s = re.sub(
            r"(?<=[A-Z0-9])\s*-\s*(?=[A-Z]{1,12}\d[A-Z0-9]*(?:\b|$))",
            " - ",
            s,
            flags=re.I,
        )

        # Lo slash con spazi viene considerato separatore tra codici.
        # Lo slash senza spazi resta dentro il codice.
        parts = re.split(r"\s*(?:;|\||,|\s/\s|\s\+\s|\s-\s)\s*", s)

        out = []
        for part in parts:
            part = (part or "").strip(" -/")
            if not part:
                continue
            part = re.sub(r"(?i)\bPackage\s+No\.?\s*", "Package No.", part).strip()
            out.append(part)
        return out

    def _norm_for_match(value):
        return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())

    def _num_float(value):
        """Converte numeri italiani/inglesi in float."""
        try:
            if value is None:
                return 0.0
            s = str(value).strip()
            if not s:
                return 0.0
            if ',' in s:
                s = s.replace('.', '').replace(',', '.')
            return float(s)
        except Exception:
            return 0.0

    def _fmt_num_clean(value):
        """Restituisce numero pulito da salvare nel campo pezzo."""
        try:
            f = float(value or 0)
            if abs(f - int(f)) < 0.000001:
                return str(int(f))
            return str(round(f, 3))
        except Exception:
            return str(value or '')


    def _cliente_richiede_controllo_pezzi(cliente):
        """Il controllo quantità è obbligatorio solo per FINCANTIERI e FINCANTIERI ARMATORE.

        Tutti gli altri clienti, compreso MARINE INTERIORS, possono creare il Buono
        anche quando il campo ``pezzo`` è vuoto oppure pari a zero.
        """
        nome = re.sub(r"[^A-Z0-9]+", " ", str(cliente or "").upper()).strip()
        return nome in {"FINCANTIERI", "FINCANTIERI ARMATORE"}


    def _piece_value_for_db(value):
        """Salva i pezzi senza .0 quando il valore è intero.

        Il campo pezzo del gestionale può essere testuale o numerico a seconda
        dello schema esistente. Restituendo un intero per i valori interi si
        evita che una nuova riga venga visualizzata come 4.0 invece di 4.
        """
        try:
            f = float(value or 0)
            if abs(f - round(f)) < 0.000001:
                return int(round(f))
            return _fmt_num_clean(f)
        except Exception:
            return _fmt_num_clean(value)

    def _split_quantita(orig_pezzi, q_scelta, orig_valore):
        """Ripartisce peso/m2/m3 proporzionalmente ai pezzi."""
        op = _num_float(orig_pezzi)
        q = _num_float(q_scelta)
        val = _num_float(orig_valore)
        if op <= 0 or q <= 0 or val <= 0:
            return orig_valore, orig_valore
        if q > op:
            q = op
        scelto = val * (q / op)
        residuo = max(0.0, val - scelto)
        return residuo, scelto


    def _round_db_number(value, ndigits=6):
        """Numero pulito per DB/campi numerici: usa float e punto decimale, non virgola."""
        try:
            f = float(value or 0)
            return round(f, ndigits)
        except Exception:
            return value

    def _is_package_token(value):
        """True solo per un riferimento logistico puro, non per Package+codice.

        Prima bastava che la parola PACKAGE fosse presente nella stringa: quindi
        una cella come ``PACKAGE 11-CB052CB`` veniva considerata interamente un
        package e il codice CB052CB non veniva mai rimosso dal residuo.
        """
        txt = re.sub(r"\s+", " ", str(value or "").strip())
        if not txt:
            return False
        patterns = (
            r"(?:PACKAGE|PKG)\s*(?:(?:NO|N)\.?)?\s*[:#.]?\s*[A-Z0-9]+",
            r"PALLET\s*[:#.]?\s*[A-Z0-9][A-Z0-9._/\-]*",
            r"(?:CASSA|CASE)\s*[:#.]?\s*[A-Z0-9][A-Z0-9._/\-]*",
        )
        return any(re.fullmatch(pat, txt, flags=re.I) for pat in patterns)


    def _dedupe_code_parts(parts):
        """Rimuove duplicati da package e marca-pezzi mantenendo l'ordine."""
        out = []
        seen = set()
        for part in parts or []:
            value = str(part or '').strip(' -/')
            key = _norm_for_match(value)
            if value and key and key not in seen:
                seen.add(key)
                out.append(value)
        return out

    def _normalizza_codice_articolo(value):
        """Normalizza il campo Codice usando sempre il trattino come separatore.

        Esempio:
        PACKAGE N.11 / CB051CF / CB052CF
        diventa:
        PACKAGE N.11-CB051CF-CB052CF
        """
        parts = _split_multi_value(value) or [str(value or '').strip()]
        package_parts = _dedupe_code_parts([p for p in parts if _is_package_token(p)])
        code_parts = _dedupe_code_parts([p for p in parts if not _is_package_token(p)])
        return '-'.join(package_parts + code_parts).strip('-')

    def _ricostruisci_codice_residuo(original, selected):
        """Ricostruisce da zero il codice della riga residua.

        Non usa replace e non riaggiunge la stringa originale. Conserva una sola
        volta PACKAGE/PALLET/CASSA, elimina esclusivamente i marca-pezzi scelti e
        usa sempre '-' come separatore.
        """
        original_parts = _split_multi_value(original) or [str(original or '').strip()]
        selected_parts = _split_multi_value(selected) or [str(selected or '').strip()]

        package_parts = _dedupe_code_parts([p for p in original_parts if _is_package_token(p)])
        original_codes = _dedupe_code_parts([p for p in original_parts if not _is_package_token(p)])
        selected_norms = {
            _norm_for_match(p)
            for p in selected_parts
            if p and not _is_package_token(p) and _norm_for_match(p)
        }

        residual_codes = [
            code for code in original_codes
            if _norm_for_match(code) not in selected_norms
        ]
        return '-'.join(package_parts + residual_codes).strip('-')

    def _selected_matches_part(part, selected_norms):
        """True se un elemento della riga originale corrisponde a uno dei codici scelti.

        Non elimina mai il Package/Pallet/Cassa: quelli devono restare sulla riga residua.
        """
        if _is_package_token(part):
            return False

        pn = _norm_for_match(part)
        if not pn or not selected_norms:
            return False

        for sn in selected_norms:
            if not sn:
                continue
            # Dopo la separazione dei marca-pezzi concatenati il confronto deve
            # essere esatto: così togliamo soltanto i codici realmente richiesti
            # e non l'intero blocco residuo.
            if pn == sn:
                return True
        return False

    def _dedupe_keep_order(values):
        """Rimuove duplicati mantenendo l'ordine."""
        out = []
        seen = set()
        for v in values or []:
            s = str(v or "").strip()
            if not s:
                continue
            key = _norm_for_match(s)
            if key and key not in seen:
                seen.add(key)
                out.append(s)
        return out



    def _format_residuo_parts(parts):
        """Ricostruisce la cella residua con separatore richiesto: ' - '."""
        clean = _dedupe_keep_order(parts)
        return " - ".join(clean).strip(" -")

    def _description_has_multiple_items(value):
        """Indica se la descrizione sembra davvero composta da più descrizioni separate.

        Se la descrizione è una frase unica, anche se l'utente nel buono la lascia uguale,
        NON va cancellata dalla riga residua.
        """
        parts = _split_multi_value(value)
        return len(parts) > 1

    def _remove_selected_from_cell(original, selected):
        """Rimuove dalla cella originale SOLO i codici/descrizioni scelti per il buono.

        Regole definitive:
        1) Package No. / PKG / Pallet / Cassa non si eliminano mai.
        2) I marca-pezzo scelti nel buono vengono tolti dalla riga residua.
        3) Il confronto ignora spazi, trattini, slash e maiuscole/minuscole.
        4) Funziona anche quando il codice è attaccato al package:
           "Package No.311-AP/060VR -VA/002VR".
        """
        original = str(original or "").strip()
        selected = str(selected or "").strip()

        if not original or not selected:
            return original

        original_parts = _split_multi_value(original) or [original]
        selected_parts = _split_multi_value(selected) or [selected]

        # I package presenti nel selezionato NON sono mai codici da togliere.
        selected_norms = {
            _norm_for_match(x)
            for x in selected_parts
            if _norm_for_match(x) and not _is_package_token(x)
        }

        if not selected_norms:
            return original

        kept = []
        removed_any = False

        for part in original_parts:
            if not part:
                continue

            # Package/Pallet/Cassa sempre conservati.
            if _is_package_token(part):
                kept.append(part)
                continue

            if _selected_matches_part(part, selected_norms):
                removed_any = True
                continue

            kept.append(part)

        if removed_any:
            return _format_residuo_parts(kept)

        # Fallback per casi in cui non si riesce a separare bene la cella:
        # rimuove testualmente solo i codici scelti, mai il package.
        new_val = original
        for item in selected_parts:
            item = str(item or "").strip()
            if not item or _is_package_token(item):
                continue
            new_val = re.sub(re.escape(item), "", new_val, flags=re.I)

        new_val = re.sub(r"\s*(?:/|;|\||,|\+|-)\s*(?:/|;|\||,|\+|-)\s*", " - ", new_val)
        new_val = re.sub(r"^\s*(?:/|;|\||,|\+|-)\s*", "", new_val)
        new_val = re.sub(r"\s*(?:/|;|\||,|\+|-)\s*$", "", new_val)
        new_val = re.sub(r"\s{2,}", " ", new_val).strip()
        return new_val

    def _clean_residual_cell(original, selected):
        """Calcola il residuo eliminando tutti gli elementi messi nel Buono.

        Mantiene sempre Package/Pallet/Cassa. Se la separazione standard non basta,
        esegue anche una rimozione testuale controllata dei singoli elementi scelti.
        """
        original = str(original or '').strip()
        selected = str(selected or '').strip()
        if not original or not selected:
            return original

        residuo = _remove_selected_from_cell(original, selected)
        selected_parts = _split_multi_value(selected) or [selected]

        # Se un codice scelto è ancora presente nel residuo, lo rimuove testualmente.
        # Il confronto non tocca mai i riferimenti logistici puri.
        for item in selected_parts:
            item = str(item or '').strip()
            if not item or _is_package_token(item):
                continue
            if _norm_for_match(item) and _norm_for_match(item) in _norm_for_match(residuo):
                residuo = re.sub(re.escape(item), '', residuo, flags=re.I)

        # Ripulisce separatori rimasti doppi o alle estremità.
        residuo = re.sub(r'\s*(?:;|\||,|\+)\s*(?:;|\||,|\+)\s*', ' - ', residuo)
        residuo = re.sub(r'\s+-\s+-\s+', ' - ', residuo)
        residuo = re.sub(r'^(?:\s*[-/;,|+]\s*)+', '', residuo)
        residuo = re.sub(r'(?:\s*[-/;,|+]\s*)+$', '', residuo)
        residuo = re.sub(r'\s{2,}', ' ', residuo).strip(' -/;,|+')
        return residuo

    def _extract_package_context(*values):
        """Estrae riferimenti logistici da conservare sulla riga residua.

        Riconosce anche formati tipo:
        Package No.305, Package No. 305, PACKAGE 305, PKG 305.
        """
        found = []
        seen = set()
        patterns = [
            r"\bPACKAGE\s*(?:NO\.?|N\.?|NUM\.?)?\s*[:#.]?\s*[A-Z0-9]+",
            r"\bPKG\s*(?:NO\.?|N\.?)?\s*[:#.]?\s*[A-Z0-9]+",
            r"\bPALLET\s*[:#.\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
            r"\bCASSA\s*[:#.\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
            r"\bCASE\s*[:#.\-]?\s*[A-Z0-9][A-Z0-9\-_/\.]*",
        ]
        for value in values:
            txt = str(value or "")
            for pat in patterns:
                for m in re.finditer(pat, txt, flags=re.I):
                    label = re.sub(r"\s+", " ", m.group(0).strip())
                    label = re.sub(r"(?i)\bPackage\s+No\.?\s*", "Package No.", label)
                    key = _norm_for_match(label)
                    if key and key not in seen:
                        seen.add(key)
                        found.append(label)
        return found

    def _preserve_package_context(residuo, *sources):
        """Garantisce che Package/Pallet/Cassa restino sulla riga residua.

        Se il package era nella riga originale e la pulizia lo ha tolto per errore,
        lo reinserisce in testa alla cella, non in fondo.
        """
        residuo = (residuo or "").strip()
        labels = _extract_package_context(*sources)
        if not labels:
            return residuo

        parts = _split_multi_value(residuo) if residuo else []
        current_norms = {_norm_for_match(x) for x in parts}

        # Package prima, poi tutti gli altri codici rimasti.
        final_parts = []
        for label in labels:
            if _norm_for_match(label) not in current_norms:
                final_parts.append(label)

        final_parts.extend(parts)
        final_parts = _dedupe_keep_order(final_parts)

        return _format_residuo_parts(final_parts)




    def _safe_int_picking(value):
        """Converte interi lasciando None se il campo è vuoto."""
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    def _safe_float_picking(value):
        """Converte numeri italiani/inglesi lasciando None se il campo è vuoto."""
        s = str(value or "").strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    def _date_from_buono_form(value):
        """Accetta DD/MM/YYYY o YYYY-MM-DD e restituisce date."""
        s = str(value or "").strip()
        if not s:
            return date.today()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        return date.today()

    def _join_unique(values, max_len=500):
        out, seen = [], set()
        for v in values or []:
            s = str(v or "").strip()
            if not s:
                continue
            key = s.upper()
            if key not in seen:
                seen.add(key)
                out.append(s)
        return "; ".join(out)[:max_len]

    def _sum_int_attr(rows, attr):
        tot = 0
        for r in rows or []:
            try:
                tot += int(float(getattr(r, attr, 0) or 0))
            except Exception:
                pass
        return tot

    def _create_picking_from_buono_form(db, form, rows, buono_n):
        """Crea o aggiorna la riga Picking/Lavorazioni collegata al Buono.

        Scrive direttamente nella tabella lavorazioni.
        Se trova stesso giorno + stesso buono/seriale aggiorna il record invece di bloccare.
        """
        try:
            dt = _date_from_buono_form(form.get('picking_data') or form.get('data_em'))
            cliente = (form.get('picking_cliente') or _join_unique([getattr(r, 'cliente', '') for r in rows], 120)).strip()
            descrizione = (form.get('picking_descrizione') or 'PICKING+FILMATURA+PALLETIZZAZIONE').strip()
            richiesta_di = (form.get('picking_richiesta_di') or '').strip()
            seriali = (form.get('picking_seriali') or buono_n or '').strip()
            if not seriali:
                seriali = str(buono_n or '').strip()
            n_arrivo = (form.get('picking_n_arrivo') or _join_unique([getattr(r, 'n_arrivo', '') for r in rows], 500)).strip()

            colli = _safe_int_picking(form.get('picking_colli'))
            if colli is None:
                colli = _sum_int_attr(rows, 'n_colli') or len(rows or []) or 0

            pallet_forniti = _safe_int_picking(form.get('picking_pallet_entrati'))
            pallet_uscita = _safe_int_picking(form.get('picking_pallet_usciti'))
            ore_blue = _safe_float_picking(form.get('picking_ore_blue'))
            ore_white = _safe_float_picking(form.get('picking_ore_white'))

            if not cliente:
                cliente = _join_unique([getattr(r, 'cliente', '') for r in rows], 120)
            if not descrizione:
                descrizione = 'PICKING+FILMATURA+PALLETIZZAZIONE'
            if not (cliente or seriali or n_arrivo):
                return False, "Picking non creato: dati insufficienti."

            params = {
                "data": dt,
                "cliente": cliente,
                "descrizione": descrizione,
                "richiesta_di": richiesta_di,
                "seriali": seriali,
                "n_arrivo": n_arrivo,
                "colli": colli,
                "pallet_forniti": pallet_forniti,
                "pallet_uscita": pallet_uscita,
                "ore_blue_collar": ore_blue,
                "ore_white_collar": ore_white,
            }

            # Assicura colonna n_arrivo su PostgreSQL. Se non supportato, non blocca.
            try:
                db.execute(text("ALTER TABLE lavorazioni ADD COLUMN IF NOT EXISTS n_arrivo TEXT"))
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

            # Verifica colonne realmente disponibili.
            has_n_arrivo = True
            try:
                cols = db.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'lavorazioni'
                """)).fetchall()
                col_names = {str(c[0]) for c in cols}
                has_n_arrivo = 'n_arrivo' in col_names
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                has_n_arrivo = hasattr(Lavorazione, 'n_arrivo') if 'Lavorazione' in globals() else True

            # Cerca record esistente: stesso giorno + stesso buono/seriale.
            existing = None
            try:
                existing = db.execute(text("""
                    SELECT id FROM lavorazioni
                    WHERE data = :data
                      AND UPPER(COALESCE(seriali, '')) = UPPER(:seriali)
                    LIMIT 1
                """), {"data": dt, "seriali": seriali}).fetchone()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                existing = None

            if existing:
                params["id"] = existing[0]
                if has_n_arrivo:
                    db.execute(text("""
                        UPDATE lavorazioni
                        SET cliente = :cliente,
                            descrizione = :descrizione,
                            richiesta_di = :richiesta_di,
                            seriali = :seriali,
                            n_arrivo = :n_arrivo,
                            colli = :colli,
                            pallet_forniti = :pallet_forniti,
                            pallet_uscita = :pallet_uscita,
                            ore_blue_collar = :ore_blue_collar,
                            ore_white_collar = :ore_white_collar
                        WHERE id = :id
                    """), params)
                else:
                    db.execute(text("""
                        UPDATE lavorazioni
                        SET cliente = :cliente,
                            descrizione = :descrizione,
                            richiesta_di = :richiesta_di,
                            seriali = :seriali,
                            colli = :colli,
                            pallet_forniti = :pallet_forniti,
                            pallet_uscita = :pallet_uscita,
                            ore_blue_collar = :ore_blue_collar,
                            ore_white_collar = :ore_white_collar
                        WHERE id = :id
                    """), params)
                db.commit()
                return True, "Picking aggiornato correttamente."

            if has_n_arrivo:
                db.execute(text("""
                    INSERT INTO lavorazioni
                    (data, cliente, descrizione, richiesta_di, seriali, n_arrivo, colli,
                     pallet_forniti, pallet_uscita, ore_blue_collar, ore_white_collar)
                    VALUES
                    (:data, :cliente, :descrizione, :richiesta_di, :seriali, :n_arrivo, :colli,
                     :pallet_forniti, :pallet_uscita, :ore_blue_collar, :ore_white_collar)
                """), params)
            else:
                db.execute(text("""
                    INSERT INTO lavorazioni
                    (data, cliente, descrizione, richiesta_di, seriali, colli,
                     pallet_forniti, pallet_uscita, ore_blue_collar, ore_white_collar)
                    VALUES
                    (:data, :cliente, :descrizione, :richiesta_di, :seriali, :colli,
                     :pallet_forniti, :pallet_uscita, :ore_blue_collar, :ore_white_collar)
                """), params)
            db.commit()
            return True, "Picking creato correttamente."

        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                scrivi_log_errore("Errore salvataggio picking da buono", e)
            except Exception:
                pass
            return False, f"Picking non creato: {e}"

    def _next_buono_number(db):
        """Genera automaticamente il prossimo N. buono.

        Formato usato: 001/26, 002/26, ...
        Legge i buoni già presenti in Articolo.buono_n e incrementa il numero più alto
        riferito all'anno corrente; se non trova riferimenti all'anno, incrementa comunque
        il numero più alto disponibile.
        """
        yy = datetime.today().strftime("%y")
        max_current_year = 0
        max_any = 0
        try:
            values = db.query(Articolo.buono_n).filter(Articolo.buono_n != None).all()
        except Exception:
            values = []

        for row in values:
            raw = row[0] if isinstance(row, (tuple, list)) else row
            txt = str(raw or "").strip()
            if not txt:
                continue
            m = re.search(r"(\d{1,6})", txt)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            max_any = max(max_any, n)
            if re.search(rf"(?:/|-|\b){re.escape(yy)}\b", txt):
                max_current_year = max(max_current_year, n)

        base = max_current_year or max_any
        return f"{base + 1:03d}/{yy}"


    def _safe_text(value):
        return str(value or '').strip()

    def _first_nonempty(rows, attr):
        for r in rows or []:
            v = _safe_text(getattr(r, attr, ''))
            if v:
                return v
        return ''

    def _sum_pezzi_rows(rows):
        tot = 0.0
        for r in rows or []:
            try:
                tot += _num_float(getattr(r, 'pezzo', 0))
            except Exception:
                pass
        if abs(tot - int(tot)) < 0.000001:
            return str(int(tot)) if tot else ''
        return str(round(tot, 2)).replace('.', ',')

    def _generate_cartello_fincantieri_pdf(form, rows, buono_n):
        """Genera un PDF multipagina: 1 cartello per ogni riga spuntata."""
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        import io as _io
        import os as _os
        import textwrap as _textwrap

        bio = _io.BytesIO()
        c = canvas.Canvas(bio, pagesize=A4)
        width, height = A4

        bn = _safe_text(buono_n) or _safe_text(form.get('buono_n'))

        selected_ids = set()
        try:
            selected_ids = {str(x).strip() for x in form.getlist('cartello_id') if str(x).strip()}
        except Exception:
            selected_ids = set()

        selected_rows = []
        for r in rows or []:
            rid = str(getattr(r, 'id_articolo', '') or '').strip()
            if not selected_ids or rid in selected_ids:
                selected_rows.append(r)

        def draw_wrapped(value, x, y, max_width=None, size=30, bold=False, max_lines=3):
            """Scrive il testo andando a capo in base allo spazio reale disponibile.

            Per i marca-pezzi prova prima a spezzare dopo i trattini, così codici come
            PACKAGE N.11-CB051CF-CB052CF-CB053CF non vengono tagliati fuori pagina.
            """
            value = _safe_text(value)
            if not value:
                return y

            font = 'Helvetica-Bold' if bold else 'Helvetica'
            c.setFont(font, size)
            max_width = float(max_width or (width - x - 35))

            # Mantiene il trattino sul codice precedente e permette il ritorno a capo
            # subito dopo ogni marca-pezzo.
            tokens = [t for t in re.split(r'(?<=-)|\s+', value) if t]
            lines = []
            current = ''

            for token in tokens:
                candidate = token if not current else current + token
                if c.stringWidth(candidate, font, size) <= max_width:
                    current = candidate
                    continue

                if current:
                    lines.append(current.rstrip())
                    current = token.lstrip()
                else:
                    # Token eccezionalmente lungo: lo divide carattere per carattere
                    # per garantire che non esca mai dal foglio.
                    piece = ''
                    for ch in token:
                        test = piece + ch
                        if piece and c.stringWidth(test, font, size) > max_width:
                            lines.append(piece)
                            piece = ch
                        else:
                            piece = test
                    current = piece

            if current:
                lines.append(current.rstrip())

            for text_line in lines[:max_lines]:
                c.drawString(x, y, text_line)
                y -= size + 8
            return y

        if not selected_rows:
            c.setFont('Helvetica-Bold', 24)
            c.drawCentredString(width / 2, height / 2, 'Nessun cartello selezionato')
            c.showPage()
            c.save()
            bio.seek(0)
            return bio

        total = len(selected_rows)

        for idx, r in enumerate(selected_rows, start=1):
            rid = getattr(r, 'id_articolo', None)

            cliente = (
                _safe_text(form.get(f'cartello_cliente_{rid}'))
                or _safe_text(getattr(r, 'cliente', ''))
                or _safe_text(form.get('picking_cliente'))
            )
            ditta = (
                _safe_text(form.get(f'cartello_ditta_{rid}'))
                or _safe_text(getattr(r, 'fornitore', ''))
                or _safe_text(form.get('fornitore'))
            )
            marca_pezzi = (
                _safe_text(form.get(f'codice_buono_{rid}'))
                or _safe_text(getattr(r, 'codice_articolo', ''))
            )
            descrizione = (
                _safe_text(form.get(f'descrizione_buono_{rid}'))
                or _safe_text(getattr(r, 'descrizione', ''))
            )
            protocollo = _safe_text(getattr(r, 'protocollo', '')) or _safe_text(form.get('protocollo'))
            arrivo = _safe_text(getattr(r, 'n_arrivo', ''))
            n_pallet = _safe_text(form.get(f'cartello_n_pallet_{rid}')) or str(idx)
            posizione = _safe_text(form.get(f'cartello_posizione_{rid}')) or _safe_text(getattr(r, 'posizione', ''))
            destinazione = _safe_text(form.get(f'cartello_destinazione_{rid}'))
            n_pezzi = _safe_text(form.get(f'q_{rid}')) or _safe_text(getattr(r, 'pezzo', ''))

            titolo_cliente = cliente.upper() if cliente else 'FINCANTIERI'
            titolo = f"{titolo_cliente} PICKING"

            try:
                logo_path = globals().get('LOGO_PATH')
                if logo_path and _os.path.exists(logo_path):
                    img = ImageReader(logo_path)
                    c.drawImage(img, width / 2 - 80, height - 95, width=160, height=55,
                                preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

            y = height - 155
            c.setFont('Helvetica-Bold', 30)
            c.drawCentredString(width / 2, y, titolo[:34])
            y -= 62

            def line(label, value='', size=31, bold_value=True, max_lines=2, value_below=False):
                nonlocal y
                label = _safe_text(label)
                value = _safe_text(value)
                c.setFont('Helvetica-Bold', size)
                c.drawString(35, y, label)

                if not value:
                    y -= 58
                    return

                if value_below:
                    # Il valore parte dalla riga successiva e sfrutta tutta la larghezza.
                    value_y = y - size - 10
                    y_after = draw_wrapped(
                        value, 35, value_y,
                        max_width=width - 70,
                        size=size,
                        bold=bold_value,
                        max_lines=max_lines
                    )
                    y = y_after - 12
                else:
                    x_val = 35 + c.stringWidth(label, 'Helvetica-Bold', size) + 8
                    y_after = draw_wrapped(
                        value, x_val, y,
                        max_width=width - x_val - 35,
                        size=size,
                        bold=bold_value,
                        max_lines=max_lines
                    )
                    y = min(y - 58, y_after - 12)

            line('DITTA :', ditta, 31, True, 2)
            line('N.BUONO:', bn, 31, True, 1)
            # I marca-pezzi vanno sotto l'etichetta e a capo dopo i trattini:
            # in questo modo non vengono mai tagliati sul bordo destro del cartello.
            line('MARCA PEZZI:', marca_pezzi, 26, True, 4, value_below=True)
            line('DESCRIZIONE:', descrizione, 24, False, 2)
            line('PROTOCOLLO:', protocollo, 26, False, 2)
            line('ARRIVO ', arrivo, 31, False, 1)
            line('N.PALLET:', n_pallet, 31, True, 1)
            line('N. PEZZI:', n_pezzi, 31, True, 1)

            if posizione:
                line('POSIZIONE:', posizione, 24, True, 34, 1)
            if destinazione:
                line('DESTINAZIONE:', destinazione, 24, True, 30, 1)

            c.setFont('Helvetica-Bold', 18)
            c.drawCentredString(width / 2, 45, f'CARTELLO {idx} DI {total}')

            c.showPage()

        c.save()
        bio.seek(0)
        return bio

    def _extract_ids_from_request(req_data):
        """Legge gli ID selezionati anche quando arrivano da più pagine.

        Accetta sia:
        - ids ripetuti: ids=1&ids=2&ids=3
        - ids come stringa: ids=1,2,3
        - selected_ids_all: 1,2,3  (campo robusto aggiunto da giacenze.html)
        """
        raw_values = []
        try:
            # Campo definitivo inviato da giacenze.html per selezioni su più pagine.
            ids_all = (req_data.get('ids_all') or '').strip()
            if ids_all:
                raw_values.append(ids_all)
        except Exception:
            pass
        try:
            all_ids = (req_data.get('selected_ids_all') or '').strip()
            if all_ids:
                raw_values.append(all_ids)
        except Exception:
            pass
        try:
            raw_values.extend(req_data.getlist('ids'))
        except Exception:
            v = req_data.get('ids') if hasattr(req_data, 'get') else ''
            if v:
                raw_values.append(v)

        ids = []
        seen = set()
        for raw in raw_values:
            for part in re.split(r'[,;\s]+', str(raw or '')):
                part = part.strip()
                if part.isdigit() and part not in seen:
                    seen.add(part)
                    ids.append(int(part))
        return ids

    @app.route('/buono/preview', methods=['POST'])
    @login_required
    def buono_preview():
        if session.get('role') != 'admin':
            flash('Accesso negato.', 'danger')
            return redirect(url_for('giacenze'))

        ids = _extract_ids_from_request(request.form)

        if not ids:
            flash("Seleziona almeno un articolo per creare il buono.", "warning")
            return redirect(url_for('giacenze'))

        db = SessionLocal()
        try:
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            if not rows:
                flash("⚠️ Nessun articolo trovato per gli ID selezionati. Torna alle Giacenze e ripeti la selezione.", "warning")
                return redirect(url_for('giacenze'))
            if len(rows) != len(ids):
                flash(f"⚠️ Attenzione: selezionati {len(ids)} ID ma trovati {len(rows)} articoli. Verifica eventuali righe eliminate o filtri attivi.", "warning")
            if len(ids) > 50:
                flash(f"ℹ️ Buono multipagina: {len(ids)} articoli selezionati. Controlla il numero righe nell'anteprima prima di salvare.", "info")
            ordine_ids = {idv: idx for idx, idv in enumerate(ids)}
            rows.sort(key=lambda r: ordine_ids.get(getattr(r, 'id_articolo', 0), 999999))

            protocolli_trovati = set()
            for r in rows:
                if r.protocollo and str(r.protocollo).strip():
                    protocolli_trovati.add(str(r.protocollo).strip())
            protocollo_auto = ", ".join(sorted(protocolli_trovati))

            commessa_auto = next((r.commessa for r in rows if r.commessa), "")
            fornitore_auto = next((r.fornitore for r in rows if r.fornitore), "")
            buono_n_esistente = next((r.buono_n for r in rows if r.buono_n), "")
            buono_n_auto = buono_n_esistente or _next_buono_number(db)
            ordine_auto = next((r.ordine for r in rows if r.ordine), "")

            picking_cliente_auto = _join_unique([getattr(r, 'cliente', '') for r in rows], 120)
            picking_n_arrivo_auto = _join_unique([getattr(r, 'n_arrivo', '') for r in rows], 500)
            picking_colli_auto = _sum_int_attr(rows, 'n_colli') or len(rows)

            meta = {
                "buono_n": buono_n_auto,
                "buono_n_auto": buono_n_auto,
                "buono_n_esistente": buono_n_esistente,
                "data_em": datetime.today().strftime("%d/%m/%Y"),
                "commessa": commessa_auto,
                "fornitore": fornitore_auto,
                "protocollo": protocollo_auto,
                "ordine": ordine_auto,
                "picking_cliente": picking_cliente_auto,
                "picking_descrizione": "PICKING+FILMATURA+PALLETIZZAZIONE",
                "picking_richiesta_di": "",
                "picking_seriali": buono_n_auto,
                "picking_n_arrivo": picking_n_arrivo_auto,
                "picking_colli": picking_colli_auto,
                "cartello_ditta": fornitore_auto,
                "cartello_n_pallet": "",
                "cartello_n_pezzi": _sum_pezzi_rows(rows),
                "cartello_marca_pezzi": "",
            }

            return render_template('buono_preview.html', rows=rows, meta=meta, ids=",".join(map(str, ids)))
        finally:
            db.close()

    @app.route('/buono/finalize_and_get_pdf', methods=['POST'])
    @login_required
    def buono_finalize_and_get_pdf():
        """Valida, genera e salva il Buono senza consentire giacenze negative o codici non presenti."""
        db = SessionLocal()

        class BuonoValidationError(Exception):
            pass

        try:
            req_data = request.form
            ids = _extract_ids_from_request(req_data)
            if not ids:
                raise BuonoValidationError("Nessuna riga selezionata per il Buono.")

            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            if len(rows) != len(ids):
                raise BuonoValidationError(
                    "Una o più righe non sono più disponibili. Aggiorna le Giacenze e ripeti la selezione."
                )

            ordine_ids = {idv: idx for idx, idv in enumerate(ids)}
            rows.sort(key=lambda r: ordine_ids.get(getattr(r, 'id_articolo', 0), 999999))

            action = (req_data.get('action') or 'preview').strip().lower()
            buono_mode = (req_data.get('buono_mode') or 'auto').strip().lower()
            bn = (req_data.get('buono_n') or '').strip()
            if buono_mode == 'auto' or not bn:
                bn = _next_buono_number(db)

            if action == 'cartello':
                pdf_bio = _generate_cartello_fincantieri_pdf(req_data, rows, bn)
                safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
                return send_file(
                    pdf_bio,
                    as_attachment=False,
                    download_name=f'Cartello_Fincantieri_{safe_bn}.pdf',
                    mimetype='application/pdf'
                )

            # Anteprima: nessuna modifica al database.
            if action != 'save':
                pdf_bio = _generate_buono_pdf(req_data, rows)
                safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
                return send_file(
                    pdf_bio,
                    as_attachment=False,
                    download_name=f'Buono_{safe_bn}.pdf',
                    mimetype='application/pdf'
                )

            # -----------------------------------------------------------------
            # VALIDAZIONE COMPLETA PRIMA DI MODIFICARE QUALSIASI RIGA
            # -----------------------------------------------------------------
            prepared = []

            for r in rows:
                rid = r.id_articolo
                old_cod = (r.codice_articolo or '').strip()
                old_desc = (r.descrizione or '').strip()
                codice_scelto = (req_data.get(f"codice_buono_{rid}") or old_cod).strip()
                descr_scelta = (req_data.get(f"descrizione_buono_{rid}") or old_desc).strip()
                q_raw = (req_data.get(f"q_{rid}") or '').strip()

                # Controllo concorrenza: il codice deve essere ancora uguale a quello
                # mostrato nell'anteprima. Il controllo dei pezzi è invece obbligatorio
                # soltanto per FINCANTIERI e FINCANTIERI ARMATORE.
                old_cod_form = (req_data.get(f"original_codice_{rid}") or old_cod).strip()
                old_pezzi_form = _num_float(req_data.get(f"original_pezzi_{rid}"))
                if _norm_for_match(old_cod_form) != _norm_for_match(old_cod):
                    raise BuonoValidationError(
                        f"La riga ID {rid} è stata modificata da un altro utente. "
                        "Aggiorna le Giacenze e ripeti il Buono."
                    )

                controlla_pezzi = _cliente_richiede_controllo_pezzi(
                    getattr(r, 'cliente', '')
                )
                pezzi_originali = _num_float(getattr(r, 'pezzo', None))

                if controlla_pezzi:
                    if abs(old_pezzi_form - pezzi_originali) > 0.000001:
                        raise BuonoValidationError(
                            f"La disponibilità della riga ID {rid} è cambiata da "
                            f"{_fmt_num_clean(old_pezzi_form)} a {_fmt_num_clean(pezzi_originali)} pezzi. "
                            "Aggiorna le Giacenze e ripeti il Buono."
                        )

                    if pezzi_originali <= 0:
                        raise BuonoValidationError(
                            "CAMY AI - PRELIEVO BLOCCATO\n\n"
                            f"Marca pezzo: {codice_scelto or old_cod or 'non indicato'}\n"
                            "Disponibilità: 0 pezzi.\n\n"
                            "Il materiale risulta esaurito o già prelevato. Il Buono non è stato creato."
                        )

                    if not q_raw:
                        raise BuonoValidationError(
                            f"Inserisci la quantità da prelevare per il marca pezzo {codice_scelto or old_cod}."
                        )

                    pezzi_scelti = _num_float(q_raw)
                    if pezzi_scelti <= 0:
                        raise BuonoValidationError(
                            f"La quantità del marca pezzo {codice_scelto or old_cod} deve essere maggiore di zero."
                        )
                    if pezzi_scelti > pezzi_originali:
                        raise BuonoValidationError(
                            "CAMY AI - GIACENZA INSUFFICIENTE\n\n"
                            f"Marca pezzo: {codice_scelto or old_cod}\n"
                            f"Richiesti: {_fmt_num_clean(pezzi_scelti)} pezzi\n"
                            f"Disponibili: {_fmt_num_clean(pezzi_originali)} pezzi\n\n"
                            "Riduci la quantità e riprova. Il Buono non è stato creato."
                        )
                else:
                    # Per MARINE INTERIORS e per tutti gli altri clienti il campo pezzi
                    # può essere vuoto. Se è valorizzato lo conserviamo; altrimenti il
                    # Buono prende l'intera riga senza eseguire controlli quantitativi.
                    pezzi_scelti = _num_float(q_raw) if q_raw else pezzi_originali
                    if pezzi_scelti < 0:
                        pezzi_scelti = 0

                if not codice_scelto:
                    raise BuonoValidationError(f"Il codice/marca pezzo della riga ID {rid} è vuoto.")

                # I marca-pezzi scelti devono esistere davvero nella riga originale.
                original_parts = [p for p in (_split_multi_value(old_cod) or [old_cod]) if not _is_package_token(p)]
                original_norms = {_norm_for_match(p) for p in original_parts if _norm_for_match(p)}
                selected_parts = [p for p in (_split_multi_value(codice_scelto) or [codice_scelto]) if not _is_package_token(p)]
                selected_norms = [_norm_for_match(p) for p in selected_parts if _norm_for_match(p)]

                if selected_norms and original_norms:
                    # Il codice può essere composto da più marca-pezzi consecutivi, ad esempio
                    # CB052CF-CB053CF, mentre la riga originale contiene anche CB051CF prima.
                    # In questo caso il blocco completo selezionato è comunque presente nella
                    # stringa originale e non deve essere segnalato come mancante.
                    original_full_norm = _norm_for_match(old_cod)
                    mancanti = []
                    for parte in selected_parts:
                        parte_norm = _norm_for_match(parte)
                        if not parte_norm:
                            continue
                        presente = (
                            parte_norm in original_norms
                            or parte_norm in original_full_norm
                        )
                        if not presente:
                            mancanti.append(parte)

                    if mancanti:
                        raise BuonoValidationError(
                            "CAMY AI - MARCA PEZZO NON DISPONIBILE\n\n"
                            f"Riga ID: {rid}\n"
                            f"Non presente nella giacenza: {', '.join(mancanti)}\n\n"
                            "Controlla il codice richiesto. Il Buono non è stato creato."
                        )

                # Nel magazzino lo stesso marca-pezzo può comparire più volte:
                # - nella stessa cassa/package, quando rappresenta più pezzi uguali;
                # - su casse/package o ID differenti.
                # Non viene quindi applicato alcun blocco per codici ripetuti.
                # Restano attivi i controlli su disponibilità, quantità e presenza
                # reale del codice nella riga selezionata.

                prepared.append({
                    'row': r,
                    'old_cod': old_cod,
                    'old_desc': old_desc,
                    'codice_scelto': codice_scelto,
                    'descr_scelta': descr_scelta,
                    'note_inserite': req_data.get(f"note_{rid}"),
                    'note_originale': r.note,
                    'pezzi_originali': pezzi_originali,
                    'pezzi_scelti': pezzi_scelti,
                    'pezzi_residui': max(0.0, pezzi_originali - pezzi_scelti),
                    'controlla_pezzi': controlla_pezzi,
                })

            scarico_parziale_eseguito = False

            # -----------------------------------------------------------------
            # APPLICAZIONE DELLE MODIFICHE DOPO CHE TUTTE LE RIGHE SONO VALIDE
            # -----------------------------------------------------------------
            for item in prepared:
                r = item['row']
                old_cod = item['old_cod']
                old_desc = item['old_desc']
                codice_scelto = item['codice_scelto']
                descr_scelta = item['descr_scelta']
                note_inserite = item['note_inserite']
                note_originale = item['note_originale']
                pezzi_originali = item['pezzi_originali']
                pezzi_scelti = item['pezzi_scelti']
                pezzi_residui = item['pezzi_residui']

                cod_parziale = bool(_norm_for_match(codice_scelto) != _norm_for_match(old_cod))
                desc_parziale = bool(descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc))
                qta_parziale = item.get('controlla_pezzi', False) and pezzi_scelti < pezzi_originali

                if cod_parziale or desc_parziale or qta_parziale:
                    scarico_parziale_eseguito = True
                    r.buono_n = ""

                    riga_buono = Articolo()
                    for col in Articolo.__table__.columns:
                        if col.name != 'id_articolo':
                            setattr(riga_buono, col.name, getattr(r, col.name))

                    riga_buono.codice_articolo = _normalizza_codice_articolo(codice_scelto)
                    riga_buono.descrizione = descr_scelta or old_desc
                    riga_buono.buono_n = bn
                    riga_buono.pezzo = _piece_value_for_db(pezzi_scelti)
                    r.pezzo = _piece_value_for_db(pezzi_residui)

                    for campo in ('peso', 'm2', 'm3'):
                        residuo_val, scelto_val = _split_quantita(
                            pezzi_originali, pezzi_scelti, getattr(r, campo, None)
                        )
                        setattr(riga_buono, campo, _round_db_number(scelto_val))
                        setattr(r, campo, _round_db_number(residuo_val))

                    # Regola aziendale: una riga rappresenta sempre un collo.
                    riga_buono.n_colli = 1
                    r.n_colli = 1
                    riga_buono.note = (note_inserite or '').strip()
                    db.add(riga_buono)

                    if cod_parziale:
                        # Ricostruzione deterministica: PACKAGE una sola volta,
                        # solo i marca-pezzi residui e separatore sempre '-'.
                        r.codice_articolo = _ricostruisci_codice_residuo(
                            old_cod, codice_scelto
                        )
                    else:
                        r.codice_articolo = _normalizza_codice_articolo(old_cod)

                    if desc_parziale:
                        descr_residua = _clean_residual_cell(old_desc, descr_scelta)
                        descr_residua = _preserve_package_context(
                            descr_residua, old_desc, descr_scelta
                        )
                        r.descrizione = descr_residua if descr_residua else old_desc
                    else:
                        r.descrizione = old_desc

                    r.note = note_originale
                else:
                    r.buono_n = bn
                    if note_inserite is not None:
                        r.note = note_inserite
                    r.pezzo = _piece_value_for_db(pezzi_scelti)
                    r.n_colli = 1

            # Genera il PDF prima del commit: se il PDF fallisce, il DB resta invariato.
            db.flush()
            pdf_bio = _generate_buono_pdf(req_data, rows)
            db.commit()

            # Picking separato: un eventuale errore non annulla il Buono già salvato.
            picking_msg = ""
            picking_created = False
            try:
                if req_data.get('picking_enable') == '1':
                    fresh_rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
                    picking_created, picking_msg = _create_picking_from_buono_form(
                        db, req_data, fresh_rows, bn
                    )
                    db.commit()
            except Exception as e_pick:
                db.rollback()
                picking_msg = "Picking non creato automaticamente: controllare la sezione Picking/Lavorazioni."
                try:
                    scrivi_log_errore("Errore creazione picking da buono", e_pick)
                except Exception:
                    pass

            if picking_msg:
                flash(picking_msg, "success" if picking_created else "warning")

            if scarico_parziale_eseguito:
                flash(
                    "Scarico parziale salvato: i pezzi sono stati scalati, i marca-pezzi del Buono "
                    "sono stati rimossi dal residuo e PACKAGE/PALLET/CASSA sono rimasti in giacenza.",
                    "success"
                )
            else:
                flash("Buono salvato correttamente.", "success")

            safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
            return send_file(
                pdf_bio,
                as_attachment=True,
                download_name=f'Buono_{safe_bn}.pdf',
                mimetype='application/pdf'
            )

        except BuonoValidationError as e:
            db.rollback()
            return str(e), 409, {'Content-Type': 'text/plain; charset=utf-8'}
        except Exception as e:
            db.rollback()
            try:
                scrivi_log_errore("Errore Buono di Prelievo", e)
            except Exception:
                pass
            print(f"ERRORE BUONO: {e}")
            return "Errore durante la creazione del Buono. Nessuna modifica è stata salvata.", 500, {
                'Content-Type': 'text/plain; charset=utf-8'
            }
        finally:
            db.close()
