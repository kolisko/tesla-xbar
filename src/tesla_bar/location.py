"""Location responsibilities for Tesla xBar."""
import hashlib
import json
import math
import os
import struct
import subprocess
import tempfile
import time
import urllib.request
from . import runtime
from .transport import NoRedirect, retry_after_seconds
from .models import number


MAP_IMAGE_LIMIT = 3_000_000


MAP_IMAGE_FILE = "location-map.png"


def coordinates(data):
    if not isinstance(data, dict):
        return None
    lat, lon = data.get("latitude"), data.get("longitude")
    if number(lat) and number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def reverse_geocode(point):
    """Apple's geocoder; no Tesla credentials, VIN, or Mac location access."""
    try:
        result = subprocess.run([str(runtime.HERE / "tesla-location")],
            input=json.dumps({"latitude": point[0], "longitude": point[1]}),
            capture_output=True, text=True, timeout=9, umask=0o077)
        if result.returncode == 0:
            address = json.loads(result.stdout).get("address")
            if isinstance(address, str) and address.strip():
                return address.strip()[:500]
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass
    return None


def update_location(cache, response, now):
    # Fleet API requests location_data, but returns GPS in drive_state.
    data = response.get("drive_state")
    point = coordinates(data)
    if point is None:
        cache["location_error"] = "Tesla has not provided a current location."
        return
    previous = cache.get("location") or {}
    timestamp = data.get("timestamp")
    if not number(timestamp) or timestamp <= 0 or timestamp / 1000 > now + 60:
        cache["location_error"] = "Tesla has not provided a valid location timestamp."
        return
    stamp = min(now, timestamp / 1000)
    if number(previous.get("updated_at")) and stamp < previous["updated_at"]:
        cache["location_error"] = "Tesla returned an older location. Keeping the last known position."
        return
    snapshot = {"latitude": point[0], "longitude": point[1], "updated_at": stamp}
    # An address belongs only to the exact coordinates which were looked up.
    same_point = point == coordinates(previous)
    if same_point and previous.get("address"):
        snapshot["address"] = previous["address"]
    attempted = previous.get("geocoded_at", 0)
    snapshot["geocoded_at"] = attempted
    if not snapshot.get("address") and now - attempted >= 60:
        snapshot["geocoded_at"] = now
        address = reverse_geocode(point)
        if address:
            snapshot["address"] = address
    cache["location"] = snapshot
    cache.pop("location_error", None)


def clear_location_map(cache):
    cache.pop("location_map", None)
    (runtime.APP_DIR / MAP_IMAGE_FILE).unlink(missing_ok=True)


def location_map_request(cache):
    """Private viewport/identity; never include account data in the map request."""
    point = coordinates(cache.get("location"))
    if point is None or not cache.get("vin") or abs(point[0]) > 85.05112878:
        return None
    lat, lon = point
    scale = 256 * 2 ** 17
    px = (lon + 180) / 360 * scale
    py = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    left, top = px - 360, py - 240
    longitude = lambda x: x / scale * 360 - 180
    latitude = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    bbox = [longitude(left), latitude(top + 480), longitude(left + 720), latitude(top)]
    if bbox[0] < -180 or bbox[2] > 180 or top < 0 or top + 480 > scale:
        return None  # Keep the coordinate link at projection/dateline edges.
    # VIN binds the local image to the selected vehicle; it is never sent to MapMap.
    key = hashlib.sha256(json.dumps([cache["vin"], lat, lon, "mapmap-light-no-poi-v1"]).encode()).hexdigest()
    query = urllib.parse.urlencode({"bbox": ",".join(map(str, bbox)), "size": "360x240@2x",
        "pois": "0", "style": "light", "format": "png", "lang": "local"})
    return key, "https://mapmap.ai/api/static-map?" + query


def valid_map_png(data):
    return (isinstance(data, bytes) and 24 <= len(data) <= MAP_IMAGE_LIMIT
            and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR"
            and struct.unpack(">II", data[16:24]) == (720, 480))


def saved_map_png(cache):
    request = location_map_request(cache)
    state = cache.get("location_map") or {}
    if not request or state.get("key") != request[0] or not state.get("sha256"):
        return None
    try:
        with (runtime.APP_DIR / MAP_IMAGE_FILE).open("rb") as stream:
            data = stream.read(MAP_IMAGE_LIMIT + 1)
        if valid_map_png(data) and hashlib.sha256(data).hexdigest() == state["sha256"]:
            return data
    except OSError:
        pass
    return None


def download_location_map(url):
    request = urllib.request.Request(url, headers={"Accept": "image/png",
        "User-Agent": "Tesla-xBar/1.0 (+https://github.com/kolisko/tesla-xbar)"})
    # A separate, credential-free request. Do not forward the private viewport on redirects.
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(MAP_IMAGE_LIMIT + 1)
    if not valid_map_png(raw):
        raise ValueError("Unsupported map image")
    result = subprocess.run([str(runtime.HERE / "tesla-map-image")],
        input=raw, capture_output=True, timeout=5, umask=0o077)
    if result.returncode or not valid_map_png(result.stdout):
        raise ValueError("Map image could not be rendered")
    return result.stdout


def update_location_map(cache, config):
    """One bounded map request only when the saved vehicle position changes."""
    if config.get("location_enabled") is not True or config.get("location_map_enabled") is not True:
        clear_location_map(cache)
        return
    request = location_map_request(cache)
    if request is None:
        clear_location_map(cache)
        return
    if saved_map_png(cache) is not None:
        return
    previous = cache.get("location_map") or {}
    if time.time() < previous.get("retry_at", 0):
        return  # Honor only the provider's Retry-After, across GPS changes too.
    state = {"key": request[0]}
    cache["location_map"] = state
    try:
        data = download_location_map(request[1])
        runtime.APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".map-", dir=runtime.APP_DIR)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, runtime.APP_DIR / MAP_IMAGE_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        state["sha256"] = hashlib.sha256(data).hexdigest()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            state["retry_at"] = time.time() + retry_after_seconds(exc.headers.get("Retry-After", ""))
        state["error"] = "Map preview unavailable. Open the position in Apple Maps."
    except (OSError, ValueError, subprocess.SubprocessError):
        state["error"] = "Map preview unavailable. Open the position in Apple Maps."
