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

    # ========================================================
    #  BACKUP (DB + JSON + Media) - crea ZIP in /media/backups
    # ========================================================
    BACKUP_DIR = MEDIA_DIR / "backups"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def create_backup_zip(include_media: bool = True) -> Path:
        """Crea un backup ZIP e ritorna il path."""
        import zipfile
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BACKUP_DIR / f"backup_camar_{ts}.zip"

        def _safe_add(zf, p: Path, arcname: str):
            try:
                if p.exists():
                    zf.write(p, arcname=arcname)
            except Exception as e:
                print(f"[WARN] backup skip {p}: {e}")

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # DB
            _safe_add(zf, APP_DIR / "magazzino.db", "magazzino.db")

            # Config / JSON
            for name in ["mappe_excel.json", "destinatari_saved.json", "progressivi_ddt.json"]:
                _safe_add(zf, APP_DIR / name, f"config/{name}")
                _safe_add(zf, MEDIA_DIR / name, f"config/{name}")  # se sta sul disco

            _safe_add(zf, _rubrica_email_path(), "config/rubrica_email.json")

            # Media (docs + photos)
            if include_media:
                for folder, arcroot in [(DOCS_DIR, "media/docs"), (PHOTOS_DIR, "media/photos")]:
                    if folder.exists():
                        for p in folder.rglob("*"):
                            if p.is_file():
                                _safe_add(zf, p, f"{arcroot}/{p.name}")

        return out


    def pulisci_backup_vecchi(max_files=50):
        files = sorted(
            Path(BACKUP_DIR).glob("backup_*.zip"),
            key=os.path.getmtime,
            reverse=True
        )
        for f in files[max_files:]:
            f.unlink()


    from pathlib import Path
    import zipfile
    import tempfile
    import shutil
    from datetime import datetime

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
            # Backup manuale completo: include anche PDF/foto/media.
            p = create_backup_zip(include_media=True)
            return send_file(p, as_attachment=True, download_name=p.name, mimetype="application/zip")
        except Exception as e:
            flash(f"Errore backup: {e}", "danger")
            return redirect(url_for('home'))

