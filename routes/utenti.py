# -*- coding: utf-8 -*-
"""
Modulo Gestione Utenti.
Permette agli admin di aggiungere utenti/clienti, cambiare password e gestire ruoli.
"""

def register_utenti_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    USERS_FILE = MEDIA_DIR / "utenti_gestionale.json"
    ROLE_LABELS = {"client": "Cliente", "magazzino": "Magazzino", "admin": "Admin"}

    def _load_users_file():
        try:
            if USERS_FILE.exists():
                data = json.loads(USERS_FILE.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[WARN] impossibile leggere utenti_gestionale.json: {e}")
        return {}

    def _save_users_file(data):
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _role_from_username(username):
        u = (username or "").strip().upper()
        if u in ADMIN_USERS:
            return "admin"
        if u in WAREHOUSE_USERS:
            return "magazzino"
        return "client"

    def _merged_users():
        out = {}
        try:
            for username, password in (get_users() or {}).items():
                u = (username or "").strip().upper()
                if not u:
                    continue
                out[u] = {
                    "username": u,
                    "password": password,
                    "role": _role_from_username(u),
                    "active": True,
                    "source": "base",
                }
        except Exception:
            pass

        for username, rec in _load_users_file().items():
            u = (username or "").strip().upper()
            if not u:
                continue
            if isinstance(rec, dict):
                out[u] = {
                    "username": u,
                    "password": rec.get("password", ""),
                    "role": rec.get("role") or _role_from_username(u),
                    "active": bool(rec.get("active", True)),
                    "source": "gestione",
                }
            else:
                out[u] = {
                    "username": u,
                    "password": str(rec or ""),
                    "role": _role_from_username(u),
                    "active": True,
                    "source": "gestione",
                }
        return out

    def _persist_user(username, password_hash=None, role="client", active=True):
        username = (username or "").strip().upper()
        if not username:
            raise ValueError("Nome utente non valido.")
        data = _load_users_file()
        old = data.get(username, {})
        if not isinstance(old, dict):
            old = {"password": str(old or ""), "role": _role_from_username(username), "active": True}
        data[username] = {
            "password": password_hash if password_hash is not None else old.get("password", ""),
            "role": role or old.get("role", "client"),
            "active": bool(active),
        }
        _save_users_file(data)

    @app.route("/admin/utenti", methods=["GET", "POST"])
    @login_required
    @require_admin
    def admin_utenti():
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            try:
                if action == "add_user":
                    username = (request.form.get("username") or "").strip().upper()
                    password = (request.form.get("password") or "").strip()
                    role = (request.form.get("role") or "client").strip()
                    if role not in ("client", "magazzino", "admin"):
                        role = "client"
                    if not username:
                        flash("Inserisci il nome utente/cliente.", "warning")
                        return redirect(url_for("admin_utenti"))
                    if not password:
                        flash("Inserisci una password.", "warning")
                        return redirect(url_for("admin_utenti"))
                    _persist_user(username, password_hash=generate_password_hash(password), role=role, active=True)
                    flash(f"Utente {username} creato/aggiornato correttamente.", "success")
                    return redirect(url_for("admin_utenti"))

                if action == "change_password":
                    username = (request.form.get("username") or "").strip().upper()
                    password = (request.form.get("password") or "").strip()
                    if not username or not password:
                        flash("Utente o password mancante.", "warning")
                        return redirect(url_for("admin_utenti"))
                    rec = _merged_users().get(username, {})
                    _persist_user(username, password_hash=generate_password_hash(password), role=rec.get("role") or _role_from_username(username), active=rec.get("active", True))
                    flash(f"Password aggiornata per {username}.", "success")
                    return redirect(url_for("admin_utenti"))

                if action == "update_role":
                    username = (request.form.get("username") or "").strip().upper()
                    role = (request.form.get("role") or "client").strip()
                    active = request.form.get("active") == "1"
                    if role not in ("client", "magazzino", "admin"):
                        role = "client"
                    rec = _merged_users().get(username)
                    if not rec:
                        flash("Utente non trovato.", "warning")
                        return redirect(url_for("admin_utenti"))
                    _persist_user(username, password_hash=rec.get("password", ""), role=role, active=active)
                    flash(f"Utente {username} aggiornato.", "success")
                    return redirect(url_for("admin_utenti"))

            except Exception as e:
                scrivi_log_errore("Errore gestione utenti", e)
                flash(f"Errore gestione utenti: {e}", "danger")
                return redirect(url_for("admin_utenti"))

        users = sorted(_merged_users().values(), key=lambda r: (r.get("role", ""), r.get("username", "")))
        return render_template("utenti.html", users=users, role_labels=ROLE_LABELS)
