"""Run-scoped HTTPS connections, with no redirects or automatic command retries."""
import atexit
import time
import email.utils
import http.client
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

from .errors import AppError, APIError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward bearer tokens or secrets across redirects.


def retry_after_seconds(value):
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0


class HTTPSession:
    """One connection per HTTPS origin, reused only during this plugin process.

    System/environment proxies retain urllib's existing behavior. Credentials
    are supplied per request, never saved in default session headers. A failed
    connection is discarded; an uncertain request is never sent a second time.
    """
    def __init__(self, connection_factory=None):
        self.connections = {}
        self.connection_factory = connection_factory or http.client.HTTPSConnection
        self.context = ssl.create_default_context()

    def close(self):
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()

    def request(self, url, *, token=None, form=None, body=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise AppError("Only direct HTTPS API addresses are allowed.")
        headers = {"Accept": "application/json", "User-Agent": "Tesla-xBar/1.0"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        origin = (parsed.hostname, parsed.port or 443)
        try:
            # Preserve configured proxy support; direct HTTPS benefits from reuse.
            if urllib.request.getproxies().get("https") and not urllib.request.proxy_bypass(parsed.hostname):
                with urllib.request.build_opener(NoRedirect).open(
                        urllib.request.Request(url, data=data, headers=headers), timeout=18) as response:
                    raw = response.read()
            else:
                connection = self.connections.get(origin)
                if connection is None:
                    connection = self.connection_factory(*origin, timeout=18, context=self.context)
                    self.connections[origin] = connection
                path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                connection.request("POST" if data is not None else "GET", path, body=data, headers=headers)
                response = connection.getresponse()
                raw = response.read()  # Consume the body before reusing the connection.
                if response.status >= 300:
                    raise APIError(response.status, retry_after_seconds(response.getheader("Retry-After", "")))
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise AppError("Tesla returned an unexpected response.")
            return result
        except urllib.error.HTTPError as exc:
            raise APIError(exc.code, retry_after_seconds(exc.headers.get("Retry-After", ""))) from None
        except (OSError, http.client.HTTPException, urllib.error.URLError):
            connection = self.connections.pop(origin, None)
            if connection is not None:
                connection.close()
            raise AppError("Network unavailable. Showing the last known reading.") from None
        except (ValueError, TypeError):
            raise AppError("Tesla returned invalid data.") from None


_session = None


def close_session():
    global _session
    if _session is not None:
        _session.close()
        _session = None


@contextmanager
def session_scope():
    """CLI entrypoint owns connection lifetime, including errors and sign-in."""
    try:
        yield
    finally:
        close_session()


def request_json(url, **kwargs):
    global _session
    if _session is None:
        _session = HTTPSession()
    return _session.request(url, **kwargs)


atexit.register(close_session)
