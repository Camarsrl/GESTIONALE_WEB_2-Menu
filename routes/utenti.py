# -*- coding: utf-8 -*-
"""
Modulo Gestione Utenti.
Usa il file già presente nel gestionale:
password Utenti Gestionale.txt

Permette agli admin di:
- vedere utenti/clienti esistenti;
- aggiungere nuovi clienti/utenti;
- cambiare password;
- gestire ruolo visualizzato.
"""

def register_utenti_routes(app_obj, deps):
    globals().update(deps)
    globals()["app"] = app_obj

    USERS_TXT_FILE = APP_DIR / "password Utenti Gestionale.txt"
    ROLE_LABELS = {"client": "Cliente", "magazzino": "Magazzino", "admin": "Admin"}

    def _role_from_username(username):
        u = (username or "").strip().upper()
        if u in ADMIN_USERS:
            return "admin"
        if u in WAREHOUSE_USERS:
            return "magazzino"
        return "client"

    def _read_all_users():
        """Legge utenti usando la funzione principale get_users()."""
        try:
            data = get_users() or {}
            return {str(k).strip().upper(): str(v).strip() for k, v in data.items() if str(k).strip()}
        except Exception:
            return dict(DEFAULT_USERS)

    def _save_all_users(users):
        """
        Salva gli utenti nel file password Utenti Gestionale.txt
        in formato dizionario Python semplice, compatibile con get_users().
        """
        USERS_TXT_FILE.parent.mkdir(parents=True, exist_ok=True)

        righe = ["{"]

        for username in sorted(users.keys()):
            password = str(users[username] or "").replace("\\", "\\\\").replace("'", "\\'")
            user = str(username or "").replace("\\", "\\\\").replace("'", "\\'")
            righe.append(f"    '{user}': '{password}',")

        righe.append("}")

        USERS_TXT_FILE.write_text("\n".join(righe), encoding="utf-8")

    def _merged_users():
        out = []
        users = _read_all_users()

        for username, password in users.items():
            out.append({
                "username": username,
                "password": password,
                "role": _role_from_username(username),
                "active": True,
                "source": "password txt",
            })

        return out

    @app.route("/admin/utenti", methods=["GET", "POST"])
    @login_required
    @require_admin
    def admin_utenti():
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()

            try:
                users = _read_all_users()

                if action == "add_user":
                    username = (request.form.get("username") or "").strip().upper()
                    password = (request.form.get("password") or "").strip()
                    role = (request.form.get("role") or "client").strip()

                    if not username:
                        flash("Inserisci il nome utente/cliente.", "warning")
                        return redirect(url_for("admin_utenti"))

                    if not password:
                        flash("Inserisci una password.", "warning")
                        return redirect(url_for("admin_utenti"))

                    # Le password restano compatibili con il login attuale.
                    # Non le salvo in json: aggiorno password Utenti Gestionale.txt
                    users[username] = password
                    _save_all_users(users)

                    # Ruolo operativo:
                    # - i clienti nuovi sono client;
                    # - admin/magazzino storici restano gestiti dagli insiemi ADMIN_USERS/WAREHOUSE_USERS.
                    flash(f"Utente {username} creato/aggiornato nel file password Utenti Gestionale.txt.", "success")
                    return redirect(url_for("admin_utenti"))

                if action == "change_password":
                    username = (request.form.get("username") or "").strip().upper()
                    password = (request.form.get("password") or "").strip()

                    if not username or not password:
                        flash("Utente o password mancante.", "warning")
                        return redirect(url_for("admin_utenti"))

                    users[username] = password
                    _save_all_users(users)

                    flash(f"Password aggiornata per {username}.", "success")
                    return redirect(url_for("admin_utenti"))

                if action == "update_role":
                    # Per ora il ruolo reale resta quello già previsto dal gestionale:
                    # ADMIN_USERS / WAREHOUSE_USERS / cliente.
                    flash("Ruolo visualizzato. Per cambiare ruolo reale bisogna aggiornare ADMIN_USERS o WAREHOUSE_USERS nel file principale.", "info")
                    return redirect(url_for("admin_utenti"))

            except Exception as e:
                scrivi_log_errore("Errore gestione utenti", e)
                flash(f"Errore gestione utenti: {e}", "danger")
                return redirect(url_for("admin_utenti"))

        users = sorted(_merged_users(), key=lambda r: (r.get("role", ""), r.get("username", "")))
        return render_template("utenti.html", users=users, role_labels=ROLE_LABELS)
