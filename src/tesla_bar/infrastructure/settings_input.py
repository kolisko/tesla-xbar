"""Interactive terminal and loopback HTTP input adapters.

Settings rules are supplied as callbacks; this adapter never constructs services.
"""
import getpass
import html
import http.server
import secrets
import subprocess
import time
import urllib.parse
import webbrowser
from ..domain.settings import SETTINGS, CONNECTION_FIELDS
from ..domain.errors import AppError

def configure(load, apply):
    print("Tesla xBar • Settings\nFind your Client ID and Client Secret in the Tesla Developer portal.")
    config = load()
    changes = {}
    for name in CONNECTION_FIELDS:
        field = SETTINGS[name]
        choices = " (" + "/".join(dict(field.choices)) + ")" if field.choices else ""
        value = input(f"{field.label}{choices} [{config.get(name, field.default)}]: ").strip()
        changes[name] = value or config.get(name, field.default)
    secret = getpass.getpass("Client Secret (press Enter to keep the saved value): ").strip()
    apply(changes, secret)
    print("Settings saved. Next, register the app and connect your Tesla account.")


def provision(config, apply, sessions, form, launch=True):
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
                + form(config) + "<button type='submit'>Save settings</button></form>")

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
                apply(changes, client_secret)
                result["success"] = True
                self.respond("<h1>Credentials saved</h1><p>You can now complete registration and connect your Tesla account.</p>")
            except AppError as exc:
                self.respond("<h1>Could not save settings</h1><p>" + html.escape(str(exc)) + "</p>", 400)
            except (ValueError, subprocess.SubprocessError):
                self.respond("<h1>Could not save credentials</h1><p>Unlock Keychain and try connecting again.</p>", 400)

    with http.server.HTTPServer(("127.0.0.1", 8766), Setup) as server:
        server.timeout = 1
        url = "http://127.0.0.1:8766/setup/" + nonce
        sessions.save( {"url": url, "expires_at": time.time() + 600})
        print("Local credential setup is ready (expires in 10 minutes).", flush=True)
        if launch:
            webbrowser.open(url)
        deadline = time.monotonic() + 600
        try:
            while not result and time.monotonic() < deadline:
                server.handle_request()
        finally:
            sessions.delete()
    if not result:
        raise AppError("Credential setup timed out.")
    print("Credentials saved to Keychain.")
