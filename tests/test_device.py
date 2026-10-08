import datetime as dt
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
from camera import Queue, Cloud, capture, drain

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
    def test_conflicting_bytes_never_discard_local(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        def request(path, data=None, method='GET', content_type='application/json', headers=None):
            if method == 'POST': raise HTTPError(path, 409, 'duplicate', {}, io.BytesIO())
            return b'different'
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            with self.assertRaises(ValueError): drain(self.q, cloud)
        self.assertEqual(self.q.count(), 1)
    def test_metadata_failure_keeps_capture(self):
        self.q.add(JPEG, NOW)
        cloud = Cloud({'supabase_url':'https://example.supabase.co', 'publishable_key':'test'})
        cloud.user_id = 'device'
        def request(path, *args, **kwargs):
            if '/rest/' in path: raise ConnectionError()
        with patch.object(cloud, 'login'), patch.object(cloud, 'request', side_effect=request):
            with self.assertRaises(ConnectionError): drain(self.q, cloud)
        self.assertEqual(self.q.count(), 1)

if __name__ == '__main__': unittest.main()
