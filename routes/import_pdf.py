# -*- coding: utf-8 -*-
"""
Modulo Import PDF - Step 1.

Sono state spostate qui le funzioni principali collegate a:
- import_pdf
- save_pdf_import
- estrazione/OCR dati da PDF DDT/Bolla

Il file principale resta più leggero e le route mantengono gli stessi endpoint.
"""

def register_import_pdf_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    # --- HELPER ESTRAZIONE PDF (Necessario per Import PDF) ---


    def extract_data_from_ddt_pdf(path):
        import pdfplumber
        import pytesseract
        import re
        from datetime import date, datetime

        def _to_float_it(s):
            s = (s or "").strip()
            if not s:
                return None
            s = s.replace(".", "").replace(",", ".")
            try:
                return float(s)
            except Exception:
                return None

        def _to_int(s):
            try:
                return int(float(str(s).strip().replace(",", ".")))
            except Exception:
                return None

        def _clean_spaces(s):
            return re.sub(r"\s+", " ", (s or "")).strip()

        def _norm(s):
            return re.sub(r"[^A-Z0-9]+", "", (s or "").upper())

        def _looks_like_code(tok):
            tok = (tok or "").strip().upper()
            if not tok:
                return False
            patterns = [
                r"\d{6,8}-\d{4}-\d+-\d+",
                r"\d{6,8}-\d{4}",
                r"ITM\d{5,}",
                r"U\d{6,}",
                r"[A-Z]{1,4}/\d{4,8}",
                r"\d{4}\.\d{3}",
                r"[0-9A-Z]{3,}(?:[-/.][0-9A-Z]{2,}){1,}",
            ]
            return any(re.fullmatch(p, tok) for p in patterns)

        def _first_code_in_line(line):
            patterns = [
                r"\b\d{6,8}-\d{4}-\d+-\d+\b",
                r"\b\d{6,8}-\d{4}\b",
                r"\bITM\d{5,}\b",
                r"\bU\d{6,}\b",
                r"\b[A-Z]{1,4}/\d{4,8}\b",
                r"\b\d{4}\.\d{3}\b",
                r"\b[0-9A-Z]{3,}(?:[-/.][0-9A-Z]{2,}){1,}\b",
                r"\bW\d{8,}[A-Z0-9]*\b",
                r"\b\d{7,12}\b",
            ]
            for pat in patterns:
                m = re.search(pat, line)
                if m:
                    return m.group(0).strip()
            return ""

        def _ocr_page(page):
            """OCR robusto per scansioni dritte o ruotate.
            Ottimizzato per i PDF Fincantieri/VARD: le pagine di packing list sono spesso ruotate.
            """
            try:
                img = page.to_image(resolution=100).original
                page_no = int(getattr(page, 'page_number', 1) or 1)

                # Nei PDF VARD/Fincantieri le packing list sono spesso da pag. 4 in poi e ruotate.
                rotations = (270, 0) if page_no >= 4 else (0, 270)
                best_txt = ""
                best_score = 0
                for rot in rotations:
                    try:
                        im = img.rotate(rot, expand=True) if rot else img
                        txt = pytesseract.image_to_string(im, lang='eng', config='--psm 6') or ""
                        score = len(re.findall(r"[A-Za-z0-9]", txt))
                        if score > best_score:
                            best_score = score
                            best_txt = txt
                        # Se la prima rotazione è già sufficiente, non insiste.
                        if score > 450:
                            break
                    except Exception:
                        pass
                return best_txt
            except Exception:
                return ""

        def _extract_text(pdf):
            chunks = []
            for page in pdf.pages:
                txt = (page.extract_text() or "").strip()
                if len(re.findall(r"[A-Za-z0-9]", txt)) < 40:
                    ocr_txt = _ocr_page(page).strip()
                    if len(re.findall(r"[A-Za-z0-9]", ocr_txt)) > len(re.findall(r"[A-Za-z0-9]", txt)):
                        txt = ocr_txt
                chunks.append(txt)
            return "\n".join([c for c in chunks if c])

        def _canonical_client_from_text(full_text, lines):
            t = (full_text or "").upper()
            destination_zone = " ".join(
                ln for ln in lines
                if re.search(r"DESTINAT|DESTINAZIONE|DELIVERY ADDRESS|LUOGO DESTINAZIONE MERCE|LUOGO DESTINAZIONE|CLIENTE", ln, re.I)
                or ('C/O CAMAR' in ln.upper())
            ).upper()
            zone = destination_zone or t

            alias_map = {
                'GALVANO TECNICA': [r'COTUGNO\s+GALVANOTECNICA', r'GALVANO ?TECNICA', r'GALVANOTECNICA'],
                'FINCANTIERI': [r'FINCANTIERI'],
                'AMICO': [r'AMICO\s*&\s*CO', r'AMICO'],
                'DUFERCO': [r'DUFERCO'],
                'WINGECO': [r'WINGECO'],
                'DE WAVE': [r'DE\s*WAVE'],
                'RF-DE WAVE': [r'RF\s*[- ]\s*DE\s*WAVE'],
                'DE WAVE SAMA': [r'DE\s*WAVE\s*SAMA'],
                'MARINE INTERIORS': [r'MARINE\s+INTERIORS'],
                'SIEMGROUP': [r'SIEMGROUP', r'SIEM\s+GROUP'],
                'SGDP': [r'SGDP'],
                'SCORZA': [r'SCORZA'],
            }

            for canonical, pats in alias_map.items():
                if any(re.search(p, zone, re.I) for p in pats):
                    return canonical
            for canonical, pats in alias_map.items():
                if any(re.search(p, t, re.I) for p in pats):
                    return canonical

            try:
                clienti_validi = get_clienti_utenti()
            except Exception:
                clienti_validi = []
            for c in clienti_validi:
                if _norm(c) and _norm(c) in _norm(zone):
                    return c
            for c in clienti_validi:
                if _norm(c) and _norm(c) in _norm(t):
                    return c
            return ""

        def _extract_supplier(lines, full_text):
            known = [
                r'ATOTECH(?:\s+ITALIA)?\s+S\.R\.L\.?',
                r'MKS\s+ATOTECH',
                r'HALTON\s+MARINE\s+OY',
                r'CO\. ?ME\. ?FRI\.?[-A-Z ]*S\.P\.A\.?',
                r'FINCANTIERI\s+S\.P\.A\.?',
                r'AMICO\s*&\s*CO\.\s*S\.P\.A\.?',
                r'AMICO\s*&\s*CO',
                r'ATENA\s+S\.?R\.?L\.?',
                r'FERTUBI\s+FRIULI(?:\s+S\.?R\.?L\.?)?',
            ]
            head = lines[:80]
            joined_head = "\n".join(head)
            for pat in known:
                m = re.search(pat, joined_head, re.I)
                if m:
                    val = _clean_spaces(m.group(0).replace('MKS ', ''))
                    return val

            bad_words = ('LOGISTICA', 'LOGISTICS', 'VETTORE', 'CORRIERE', 'TRASPORT', 'CA.MAR', 'CAMAR')
            company_re = re.compile(r'([A-Z0-9&.,\- ]{3,}(?:S\.R\.L\.?|S\.P\.A\.?|SRL|SPA|OY|LTD|GMBH|SAS))', re.I)
            for ln in head:
                cand = _clean_spaces(ln)
                if not cand or any(b in cand.upper() for b in bad_words):
                    continue
                m = company_re.search(cand)
                if m:
                    return _clean_spaces(m.group(1))
            return ""

        def _extract_meta(lines, full_text):
            meta = {
                "cliente": _canonical_client_from_text(full_text, lines),
                "fornitore": _extract_supplier(lines, full_text),
                "commessa": "",
                "n_ddt": "",
                "data_ingresso": date.today().strftime("%Y-%m-%d"),
            }
            # Se il file si chiama tipo "ARRIVO N°32_26 FINCANTIERI.pdf", precompila N. Arrivo = 32/26
            try:
                fname = os.path.basename(str(path))
                m_arr = re.search(r"ARRIVO\s*N[°º.]?\s*(\d+)\s*[_/-]\s*(\d+)", fname, re.I)
                if m_arr:
                    meta["n_arrivo"] = f"{m_arr.group(1)}/{m_arr.group(2)}"
            except Exception:
                pass

            for ln in lines:
                if not meta['n_ddt']:
                    for pat in [
                        r"(?:DDT\s*N[°º.]?|N[°º.]?\s*DDT|NUMERO\s*BOLLA|DELIVERY\s*NOTE|DOCUMENTO\s*DI\s*TRASPORTO)\s*[:\-]?\s*([A-Z0-9./\-]{4,})",
                        r"\b(DN\d{5,})\b",
                        r"\b([A-Z]{1,3}\d{5,})\b",
                    ]:
                        m = re.search(pat, ln, re.I)
                        if m:
                            val = m.group(1).strip()
                            if val.upper() not in ('D.D.T', 'DDT'):
                                meta['n_ddt'] = val
                                break

                if not meta['commessa']:
                    m = re.search(r"(?:COMMESSA|ORDINE\s*/\s*CONTRATTO|YOUR\s+ORDER\s+NO\.?|VS\.?\s*RIF\.?|RIFERIMENTO)\s*[:\-]?\s*([A-Z0-9./\-]{4,})", ln, re.I)
                    if m:
                        meta['commessa'] = m.group(1).strip()

            if not meta['commessa']:
                m = re.search(r"\b(00\d{4,}[A-Z]{1,5}|SE-COP-\d+|OV\d+|[A-Z]{2}\d{6,})\b", full_text, re.I)
                if m:
                    meta['commessa'] = m.group(1).strip()

            m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", full_text)
            if m:
                try:
                    meta['data_ingresso'] = datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
                except Exception:
                    pass
            else:
                m = re.search(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b", full_text)
                if m:
                    try:
                        meta['data_ingresso'] = datetime.strptime(m.group(1), "%d.%m.%Y").strftime("%Y-%m-%d")
                    except Exception:
                        pass

            return {k: _clean_spaces(v) for k, v in meta.items()}

        def _merge_rows(rows):
            merged = {}
            for r in rows:
                key = (r.get('codice') or '', r.get('descrizione') or '', r.get('lotto') or '', r.get('serial_number') or '')
                if key not in merged:
                    merged[key] = dict(r)
                else:
                    merged[key]['colli'] = to_int_eu(merged[key].get('colli')) + to_int_eu(r.get('colli'))
                    try:
                        merged[key]['pezzi'] = float(merged[key].get('pezzi') or 0) + float(r.get('pezzi') or 0)
                    except Exception:
                        pass
                    if not merged[key].get('pezzi_articolo') and r.get('pezzi_articolo'):
                        merged[key]['pezzi_articolo'] = r.get('pezzi_articolo')
                    if not merged[key].get('um') and r.get('um'):
                        merged[key]['um'] = r.get('um')
            return list(merged.values())

        def _base_row(codice='', descrizione='', colli=0, pezzi=0, um='', pezzi_articolo='', lotto='', serial_number=''):
            return {
                'codice': (codice or '').strip(),
                'descrizione': _clean_spaces(descrizione),
                'colli': colli if colli is not None else 0,
                'pezzi': pezzi if pezzi is not None else 0,
                'um': (um or '').strip().upper(),
                'pezzi_articolo': (pezzi_articolo or '').strip(),
                'lotto': (lotto or '').strip(),
                'serial_number': (serial_number or '').strip(),
            }

        def _parse_atotech(lines):
            rows = []
            current = None
            for ln in lines:
                m = re.search(r"\b(\d{7}-\d{4}-\d+-\d+)\b\s+(.+?)\s+(?:CAN|PAL|BOX|CRT|UN)\s+(\d+)\s+(\d+(?:,\d+)?)\s+(\d+(?:,\d+)?)\s+(KG|PZ|NR|UN)\s+(\d+(?:,\d+)?)", ln, re.I)
                if m:
                    codice = m.group(1)
                    descr = m.group(2)
                    colli = _to_int(m.group(3)) or 0
                    um = m.group(6).upper()
                    qta = _to_float_it(m.group(7)) or 0
                    pezzi_articolo = ''
                    mc = re.match(r"^(\d{6,8})-(\d{4})-(\d+)-", codice)
                    if mc:
                        pezzi_articolo = mc.group(3).lstrip('0') or mc.group(3)
                    current = _base_row(codice, descr, colli, qta, um, pezzi_articolo)
                    rows.append(current)
                    continue
                if current is not None:
                    mlot = re.search(r"\bLOTTO\b\s*([A-Z0-9\-./]+)", ln, re.I)
                    if mlot:
                        current['lotto'] = mlot.group(1).strip()
            return rows

        def _parse_comefri(lines):
            rows = []
            for ln in lines:
                m = re.search(r"^(?:\d+\s+)?([A-Z]{1,4}/\d{3,8})\s+(U\d{6,}|[A-Z0-9.\-/]{5,})\s+(.+?)\s+(PZ|KG|NR)\s+(\d+(?:[.,]\d+)?)\s*$", ln, re.I)
                if m:
                    articolo_cliente = m.group(1).strip()
                    codice = m.group(2).strip()
                    descr = m.group(3).strip()
                    um = m.group(4).upper()
                    qta = _to_float_it(m.group(5)) or 0
                    rows.append(_base_row(codice, descr, 1, qta, um, str(_to_int(qta) or '')))
            return rows

        def _parse_amico(lines):
            rows = []
            i = 0
            while i < len(lines):
                ln = lines[i]
                if re.fullmatch(r"\d{1,3}", ln.strip()):
                    collo = _to_int(ln.strip()) or 0
                    block = []
                    j = i + 1
                    while j < len(lines) and len(block) < 6:
                        nxt = lines[j]
                        if re.fullmatch(r"\d{1,3}", nxt.strip()) and block:
                            break
                        block.append(nxt)
                        if re.search(r"\b\d{4}\.\d{3}\b.*\b\d+(?:[.,]\d+)?\b$", nxt):
                            break
                        j += 1
                    joined = " ".join(block)
                    m = re.search(r"(.+?)\s+(\d{4}\.\d{3})\s+(\d+(?:[.,]\d+)?)\s*$", joined)
                    if m:
                        descr = m.group(1)
                        codice = m.group(2)
                        qta = _to_float_it(m.group(3)) or 0
                        rows.append(_base_row(codice, descr, collo, qta, 'PZ', str(_to_int(qta) or '')))
                        i = j
                i += 1
            return rows

        def _parse_halton(lines):
            rows = []
            for idx, ln in enumerate(lines):
                if 'ITM' not in ln.upper():
                    continue
                m = re.search(r"\b(ITM\d{5,})\b\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s+(?:\d+(?:[.,]\d+)?\s+)?(PCS|PZ|KG)\b", ln, re.I)
                if m:
                    codice = m.group(1)
                    descr = m.group(2)
                    qta = _to_float_it(m.group(3)) or 0
                    um = m.group(4).upper()
                    extra = []
                    k = idx + 1
                    while k < len(lines) and len(extra) < 3:
                        nxt = lines[k]
                        if _first_code_in_line(nxt) or re.search(r"^\d+\s+\d+\s+ITM", nxt):
                            break
                        if not re.search(r"COMMODITY CODE|COUNTRY OF ORIGIN|EARLIER DELIVERED|PAGE\b", nxt, re.I):
                            extra.append(nxt)
                        k += 1
                    descr = _clean_spaces(" ".join([descr] + extra))
                    rows.append(_base_row(codice, descr, 0, qta, um, str(_to_int(qta) or '')))
            return rows

        def _parse_fincantieri_generic(lines):
            """Parser dedicato Fincantieri/VARD.

            Regola richiesta:
            - Codice articolo = Numero Package + Marca pezzo
            - Pezzi = colonna QTY
            - Descrizione = descrizione/merce letta dalla packing list
            - Colli = numero package, se leggibile, altrimenti 1
            - Peso = gross weight, se leggibile
            """
            rows = []
            full = "\n".join(lines)
            up = full.upper()

            # Attiva solo sui documenti Fincantieri/VARD/packing list.
            is_fincantieri_vard = bool(
                re.search(r"FINCANTIERI", up)
                and re.search(r"\bVARD\b|SHIPYARDS|PACKING\s*LIST|C6333", up)
            )

            # Caso pedane / nessun codice articolo già gestito in precedenza.
            if re.search(r"\bPEDANE\b", full, re.I):
                m_qty = re.search(r"\b(\d+)\s+PZ\s+PEDANE\b", full, re.I)
                m_colli = re.search(r"NUMERO\s+COLLI\s+(\d+)", full, re.I)
                m_peso = re.search(r"TOTALE:\s*\d+\s+(\d+[.,]\d+)", full, re.I)
                qty = _to_int(m_qty.group(1)) if m_qty else 0
                colli = _to_int(m_colli.group(1)) if m_colli else qty
                peso = _to_float_it(m_peso.group(1)) if m_peso else qty
                rows.append(_base_row('', 'PEDANE', colli or 0, peso or 0, 'KG', str(qty or '')))

            if not is_fincantieri_vard:
                return rows

            def _clean_ocr_cell(s):
                s = _clean_spaces(s or '')
                s = s.replace('|', ' ')
                s = re.sub(r"[\[\]{}]+", " ", s)
                s = re.sub(r"\s+", " ", s).strip(" -_;:,.|")
                return s

            def _fix_package_no(s):
                s = _clean_ocr_cell(s)
                s = s.replace(',', '.')
                # 620/14.04.2026, 8976/05.05.2026, ecc.
                m = re.search(r"(\d{2,5}\s*/\s*\d{1,2}[./]\d{1,2}[./]\d{4})", s)
                if not m:
                    return ''
                val = re.sub(r"\s+", "", m.group(1)).replace('/', '/', 1)
                return val.replace('.', '.')

            def _extract_nums_tail(s):
                # Ritorna possibili quantità, colli, peso dalla coda della riga.
                nums = re.findall(r"(?<![A-Z0-9/])\d+(?:[.,]\d+)?(?![A-Z0-9/])", s)
                # Rimuove numeri che fanno parte del package/date, tenendo quelli dopo U/M se possibile.
                after_um = s
                m_um = re.search(r"\b(PCS|PZ|SET|KG)\b", s, re.I)
                if m_um:
                    after_um = s[m_um.end():]
                    nums2 = re.findall(r"\d+(?:[.,]\d+)?", after_um)
                    if nums2:
                        nums = nums2
                qty = _to_int(nums[0]) if nums else 1
                colli = _to_int(nums[1]) if len(nums) >= 2 else 1
                peso = _to_float_it(nums[-1]) if len(nums) >= 3 else None
                if not qty or qty < 0:
                    qty = 1
                if not colli or colli < 0:
                    colli = 1
                return qty, colli, peso

            def _row_from_line(ln):
                raw = _clean_ocr_cell(ln)
                if not re.search(r"PACKING\s*LIST|POCTING|PACING|PACKINGL", raw, re.I):
                    return None
                pkg = _fix_package_no(raw)
                if not pkg:
                    return None

                # Parte prima del package = descrizione generale, se utile.
                before, after = raw.split(pkg, 1)
                before = re.sub(r"^\s*\d+\s*", "", before)
                before = re.sub(r"PACKING\s*LIST", "", before, flags=re.I)
                before = re.sub(r"\b(?:WARTSILA|VARD|LUMINITA|SCENSHIP|SCANSHIP|OFFICINA\s+MECCANICA)\b", "", before, flags=re.I)
                before = _clean_ocr_cell(before)

                # Parte dopo il package = marca pezzo / descrizione, prima di UM/quantità.
                after0 = after
                marca = re.split(r"\b(?:PCS|PZ|SET|KG)\b", after0, flags=re.I)[0]
                marca = _clean_ocr_cell(marca)
                marca = re.sub(r"\b(?:FAT|LOT|TOTAL|TOTALE)\b.*$", "", marca, flags=re.I).strip()

                # Se l'OCR mette la descrizione nella riga prima e lascia marca vuota, usa before.
                descr = marca or before or 'Packing list Fincantieri'
                if before and marca and before.upper() not in marca.upper():
                    # Mantiene una descrizione più completa senza sporcare troppo.
                    descr = _clean_ocr_cell(f"{before} {marca}")

                # Evita righe troppo generiche/gruppi pacchi.
                if re.fullmatch(r"(?i)(PACKING|LIST|PACKING LIST|VARD|WARTSILA)", descr or ''):
                    return None

                qty, colli, peso = _extract_nums_tail(after0)
                um_m = re.search(r"\b(PCS|PZ|SET|KG)\b", after0, re.I)
                um = 'PZ'
                if um_m:
                    um_raw = um_m.group(1).upper()
                    um = {'PCS': 'PZ', 'SET': 'PZ'}.get(um_raw, um_raw)

                codice = _clean_ocr_cell(f"PACKAGE No.{pkg} - {descr}")
                return _base_row(
                    codice=codice,
                    descrizione=descr,
                    colli=colli or 1,
                    pezzi=peso if peso is not None else qty,
                    um='KG' if peso is not None else um,
                    pezzi_articolo=str(qty or 1),
                )

            # Scansione righe OCR. Una riga = una riga di packing list quando possibile.
            for ln in lines:
                row = _row_from_line(ln)
                if row:
                    rows.append(row)

            # Fallback: se alcune righe sono state spezzate, unisci piccole finestre di righe.
            if len(rows) < 3:
                for i in range(len(lines)):
                    joined = _clean_ocr_cell(' '.join(lines[i:i+3]))
                    row = _row_from_line(joined)
                    if row:
                        rows.append(row)

            # Dedup mantenendo il primo risultato.
            dedup = []
            seen = set()
            for r in rows:
                key = (r.get('codice') or '').upper()
                if key and key not in seen:
                    seen.add(key)
                    dedup.append(r)

            return dedup

        def _parse_generic(lines):
            extracted_rows = []
            last_row = None
            for line in lines:
                if last_row is not None:
                    m_lotto = re.search(r"\bLOTTO\b\s*[:\-]?\s*([A-Z0-9\-./]+)", line, flags=re.I)
                    if m_lotto:
                        last_row['lotto'] = m_lotto.group(1).strip()
                        continue
                    m_ser = re.search(r"\b(?:SERIAL(?:E)?|SERIAL\s*NUMBER|MATRICOLA|S/?N)\b\s*[:\-]?\s*([A-Z0-9\-./]+)", line, flags=re.I)
                    if m_ser:
                        last_row['serial_number'] = m_ser.group(1).strip()
                        continue

                if re.search(r"^(CLIENTE|FORNITORE|DESTINATARIO|MITTENTE|COMMESSA|N\.?\s*DDT|DDT|BOLLA|DATA)\b", line, re.I):
                    continue

                codice = _first_code_in_line(line)
                if not codice and not re.search(r"\bPEDANE\b", line, re.I):
                    continue

                rest = _clean_spaces(line.replace(codice, ' ', 1)) if codice else line
                um = ''
                um_m = re.search(r"\b(KG|KGS|PZ|PZS|NR|N\.?|UN|PCS)\b", line, flags=re.I)
                if um_m:
                    um = um_m.group(1).upper().replace('.', '')
                    um = {'KGS': 'KG', 'PZS': 'PZ', 'PCS': 'PZ'}.get(um, um)

                colli = None
                m_colli = re.search(r"\bCOLLI\b\s*[:\-]?\s*(\d+)", line, flags=re.I)
                if m_colli:
                    colli = _to_int(m_colli.group(1))
                else:
                    tokens = rest.split()
                    for tok in tokens:
                        if tok.isdigit():
                            v = _to_int(tok)
                            if v is not None and 0 <= v <= 9999:
                                colli = v
                                break

                lotto = ''
                m_lotto_inline = re.search(r"\bLOTTO\b\s*[:\-]?\s*([A-Z0-9\-./]+)", line, flags=re.I)
                if m_lotto_inline:
                    lotto = m_lotto_inline.group(1).strip()

                serial = ''
                m_ser_inline = re.search(r"\b(?:SERIAL(?:E)?|SERIAL\s*NUMBER|MATRICOLA|S/?N)\b\s*[:\-]?\s*([A-Z0-9\-./]+)", line, flags=re.I)
                if m_ser_inline:
                    serial = m_ser_inline.group(1).strip()

                pezzi_articolo = ''
                m_pz_code = re.match(r"^(\d{6,8})-(\d{4})-(\d+)-", codice or '')
                if m_pz_code:
                    pezzi_articolo = m_pz_code.group(3).lstrip('0') or m_pz_code.group(3)

                temp_for_nums = line
                if codice:
                    temp_for_nums = temp_for_nums.replace(codice, ' ')
                temp_for_nums = re.sub(r"\b(?:LOTTO|SERIAL(?:E)?|SERIAL\s*NUMBER|MATRICOLA|S/?N)\b\s*[:\-]?\s*[A-Z0-9\-./]+", ' ', temp_for_nums, flags=re.I)
                nums = re.findall(r"\d+(?:[.,]\d+)?", temp_for_nums)
                qta = None
                if nums:
                    preferred = None
                    for n in nums:
                        if ',' in n or '.' in n:
                            preferred = n
                    if preferred is None:
                        preferred = nums[-1]
                    qta = _to_float_it(preferred)

                descrizione = rest
                descrizione = re.sub(r"\bLOTTO\b\s*[:\-]?\s*[A-Z0-9\-./]+", ' ', descrizione, flags=re.I)
                descrizione = re.sub(r"\b(?:SERIAL(?:E)?|SERIAL\s*NUMBER|MATRICOLA|S/?N)\b\s*[:\-]?\s*[A-Z0-9\-./]+", ' ', descrizione, flags=re.I)
                descrizione = re.sub(r"\b(CAN|PAL|BOX|CRT|CASS|COLLI?|PCS)\b", ' ', descrizione, flags=re.I)
                if colli is not None:
                    descrizione = re.sub(rf"\b{re.escape(str(colli))}\b", ' ', descrizione, count=1)
                if um:
                    descrizione = re.sub(rf"\b{re.escape(um)}\b", ' ', descrizione, flags=re.I)
                descrizione = _clean_spaces(descrizione)

                if not codice and not descrizione:
                    continue

                row = _base_row(codice, descrizione, colli if colli is not None else 0, qta if qta is not None else 0, um, pezzi_articolo, lotto, serial)
                extracted_rows.append(row)
                last_row = row
            return extracted_rows

        def _profile_fix_meta(meta, lines, full_text):
            txt = "\n".join(lines)
            up = (txt + "\n" + (full_text or '')).upper()
            meta = dict(meta or {})

            if re.search(r"COTUGNO\s+GALVANOTECNICA|GALVANO\s*TECNICA", up):
                meta['cliente'] = 'GALVANO TECNICA'
            if re.search(r"MARINE\s+INTERIORS", up):
                meta['cliente'] = 'MARINE INTERIORS'
            if re.search(r"DE\s+WAVE", up):
                meta['cliente'] = 'DE WAVE'
            if re.search(r"FINCANTIERI", up) and re.search(r"\bVARD\b|SHIPYARDS|C6333|PACKING\s*LIST", up):
                meta['cliente'] = 'FINCANTIERI'
                meta['fornitore'] = meta.get('fornitore') or 'VARD'

            if re.search(r"ATOTECH|MKS", up):
                meta['fornitore'] = 'ATOTECH ITALIA S.R.L.'
            if re.search(r"\bATENA\b", up):
                meta['fornitore'] = 'ATENA S.R.L.'
            if re.search(r"FERTUBI\s+FRIULI", up):
                meta['fornitore'] = 'FERTUBI FRIULI S.R.L.'

            if not meta.get('n_ddt'):
                for pat in [
                    r"SERIA\s*[:\-]?\s*(?:VSRTL\s*[*#-]?)?\s*(\d{3,})",
                    r"\bVSRTL\s*[*#-]?(\d{3,})\b",
                    r"NUMERO\s+BOLLA\s+(?:DATA\s+BOLLA\s+)?([A-Z0-9./-]{3,})",
                    r"\b(AT\d{5,})\b",
                    r"NUMERO\s+DOCUMENTO\s+(\d{3,})",
                    r"DOCUMENTO\s+DI\s+TRASPORTO.*?NUMERO\s+(\d{3,})",
                    r"\bNUMERO\b\s*\n?\s*(\d{3,})\s+\d{1,2}/\d{1,2}/\d{4}",
                ]:
                    m = re.search(pat, txt, re.I | re.S)
                    if m:
                        meta['n_ddt'] = m.group(1).strip(); break

            if not meta.get('commessa'):
                for pat in [
                    r"ORDINE\s+INTERNO\s+(\d{5,})",
                    r"RIF\.?\s*\(OR\)\s*N\.?\s*(\d+)",
                    r"FUORI\s+ORDINE\s+(REF/?\d+)",
                    r"(REGENT\s+VOYAGER[-\s]*\d*)",
                ]:
                    m = re.search(pat, txt, re.I)
                    if m:
                        meta['commessa'] = _clean_spaces(m.group(1)); break

            if not meta.get('data_ingresso') or meta.get('data_ingresso') == date.today().strftime('%Y-%m-%d'):
                m = re.search(r"\b(\d{1,2}[/.]\d{1,2}[/.]\d{4})\b", txt)
                if m:
                    try:
                        meta['data_ingresso'] = datetime.strptime(m.group(1).replace('.', '/'), '%d/%m/%Y').strftime('%Y-%m-%d')
                    except Exception:
                        pass

            meta.setdefault('magazzino', 'STRUPPA')
            meta.setdefault('stato', 'NAZIONALE')
            return meta

        def _parse_marine_interiors(lines):
            rows = []
            for idx, ln in enumerate(lines):
                m = re.search(r"\b(W\d{8,}[A-Z0-9]*)\b", ln, re.I)
                if not m:
                    continue
                codice = m.group(1).strip()
                block = [ln.replace(codice, ' ')]
                j = idx + 1
                while j < len(lines) and len(block) < 5:
                    nxt = lines[j]
                    if re.search(r"\bW\d{8,}[A-Z0-9]*\b", nxt, re.I):
                        break
                    block.append(nxt)
                    # in queste bolle la quantità è spesso sul finale della descrizione, es. PZ 2,000
                    if re.search(r"\bPZ\b\s+\d+(?:[.,]\d+)?", nxt, re.I):
                        break
                    j += 1
                joined = _clean_spaces(' '.join(block))
                m_qta = re.search(r"\b(PZ|KG|MT|NR)\b\s+(\d+(?:[.,]\d+)?)", joined, re.I)
                um = m_qta.group(1).upper() if m_qta else 'PZ'
                qta = _to_float_it(m_qta.group(2)) if m_qta else 0
                descr = re.sub(r"\b(PZ|KG|MT|NR)\b\s+\d+(?:[.,]\d+)?", ' ', joined, flags=re.I)
                descr = _clean_spaces(descr)
                rows.append(_base_row(codice, descr, 1, qta or 0, um, str(_to_int(qta) or '') if qta else ''))
            return rows

        def _parse_fertubi_dewave(lines):
            rows = []
            txt = "\n".join(lines)
            if not re.search(r"FERTUBI\s+FRIULI|TUBI\s+SALD", txt, re.I):
                return rows
            for idx, ln in enumerate(lines):
                m = re.search(r"\b(\d{7,12})\b", ln)
                if not m:
                    continue
                codice = m.group(1)
                block = [ln.replace(codice, ' ')]
                j = idx + 1
                while j < len(lines) and len(block) < 7:
                    nxt = lines[j]
                    if re.search(r"\b\d{7,12}\b", nxt) and block:
                        break
                    block.append(nxt)
                    if re.search(r"\b(MT|KG|PZ)\b\s+\d+(?:[.,]\d+)?", nxt, re.I):
                        break
                    j += 1
                joined = _clean_spaces(' '.join(block))
                # esempio Fertubi: dimensioni 30 15 1.5 MT 66,00 62,00
                m_tail = re.search(r"(.*?)(?:\b\d+(?:[.,]\d+)?\s+\d+(?:[.,]\d+)?\s+\d+(?:[.,]\d+)?\s+)?\b(MT|KG|PZ)\b\s+(\d+(?:[.,]\d+)?)(?:\s+(\d+(?:[.,]\d+)?))?", joined, re.I)
                if m_tail:
                    descr = _clean_spaces(m_tail.group(1))
                    um = m_tail.group(2).upper()
                    qta = _to_float_it(m_tail.group(3)) or 0
                    peso = _to_float_it(m_tail.group(4)) if m_tail.group(4) else qta
                else:
                    descr, um, qta, peso = joined, '', 0, 0
                rows.append(_base_row(codice, descr, 1, peso or qta or 0, um, str(_to_int(qta) or '')))
            return rows

        with pdfplumber.open(path) as pdf:
            full_text = _extract_text(pdf)

        lines = [_clean_spaces(l) for l in full_text.splitlines() if _clean_spaces(l)]
        meta = _profile_fix_meta(_extract_meta(lines, full_text), lines, full_text)

        rows = []
        rows.extend(_parse_atotech(lines))
        rows.extend(_parse_comefri(lines))
        rows.extend(_parse_amico(lines))
        rows.extend(_parse_halton(lines))
        rows.extend(_parse_marine_interiors(lines))
        rows.extend(_parse_fertubi_dewave(lines))
        rows.extend(_parse_fincantieri_generic(lines))
        rows.extend(_parse_generic(lines))

        # pulizia righe improbabili / preferenza codice articolo vero
        cleaned = []
        seen = set()
        for r in rows:
            codice = (r.get('codice') or '').strip()
            descr = _clean_spaces(r.get('descrizione') or '')
            if not codice and not descr:
                continue
            if descr.upper() in {'CLIENTE', 'FORNITORE', 'DESTINATARIO', 'MITTENTE'}:
                continue
            # evita righe duplicate palesi
            sig = (codice, descr, r.get('colli') or 0, r.get('pezzi') or 0, r.get('lotto') or '', r.get('serial_number') or '')
            if sig in seen:
                continue
            seen.add(sig)
            r['descrizione'] = descr
            cleaned.append(r)

        if not cleaned:
            # Fallback controllato: permette comunque la conferma manuale anche con PDF scansiti difficili.
            cleaned.append(_base_row('', 'MERCE VARIA', 1, 0, '', '', '', ''))

        return meta, _merge_rows(cleaned)

    # --- ROUTE IMPORT PDF (PROTETTA ADMIN) ---
    @app.route('/import_pdf', methods=['GET', 'POST'])
    @login_required
    @require_admin
    def import_pdf():
        # PROTEZIONE ADMIN
        if session.get('role') != 'admin':
            flash("Accesso negato: Funzione riservata agli amministratori.", "danger")
            return redirect(url_for('giacenze'))

        if request.method == 'POST':
            if 'file' not in request.files: return redirect(request.url)
            f = request.files['file']
            if f.filename:
                temp_path = os.path.join(DOCS_DIR, f"temp_{uuid.uuid4().hex}.pdf")
                f.save(temp_path)
                try:
                    meta, rows = extract_data_from_ddt_pdf(temp_path)
                    # Pulisce file temp
                    if os.path.exists(temp_path): os.remove(temp_path)
                    return render_template('import_pdf.html', meta=meta, rows=rows, clienti_validi=get_clienti_utenti())
                except Exception as e:
                    flash(f"Errore PDF: {e}", "danger")
                    return redirect(url_for('giacenze'))
                
        return render_template('import_pdf.html', meta={}, rows=[], clienti_validi=get_clienti_utenti())

    @app.route('/save_pdf_import', methods=['POST'])
    @login_required
    @require_admin
    def save_pdf_import():
        if session.get('role') != 'admin':
            return "Accesso Negato", 403

        db = SessionLocal()
        try:
            cliente_pdf_import = cliente_from_form_or_current(request.form, request.form.get('cliente'))
            codice_entrata_shared = ensure_codice_entrata(
                request.form.get('codice_entrata'),
                n_arrivo=strip_arrivo_progressivo(request.form.get('n_arrivo')),
                n_ddt=request.form.get('n_ddt'),
                data_ingresso=request.form.get('data_ingresso'),
                cliente=cliente_pdf_import
            )
            codici = request.form.getlist('codice[]')
            descrizioni = request.form.getlist('descrizione[]')
            colli_list = request.form.getlist('colli[]')
            qta_list = request.form.getlist('pezzi[]')  # peso / quantità
            um_list = request.form.getlist('um[]')
            pezzi_articolo_list = request.form.getlist('pezzi_articolo[]')  # pezzi (separati dal peso)
            lotto_list = request.form.getlist('lotto[]')
            serial_list = request.form.getlist('serial_number[]')

            c = 0
            for i in range(len(codici)):
                codice = (codici[i] or "").strip()
                descr = (descrizioni[i] or "").strip()
                if not codice and not descr:
                    continue

                art = Articolo()

                # testata
                art.cliente = validate_cliente_or_raise(request.form.get('cliente'))
                art.fornitore = request.form.get('fornitore')
                art.commessa = request.form.get('commessa')
                art.n_ddt_ingresso = request.form.get('n_ddt')
                art.data_ingresso = (parse_date_ui(request.form.get('data_ingresso')) or date.today()).strftime('%Y-%m-%d')
                art.n_arrivo = request.form.get('n_arrivo')
                art.codice_entrata = codice_entrata_shared
                art.magazzino = (request.form.get('magazzino') or 'STRUPPA').strip().upper()
                art.stato = (request.form.get('stato') or 'NAZIONALE').strip().upper()

                # riga
                art.codice_articolo = codice
                art.descrizione = descr
                art.n_colli = max(0, to_int_eu(colli_list[i] if i < len(colli_list) else 0))
                # Lotto (se presente nel PDF o inserito a mano)
                lt = lotto_list[i] if i < len(lotto_list) else ""
                art.lotto = (lt or "").strip()
                sr = serial_list[i] if i < len(serial_list) else ""
                art.serial_number = (sr or "").strip()

                # Quantità/Peso: il campo 'pezzi[]' in tabella è usato come Peso/Q.tà.
                qta = qta_list[i] if i < len(qta_list) else ""
                um = (um_list[i] if i < len(um_list) else "").strip().upper()

                # Pezzi articolo (separato): es. da codice 1689615-0025-1-000 -> 1
                pz_art = pezzi_articolo_list[i] if i < len(pezzi_articolo_list) else ""
                pz_art = str(pz_art).strip()

                if um == "KG":
                    # qta = peso in Kg
                    art.peso = to_float_eu(qta)
                    # salva anche i pezzi se presenti
                    art.pezzo = pz_art
                else:
                    # qta = pezzi/quantità (non Kg)
                    art.pezzo = str(pz_art or qta).strip()
                    art.peso = to_float_eu(qta) if str(qta).strip() else None

                db.add(art)
                c += 1

            db.commit()
            flash(f"Importati {c} articoli.", "success")
            return redirect(url_for('giacenze'))
        except Exception as e:
            db.rollback()
            flash(f"Errore import PDF: {e}", "danger")
            return redirect(url_for('import_pdf'))
        finally:
            db.close()

