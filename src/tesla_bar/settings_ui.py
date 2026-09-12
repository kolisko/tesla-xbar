"""Settings ui responsibilities for Tesla xBar."""
import getpass
import html
import http.server
import secrets
import subprocess
import time
import urllib.parse
import webbrowser
from . import runtime
from .config import SETTINGS, CONNECTION_FIELDS, validate_configuration, save_configuration
from .runtime import locked, read_json, save_json
from .errors import AppError
from .config import configuration
from .auth import Keychain


def apply_settings(config, changes, secret="", vault=None):
    """Validate before writing; every credential/settings UI uses this path."""
    updated = validate_configuration(config | changes, require_connection=True)
    if not isinstance(secret, str) or len(secret) > 2048:
        raise AppError("Invalid Client Secret.")
    vault = vault or Keychain()
    changed_client = bool(config.get("client_id") and config["client_id"] != updated["client_id"])
    if not secret and (changed_client or not vault.get("client-secret")):
        raise AppError("Enter the Client Secret for this application.")
    if secret:
        vault.set("client-secret", secret)
    if changed_client:
        vault.request("delete", "oauth")
        updated.pop("vin", None)
        updated.pop("registered", None)
        save_json("cache.json", {})
    updated = save_configuration(updated)
    cache = read_json("cache.json")
    cache.pop("next_poll", None)
    save_json("cache.json", cache)
    return updated


def configure():
    print("Tesla xBar • Settings\nFind your Client ID and Client Secret in the Tesla Developer portal.")
    config = configuration()
    changes = {}
    for name in CONNECTION_FIELDS:
        field = SETTINGS[name]
        choices = " (" + "/".join(dict(field.choices)) + ")" if field.choices else ""
        value = input(f"{field.label}{choices} [{config.get(name, field.default)}]: ").strip()
        changes[name] = value or config.get(name, field.default)
    secret = getpass.getpass("Client Secret (press Enter to keep the saved value): ").strip()
    with locked():
        apply_settings(configuration(), changes, secret)
    print("Settings saved. Next, register the app and connect your Tesla account.")


def settings_fields_html(config):
    fields = []
    for name in CONNECTION_FIELDS + ("display_mode",):
        field = SETTINGS[name]
        value = str(config.get(name, field.default))
        fields.append(f'<label for="{name}">{field.label}</label>')
        if field.choices:
            options = "".join(f'<option value="{key}"' + (' selected' if key == value else '')
                              + f'>{label}</option>' for key, label in field.choices)
            fields.append(f'<select id="{name}" name="{name}">{options}</select>')
        else:
            fields.append(f'<input id="{name}" name="{name}" required maxlength="{field.max_length}" '
                          + f'value="{html.escape(value, quote=True)}">')
    fields.append('<label for="client_secret">Client Secret (leave blank to keep saved)</label>'
                  '<input id="client_secret" name="client_secret" type="password" maxlength="2048">')
    return "".join(fields)


def provision(config, launch=True):
    """Short-lived loopback form for private browser-to-Keychain provisioning."""
    nonce = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    result = {}

    class Setup(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def valid_request(self):
            return self.path == "/setup/" + nonce and self.headers.get("Host") == "127.0.0.1:8766"

        def respond(self, text, status=200):
            body = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>Tesla xBar • Connection setup</title><style>body{font:18px system-ui;max-width:560px;margin:8vh auto;padding:24px}"
                    "label{display:block;margin:24px 0 8px}input,select{box-sizing:border-box;width:100%;padding:12px;font:inherit}"
                    "button{margin-top:24px;padding:12px 24px;font:inherit}</style><body>" + text + "</body></html>").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_request():
                self.send_error(404)
                return
            self.respond("<h1>Tesla xBar Settings</h1><p>Your Client Secret stays in this Mac's Keychain.</p>"
                "<form method='post' autocomplete='off'>"
                f"<input type='hidden' name='csrf' value='{csrf}'>"
                + settings_fields_html(config) + "<button type='submit'>Save settings</button></form>")

        def do_POST(self):
            # Embedded browsers may send an opaque Origin. Both the unguessable
            # URL and a separate form token are required; other origins fail.
            if not self.valid_request() or self.headers.get("Origin") not in (None, "null", "http://127.0.0.1:8766"):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                    self.send_error(400)
                    return
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if not secrets.compare_digest(fields.get("csrf", [""])[0], csrf):
                    self.send_error(403)
                    return
                changes = {name: fields.get(name, [config.get(name, SETTINGS[name].default)])[0]
                           for name in CONNECTION_FIELDS + ("display_mode",)}
                client_secret = fields.get("client_secret", [""])[0].strip()
                with locked():
                    apply_settings(configuration(), changes, client_secret)
                result["success"] = True
                self.respond("<h1>Credentials saved</h1><p>You can now complete registration and connect your Tesla account.</p>")
            except AppError as exc:
                self.respond("<h1>Could not save settings</h1><p>" + html.escape(str(exc)) + "</p>", 400)
            except (ValueError, subprocess.SubprocessError):
                self.respond("<h1>Could not save credentials</h1><p>Unlock Keychain and try connecting again.</p>", 400)

    with http.server.HTTPServer(("127.0.0.1", 8766), Setup) as server:
        server.timeout = 1
        url = "http://127.0.0.1:8766/setup/" + nonce
        save_json("setup-session.json", {"url": url, "expires_at": time.time() + 600})
        print("Local credential setup is ready (expires in 10 minutes).", flush=True)
        if launch:
            webbrowser.open(url)
        deadline = time.monotonic() + 600
        try:
            while not result and time.monotonic() < deadline:
                server.handle_request()
        finally:
            (runtime.APP_DIR / "setup-session.json").unlink(missing_ok=True)
    if not result:
        raise AppError("Credential setup timed out.")
    print("Credentials saved to Keychain.")
