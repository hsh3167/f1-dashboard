import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update', ROOT / 'scripts/update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def test_530_retries_with_delay(self):
        error = urllib.error.HTTPError('https://example.test', 530, 'down', {}, None)
        with patch.object(update.urllib.request, 'urlopen', side_effect=error) as request, patch.object(update.time, 'sleep') as sleep:
            self.assertIsNone(update.getjson('https://example.test'))
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_permanent_http_error_not_retried(self):
        error = urllib.error.HTTPError('https://example.test', 404, 'missing', {}, None)
        with patch.object(update.urllib.request, 'urlopen', side_effect=error) as request, patch.object(update.time, 'sleep') as sleep:
            self.assertIsNone(update.get('https://example.test'))
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_malformed_json_retried(self):
        with patch.object(update.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'<html>down</html>')) as request, patch.object(update.time, 'sleep'):
            self.assertIsNone(update.getjson('https://example.test'))
        self.assertEqual(request.call_count, 3)

    def test_later_page_failure_rejects_partial_results(self):
        page = {'MRData': {'total': '101', 'RaceTable': {'Races': [{'round': '1', 'Results': [{}] * 100}]}}}
        with patch.object(update, 'getjson', side_effect=[page, None]):
            with self.assertRaises(update.DataUnavailable):
                update.fetch_results()

    def test_empty_sprint_season_is_valid(self):
        with patch.object(update, 'getjson', return_value={'MRData': {'total': '0', 'RaceTable': {'Races': []}}}):
            self.assertEqual(update.fetch_sprints(), {})

    def test_empty_middle_page_rejected(self):
        with patch.object(update, 'getjson', return_value={'MRData': {'total': '5', 'RaceTable': {'Races': []}}}):
            with self.assertRaises(update.DataUnavailable):
                update.fetch_results()

    def test_saved_snapshot_and_regression_guard(self):
        saved = json.loads((ROOT / 'data/live.json').read_text(encoding='utf-8'))
        update.validate_snapshot(saved)
        broken = copy.deepcopy(saved)
        broken['sprints'] = {}
        with self.assertRaises(update.DataUnavailable):
            update.validate_snapshot(broken, saved)

    def test_outage_preserves_file_bytes_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / 'live.json'
            original = (ROOT / 'data/live.json').read_bytes()
            live.write_bytes(original)
            with patch.object(update, 'LIVE', str(live)), patch.object(update, 'fetch_season', side_effect=update.DataUnavailable('HTTP 530')):
                self.assertEqual(update.main(), 0)
            self.assertEqual(live.read_bytes(), original)

    def test_outage_without_snapshot_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(update, 'LIVE', str(Path(tmp) / 'missing.json')), patch.object(update, 'fetch_season', side_effect=update.DataUnavailable('HTTP 530')):
                self.assertEqual(update.main(), 1)

    def test_atomic_write_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / 'live.json'
            live.write_text('original', encoding='utf-8')
            with patch.object(update, 'LIVE', str(live)), patch.object(update.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    update.atomic_write({'updated': 'new'})
            self.assertEqual(live.read_text(), 'original')
            self.assertEqual(list(Path(tmp).iterdir()), [live])


if __name__ == '__main__':
    unittest.main()
