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

        # Se dopo un trattino inizia un marca-pezzo con / oppure *, separo.
        # Non rompe lo slash interno di SE/007VD e riconosce AV*002VD.
        s = re.sub(r"\s*-\s*(?=[A-Z0-9]{1,25}(?:/|\*)[A-Z0-9])", " - ", s, flags=re.I)

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
        n = _norm_for_match(value)
        return bool(re.search(r"\b(PACKAGE|PKG|PALLET|CASSA|CASE)\b", str(value or ""), re.I) or n.startswith("PACKAGENO") or n.startswith("PKG"))

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
            if pn == sn or sn in pn or pn in sn:
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

    def _wrap_text_canvas(c, text, x, y, max_width, font_name='Helvetica', font_size=30, leading=36, max_lines=3):
        """Scrive testo grande andando a capo senza uscire dal foglio."""
        text = str(text or '').strip()
        if not text:
            return y
        words = text.split()
        lines = []
        cur = ''
        for w in words:
            test = (cur + ' ' + w).strip()
            if c.stringWidth(test, font_name, font_size) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        lines = lines[:max_lines]
        c.setFont(font_name, font_size)
        for line in lines:
            c.drawString(x, y, line)
            y -= leading
        return y

    def _generate_cartello_bancali_pdf(form, rows, buono_n):
        """Genera un PDF A4 con 1 cartello per ogni riga selezionata/spuntata."""
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        import io as _io
        import os as _os

        selected_cartelli = set()
        try:
            selected_cartelli = {str(x).strip() for x in form.getlist('cartello_id') if str(x).strip()}
        except Exception:
            selected_cartelli = set()

        if not selected_cartelli:
            selected_cartelli = {str(getattr(r, 'id_articolo', '')) for r in rows or [] if getattr(r, 'id_articolo', None)}

        selected_rows = [
            r for r in (rows or [])
            if str(getattr(r, 'id_articolo', '')).strip() in selected_cartelli
        ]

        bio = _io.BytesIO()
        c = canvas.Canvas(bio, pagesize=A4)
        width, height = A4
        logo_path = globals().get('LOGO_PATH')

        if not selected_rows:
            c.setFont('Helvetica-Bold', 22)
            c.drawCentredString(width / 2, height / 2, 'Nessun cartello selezionato')
            c.showPage()
            c.save()
            bio.seek(0)
            return bio

        bn = _safe_text(buono_n) or _safe_text(form.get('buono_n'))

        for r in selected_rows:
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
            protocollo = _safe_text(getattr(r, 'protocollo', '')) or _safe_text(form.get('protocollo'))
            arrivo = _safe_text(getattr(r, 'n_arrivo', ''))
            n_pallet = _safe_text(form.get(f'cartello_n_pallet_{rid}')) or '1'
            n_pezzi = _safe_text(form.get(f'q_{rid}')) or _safe_text(getattr(r, 'pezzo', ''))

            titolo_cliente = cliente.upper() if cliente else ''
            titolo = f"{titolo_cliente} PICKING" if titolo_cliente else "CARTELLO PICKING"

            try:
                if logo_path and _os.path.exists(logo_path):
                    img = ImageReader(logo_path)
                    c.drawImage(img, width / 2 - 80, height - 95, width=160, height=55,
                                preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

            y = height - 155
            c.setFont('Helvetica-Bold', 30)
            c.drawCentredString(width / 2, y, titolo[:34])
            y -= 65

            def label_value(label, value='', font_size=33, value_font='Helvetica'):
                nonlocal y
                label = str(label or '')
                value = str(value or '').strip()
                c.setFont('Helvetica-Bold', font_size)
                c.drawString(35, y, label)
                x_val = 35 + c.stringWidth(label, 'Helvetica-Bold', font_size) + 5
                if value:
                    y_after = _wrap_text_canvas(
                        c, value, x_val, y, width - x_val - 25,
                        font_name=value_font, font_size=font_size,
                        leading=font_size + 8, max_lines=2
                    )
                    y = min(y - 62, y_after - 18)
                else:
                    y -= 62

            label_value('DITTA :', ditta, 33)
            label_value('N.BUONO:', bn, 33)
            label_value('MARCA PEZZI:', marca_pezzi, 30, 'Helvetica-Bold')
            label_value('PROTOCOLLO:', protocollo, 30)
            label_value('ARRIVO ', arrivo, 33)
            label_value('N.PALLET:', n_pallet, 33, 'Helvetica-Bold')
            label_value('N. PEZZI:', n_pezzi, 33, 'Helvetica-Bold')
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
        db = SessionLocal()
        try:
            req_data = request.form
            ids = _extract_ids_from_request(req_data)
            rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
            ordine_ids = {idv: idx for idx, idv in enumerate(ids)}
            rows.sort(key=lambda r: ordine_ids.get(getattr(r, 'id_articolo', 0), 999999))

            action = req_data.get('action')
            buono_mode = (req_data.get('buono_mode') or 'auto').strip().lower()
            bn = (req_data.get('buono_n') or '').strip()
            if buono_mode == 'auto' or not bn:
                # Se l'utente lascia automatico, oppure non compila il numero manuale,
                # assegno il prossimo numero disponibile prima di salvare/generare il PDF.
                bn = _next_buono_number(db)

            if action == 'cartello':
                pdf_bio = _generate_cartello_bancali_pdf(req_data, rows, bn)
                safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
                return send_file(
                    pdf_bio,
                    as_attachment=False,
                    download_name=f'Cartello_Bancali_{safe_bn}.pdf',
                    mimetype='application/pdf'
                )

            scarico_parziale_eseguito = False

            for r in rows:
                codice_scelto = (req_data.get(f"codice_buono_{r.id_articolo}") or str(r.codice_articolo or '')).strip()
                descr_scelta = (req_data.get(f"descrizione_buono_{r.id_articolo}") or str(r.descrizione or '')).strip()

                # Le note del buono NON devono essere copiate subito sulla riga originale.
                # Nel parziale vanno solo sulla nuova riga creata; la riga residua mantiene le sue note originali.
                note_inserite = req_data.get(f"note_{r.id_articolo}")
                note_originale = r.note

                # Scarico parziale:
                # deve funzionare sia quando viene tolto solo un codice/descrizione da una cella multi-valore,
                # sia quando viene prelevata solo una parte dei pezzi/colli della stessa riga.
                #
                # Logica corretta:
                # 1) la riga originale resta in giacenza con il residuo;
                # 2) viene creata una nuova riga per il materiale messo nel buono;
                # 3) la nuova riga mantiene codice/descrizione del buono e N. buono;
                # 4) se lo scarico è solo quantitativo, la riga residua mantiene lo stesso codice/descrizione.
                if action == 'save':
                    old_cod = (r.codice_articolo or '').strip()
                    old_desc = (r.descrizione or '').strip()

                    q_scelta = req_data.get(f"q_{r.id_articolo}")
                    pezzi_originali = _num_float(getattr(r, 'pezzo', None))
                    pezzi_scelti = _num_float(q_scelta) if q_scelta is not None else pezzi_originali
                    if pezzi_originali > 0 and (pezzi_scelti <= 0 or pezzi_scelti > pezzi_originali):
                        pezzi_scelti = pezzi_originali
                    pezzi_residui = max(0.0, pezzi_originali - pezzi_scelti) if pezzi_originali > 0 else 0.0

                    cod_parziale = bool(codice_scelto and _norm_for_match(codice_scelto) != _norm_for_match(old_cod))
                    desc_parziale = bool(descr_scelta and _norm_for_match(descr_scelta) != _norm_for_match(old_desc))

                    # Parziale anche se il codice/descrizione resta uguale ma viene indicata una quantità inferiore.
                    qta_parziale = bool(
                        q_scelta is not None
                        and pezzi_originali > 0
                        and pezzi_scelti > 0
                        and pezzi_scelti < pezzi_originali
                    )

                    if cod_parziale or desc_parziale or qta_parziale:
                        scarico_parziale_eseguito = True

                        # Scarico parziale:
                        # la riga originale resta in giacenza SENZA numero buono;
                        # il numero buono va solo sulla nuova riga del materiale prelevato.
                        r.buono_n = ""

                        # Prima creo la riga "materiale del buono", così non si perde nulla.
                        riga_buono = Articolo()
                        for col in Articolo.__table__.columns:
                            if col.name == 'id_articolo':
                                continue
                            setattr(riga_buono, col.name, getattr(r, col.name))

                        riga_buono.codice_articolo = codice_scelto or old_cod
                        riga_buono.descrizione = descr_scelta or old_desc
                        riga_buono.buono_n = bn or r.buono_n

                        # I pezzi scaricati vanno sulla nuova riga; sulla riga originale resta il residuo.
                        if pezzi_originali > 0:
                            riga_buono.pezzo = _fmt_num_clean(pezzi_scelti)
                            r.pezzo = _fmt_num_clean(pezzi_residui)

                            for campo in ('peso', 'm2', 'm3'):
                                residuo_val, scelto_val = _split_quantita(pezzi_originali, pezzi_scelti, getattr(r, campo, None))
                                try:
                                    setattr(riga_buono, campo, _round_db_number(scelto_val))
                                    setattr(r, campo, _round_db_number(residuo_val))
                                except Exception:
                                    pass

                        riga_buono.data_uscita = getattr(r, 'data_uscita', '') or ''
                        riga_buono.n_ddt_uscita = getattr(r, 'n_ddt_uscita', '') or ''

                        # Le note scritte nel buono vanno solo sulla nuova riga.
                        # Non aggiungo testi automatici tipo "scarico parziale".
                        riga_buono.note = (note_inserite or '').strip()

                        db.add(riga_buono)

                        # Poi aggiorno la riga originale lasciando solo il residuo.
                        # Se il parziale è solo quantitativo, codice e descrizione devono restare sulla riga in giacenza.
                        if cod_parziale:
                            codice_residuo = _remove_selected_from_cell(old_cod, codice_scelto)
                            # Mantiene sulla riga residua eventuale N. package / pallet / cassa.
                            r.codice_articolo = _preserve_package_context(codice_residuo, old_cod, codice_scelto)
                        else:
                            r.codice_articolo = old_cod

                        if desc_parziale and _description_has_multiple_items(old_desc):
                            descr_residua = _remove_selected_from_cell(old_desc, descr_scelta)
                            # Mantiene sulla riga residua eventuale N. package / pallet / cassa anche se scritto in descrizione.
                            r.descrizione = _preserve_package_context(descr_residua, old_desc, descr_scelta)
                        else:
                            # Se la descrizione è unica, va mantenuta anche sulla riga residua.
                            r.descrizione = old_desc

                        # La riga residua mantiene le note originali.
                        r.note = note_originale
                    else:
                        # Buono normale/non parziale: qui il N. buono e le note restano sulla riga selezionata.
                        if bn:
                            r.buono_n = bn
                        if note_inserite is not None:
                            r.note = note_inserite
                        if q_scelta is not None and _num_float(q_scelta) > 0:
                            r.pezzo = _fmt_num_clean(_num_float(q_scelta))

            picking_msg = ""
            if action == 'save':
                # 1) Salvo SEMPRE prima il Buono e le modifiche alle Giacenze.
                # Il Picking è un'operazione collegata ma non deve mai bloccare
                # la creazione del PDF del Buono.
                db.commit()

                # 2) Creo il Picking in una transazione separata.
                # Se il Picking fallisce per schema/colonne/dati, faccio rollback
                # solo del Picking e lascio valido il Buono appena creato.
                picking_created = False
                try:
                    try:
                        # Crea il Picking SOLO se la spunta è attiva.
                        # Quando la checkbox non viene selezionata, il browser non invia picking_enable.
                        picking_enable = (req_data.get('picking_enable') == '1')
                        if picking_enable:
                            fresh_rows = db.query(Articolo).filter(Articolo.id_articolo.in_(ids)).all()
                            picking_created, picking_msg = _create_picking_from_buono_form(db, req_data, fresh_rows, bn)
                            db.commit()
                        else:
                            picking_created = False
                            picking_msg = ''
                    except Exception as e_pick_inner:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        picking_msg = str(e_pick_inner) if "e_pick_inner" in locals() else "Picking non creato automaticamente: controllare la sezione Picking/Lavorazioni."
                        try:
                            scrivi_log_errore("Errore creazione picking da buono", e_pick_inner)
                        except Exception:
                            pass
                except Exception as e_pick:
                    picking_msg = str(e_pick_inner) if "e_pick_inner" in locals() else "Picking non creato automaticamente: controllare la sezione Picking/Lavorazioni."
                    try:
                        scrivi_log_errore("Errore creazione picking da buono", e_pick)
                    except Exception:
                        pass

                if picking_msg:
                    try:
                        flash(picking_msg, "success" if picking_created else "warning")
                    except Exception:
                        pass

                if scarico_parziale_eseguito:
                    flash(
                        "Scarico parziale salvato. Pezzi, note e N. buono sono stati inseriti solo sulla nuova riga prelevata; la riga residua resta pulita.",
                        "success"
                    )
                else:
                    flash("Buono salvato correttamente.", "success")

            pdf_bio = _generate_buono_pdf(req_data, rows)

            safe_bn = (bn or "senza_numero").replace("/", "-").replace("\\", "-")
            return send_file(
                pdf_bio,
                as_attachment=(action == 'save'),
                download_name=f'Buono_{safe_bn}.pdf',
                mimetype='application/pdf'
            )

        except Exception as e:
            db.rollback()
            scrivi_log_errore("Errore Buono di Prelievo", e)
            print(f"ERRORE BUONO: {e}")
            return f"Errore server: {e}", 500
        finally:
            db.close()
