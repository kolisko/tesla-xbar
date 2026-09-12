"""Auth responsibilities for Tesla xBar."""
import base64
import html
import http.server
import json
import secrets
import subprocess
import time
import urllib.parse
import webbrowser
from . import runtime
from .runtime import locked, read_json, save_json
from .errors import AppError
from .config import REGIONS, save_configuration, validate_configuration
from . import transport


TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"


AUTH_URL = "https://auth.tesla.com/oauth2/v3/authorize"


SCOPES = "openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds"


class Keychain:
    def request(self, operation, account, value=None):
        payload = {"operation": operation, "account": account}
        if value is not None:
            payload["value"] = value
        result = subprocess.run([str(runtime.HERE / "tesla-keychain")], input=json.dumps(payload),
                                capture_output=True, text=True, timeout=90)
        if result.returncode == 3:
            return None
        if result.returncode:
            raise AppError("Keychain is unavailable. Unlock it and try again.")
        return result.stdout

    def get(self, account):
        return self.request("get", account)

    def set(self, account, value):
        self.request("set", account, value)


class Authenticator:
    def __init__(self, config, vault=None):
        self.config = config
        self.vault = vault or Keychain()

    def save_tokens(self, result, previous=None):
        if not result.get("access_token") or not (result.get("refresh_token") or (previous or {}).get("refresh_token")):
            raise AppError("Tesla did not return the required tokens. Allow offline access.")
        stored = {"access_token": result["access_token"],
                  "refresh_token": result.get("refresh_token") or previous["refresh_token"],
                  "expires_at": time.time() + float(result.get("expires_in", 3600))}
        # Save rotated refresh token before making any subsequent request.
        self.vault.set("oauth", json.dumps(stored))
        return stored

    def access_token(self, force=False):
        raw = self.vault.get("oauth")
        if not raw:
            raise AppError("Connect your Tesla account from the plugin menu.")
        tokens = json.loads(raw)
        if not force and tokens.get("expires_at", 0) > time.time() + 120:
            return tokens["access_token"]
        result = transport.request_json(TOKEN_URL, form={"grant_type": "refresh_token",
            "client_id": self.config["client_id"], "refresh_token": tokens["refresh_token"]})
        return self.save_tokens(result, tokens)["access_token"]

    def detect_region(self):
        """Best-effort, once after sign-in. Never accept a host outside Tesla's allowlist."""
        try:
            result = transport.request_json(REGIONS[self.config["region"]] + "/api/1/users/region",
                                            token=self.access_token())
            response = result.get("response")
            base = response.get("fleet_api_base_url") if isinstance(response, dict) else None
            if not isinstance(base, str):
                return False
            region = next((name for name, host in REGIONS.items() if base.rstrip("/") == host), None)
            if region is None:
                return False
            saved = save_configuration(self.config, {"region": region})
            self.config.update(saved)
            return True
        except AppError:
            # Keep the configured fallback; token exchange has already succeeded.
            return False

    def granted_scopes(self):
        # Used only to explain missing consent; Tesla validates authorization.
        try:
            part = self.access_token().split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            scopes = payload.get("scp", payload.get("scope", []))
            return set(scopes.split() if isinstance(scopes, str) else scopes)
        except (ValueError, IndexError, TypeError):
            return set()


def reset_after_authorization():
    # A scope upgrade must not erase the last reading while the car is asleep.
    # The next vehicle-list response still checks the VIN before reusing it.
    cache = read_json("cache.json")
    for key in ("next_poll", "retry_at", "retry_status", "error", "wake_in_progress"):
        cache.pop(key, None)
    cache["state"] = "unknown"
    save_json("cache.json", cache)


