import base64
import io
import struct
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import zlib
from pathlib import Path
from unittest.mock import patch, MagicMock

from tests import harness as app
from src.tesla_bar.infrastructure import maps as location, runtime
import urllib.request
from tests.test_sentry_location import FeatureClient


def image(width=720, height=480):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\xff\xff' * width) * height)) + chunk(b'IEND', b''))


class LocationMapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        mock = patch.object(runtime, 'APP_DIR', self.root)
        mock.start(); self.addCleanup(mock.stop)
        self.config = app.DEFAULTS | {'location_enabled': True, 'location_map_enabled': True}
        self.cache = {'vin': 'EXAMPLEVIN', 'state': 'online', 'location': {
            'latitude': 40.758, 'longitude': -73.9855, 'updated_at': time.time(), 'address': 'Example Street'}}
        self.png = image()
        mock = patch.object(location, 'download_location_map', return_value=self.png)
        self.download = mock.start(); self.addCleanup(mock.stop)

    def test_opt_in_missing_or_revoked_location_clears_map_without_requests(self):
        for config, cache in ((self.config | {'location_enabled': False}, self.cache),
                              (self.config | {'location_map_enabled': False}, self.cache),
                              (self.config, {'vin': 'EXAMPLEVIN'})):
            (self.root / app.MAP_IMAGE_FILE).write_bytes(self.png)
            app.update_location_map(cache, config)
            self.assertFalse((self.root / app.MAP_IMAGE_FILE).exists())
        self.download.assert_not_called()

    def test_same_position_and_sleep_reuse_image_with_original_location_time(self):
        app.update_location_map(self.cache, self.config)
        stamp = self.cache['location']['updated_at']
        self.cache['state'] = 'asleep'
        app.update_location_map(self.cache, self.config)
        self.download.assert_called_once()
        self.assertEqual(self.cache['location']['updated_at'], stamp)
        menu = '\n'.join(app.location_menu(self.cache, self.config))
        self.assertIn('image=' + base64.b64encode(self.png).decode(), menu)
        self.assertIn('Last known address', menu)
        self.assertEqual((self.root / app.MAP_IMAGE_FILE).stat().st_mode & 0o777, 0o600)

    def test_moved_vehicle_failure_never_displays_old_map(self):
        app.update_location_map(self.cache, self.config)
        self.cache['location']['longitude'] += 0.01
        self.download.side_effect = TimeoutError('private URL must never be printed')
        app.update_location_map(self.cache, self.config)
        self.assertIsNone(app.saved_map_png(self.cache))
        menu = '\n'.join(app.location_menu(self.cache, self.config))
        self.assertNotIn('image=', menu)
        self.assertIn('Open in Apple Maps', menu)
        self.assertNotIn('private URL', menu)
        self.assertNotIn('private URL', str(self.cache))

    def test_vehicle_switch_and_corrupt_file_cannot_reuse_a_different_image(self):
        app.update_location_map(self.cache, self.config)
        self.cache['vin'] = 'DIFFERENTVIN'
        self.assertIsNone(app.saved_map_png(self.cache))
        app.update_location_map(self.cache, self.config)
        self.assertEqual(self.download.call_count, 2)
        (self.root / app.MAP_IMAGE_FILE).write_bytes(self.png[:-1] + b'x')
        self.assertIsNone(app.saved_map_png(self.cache))
        app.update_location_map(self.cache, self.config)
        self.assertEqual(self.download.call_count, 3)

    def test_retry_after_is_provider_scoped_and_survives_movement(self):
        self.download.side_effect = urllib.error.HTTPError('private-url', 429, '', {'Retry-After': '60'}, None)
        app.update_location_map(self.cache, self.config)
        self.cache['location']['latitude'] += 0.001
        app.update_location_map(self.cache, self.config)
        self.download.assert_called_once()
        self.assertGreater(self.cache['location_map']['retry_at'], time.time())
        self.assertNotIn('private-url', str(self.cache))

    def test_viewport_contains_no_vehicle_identifier_or_provider_marker(self):
        _, url = app.location_map_request(self.cache)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query['pois'], ['0'])
        self.assertEqual(query['size'], ['360x240@2x'])
        self.assertNotIn('markers', query)
        self.assertNotIn('EXAMPLEVIN', url)
        for point in ({'latitude': 90, 'longitude': 0}, {'latitude': 0, 'longitude': 180}):
            self.assertIsNone(app.location_map_request(self.cache | {'location': point}))

    def test_shared_tesla_read_updates_map_without_extra_vehicle_calls_or_wake(self):
        config = self.config | {'client_id': 'example', 'vin': 'EXAMPLEVIN'}
        client = FeatureClient()
        with patch.object(location, 'reverse_geocode', return_value='Example Street'):
            cache = app.fetch_state(config, client)
            self.assertEqual(len(client.calls), 2)
            self.assertIsNotNone(app.saved_map_png(cache))
            client.state = 'offline'
            app.fetch_state(config, client)
        self.download.assert_called_once()
        self.assertEqual(client.wakes, [])
        self.assertEqual(client.commands, [])

    def test_disabling_map_clears_image_and_published_menu_but_keeps_location(self):
        app.update_location_map(self.cache, self.config)
        app.save_json('cache.json', self.cache)
        app.save_json('config.json', self.config)
        with patch('sys.argv', ['plugin', 'map-disable']), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertFalse((self.root / app.MAP_IMAGE_FILE).exists())
        self.assertNotIn('image=', (self.root / 'display.txt').read_text())
        self.assertIn('location', app.read_json('cache.json'))


class MapTransportTests(unittest.TestCase):
    def test_no_credentials_redirects_oversized_images_or_helper_errors(self):
        raw = image()
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = raw
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(urllib.request, 'build_opener', return_value=opener) as build, \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, raw)) as run:
            self.assertEqual(app.download_location_map('https://mapmap.ai/api/static-map?bbox=example'), raw)
            self.assertIs(build.call_args.args[0], app.NoRedirect)
            request = opener.open.call_args.args[0]
            self.assertIsNone(request.get_header('Authorization'))
            self.assertIsNone(request.get_header('Cookie'))
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 20)
            self.assertEqual(response.read.call_args.args, (app.MAP_IMAGE_LIMIT + 1,))
            self.assertEqual(run.call_args.kwargs['input'], raw)
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
            for invalid in (b'<html>error</html>', image(1, 1), raw + b'x' * app.MAP_IMAGE_LIMIT):
                response.read.return_value = invalid
                with self.assertRaises(ValueError):
                    app.download_location_map('https://mapmap.ai/api/static-map')
            response.read.return_value = raw
            run.return_value = subprocess.CompletedProcess([], 1, b'')
            with self.assertRaises(ValueError):
                app.download_location_map('https://mapmap.ai/api/static-map')
