from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from cloud.labeller import MAX_ATTEMPTS, MODEL_VERSION, PROMPTS, label_pending, pick_label, visibility


class LabellerTests(unittest.TestCase):
    def test_person_wins_even_if_something_else_scores_higher(self):
        scores = dict.fromkeys(PROMPTS, 0.02)
        scores.update(person=0.15, fox=0.9)
        self.assertEqual(pick_label(scores), ('person', 0.15))
        self.assertEqual(visibility('person', 'scheduled'), 'needs_review')
        self.assertEqual(visibility('person', 'motion'), 'needs_review')

    def test_best_detection_and_false_trigger_rules(self):
        scores = dict.fromkeys(PROMPTS, 0.02)
        self.assertEqual(pick_label(scores)[0], 'nothing')
        self.assertEqual(visibility('nothing', 'scheduled'), 'visible')
        self.assertEqual(visibility('nothing', 'motion'), 'false_trigger')
        scores.update(fox=0.87)
        self.assertEqual(pick_label(scores), ('fox', 0.87))
        self.assertEqual(visibility('fox', 'motion'), 'visible')

    def test_failed_image_does_not_block_next_capture(self):
        store = Mock()
        bad = dict(id='bad', object_path='bad.jpg', trigger='scheduled', label_attempts=MAX_ATTEMPTS - 1)
        good = dict(id='good', object_path='good.jpg', trigger='motion', label_attempts=0)
        store.pending.return_value = [bad, good]
        store.download.side_effect = [ValueError('invalid JPEG'), b'jpeg']
        detector = Mock(return_value=('nothing', 0.9))
        log = io.StringIO()
        with redirect_stdout(log):
            label_pending(store, Mock(return_value=detector))
        self.assertIn('Capture 1: ValueError', log.getvalue())
        self.assertIn('Capture 2: nothing', log.getvalue())
        for row in (bad, good):
            self.assertNotIn(row['id'], log.getvalue())
        detector.assert_called_once_with(b'jpeg')
        self.assertEqual(store.update.call_args_list[0].args, (bad, {'label_attempts': MAX_ATTEMPTS}))
        self.assertEqual(store.update.call_args_list[1].args, (good, {
            'label': 'nothing', 'label_confidence': 0.9, 'label_model': MODEL_VERSION,
            'label_visibility': 'false_trigger',
        }))

    def test_authentication_failure_does_not_use_up_retries(self):
        store = Mock()
        store.pending.return_value = [dict(object_path='photo.jpg', label_attempts=0)]
        store.download.side_effect = HTTPError('/', 403, 'Forbidden', {}, io.BytesIO())
        with self.assertRaises(HTTPError):
            label_pending(store, Mock())
        store.update.assert_not_called()

    def test_empty_queue_does_not_load_model(self):
        store = Mock()
        store.pending.return_value = []
        factory = Mock()
        with patch('builtins.print'):
            label_pending(store, factory)
        factory.assert_not_called()
