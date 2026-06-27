# -*- coding: utf-8 -*-
"""
Modulo Backup Gestionale Camar.

Contiene:
- creazione ZIP backup
- backup automatico leggero
- pagina admin backup/ripristino
- download backup manuale completo
"""

def register_backup_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    import os
    import time
    import zipfile
    import tempfile
    import shutil
    from pathlib import Path
    from datetime import datetime

    # ========================================================
    #  BACKUP (DB + JSON + Media) - crea ZIP in /media/backups
    # ========================================================
    BACKUP_DIR = MEDIA_DIR / "backups"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def create_backup_zip(include_media: bool = True) -> Path:
        """Crea un backup ZIP e ritorna il path.

        Versione anti-timeout Render:
        - evita file duplicati nello ZIP;
        - non inserisce mai la cartella backups dentro un nuovo backup;
        - mantiene il percorso relativo dei media, evitando nomi duplicati;
        - per default il backup manuale /backup è LEGGERO, cioè DB/config senza foto/PDF.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BACKUP_DIR / f"backup_camar_{ts}.zip"
        added = set()

        def _is_inside(child: Path, parent: Path) -> bool:
            try:
                child.resolve().relative_to(parent.resolve())
                return True
            except Exception:
                return False

        def _unique_arcname(arcname: str) -> str:
            arcname = str(arcname or "").replace("\\", "/").lstrip("/")
            base = arcname
            if arcname not in added:
                return arcname
            stem = Path(base).stem
            suffix = Path(base).suffix
            parent = str(Path(base).parent).replace(".", "")
            i = 2
            while True:
                candidate = f"{parent}/{stem}_{i}{suffix}" if parent else f"{stem}_{i}{suffix}"
                candidate = candidate.replace("\\", "/").lstrip("/")
                if candidate not in added:
                    return candidate
                i += 1

        def _safe_add(zf, p: Path, arcname: str, compress_type=None):
            try:
                p = Path(p)
                if not p.exists() or not p.is_file():
                    return False

                # Mai includere backup vecchi o il file ZIP in costruzione.
                if _is_inside(p, BACKUP_DIR) or p.resolve() == out.resolve():
                    return False

                arcname = _unique_arcname(arcname)
                added.add(arcname)

                if compress_type is None:
                    compress_type = zipfile.ZIP_STORED if p.stat().st_size > 3 * 1024 * 1024 else zipfile.ZIP_DEFLATED

                zf.write(p, arcname=arcname, compress_type=compress_type)
                return True
            except Exception as e:
                print(f"[WARN] backup skip {p}: {e}")
                return False

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            # DB locale, se presente. Su Render con Postgres spesso non esiste: in quel caso lo salto.
            for db_path in [MEDIA_DIR / "magazzino.db", APP_DIR / "magazzino.db"]:
                _safe_add(zf, db_path, "magazzino.db")

            # Config / JSON: prima disco persistente, poi repo. Stesso arcname ma senza duplicare.
            for name in ["mappe_excel.json", "destinatari_saved.json", "progressivi_ddt.json", "utenti_gestionale.json"]:
                if not _safe_add(zf, MEDIA_DIR / name, f"config/{name}"):
                    _safe_add(zf, APP_DIR / name, f"config/{name}")
                _safe_add(zf, APP_DIR / "config" / name, f"config/{name}")

            try:
                rubrica = _rubrica_email_path()
                _safe_add(zf, Path(rubrica), "config/rubrica_email.json")
            except Exception:
                pass

            # Metadati utili per capire da dove arriva il backup.
            try:
                info = (
                    f"Backup creato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"MEDIA_DIR: {MEDIA_DIR}\n"
                    f"APP_DIR: {APP_DIR}\n"
                    f"include_media: {include_media}\n"
                    f"file_inclusi: {len(added)}\n"
                )
                zf.writestr("backup_info.txt", info)
            except Exception:
                pass

            # Media opzionali: mantiene sottocartelle e non appiattisce i nomi.
            # Usare /backup?media=1 solo quando serve davvero il backup completo con PDF/foto.
            if include_media:
                for folder, arcroot in [(DOCS_DIR, "media/docs"), (PHOTOS_DIR, "media/photos")]:
                    folder = Path(folder)
                    if not folder.exists():
                        continue
                    for p in folder.rglob("*"):
                        if not p.is_file():
                            continue
                        # salta file temporanei/cache
                        name_low = p.name.lower()
                        if name_low.endswith((".tmp", ".part", ".bak")) or "__pycache__" in str(p):
                            continue
                        try:
                            rel = p.relative_to(folder).as_posix()
                        except Exception:
                            rel = p.name
                        _safe_add(zf, p, f"{arcroot}/{rel}")

        return out


    _AUTO_BACKUP_LAST_CHECK = {"ts": 0}

    def auto_backup_if_due():
        """Backup automatico leggero ogni 2 ore, senza PDF/foto."""
        try:
            now = time.time()

            # controlla al massimo ogni 10 minuti
            if _AUTO_BACKUP_LAST_CHECK["ts"] and (now - _AUTO_BACKUP_LAST_CHECK["ts"]) < 600:
                return
            _AUTO_BACKUP_LAST_CHECK["ts"] = now

            if str(os.environ.get("AUTO_BACKUP", "1")).lower() in ("0", "false", "no", "off"):
                app.logger.info("[AUTO_BACKUP] disabilitato via AUTO_BACKUP=0")
                return

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backups = sorted(
                BACKUP_DIR.glob("backup_camar_*.zip"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            latest = backups[0] if backups else None
            intervallo = 2 * 3600

            if latest is None or (now - latest.stat().st_mtime) > intervallo:
                app.logger.warning("[AUTO_BACKUP] CREAZIONE backup automatico LEGGERO in corso...")
                zip_path = create_backup_zip(include_media=False)
                app.logger.warning(f"[AUTO_BACKUP] OK creato backup leggero: {zip_path}")

                backups = sorted(
                    BACKUP_DIR.glob("backup_camar_*.zip"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                for old in backups[50:]:
                    try:
                        old.unlink()
                    except Exception:
                        pass
            else:
                ore_passate = (now - latest.stat().st_mtime) / 3600.0
                app.logger.info(f"[AUTO_BACKUP] skip: ultimo backup {latest.name} ({ore_passate:.1f} ore fa)")
        except Exception as e:
            app.logger.warning(f"[AUTO_BACKUP] fallito: {e}")

    @app.before_request
    def _auto_backup_hook():
        try:
            auto_backup_if_due()
        except Exception:
            pass


    def pulisci_backup_vecchi(max_files=50):
        files = sorted(
            Path(BACKUP_DIR).glob("backup_*.zip"),
            key=os.path.getmtime,
            reverse=True
        )
        for f in files[max_files:]:
            f.unlink()


    # Assumo che tu abbia già:
    # BACKUP_DIR = Path("/var/data/app/backups")
    # MEDIA_DIR = Path("/var/data/app")
    # e che magazzino.db stia in MEDIA_DIR

    def _get_db_path():
        # Percorso DB (modifica qui se nel tuo progetto è diverso)
        return (MEDIA_DIR / "magazzino.db")

    def list_backups():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(BACKUP_DIR.glob("backup_camar_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for p in files:
            out.append({
                "name": p.name,
                "path": p,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            })
        return out

    def restore_from_backup_zip(zip_filename: str, restore_media: bool = False):
        """
        Ripristino sicuro:
        - valida che il file stia dentro BACKUP_DIR
        - crea una copia di emergenza del DB attuale
        - estrae lo zip in temp
        - ripristina magazzino.db + JSON
        - opzionale: ripristina cartelle docs/photos
        """
        # ✅ sicurezza: niente path traversal
        zip_path = (BACKUP_DIR / zip_filename).resolve()
        if not str(zip_path).startswith(str(BACKUP_DIR.resolve())):
            raise Exception("Backup non valido (path non consentito).")
        if not zip_path.exists():
            raise Exception("Backup non trovato.")

        db_path = _get_db_path()
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        # ✅ copia emergenza DB attuale
        if db_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            emergency = db_path.with_suffix(f".pre_restore_{ts}.bak")
            shutil.copy2(db_path, emergency)

        # ✅ estrai in temp e ripristina
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(tmpdir)

            # --- ripristina DB ---
            extracted_db = tmpdir / "magazzino.db"
            if extracted_db.exists():
                shutil.copy2(extracted_db, db_path)
            else:
                raise Exception("Nel backup non c'è magazzino.db")

            # --- ripristina JSON (se presenti) ---
            for json_name in ["mappe_excel.json", "destinatari_saved.json", "rubrica_email.json"]:
                src = tmpdir / json_name
                if src.exists():
                    shutil.copy2(src, MEDIA_DIR / json_name)

            # --- ripristina media (opzionale) ---
            if restore_media:
                for folder in ["docs", "photos"]:
                    src_folder = tmpdir / folder
                    dst_folder = MEDIA_DIR / folder
                    if src_folder.exists():
                        if dst_folder.exists():
                            shutil.rmtree(dst_folder)
                        shutil.copytree(src_folder, dst_folder)

        return True

    # ==========================================================
    # TEMPLATE ADMIN BACKUPS (gestito dentro al file Python)
    # ==========================================================

    ADMIN_BACKUPS_HTML = """
    {% extends "base.html" %}
    {% block content %}

    <div class="container-fluid mt-4">
      <h3><i class="bi bi-hdd-stack"></i> Backup & Ripristino</h3>

      <div class="alert alert-info">
        I backup sono salvati su disco persistente Render:<br>
        <b>/var/data/app/backups</b>
      </div>

      <div class="mb-3 d-flex gap-2 flex-wrap">
        <a class="btn btn-primary" href="{{ url_for('backup_download') }}">
          <i class="bi bi-download"></i> Crea backup leggero
        </a>
        <a class="btn btn-outline-primary" href="{{ url_for('backup_download') }}?media=1">
          <i class="bi bi-file-zip"></i> Crea backup completo PDF/Foto
        </a>
      </div>

      {% if backups %}
        <div class="card shadow-sm">
          <div class="table-responsive">
            <table class="table table-striped align-middle mb-0">
              <thead style="background:#f0f0f0;">
                <tr>
                  <th>File Backup</th>
                  <th class="text-center">Data</th>
                  <th class="text-center">Dimensione (MB)</th>
                  <th class="text-end">Azioni</th>
                </tr>
              </thead>

              <tbody>
                {% for b in backups %}
                <tr>
                  <td><code>{{ b.name }}</code></td>
                  <td class="text-center">{{ b.mtime }}</td>
                  <td class="text-center">{{ b.size_mb }}</td>

                  <td class="text-end">

                    <!-- DOWNLOAD -->
                    <a class="btn btn-sm btn-outline-primary"
                       href="{{ url_for('admin_backup_download', filename=b.name) }}">
                      <i class="bi bi-download"></i> Scarica
                    </a>

                    <!-- RIPRISTINA DB + JSON -->
                    <form method="post"
                          style="display:inline-block"
                          onsubmit="return confirm('Confermi ripristino di questo backup?');">
                      <input type="hidden" name="action" value="restore">
                      <input type="hidden" name="filename" value="{{ b.name }}">
                      <input type="hidden" name="restore_media" value="0">

                      <button type="submit" class="btn btn-sm btn-warning">
                        <i class="bi bi-arrow-counterclockwise"></i>
                        Ripristina DB
                      </button>
                    </form>

                    <!-- RIPRISTINO COMPLETO -->
                    <form method="post"
                          style="display:inline-block"
                          onsubmit="return confirm('Ripristino completo (DB+PDF+Foto). Confermi?');">
                      <input type="hidden" name="action" value="restore">
                      <input type="hidden" name="filename" value="{{ b.name }}">
                      <input type="hidden" name="restore_media" value="1">

                      <button type="submit" class="btn btn-sm btn-danger">
                        <i class="bi bi-exclamation-triangle"></i>
                        Ripristina Completo
                      </button>
                    </form>

                  </td>
                </tr>
                {% endfor %}
              </tbody>

            </table>
          </div>
        </div>

      {% else %}
        <div class="alert alert-warning">
          Nessun backup trovato nella cartella backups.
        </div>
      {% endif %}

      <a href="{{ url_for('home') }}" class="btn btn-outline-secondary mt-3">
        <i class="bi bi-arrow-left"></i> Torna alla Home
      </a>
    </div>

    {% endblock %}
    """
    @app.route("/admin/backups", methods=["GET", "POST"])
    @login_required
    @require_admin
    def admin_backups():

        if request.method == "POST":
            action = request.form.get("action")
            filename = request.form.get("filename", "")
            restore_media = (request.form.get("restore_media") == "1")

            try:
                if action == "restore":
                    restore_from_backup_zip(filename, restore_media=restore_media)
                    flash("✅ Ripristino completato!", "success")
                else:
                    flash("Azione non valida.", "warning")

            except Exception as e:
                flash(f"Errore ripristino: {e}", "danger")

            return redirect(url_for("admin_backups"))

        backups = list_backups()
        return render_template_string(ADMIN_BACKUPS_HTML, backups=backups)


    @app.route("/admin/backups/download/<path:filename>")
    @login_required
    @require_admin
    def admin_backup_download(filename):
        # ✅ sicurezza path
        p = (BACKUP_DIR / filename).resolve()
        if not str(p).startswith(str(BACKUP_DIR.resolve())) or not p.exists():
            flash("Backup non trovato.", "danger")
            return redirect(url_for("admin_backups"))

        return send_file(p, as_attachment=True, download_name=p.name)


    @app.route('/backup', methods=['GET'])
    @login_required
    @require_admin
    def backup_download():
        try:
            # Backup manuale anti-timeout: leggero di default.
            # Per includere anche PDF/foto: /backup?media=1
            include_media = str(request.args.get('media', '')).lower() in ('1', 'true', 'si', 'sì', 'yes')
            p = create_backup_zip(include_media=include_media)
            return send_file(p, as_attachment=True, download_name=p.name, mimetype="application/zip")
        except Exception as e:
            try:
                scrivi_log_errore("Errore backup manuale", e)
            except Exception:
                pass
            flash(f"Errore backup: {e}", "danger")
            return redirect(url_for('home'))