def register(config):
    config = validate_configuration(config, require_connection=True)
    domain = config.get("domain", "")
    if not domain or "/" in domain or ":" in domain or "." not in domain:
        raise AppError("Set the public app domain first.")
    client_secret = Keychain().get("client-secret")
    if not client_secret or not config.get("client_id"):
        raise AppError("Save your Client ID and Client Secret in Settings first.")
    token = transport.request_json(TOKEN_URL, form={"grant_type": "client_credentials",
        "client_id": config["client_id"], "client_secret": client_secret,
        "audience": REGIONS[config["region"]], "scope": "vehicle_device_data"})
    if not token.get("access_token"):
        raise AppError("Tesla did not return a partner token.")
    transport.request_json(REGIONS[config["region"]] + "/api/1/partner_accounts",
                 token=token["access_token"], body={"domain": domain})
    config["registered"] = True
    save_configuration(config)
    print("Region registration complete.")


def authorize(config, launch=True):
    config = validate_configuration(config)
    if not config.get("client_id") or not Keychain().get("client-secret"):
        raise AppError("Save your Client ID and Client Secret in Settings first.")
    parsed = urllib.parse.urlsplit(config["redirect_uri"])
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or parsed.path != "/callback" or not parsed.port:
        raise AppError("Set the local Redirect URI to http://localhost:8765/callback.")
    state = secrets.token_urlsafe(32)
    outcome = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth codes never enter request logs.

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            params = urllib.parse.parse_qs(url.query)
            expected_hosts = {f"localhost:{parsed.port}", f"127.0.0.1:{parsed.port}"}
            if url.path != "/callback" or self.headers.get("Host") not in expected_hosts:
                self.send_error(404)
                return
            supplied_state = params.get("state", [""])[0]
            if not secrets.compare_digest(supplied_state, state):
                self.send_error(400, "Invalid OAuth state")
                return
            if "error" in params:
                outcome["error"] = "Tesla account access was denied."
            elif params.get("code"):
                outcome["code"] = params["code"][0]
            else:
                self.send_error(400, "Missing authorization code")
                return
            # Exchange before showing success; the callback server is loopback-only.
            if "code" in outcome:
                try:
                    with locked():
                        tokens = transport.request_json(TOKEN_URL, form={"grant_type": "authorization_code",
                            "client_id": config["client_id"], "client_secret": Keychain().get("client-secret"),
                            "code": outcome.pop("code"), "audience": REGIONS[config["region"]],
                            "redirect_uri": config["redirect_uri"]})
                        auth = Authenticator(config)
                        auth.save_tokens(tokens)
                        auth.detect_region()
                        reset_after_authorization()
                    outcome["success"] = True
                except AppError as exc:
                    outcome["error"] = str(exc)
            title = "Tesla account connected" if outcome.get("success") else "Could not connect"
            message = "Return to xBar. Battery data will be loaded on the next refresh." if outcome.get("success") else outcome["error"]
            page = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>" + title + "</title><body style='font:18px system-ui;max-width:600px;margin:15vh auto;padding:24px'>"
                    "<h1>" + title + "</h1><p>" + html.escape(message) + "</p></body></html>").encode()
            self.send_response(200 if outcome.get("success") else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    try:
        server = http.server.HTTPServer(("127.0.0.1", parsed.port), Callback)
    except OSError:
        raise AppError(f"Port {parsed.port} is already in use or unavailable.") from None
    server.timeout = 1
    url = AUTH_URL + "?" + urllib.parse.urlencode({"client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"], "response_type": "code", "scope": SCOPES + (" vehicle_location" if config.get("location_enabled") is True else ""),
        "state": state, "locale": "en-US", "require_requested_scopes": "true", "prompt_missing_scopes": "true"})
    save_json("authorization.json", {"url": url, "expires_at": time.time() + 600})
    print("Tesla sign-in is ready (expires in 10 minutes).", flush=True)
    if launch:
        webbrowser.open(url)
    deadline = time.monotonic() + 600
    try:
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
        (runtime.APP_DIR / "authorization.json").unlink(missing_ok=True)
    if not outcome.get("success"):
        raise AppError(outcome.get("error", "Sign-in timed out. Connect your account again."))
    print("Tesla account connected. Tokens are stored in Keychain.")
