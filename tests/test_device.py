import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
from camera import Queue, Cloud, PermanentUploadError, capture, drain, main, run_scheduled
from daylight import Daylight, london_daylight

JPEG = b'\xff\xd8test-jpeg\xff\xd9'
NOW = dt.datetime.now(dt.timezone.utc).isoformat()

class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.q = Queue(self.temp.name)
    def tearDown(self):
        self.q.db.close()
        self.temp.cleanup()
    def test_survives_restart(self):
        identifier = self.q.add(JPEG, NOW)
        self.q.db.close()
        self.q = Queue(self.temp.name)
        self.assertEqual(self.q.first()['id'], identifier)
        self.assertEqual(self.q.first()['jpeg'], JPEG)
    def test_network_failure_preserves_queue(self):
        self.q.add(JPEG, NOW)
        class Offline:
            def upload(self, item): raise ConnectionError()
        with self.assertRaises(ConnectionError): drain(self.q, Offline())
        self.assertEqual(self.q.count(), 1)
        self.assertEqual(self.q.status()['upload_status'], 'retrying')
        self.assertEqual(self.q.status()['quarantined'], 0)
    def test_acknowledged_upload_removes_only_acknowledged(self):
        self.q.add(JPEG, NOW)
        self.q.add(JPEG, NOW)
        class CloudOK:
            def upload(self, item): pass
        drain(self.q, CloudOK(), limit=1)
        self.assertEqual(self.q.count(), 1)
    def test_full_queue_preserves_old_capture(self):
        self.q.add(JPEG, NOW)
        capture(self.q, {'max_queue_bytes':1}, '/does/not/exist.jpg')
        self.assertEqual(self.q.count(), 1)
    def test_full_disk_cannot_stop_the_capture_loop_when_health_writes_fail(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        full = sqlite3.OperationalError('database or disk is full')
        path = Path(self.temp.name) / 'mock.jpg'
        path.write_bytes(JPEG)
        with patch('camera.shutil.disk_usage', side_effect=[Mock(free=0), Mock(free=2 ** 30)]), \
             patch.object(self.q, 'error', side_effect=full) as write_error, \
             self.assertLogs('backyard', level='WARNING') as logs:
            run_scheduled(self.q, {}, str(path), stop, 300, None)
        write_error.assert_called_once_with('capture', 'queue_limit')
        self.assertIn('skipping new capture', '\n'.join(logs.output))
        self.assertEqual(self.q.count(), 1)
    def test_capture_loop_recovers_when_capture_and_health_write_hit_full_disk(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        full = sqlite3.OperationalError('database or disk is full')
        with patch('camera.capture', side_effect=[full, None]) as take, \
             patch.object(self.q, 'error', side_effect=full), \
             self.assertLogs('backyard', level='WARNING') as logs:
            run_scheduled(self.q, {}, 'mock.jpg', stop, 300, None)
        self.assertEqual(take.call_count, 2)
        self.assertIn('Capture failed (OperationalError)', '\n'.join(logs.output))
    def test_invalid_jpeg_not_queued(self):
        with self.assertRaises(ValueError): self.q.add(b'not a jpeg', NOW)
        self.assertEqual(self.q.count(), 0)
    def test_mock_uses_same_queue_and_marks_metadata(self):
        path = Path(self.temp.name) / 'mock.jpg'
        path.write_bytes(JPEG)
        capture(self.q, {}, str(path))
        self.assertTrue(self.q.first()['mock'])
    def test_upload_conflict_compares_remote_hash(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        calls = []
        def request(path, data=None, method='GET', content_type='application/json', headers=None):
            calls.append((path, method))
            if method == 'POST' and '/storage/' in path: raise HTTPError(path, 409, 'duplicate', {}, io.BytesIO())
            if '/authenticated/' in path: return JPEG
            return None
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            drain(self.q, cloud)
        self.assertEqual(self.q.count(), 0)
        self.assertTrue(any('/rest/v1/captures' in p for p, _ in calls))
    def test_duplicate_hidden_metadata_uses_device_verification(self):
        self.q.add(JPEG, NOW)
        item = self.q.first()
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        def request(path, data=None, method='GET', content_type='application/json', headers=None):
            if '/rpc/' in path:
                self.assertEqual(path, '/rest/v1/rpc/verify_hidden_capture')
                self.assertEqual(data['expected']['id'], item['id'])
                self.assertEqual(data['expected']['sha256'], item['sha256'])
                return verified
            if method == 'GET':
                return []
            if path == '/rest/v1/captures':
                raise HTTPError(path, 409, 'duplicate', {}, io.BytesIO())
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            verified = True
            cloud.upload(item)
            verified = False
            with self.assertRaisesRegex(PermanentUploadError, 'metadata_conflict'):
                cloud.upload(item)
    def test_conflicting_bytes_never_discard_local(self):
        first = self.q.add(JPEG, NOW)
        later = (dt.datetime.fromisoformat(NOW) + dt.timedelta(minutes=5)).isoformat()
        self.q.add(JPEG, later)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        def request(path, data=None, method='GET', content_type='application/json', headers=None):
            if first in path and method == 'POST':
                raise HTTPError(path, 409, 'duplicate', {}, io.BytesIO())
            if first in path: return b'different'
            return None
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            drain(self.q, cloud)
        self.assertEqual(self.q.db.execute('select id,jpeg from captures').fetchall(), [(first, JPEG)])
        self.assertEqual(self.q.count(), 0)
        self.assertEqual(self.q.db.execute('select id,code from quarantine').fetchall(), [(first, 'object_hash_conflict')])
        self.assertIsNotNone(self.q.status()['last_upload_at'])
        self.assertEqual(self.q.status()['upload_status'], 'quarantined')
        self.assertEqual(self.q.status()['bytes'], len(JPEG))
    def test_metadata_failure_keeps_capture(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        def request(path, *args, **kwargs):
            if '/rest/' in path: raise ConnectionError()
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            with self.assertRaises(ConnectionError): drain(self.q, cloud)
        self.assertEqual(self.q.count(), 1)

    def test_health_survives_restart_and_keeps_errors_sanitized(self):
        self.assertEqual(self.q.status()['upload_status'], 'idle')
        self.q.add(JPEG, NOW)
        self.assertEqual(self.q.status()['upload_status'], 'pending')
        class Failed:
            def upload(self, item): raise TimeoutError('private backend response')
        with self.assertRaises(TimeoutError):
            drain(self.q, Failed())
        self.q.db.close()
        self.q = Queue(self.temp.name)
        failed = self.q.status()
        self.assertEqual(failed['last_capture_at'], NOW)
        self.assertIsNone(failed['last_upload_at'])
        self.assertEqual(failed['last_error']['operation'], 'upload')
        self.assertEqual(failed['last_error']['code'], 'TimeoutError')
        self.assertNotIn('private backend response', str(failed))
        self.assertEqual(failed['upload_status'], 'retrying')
        class Restored:
            def upload(self, item): pass
        drain(self.q, Restored())
        with patch.object(sys, 'argv', ['camera.py', '--config', '/dev/stdin', '--status']), \
             patch('camera.Path.read_text', return_value=json.dumps({'queue_dir': self.temp.name})), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            main()
        status = json.loads(output.getvalue())
        self.assertEqual(status['last_capture_at'], NOW)
        self.assertGreater(dt.datetime.fromisoformat(status['last_upload_at']), dt.datetime.fromisoformat(NOW))
        self.assertEqual(status['last_error'], failed['last_error'])
        self.assertEqual(status['upload_status'], 'ok')

    def test_auth_and_unknown_http_errors_never_quarantine(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                error = HTTPError('/', status, 'private', {}, io.BytesIO(b'{"error":"not duplicate"}'))
                with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=error) as request:
                    with self.assertRaises(HTTPError):
                        drain(self.q, cloud)
                    request.assert_called_once()
                self.assertEqual(self.q.count(), 1)
                self.assertEqual(self.q.status()['quarantined'], 0)
                self.assertEqual(self.q.status()['last_error']['code'], f'http_{status}')

    def test_only_known_item_constraint_is_quarantined(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        for constraint in ('captures_captured_at_check', 'capture_event_shape'):
            body = json.dumps({'code': '23514', 'message': f'constraint "{constraint}"'}).encode()
            def request(path, *args, **kwargs):
                if '/rest/' in path:
                    raise HTTPError(path, 400, 'private', {}, io.BytesIO(body))
            with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
                if constraint == 'captures_captured_at_check':
                    with self.assertRaises(HTTPError):
                        drain(self.q, cloud)
                    self.assertEqual(self.q.count(), 1)
                else:
                    drain(self.q, cloud)
        self.assertEqual(self.q.status()['quarantined'], 1)
        self.assertEqual(self.q.status()['last_error']['code'], 'invalid_capture_metadata')

    def test_corrupt_queued_image_is_isolated_without_contacting_cloud(self):
        item = self.q.add(JPEG, NOW)
        with self.q.db:
            self.q.db.execute('update captures set jpeg=? where id=?', (b'corrupt', item))
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        with patch.object(cloud, 'login') as login:
            drain(self.q, cloud)
        login.assert_not_called()
        self.assertEqual(self.q.status()['quarantined'], 1)
        self.assertEqual(self.q.status()['last_error']['code'], 'invalid_queued_jpeg')

    def test_irrecoverably_old_timestamp_is_quarantined(self):
        self.q.add(JPEG, '1970-01-01T00:00:00+00:00')
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        with patch.object(cloud, 'login') as login:
            drain(self.q, cloud)
        login.assert_not_called()
        self.assertEqual(self.q.status()['quarantined'], 1)
        self.assertEqual(self.q.status()['last_error']['code'], 'invalid_capture_timestamp')

    def test_scheduled_gate_and_capture_failure(self):
        dark = dt.datetime(2026, 6, 21, 2, tzinfo=dt.timezone.utc)
        light = dark.replace(hour=12)
        class StopAfterTwo:
            ticks = 0
            def is_set(self): return self.ticks == 2
            def wait(self, delay): self.ticks += 1
        with patch('camera.utc_now', side_effect=[dark, light, light]), \
             patch('camera.capture', side_effect=OSError('private camera path')) as take:
            run_scheduled(self.q, {}, None, StopAfterTwo(), 300, Daylight({}))
        take.assert_called_once_with(self.q, {}, None)
        self.assertEqual(self.q.status()['last_error']['code'], 'OSError')
        with patch('camera.capture') as take:
            run_scheduled(self.q, {}, 'test.jpg', StopAfterTwo(), 300, None)
        self.assertEqual(take.call_count, 2)

    def test_once_does_not_construct_daylight_gate(self):
        config = json.dumps({'queue_dir': self.temp.name})
        with patch.object(sys, 'argv', ['camera.py', '--config', '/dev/stdin', '--once', '--offline']), \
             patch('camera.Path.read_text', return_value=config), patch('camera.Daylight') as daylight, \
             patch('camera.capture') as take:
            main()
        daylight.assert_not_called()
        take.assert_called_once()

    def test_upload_only_does_not_construct_daylight_gate(self):
        self.q.add(JPEG, NOW)
        config = json.dumps({'queue_dir': self.temp.name})
        with patch.object(sys, 'argv', ['camera.py', '--config', '/dev/stdin', '--upload-only']), \
             patch('camera.Path.read_text', return_value=config), patch('camera.Daylight') as daylight, \
             patch('camera.Cloud') as cloud:
            main()
        daylight.assert_not_called()
        self.assertEqual(cloud.return_value.upload.call_count, 1)
        self.assertEqual(self.q.status()['upload_status'], 'ok')

    def test_upload_only_fails_when_it_quarantines_a_capture(self):
        capture_id = self.q.add(JPEG, NOW)
        config = json.dumps({'queue_dir': self.temp.name})
        with patch.object(sys, 'argv', ['camera.py', '--config', '/dev/stdin', '--upload-only']), \
             patch('camera.Path.read_text', return_value=config), patch('camera.Cloud') as cloud:
            cloud.return_value.upload.side_effect = PermanentUploadError('object_hash_conflict')
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        status = self.q.status()
        self.assertIsNone(status['last_upload_at'])
        self.assertEqual(status['upload_status'], 'quarantined')
        self.assertEqual(self.q.db.execute('select id,jpeg from captures').fetchall(), [(capture_id, JPEG)])


class DaylightTests(unittest.TestCase):
    def test_london_solstices_and_offset(self):
        for month, rise, set_ in ((6, (3, 43), (20, 21)), (12, (8, 4), (15, 54))):
            with self.subTest(month=month):
                date = dt.date(2026, month, 21)
                actual = london_daylight(date)
                for time, (hour, minute) in zip(actual, (rise, set_)):
                    expected = dt.datetime.combine(date, dt.time(hour, minute), tzinfo=dt.timezone.utc)
                    self.assertLess(abs(time - expected), dt.timedelta(minutes=4))
        summer_rise, summer_set = london_daylight(dt.date(2026, 6, 21))
        default = Daylight({})
        self.assertTrue(default.allows(summer_rise.astimezone(dt.timezone(dt.timedelta(hours=1)))))
        self.assertFalse(default.allows(summer_set))
        inset = Daylight({'daylight_margin_minutes': 15})
        self.assertFalse(inset.allows(summer_rise))
        self.assertTrue(inset.allows(summer_rise + dt.timedelta(minutes=15)))
        self.assertFalse(inset.allows(summer_set - dt.timedelta(minutes=15)))
        expanded = Daylight({'daylight_margin_minutes': -15})
        self.assertTrue(expanded.allows(summer_rise - dt.timedelta(minutes=10)))
        with self.assertRaises(ValueError):
            Daylight({'daylight_margin_minutes': 'nan'})

if __name__ == '__main__': unittest.main()
