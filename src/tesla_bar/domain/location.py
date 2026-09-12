"""Validated geographic coordinates."""
from .models import number

def coordinates(data):
    if not isinstance(data, dict):
        return None
    lat, lon = data.get("latitude"), data.get("longitude")
    if number(lat) and number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None
