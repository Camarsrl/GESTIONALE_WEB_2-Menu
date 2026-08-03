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
    from datetime import datetime, date
    from decimal import Decimal
    import json
    import subprocess
    from sqlalchemy import MetaData, inspect as sa_inspect, select, text
    from sqlalchemy.sql.sqltypes import Date, DateTime, Time, Boolean, Integer, Float, Numeric

    # ========================================================
    #  BACKUP (DB + JSON + Media) - crea ZIP in /media/backups
    # ========================================================
    BACKUP_DIR = MEDIA_DIR / "backups"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def _db_dialect():
        try:
            return str(engine.dialect.name or "").lower()
        except Exception:
            return ""

    def _safe_db_label():
        try:
            url = engine.url
            return f"{url.drivername}://{url.host or 'locale'}/{url.database or ''}"
        except Exception:
            return _db_dialect() or "sconosciuto"

    def _json_value(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            import base64
            return {"__bytes_base64__": base64.b64encode(bytes(value)).decode("ascii")}
        return str(value)

    def _export_database_json(destination: Path):
        inspector = sa_inspect(engine)
        table_names = sorted(
            name for name in inspector.get_table_names()
            if name and not name.startswith("pg_") and name != "alembic_version"
        )
        if not table_names:
            raise RuntimeError("Il database non contiene tabelle esportabili.")

        metadata = MetaData()
        metadata.reflect(bind=engine, only=table_names)
        payload = {
            "format": "CAMAR_DATABASE_EXPORT_V2",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "dialect": _db_dialect(),
            "database": _safe_db_label(),
            "tables": [],
        }
        total_rows = 0
        with engine.connect() as conn:
            for table_name in table_names:
                table = metadata.tables.get(table_name)
                if table is None:
                    continue
                rows = [
                    {key: _json_value(value) for key, value in row.items()}
                    for row in conn.execute(select(table)).mappings()
                ]
                total_rows += len(rows)
                payload["tables"].append({
                    "name": table_name,
                    "columns": [
                        {
                            "name": column.name,
                            "type": column.type.__class__.__name__,
                            "primary_key": bool(column.primary_key),
                            "nullable": bool(column.nullable),
                        }
                        for column in table.columns
                    ],
                    "row_count": len(rows),
                    "rows": rows,
                })

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not destination.exists() or destination.stat().st_size < 100:
            raise RuntimeError("L'esportazione JSON del database risulta vuota.")
        return {"tables": len(payload["tables"]), "rows": total_rows}

    def _try_pg_dump(destination: Path):
        if _db_dialect() != "postgresql":
            return False, "Database non PostgreSQL"
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            return False, "pg_dump non installato; presente comunque database_export.json"
        db_url = str(os.environ.get("DATABASE_URL") or "").strip()
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        if not db_url:
            try:
                db_url = engine.url.render_as_string(hide_password=False)
            except Exception:
                db_url = ""
        if not db_url:
            return False, "DATABASE_URL non disponibile"
        destination.parent.mkdir(parents=True, exist_ok=True)
        cmd = [pg_dump, "--dbname", db_url, "--format=p", "--no-owner", "--no-privileges", "--clean", "--if-exists", "--file", str(destination)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
            if result.returncode != 0:
                destination.unlink(missing_ok=True)
                return False, (result.stderr or result.stdout or "errore pg_dump").strip()[-1000:]
            if not destination.exists() or destination.stat().st_size < 100:
                destination.unlink(missing_ok=True)
                return False, "pg_dump ha prodotto un file vuoto"
            return True, "OK"
        except Exception as exc:
            destination.unlink(missing_ok=True)
            return False, str(exc)

    def create_backup_zip(include_media: bool = False) -> Path:
        """Crea un backup reale. Se il database non viene esportato, non crea lo ZIP."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BACKUP_DIR / f"backup_camar_{ts}.zip"
        added = set()

        def _is_inside(child: Path, parent: Path) -> bool:
            try:
                child.resolve().relative_to(parent.resolve())
                return True
            except Exception:
                return False

        def _safe_add(zf, p: Path, arcname: str, required=False):
            p = Path(p)
            if not p.exists() or not p.is_file():
                if required:
                    raise RuntimeError(f"File obbligatorio assente: {p}")
                return False
            if _is_inside(p, BACKUP_DIR) or p.resolve() == out.resolve():
                return False
            arcname = str(arcname).replace("\\", "/").lstrip("/")
            if arcname in added:
                return False
            added.add(arcname)
            compress_type = zipfile.ZIP_STORED if p.stat().st_size > 3 * 1024 * 1024 else zipfile.ZIP_DEFLATED
            zf.write(p, arcname=arcname, compress_type=compress_type)
            return True

        try:
            with tempfile.TemporaryDirectory(prefix="camar_backup_") as tmp:
                tmp = Path(tmp)
                db_json = tmp / "database_export.json"
                stats = _export_database_json(db_json)
                pg_sql = tmp / "database_postgresql.sql"
                pg_ok, pg_msg = _try_pg_dump(pg_sql)

                with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                    _safe_add(zf, db_json, "database/database_export.json", required=True)
                    if pg_ok:
                        _safe_add(zf, pg_sql, "database/database_postgresql.sql")

                    for db_path in [MEDIA_DIR / "magazzino.db", APP_DIR / "magazzino.db"]:
                        if _safe_add(zf, db_path, "database/magazzino.db"):
                            break

                    for name in ["mappe_excel.json", "destinatari_saved.json", "progressivi_ddt.json", "utenti_gestionale.json"]:
                        for candidate in [MEDIA_DIR / name, APP_DIR / name, APP_DIR / "config" / name]:
                            if _safe_add(zf, candidate, f"config/{name}"):
                                break
                    try:
                        _safe_add(zf, Path(_rubrica_email_path()), "config/rubrica_email.json")
                    except Exception:
                        pass

                    if include_media:
                        for folder, arcroot in [(DOCS_DIR, "media/docs"), (PHOTOS_DIR, "media/photos")]:
                            folder = Path(folder)
                            if not folder.exists():
                                continue
                            for p in folder.rglob("*"):
                                if not p.is_file():
                                    continue
                                low = p.name.lower()
                                if low.endswith((".tmp", ".part", ".bak")) or "__pycache__" in str(p):
                                    continue
                                _safe_add(zf, p, f"{arcroot}/{p.relative_to(folder).as_posix()}")

                    info = (
                        "Backup Gestionale CAMAR\n\n"
                        f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                        "Database PostgreSQL: OK\n"
                        "Configurazioni: OK\n"
                        f"Documenti e fotografie: {'INCLUSI' if include_media else 'NON INCLUSI'}\n\n"
                        "Backup creato correttamente.\n"
                    )
                    zf.writestr("backup_info.txt", info)
            if not out.exists() or out.stat().st_size < 200:
                raise RuntimeError("Il file ZIP del backup non è stato creato correttamente.")
            return out
        except Exception:
            out.unlink(missing_ok=True)
            raise


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

    def _decode_value(value, column):
        if isinstance(value, dict) and "__bytes_base64__" in value:
            import base64
            return base64.b64decode(value["__bytes_base64__"])
        if value is None:
            return None
        try:
            if isinstance(column.type, DateTime):
                return datetime.fromisoformat(str(value))
            if isinstance(column.type, Date):
                return date.fromisoformat(str(value)[:10])
            if isinstance(column.type, Time):
                return datetime.fromisoformat(f"2000-01-01T{value}").time()
            if isinstance(column.type, Boolean):
                return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "si", "sì")
            if isinstance(column.type, Integer):
                return int(value)
            if isinstance(column.type, (Float, Numeric)):
                return float(value)
        except Exception:
            return value
        return value

    def _restore_database_json(export_file: Path):
        payload = json.loads(export_file.read_text(encoding="utf-8"))
        if payload.get("format") != "CAMAR_DATABASE_EXPORT_V2":
            raise RuntimeError("Formato database_export.json non riconosciuto.")
        if str(os.environ.get("ENABLE_DATABASE_RESTORE", "0")).lower() not in ("1", "true", "yes", "si", "sì"):
            raise RuntimeError("Ripristino database disabilitato per sicurezza. Imposta ENABLE_DATABASE_RESTORE=1 su Render solo durante il ripristino.")

        metadata = MetaData()
        metadata.reflect(bind=engine)
        exported = {item.get("name"): item for item in payload.get("tables", [])}
        available = [name for name in exported if name in metadata.tables]
        if not available:
            raise RuntimeError("Nessuna tabella del backup corrisponde al database attuale.")

        with engine.begin() as conn:
            if _db_dialect() == "postgresql":
                quoted = ", ".join(engine.dialect.identifier_preparer.quote(name) for name in available)
                conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
            else:
                for table in reversed(metadata.sorted_tables):
                    if table.name in available:
                        conn.execute(table.delete())
            for table in metadata.sorted_tables:
                item = exported.get(table.name)
                if not item:
                    continue
                rows = []
                for raw_row in item.get("rows", []):
                    converted = {}
                    for key, value in raw_row.items():
                        if key in table.c:
                            converted[key] = _decode_value(value, table.c[key])
                    rows.append(converted)
                if rows:
                    conn.execute(table.insert(), rows)

    def _safe_extract(zf, destination: Path):
        destination = destination.resolve()
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if not str(target).startswith(str(destination)):
                raise RuntimeError("Backup non valido: percorso ZIP non consentito.")
        zf.extractall(destination)

    def restore_from_backup_zip(zip_filename: str, restore_media: bool = False):
        zip_path = (BACKUP_DIR / zip_filename).resolve()
        if not str(zip_path).startswith(str(BACKUP_DIR.resolve())) or not zip_path.exists():
            raise RuntimeError("Backup non trovato o percorso non valido.")

        emergency = create_backup_zip(include_media=restore_media)
        app.logger.warning(f"[RESTORE] backup di emergenza creato: {emergency.name}")

        with tempfile.TemporaryDirectory(prefix="camar_restore_") as tmpdir:
            tmpdir = Path(tmpdir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                _safe_extract(zf, tmpdir)

            db_export = tmpdir / "database" / "database_export.json"
            if not db_export.exists():
                db_export = tmpdir / "database_export.json"
            if not db_export.exists():
                raise RuntimeError("Nel backup manca database/database_export.json.")
            _restore_database_json(db_export)

            config_dir = tmpdir / "config"
            for name in ["mappe_excel.json", "destinatari_saved.json", "progressivi_ddt.json", "utenti_gestionale.json", "rubrica_email.json"]:
                src = config_dir / name
                if src.exists():
                    shutil.copy2(src, MEDIA_DIR / name)

            if restore_media:
                for src, dst in [(tmpdir / "media" / "docs", DOCS_DIR), (tmpdir / "media" / "photos", PHOTOS_DIR)]:
                    if src.exists():
                        Path(dst).mkdir(parents=True, exist_ok=True)
                        shutil.copytree(src, dst, dirs_exist_ok=True)
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
        Ogni backup contiene obbligatoriamente tutte le tabelle PostgreSQL nel file <b>database/database_export.json</b>.<br>Se l'esportazione DB fallisce, il download viene bloccato.<br><br>I backup sono salvati su disco persistente Render:<br><b>/var/data/app/backups</b>
      </div>

      <div class="mb-3 d-flex gap-2 flex-wrap">
        <a class="btn btn-primary" href="{{ url_for('backup_download') }}">
          <i class="bi bi-download"></i> Backup DB + configurazioni
        </a>
        <a class="btn btn-outline-primary" href="{{ url_for('backup_download') }}?media=1">
          <i class="bi bi-file-zip"></i> Backup completo DB + PDF/Foto
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

