"""Exports must be portable, read-only and limited to explicitly selected evidence."""
import copy
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mac'))
from desk_store import Store
from desk_share import select_tickets, build_export, slack_text
from desk_server import make_handler


class ShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        (self.root / 'Game').mkdir()
        (self.root / 'Game/clip.mp4').write_bytes(b'synthetic-video')
        (self.root / 'Tickets/GA-001').mkdir()
        (self.root / 'Tickets/GA-001/shot.png').write_bytes(b'selected-image')
        (self.root / 'Tickets/GA-001/drop.png').write_bytes(b'dropped-image')
        (self.root / 'Tickets/settings.json').write_text('{"private":"never export"}')
        t = {'id': 'GA-001', 'game': 'Game', 'title': '<script>alert("x")</script>',
             'status': 'draft', 'kind': 'bug', 'priority': 'high', 'version': '1.2.3',
             'clip': 'Game/clip.mp4', 'moment': {'from': 12, 'to': 18},
             'where': 'Reward screen', 'now': 'No reward', 'want': 'Grant reward',
             'done_when': 'One reward granted', 'steps': ['Tap reward', 'Check balance'],
             'note': 'Edited by reviewer', 'quote': {'text': 'The reward is missing', 't': 13},
             'shots': [{'file': 'Tickets/GA-001/shot.png', 'caption': '<b>button</b>', 't': 13},
                       {'file': 'Tickets/GA-001/drop.png', 'use': False}]}
        self.store.save_ticket(t)

    def export(self, ids=None, recordings=True):
        f, name = build_export(self.store, select_tickets(self.store, ids or ['GA-001']), recordings)
        self.addCleanup(f.close)
        return zipfile.ZipFile(f), name

    def test_portable_report_with_evidence_and_no_state_changes(self):
        before = copy.deepcopy(self.store.tickets)
        snapshot = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        bundle, name = self.export()
        with bundle:
            self.assertTrue(name.startswith('playtest-feedback-Game-'))
            report = bundle.read('report.html').decode()
            self.assertIn('&lt;script&gt;', report)
            self.assertNotIn('<script>', report)
            self.assertIn('Not yet approved', report)
            self.assertIn('#t=12.0', report)
            self.assertNotIn(str(self.root), report)
            self.assertNotIn('127.0.0.1', report)
            self.assertIn('Edited by reviewer', bundle.read('feedback.md').decode())
            self.assertIn('0:12–0:18', bundle.read('feedback.md').decode())
            self.assertIn('(draft)', bundle.read('slack.txt').decode())
            self.assertNotIn('Acceptance:', bundle.read('slack.txt').decode())
            self.assertEqual({bundle.read(n) for n in bundle.namelist() if n.startswith('media/')},
                             {b'synthetic-video', b'selected-image'})
            self.assertFalse(any(n.endswith('.json') for n in bundle.namelist()))
        self.assertEqual(before, self.store.tickets)
        self.assertEqual(snapshot, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_selected_requests_only_shared_video_once_and_optional_recordings(self):
        t = copy.deepcopy(self.store.tickets['GA-001'])
        t.update(id='GA-002', title='Another request', status='fixing', runId='RUN-123', quote=None)
        self.store.save_ticket(t)
        bundle, _ = self.export(['GA-001', 'GA-002', 'GA-001'])
        with bundle:
            self.assertEqual(sum(n.endswith('.mp4') for n in bundle.namelist()), 1)
            self.assertEqual(bundle.read('slack.txt').decode().count('• '), 2)
        bundle, _ = self.export(recordings=False)
        with bundle:
            self.assertFalse(any(n.endswith('.mp4') for n in bundle.namelist()))
            self.assertNotIn('Another request', bundle.read('report.html').decode())
            self.assertTrue(any(n.endswith('.png') for n in bundle.namelist()))

    def test_missing_and_unsafe_evidence_is_reported_without_leaking_files(self):
        with tempfile.TemporaryDirectory() as outside:
            private = Path(outside) / 'private.png'; private.write_bytes(b'private-data')
            (self.root / 'Game/link.png').symlink_to(private)
            t = self.store.tickets['GA-001']
            t['clip'] = '../private.mp4'
            t['shots'] = [{'file': 'Game/link.png'}, {'file': 'Tickets/settings.json'}, {'file': 'Game/missing.png'}]
            bundle, _ = self.export()
            with bundle:
                self.assertFalse(any(n.startswith('media/') for n in bundle.namelist()))
                report = bundle.read('report.html').decode()
                self.assertIn('Evidence unavailable', report)
                self.assertNotIn('private-data', report)
                self.assertNotIn('settings.json', report)

    def test_slack_summary_is_one_line_per_finding_grouped_by_game(self):
        first = {**self.store.tickets['GA-001'], 'title': 'Fix the\nreward button', 'status': 'approved'}
        second = {**first, 'title': 'Make the coin total visible', 'status': 'draft'}
        other = {**first, 'game': 'Other Game', 'title': 'Fix the timer'}
        self.assertEqual(slack_text([first, second, other]),
                         'Game — playtest feedback\n• Fix the reward button\n• Make the coin total visible (draft)\n\nOther Game — playtest feedback\n• Fix the timer\n')
        long = slack_text([{**first, 'title': 'A very long finding ' * 30}])
        self.assertLessEqual(len(long.splitlines()[1]), 182)
        self.assertTrue(long.rstrip().endswith('…'))

    def test_invalid_or_hidden_selection_is_rejected_atomically(self):
        for ids in [[], 'GA-001', ['GA-001', 'missing'], [None]]:
            with self.assertRaises(ValueError): select_tickets(self.store, ids)
        for fields in [{'status': 'rejected'}, {'status': 'deleted'}, {'duplicateOf': 'GA-002'}]:
            original = copy.deepcopy(self.store.tickets['GA-001'])
            self.store.tickets['GA-001'].update(fields)
            with self.assertRaises(ValueError): select_tickets(self.store, ['GA-001'])
            self.store.tickets['GA-001'] = original
        self.store.clips['Game/clip.mp4'] = {'status': 'deleted'}
        with self.assertRaises(ValueError): select_tickets(self.store, ['GA-001'])

    def test_http_preview_download_host_origin_and_stale_selection(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.store, 0))
        port = server.server_port
        server.RequestHandlerClass = make_handler(self.store, port)
        thread = threading.Thread(target=server.serve_forever); thread.start()
        base = f'http://127.0.0.1:{port}'
        try:
            req = Request(base + '/api/share-preview', data=json.dumps({'ids': ['GA-001']}).encode(), headers={'Content-Type': 'application/json', 'Origin': base})
            with urlopen(req) as r:
                text = json.load(r)['text']
                self.assertIn('• ', text)
                self.assertNotIn('Grant reward', text)
            url = base + '/api/share.zip?' + urlencode({'ids': 'GA-001', 'recordings': '0'})
            with urlopen(url) as r:
                self.assertEqual(r.headers['Content-Type'], 'application/zip')
                self.assertIn('attachment;', r.headers['Content-Disposition'])
                with zipfile.ZipFile(io.BytesIO(r.read())) as z:
                    self.assertIn('report.html', z.namelist())
                    self.assertFalse(any(n.endswith('.mp4') for n in z.namelist()))
            for bad in [Request(url, headers={'Host': 'evil.test'}),
                        Request(req.full_url, data=req.data, headers={'Content-Type': 'application/json', 'Origin': 'http://evil.test'})]:
                with self.assertRaises(HTTPError) as ctx: urlopen(bad)
                self.assertEqual(ctx.exception.code, 403); ctx.exception.close()
            self.store.tickets['GA-001']['status'] = 'rejected'
            with self.assertRaises(HTTPError) as ctx: urlopen(url)
            self.assertEqual(ctx.exception.code, 409); ctx.exception.close()
        finally:
            server.shutdown(); thread.join(); server.server_close()
