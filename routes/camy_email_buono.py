# -*- coding: utf-8 -*-
"""
CAMY - Crea Buono da Email / PDF / Foto.
Fase 1 sicura: legge testo e allegati, cerca in giacenza e prepara una anteprima.
NON modifica il database e NON crea buoni senza conferma.
"""

def register_camy_email_buono_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import os
    import re
    import tempfile
    from pathlib import Path
    from html import escape
    from flask import request, render_template, flash, redirect, url_for
    from flask_login import login_required
    from sqlalchemy import or_, func
    from werkzeug.utils import secure_filename

    def _esc(v):
        return escape(str(v or ""))

    def _norm(v):
        return re.sub(r"[^A-Z0-9]+", "", str(v or "").upper())

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
                    out.append(p.extract_text() or "")
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
        tnorm = _norm(text)
        try:
            clienti = get_clienti_utenti()
        except Exception:
            clienti = []
        for cli in sorted(clienti, key=lambda x: len(_norm(x)), reverse=True):
            if _norm(cli) and _norm(cli) in tnorm:
                return cli
        # fallback comuni
        for cli in ["FINCANTIERI", "FINCANTIERI ARMATORE", "RF-DE WAVE", "DE WAVE"]:
            if _norm(cli) in tnorm:
                return cli
        return ""

    def _extract_protocollo(text):
        pats = [
            r"\bprotocollo\s*[:#\-]?\s*([A-Z0-9./_\-]{2,40})",
            r"\bprot\.?\s*[:#\-]?\s*([A-Z0-9./_\-]{2,40})",
        ]
        for pat in pats:
            m = re.search(pat, text or "", re.I)
            if m:
                return (m.group(1) or "").strip().strip(".,;:")
        return ""

    def _extract_requested_items(text):
        """Estrae marca-pezzo + quantità da testo email/OCR.
        Esempi: CB050CF 2 pezzi, CB050CF x2, codice CB050CF quantità 2.
        """
        txt = text or ""
        found = []
        seen = set()
        # Pattern con quantità esplicita vicino al codice
        patterns = [
            r"\b([A-Z]{1,6}\d{2,}[A-Z0-9_./\-]*)\b\s*(?:x|qta|qtà|quantit[aà]|pezzi|pz|n\.)?\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)?",
            r"\bcodice\s+([A-Z0-9_./\-]{3,40}).{0,25}?\b(?:qta|qtà|quantit[aà]|pezzi|pz)\s*[:=\-]?\s*(\d+(?:[,.]\d+)?)",
        ]
        stop = {"FINCANTIERI", "DE", "WAVE", "RICHIESTA", "BUONO", "EMAIL"}
        for pat in patterns:
            for m in re.finditer(pat, txt, flags=re.I):
                code = (m.group(1) or "").strip().strip(".,;:")
                qty = _parse_qty(m.group(2) or 1)
                n = _norm(code)
                if len(n) < 4 or code.upper() in stop:
                    continue
                if n not in seen:
                    seen.add(n)
                    found.append({"codice": code.upper(), "quantita": qty})
        return found

    def _split_multi_value(value):
        s = str(value or "").strip()
        if not s:
            return []
        parts = re.split(r"\s*(?:/|;|\||,|\+|\n|\r)\s*", s)
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

    def _row_match_details(row, requested_code, requested_qty):
        code_parts = _split_multi_value(getattr(row, "codice_articolo", "")) or [getattr(row, "codice_articolo", "") or ""]
        qty_parts = _split_qty_value(getattr(row, "pezzo", ""), len(code_parts))
        req_norm = _norm(requested_code)
        for idx, code in enumerate(code_parts):
            if req_norm and (req_norm == _norm(code) or req_norm in _norm(code) or _norm(code) in req_norm):
                disp = qty_parts[idx] if idx < len(qty_parts) else 1
                return {
                    "found": True,
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

    def _search_giacenze(db, requested_items, cliente=""):
        results = []
        for item in requested_items:
            code = item["codice"]
            qty = int(item.get("quantita") or 1)
            q = db.query(Articolo).filter(or_(Articolo.data_uscita == None, Articolo.data_uscita == ""))
            if cliente:
                q = q.filter(func.upper(Articolo.cliente) == cliente.upper())
            q = q.filter(Articolo.codice_articolo.ilike(f"%{code}%"))
            rows = q.order_by(Articolo.id_articolo.desc()).limit(20).all()
            matches = []
            for r in rows:
                det = _row_match_details(r, code, qty)
                if not det.get("found"):
                    continue
                cli = (getattr(r, "cliente", "") or "").strip().upper()
                protocollo = (getattr(r, "protocollo", "") or "").strip()
                warnings = []
                if cli == "FINCANTIERI" and not protocollo:
                    warnings.append("Protocollo obbligatorio FINCANTIERI mancante")
                if cli == "RF-DE WAVE" and not _has_photo(r):
                    warnings.append("Foto obbligatoria RF-DE WAVE mancante")
                if qty > int(det.get("disponibili") or 0):
                    warnings.append(f"Quantità richiesta superiore al disponibile ({det.get('disponibili')})")
                matches.append({"row": r, "details": det, "warnings": warnings})
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
