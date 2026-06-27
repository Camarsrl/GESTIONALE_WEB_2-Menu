# -*- coding: utf-8 -*-
"""
CAMY - Crea Buono da Email / PDF / Foto.
Fase sicura: legge testo e allegati, cerca in giacenza e prepara una anteprima.
NON modifica il database e NON crea buoni senza conferma.

Fix robusto:
- legge tabelle Fincantieri copiate da Outlook anche con colonne variabili;
- riconosce Supplier, Description, Marca pezzo, QTY, Package, Order, Protocollo;
- non spezza i codici con slash tipo SE/007VD;
- cerca in giacenza per marca pezzo, protocollo, ordine, fornitore e descrizione.
"""


def register_camy_email_buono_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import re
    import tempfile
    from pathlib import Path
    from html import escape
    from flask import request, render_template, flash
    from flask_login import login_required
    from sqlalchemy import or_, func
    from werkzeug.utils import secure_filename

    CLIENTI_PROTOCOLLO = {"FINCANTIERI", "FINCANTIERI ARMATORE"}

    def _esc(v):
        return escape(str(v or ""))

    def _norm(v):
        return re.sub(r"[^A-Z0-9]+", "", str(v or "").upper())

    def _sql_norm_col(col):
        expr = func.upper(func.coalesce(col, ""))
        for ch in [" ", "-", "_", "/", "\\", ".", "'", "°", ";", ","]:
            expr = func.replace(expr, ch, "")
        return expr

    def _parse_qty(v):
        try:
            s = str(v or "").strip().replace(".", "").replace(",", ".")
            return int(float(s)) if s else 1
        except Exception:
            return 1

    def _extract_text_from_pdf(path):
        try:
            import pdfplumber
            out = []
            with pdfplumber.open(str(path)) as pdf:
                for p in pdf.pages[:10]:
                    # testo normale
                    out.append(p.extract_text() or "")
                    # tabelle vere PDF, se disponibili
                    try:
                        for table in p.extract_tables() or []:
                            for row in table or []:
                                vals = [str(x or "").strip() for x in row]
                                if any(vals):
                                    out.append("\t".join(vals))
                    except Exception:
                        pass
            return "\n".join(out)
        except Exception:
            return ""

    def _extract_text_from_image(path):
        """OCR leggero: se tesseract non è disponibile non blocca la pagina."""
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(str(path))
            return pytesseract.image_to_string(img, lang="ita+eng") or ""
        except Exception:
            return ""

    def _extract_text_from_file(file_storage):
        if not file_storage or not file_storage.filename:
            return ""
        filename = secure_filename(file_storage.filename)
        suffix = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file_storage.save(tmp.name)
            tmp_path = Path(tmp.name)
        try:
            if suffix == ".pdf":
                return _extract_text_from_pdf(tmp_path)
            if suffix in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
                return _extract_text_from_image(tmp_path)
            try:
                return tmp_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _extract_cliente(text):
        txt = text or ""
        tnorm = _norm(txt)

        # Le richieste inviate da dominio/firma Fincantieri sono Fincantieri.
        if "FINCANTIERI" in txt.upper() or "FINCANTIERIIT" in tnorm:
            return "FINCANTIERI"

        try:
            clienti = get_clienti_utenti()
        except Exception:
            clienti = []
        for cli in sorted(clienti, key=lambda x: len(_norm(x)), reverse=True):
            if _norm(cli) and _norm(cli) in tnorm:
                return cli

        for cli in ["FINCANTIERI ARMATORE", "FINCANTIERI", "RF-DE WAVE", "DE WAVE SAMA", "DE WAVE"]:
            if _norm(cli) in tnorm:
                return cli
        return ""

    def _extract_protocollo(text):
        txt = text or ""
        # Formato tipico Fincantieri: 2026SE006424 / 2025SE...
        found = re.findall(r"\b(20\d{2}[A-Z]{1,8}\d{3,})\b", txt, flags=re.I)
        if found:
            return found[-1].strip().upper()
        pats = [
            r"\bprotocollo\s*[:#\-]?\s*([A-Z0-9./_\-]{2,40})",
            r"\bprot\.?\s*[:#\-]?\s*([A-Z0-9./_\-]{2,40})",
        ]
        stop = {"SUPPLIER", "DESCRIPTION", "GOODS", "MARCA", "PEZZO", "ORDER", "QTY", "ARI"}
        for pat in pats:
            m = re.search(pat, txt, re.I)
            if m:
                val = (m.group(1) or "").strip().strip(".,;:").upper()
                if val and val not in stop:
                    return val
        return ""

    def _looks_like_marca_pezzo(value):
        s = str(value or "").strip().strip(".,;:")
        n = _norm(s)
        if len(n) < 4:
            return False
        if re.match(r"^20\d{2}[A-Z]{1,8}\d{3,}$", s, re.I):
            return False
        if re.match(r"^[A-Z0-9]{1,16}/[A-Z0-9][A-Z0-9./_\-]{1,40}$", s, re.I):
            return True
        if re.match(r"^[A-Z]{1,8}\d{2,}[A-Z0-9./_\-]*$", s, re.I):
            return True
        if re.match(r"^\d+[A-Z]{1,8}/[A-Z0-9][A-Z0-9./_\-]{1,40}$", s, re.I):
            return True
        return False

    def _clean_lines(text):
        lines = []
        for raw in re.split(r"[\r\n]+", text or ""):
            clean = re.sub(r"\s+", " ", raw or "").strip()
            if clean:
                lines.append(clean)
        return lines

    def _extract_table_items_fincantieri(text):
        """Legge tabelle Fincantieri copiate da Outlook/PDF/OCR.

        Funziona anche se ci sono colonne aggiuntive:
        Supplier | Description | Marca pezzo | U/M | QTY | Package | NR TRUCK | Marca pezzo | Order | Protocollo
        NACOS MARINE | VALVULA | SE/007VD | pcs | 1 | 307 | SE/007VD | 006333MOE | 2026SE006424
        """
        items, seen = [], set()
        proto_re = re.compile(r"^20\d{2}[A-Z]{1,8}\d{3,}$", re.I)
        um_values = {"PCS", "PZ", "NR", "N", "EA", "PCE", "PC"}
        stop_tokens = {"SUPPLIER", "DESCRIPTION", "DESCRITPION", "GOODS", "MARCA", "PEZZO", "PACKAGE", "PROTOCOLLO", "ORDER", "TRUCK", "QTY", "U/M"}

        for line in _clean_lines(text):
            tokens = line.split()
            if len(tokens) < 6:
                continue

            proto_indices = [i for i, tok in enumerate(tokens) if proto_re.match(tok.strip())]
            if not proto_indices:
                continue
            proto_idx = proto_indices[-1]
            protocollo = tokens[proto_idx].strip().upper()
            before_proto = tokens[:proto_idx]

            # Cerca unità e quantità: ... marca pcs 1 package ...
            um_idx = None
            for i, tok in enumerate(before_proto):
                if tok.strip().upper() in um_values and i + 1 < len(before_proto):
                    if re.match(r"^\d+(?:[,.]\d+)?$", before_proto[i + 1]):
                        um_idx = i
                        break
            if um_idx is None or um_idx == 0:
                continue

            qty = _parse_qty(before_proto[um_idx + 1])

            # marca principale = token prima di U/M, oppure marca valida più vicina.
            codice = ""
            for j in range(um_idx - 1, -1, -1):
                cand = before_proto[j].strip().strip(".,;:")
                if _looks_like_marca_pezzo(cand):
                    codice = cand.upper()
                    marca_idx = j
                    break
            else:
                continue

            # package = primo numero dopo QTY, se presente.
            package = ""
            for tok in before_proto[um_idx + 2:]:
                if re.match(r"^\d+[A-Z0-9./_\-]*$", tok, re.I):
                    package = tok.strip()
                    break

            # order = ultimo token alfanumerico prima del protocollo che non sia il codice e non sia package.
            order = ""
            for tok in reversed(before_proto[um_idx + 2:]):
                t = tok.strip().strip(".,;:")
                if not t or t.upper() in stop_tokens:
                    continue
                if _norm(t) in {_norm(codice), _norm(package)}:
                    continue
                if re.search(r"\d", t) and len(_norm(t)) >= 4:
                    order = t.upper()
                    break

            # Fornitore/descrizione: tutto prima del codice principale.
            prefix = before_proto[:marca_idx]
            descrizione = ""
            fornitore = ""
            if prefix:
                # descrizione di solito è l'ultimo valore prima del marca pezzo.
                descrizione = prefix[-1].strip().upper()
                fornitore = " ".join(prefix[:-1]).strip().upper()

            key = (_norm(codice), _norm(protocollo), _norm(order))
            if key not in seen:
                seen.add(key)
                items.append({
                    "codice": codice,
                    "quantita": qty,
                    "fornitore": fornitore,
                    "descrizione": descrizione,
                    "package": package,
                    "ordine": order,
                    "protocollo": protocollo,
                    "origine": "tabella_fincantieri",
                })
        return items

    def _extract_requested_items(text):
        txt = text or ""
        found, seen = [], set()

        for item in _extract_table_items_fincantieri(txt):
            key = (_norm(item.get("codice")), _norm(item.get("protocollo")), _norm(item.get("ordine")))
            if key not in seen:
                seen.add(key)
                found.append(item)

        patterns = [
            r"\b([A-Z0-9]{1,16}/[A-Z0-9][A-Z0-9./_\-]{1,40})\b\s*(?:x|qta|qtà|quantit[aà]|pezzi|pz|n\.)?\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)?",
            r"\b([A-Z]{1,8}\d{2,}[A-Z0-9_./\-]*)\b\s*(?:x|qta|qtà|quantit[aà]|pezzi|pz|n\.)?\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)?",
            r"\bcodice\s+([A-Z0-9_./\-]{3,40}).{0,25}?\b(?:qta|qtà|quantit[aà]|pezzi|pz)\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)",
        ]
        stop = {"FINCANTIERI", "DE", "WAVE", "RICHIESTA", "BUONO", "EMAIL", "SUPPLIER", "DESCRIPTION", "GOODS", "MARCA", "PEZZO", "PROTOCOLLO", "PACKAGE", "PCS", "GRAZIE"}
        for pat in patterns:
            for m in re.finditer(pat, txt, flags=re.I):
                code = (m.group(1) or "").strip().strip(".,;:").upper()
                if not _looks_like_marca_pezzo(code):
                    continue
                qty = _parse_qty(m.group(2) or 1)
                n = _norm(code)
                if len(n) < 4 or code.upper() in stop:
                    continue
                key = (n, "", "")
                # evita duplicato se già presente da tabella con stesso codice
                if any(_norm(x.get("codice")) == n for x in found):
                    continue
                if key not in seen:
                    seen.add(key)
                    found.append({"codice": code, "quantita": qty, "origine": "testo_libero"})
        return found

    def _split_multi_value(value):
        """Divide celle multi-codice senza rompere codici con slash tipo SE/007VD."""
        s = str(value or "").strip()
        if not s:
            return []
        parts = re.split(r"\s*(?:\n|\r|;|\||,|\s/\s|\s\+\s)\s*", s)
        return [p.strip() for p in parts if p and p.strip()]

    def _split_qty_value(value, count):
        parts = _split_multi_value(value)
        qtys = []
        for p in parts:
            try:
                qtys.append(int(float(str(p).replace(",", "."))))
            except Exception:
                qtys.append(1)
        if not qtys and count:
            qtys = [1] * count
        while len(qtys) < count:
            qtys.append(1)
        return qtys[:count]

    def _row_match_details(row, requested_code, requested_qty, matched_by="codice"):
        full_code = getattr(row, "codice_articolo", "") or ""
        code_parts = _split_multi_value(full_code) or [full_code]
        qty_parts = _split_qty_value(getattr(row, "pezzo", ""), len(code_parts))
        req_norm = _norm(requested_code)
        for idx, code in enumerate(code_parts):
            code_norm = _norm(code)
            if req_norm and (req_norm == code_norm or req_norm in code_norm or code_norm in req_norm):
                disp = qty_parts[idx] if idx < len(qty_parts) else 1
                return {
                    "found": True,
                    "matched_by": matched_by,
                    "indice": idx,
                    "codice_riga": code,
                    "richiesti": requested_qty,
                    "disponibili": disp,
                    "scarico_parziale": requested_qty < disp,
                    "scarico_totale_codice": requested_qty >= disp,
                    "multi_codice": len(code_parts) > 1,
                    "codici_residui": [c for i, c in enumerate(code_parts) if i != idx] + ([code] if requested_qty < disp else []),
                }
        return {"found": False}

    def _has_photo(row):
        try:
            for a in getattr(row, "attachments", []) or []:
                if (getattr(a, "kind", "") or "").lower() == "photo":
                    return True
        except Exception:
            pass
        return False

    def _query_candidates(db, item, cliente=""):
        code = (item.get("codice") or "").strip()
        protocollo = (item.get("protocollo") or "").strip()
        ordine = (item.get("ordine") or item.get("order") or "").strip()
        descrizione = (item.get("descrizione") or "").strip()
        fornitore = (item.get("fornitore") or "").strip()

        q = db.query(Articolo).filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == ""))
        if cliente:
            q = q.filter(func.upper(Articolo.cliente) == cliente.upper())

        conditions = []
        if code:
            conditions.append(Articolo.codice_articolo.ilike(f"%{code}%"))
            n = _norm(code)
            if n:
                conditions.append(_sql_norm_col(Articolo.codice_articolo).ilike(f"%{n}%"))
        if protocollo:
            conditions.append(Articolo.protocollo.ilike(f"%{protocollo}%"))
            n = _norm(protocollo)
            if n:
                conditions.append(_sql_norm_col(Articolo.protocollo).ilike(f"%{n}%"))
        if ordine:
            conditions.append(Articolo.ordine.ilike(f"%{ordine}%"))
            n = _norm(ordine)
            if n:
                conditions.append(_sql_norm_col(Articolo.ordine).ilike(f"%{n}%"))
        if descrizione:
            conditions.append(Articolo.descrizione.ilike(f"%{descrizione}%"))
        if fornitore:
            conditions.append(Articolo.fornitore.ilike(f"%{fornitore}%"))

        if conditions:
            q = q.filter(or_(*conditions))
        return q.order_by(Articolo.id_articolo.desc()).limit(50).all()

    def _score_row(row, item):
        score = 0
        code = _norm(item.get("codice"))
        proto = _norm(item.get("protocollo"))
        ordine = _norm(item.get("ordine") or item.get("order"))
        descr = _norm(item.get("descrizione"))
        forn = _norm(item.get("fornitore"))

        row_code = _norm(getattr(row, "codice_articolo", ""))
        row_proto = _norm(getattr(row, "protocollo", ""))
        row_order = _norm(getattr(row, "ordine", ""))
        row_desc = _norm(getattr(row, "descrizione", ""))
        row_forn = _norm(getattr(row, "fornitore", ""))

        if code and (code == row_code or code in row_code or row_code in code):
            score += 100
        if proto and (proto == row_proto or proto in row_proto or row_proto in proto):
            score += 80
        if ordine and (ordine == row_order or ordine in row_order or row_order in ordine):
            score += 35
        if forn and (forn in row_forn or row_forn in forn):
            score += 15
        if descr and (descr in row_desc or row_desc in descr):
            score += 10
        return score

    def _search_giacenze(db, requested_items, cliente=""):
        results = []
        for item in requested_items:
            code = item["codice"]
            qty = int(item.get("quantita") or 1)
            candidates = _query_candidates(db, item, cliente=cliente)
            scored = sorted(((r, _score_row(r, item)) for r in candidates), key=lambda x: x[1], reverse=True)
            matches = []
            for r, score in scored:
                if score <= 0:
                    continue
                det = _row_match_details(r, code, qty, matched_by="codice")
                if not det.get("found"):
                    # Se ha trovato per protocollo/ordine ma il codice in riga non combacia perfettamente,
                    # mostro comunque la riga come possibile corrispondenza.
                    det = {
                        "found": True,
                        "matched_by": "protocollo/ordine" if score >= 80 else "possibile",
                        "indice": 0,
                        "codice_riga": getattr(r, "codice_articolo", "") or "",
                        "richiesti": qty,
                        "disponibili": int(getattr(r, "pezzo", None) or getattr(r, "n_colli", None) or 1),
                        "scarico_parziale": False,
                        "scarico_totale_codice": True,
                        "multi_codice": len(_split_multi_value(getattr(r, "codice_articolo", ""))) > 1,
                        "codici_residui": [],
                    }
                cli = (getattr(r, "cliente", "") or "").strip().upper()
                protocollo = (getattr(r, "protocollo", "") or "").strip()
                warnings = []
                if cli in CLIENTI_PROTOCOLLO and not protocollo:
                    warnings.append("Protocollo obbligatorio mancante")
                if cli == "RF-DE WAVE" and not _has_photo(r):
                    warnings.append("Foto obbligatoria RF-DE WAVE mancante")
                if qty > int(det.get("disponibili") or 0):
                    warnings.append(f"Quantità richiesta superiore al disponibile ({det.get('disponibili')})")
                matches.append({"row": r, "details": det, "warnings": warnings, "score": score})
                if len(matches) >= 10:
                    break
            results.append({"richiesta": item, "matches": matches})
        return results

    def _render_preview(text, cliente, protocollo, requested_items, results):
        return render_template(
            "camy_email_buono.html",
            analyzed=True,
            testo=text,
            cliente=cliente,
            protocollo=protocollo,
            richieste=requested_items,
            risultati=results,
        )

    @app.route("/camy-email-buono", methods=["GET", "POST"])
    @login_required
    @require_admin
    def camy_email_buono():
        if request.method == "GET":
            return render_template("camy_email_buono.html", analyzed=False)

        testo = (request.form.get("testo_email") or "").strip()
        for f in request.files.getlist("allegati"):
            extracted = _extract_text_from_file(f)
            if extracted:
                testo += "\n" + extracted

        if not testo.strip():
            flash("Inserisci il testo della richiesta oppure carica PDF/foto leggibile.", "warning")
            return render_template("camy_email_buono.html", analyzed=False)

        cliente = (request.form.get("cliente") or "").strip() or _extract_cliente(testo)
        protocollo = _extract_protocollo(testo)
        richieste = _extract_requested_items(testo)

        db = SessionLocal()
        try:
            risultati = _search_giacenze(db, richieste, cliente=cliente)
            return _render_preview(testo, cliente, protocollo, richieste, risultati)
        except Exception as e:
            try:
                scrivi_log_errore("CAMY crea buono da email", e)
            except Exception:
                pass
            flash(f"Errore analisi richiesta: {e}", "danger")
            return render_template("camy_email_buono.html", analyzed=False, testo=testo)
        finally:
            db.close()
