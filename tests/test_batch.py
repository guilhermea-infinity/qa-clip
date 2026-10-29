"""Real Android-compatible ZIPs must import completely, retry safely and retain recording context."""
import copy
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mac'))
from desk_store import Store
from desk_batch import import_batch, MAX_BATCH_BYTES
from desk_analyst import Analyst


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory(); root = Path(cls.fixtures.name)
        video = root / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x100:r=10:d=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-shortest', str(video)], check=True)
        cls.video = video.read_bytes()

    @classmethod
    def tearDownClass(cls): cls.fixtures.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = Store(self.root / 'inbox')
        self.manifest = {'format': 'playtest-demon-batch', 'version': 1,
                         'batchId': '12345678-1234-1234-1234-123456789abc', 'createdAt': '2026-10-27 10:00',
                         'clips': [{'file': 'clips/001.mp4', 'game': 'Race Game', 'appVersion': '1.2 (3)',
                                    'pressedAt': '2026-10-27T10:00:00Z', 'pressedAtSecond': .5,
                                    'lookbackSeconds': 10, 'receiverId': 'must-not-import', 'key': 'must-not-import'},
                                   {'file': 'clips/002.mp4', 'game': 'Other Game', 'pressedAtSecond': 1, 'lookbackSeconds': 0}]}

    def archive(self, manifest=None, files=None):
        value = io.BytesIO()
        with zipfile.ZipFile(value, 'w') as z:
            z.writestr('manifest.json', json.dumps(manifest if manifest is not None else self.manifest))
            for name, data in (files if files is not None else {'clips/001.mp4': self.video, 'clips/002.mp4': self.video}).items():
                z.writestr(name, data)
        return value.getvalue()

    def load(self, data=None):
        data = self.archive() if data is None else data
        return import_batch(self.store, io.BytesIO(data), len(data), 'phone-batch.zip')

    def test_actual_android_zip_writer_audio_metadata_and_analysis_queue(self):
        java_home = os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home')
        javac, java = str(Path(java_home) / 'bin/javac'), str(Path(java_home) / 'bin/java')
        if not Path(javac).is_file(): javac, java = shutil.which('javac'), shutil.which('java')
        if not javac or not java: self.skipTest('Java required for APK ZIP contract')
        classes = self.root / 'classes'; classes.mkdir()
        subprocess.run([javac, '-d', str(classes), str(ROOT / 'android/app/src/main/java/com/infinitygames/qaclip/BatchArchive.java'),
                        str(ROOT / 'tests/java/BatchArchiveFixture.java')], check=True)
        manifest = self.root / 'manifest.json'; manifest.write_text(json.dumps(self.manifest))
        video = self.root / 'clip.mp4'; video.write_bytes(self.video)
        archive = self.root / 'batch.zip'
        subprocess.run([java, '-cp', str(classes), 'com.infinitygames.qaclip.BatchArchiveFixture', str(archive), str(manifest), str(video)], check=True)
        result = self.load(archive.read_bytes())
        self.assertEqual((result['imported'], result['duplicates']), (2, 0))
        self.assertEqual(self.store.state()['games'], ['Other Game', 'Race Game'])
        rel = self.store.next_queued(); meta = self.store.clips[rel]['meta']
        self.assertEqual(meta['game'], 'Race Game'); self.assertEqual(meta['appVersion'], '1.2 (3)')
        self.assertEqual(meta['pressedAtSecond'], .5); self.assertEqual(meta['lookbackSeconds'], 10)
        self.assertEqual(meta['platform'], 'Android'); self.assertTrue(meta['voice'])
        self.assertNotIn('receiverId', meta); self.assertNotIn('key', meta)
        analyst = Analyst(self.store, {'ffmpeg': shutil.which('ffmpeg')}, lambda *_: None, lambda *_: None)
        prompt = analyst.prompt(meta, meta['game'], 2, 160, 100, .5, 1, None, None)
        self.assertIn('Android volume-button recorder', prompt)
        self.assertIn('1.2 (3)', prompt)
        self.assertEqual((self.store.inbox / rel).read_bytes(), self.video)

    def test_retry_concurrent_import_and_crash_receipt_recovery(self):
        data = self.archive()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.load(data), range(2)))
        self.assertEqual(sum(r['imported'] for r in results), 2)
        self.assertEqual(sum(r['duplicates'] for r in results), 2)
        self.assertEqual(len(self.store.clips), 2)
        # Simulate a crash after the atomic receipt publication but before clips.json was saved.
        (self.store.root / 'clips.json').write_text('{}')
        restored = Store(self.store.inbox); restored.sync_inbox()
        self.assertEqual(len(restored.clips), 2)
        self.assertEqual({c['status'] for c in restored.clips.values()}, {'queued'})
        self.assertEqual(self.load(data)['imported'], 0)

    def test_imported_recording_runs_through_normal_ticket_generation(self):
        self.load(); rel = self.store.next_queued()
        analyst = Analyst(self.store, {'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe')},
                          lambda *_: None, lambda *_: None)
        result = {'clip_summary': 'Synthetic reward button feedback', 'tickets': [
            {'title': 'Fix the reward button', 'kind': 'bug', 'priority': 'normal',
             'where': 'Reward screen', 'now': 'No reward', 'want': 'Grant reward', 'done_when': 'Reward is granted',
             'moment': {'from': .5, 'to': 1.5}, 'shots': [{'t': .5, 'caption': 'Reward button'}],
             'quote': {'text': 'Fix the reward button', 't': .5}, 'confidence': 'high'}]}
        with patch.object(analyst, 'ask_provider', return_value=result) as provider, patch.object(analyst, 'transcribe', return_value=[]):
            analyst.analyse(rel)
        self.assertEqual(self.store.clips[rel]['status'], 'done', self.store.clips[rel].get('error'))
        ticket = self.store.state()['drafts'][0]
        self.assertEqual(ticket['game'], 'Race Game'); self.assertEqual(ticket['version'], '1.2 (3)')
        self.assertEqual(ticket['pressedAtSecond'], .5)
        self.assertTrue((self.store.inbox / ticket['shots'][0]['file']).is_file())
        self.assertIn('Android volume-button recorder', provider.call_args.args[0])

    def test_invalid_archive_cannot_publish_a_partial_batch(self):
        for data in [b'not a zip', self.archive(files={'clips/001.mp4': self.video, 'clips/002.mp4': b'broken'}),
                     self.archive(files={'clips/001.mp4': self.video, '../outside.mp4': self.video}),
                     self.archive(files={'clips/001.mp4': self.video, 'clips/002.mp4': self.video, 'settings.json': b'{}'})]:
            with self.subTest(size=len(data)), self.assertRaises(ValueError): self.load(data)
            self.assertFalse(self.store.clips)
            self.assertFalse(list((self.store.inbox / 'Imports').glob('batch-*')))
        truncated = self.archive()
        with self.assertRaises(ValueError):
            import_batch(self.store, io.BytesIO(truncated[:-20]), len(truncated), 'batch.zip')

    def test_manifest_timing_paths_limits_and_symlinks(self):
        changes = [('pressedAtSecond', float('nan')), ('pressedAtSecond', 90), ('lookbackSeconds', -1),
                   ('lookbackSeconds', True), ('game', ''), ('file', '../../private.mp4')]
        for key, value in changes:
            manifest = copy.deepcopy(self.manifest); manifest['clips'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.load(self.archive(manifest))
        for field, value in [('version', True), ('batchId', '../outside'), ('clips', [])]:
            manifest = copy.deepcopy(self.manifest); manifest[field] = value
            with self.assertRaises(ValueError): self.load(self.archive(manifest))
        for size in [0, MAX_BATCH_BYTES + 1]:
            with self.assertRaises(ValueError): import_batch(self.store, io.BytesIO(), size, 'batch.zip')
        value = io.BytesIO()
        with zipfile.ZipFile(value, 'w') as z:
            z.writestr('manifest.json', json.dumps(self.manifest))
            link = zipfile.ZipInfo('clips/001.mp4'); link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, '/etc/passwd'); z.writestr('clips/002.mp4', self.video)
        with self.assertRaises(ValueError): self.load(value.getvalue())
        self.assertFalse(self.store.clips)

    def test_reimport_only_restores_an_explicitly_reimported_trashed_recording(self):
        self.load(); first = self.store.next_queued()
        self.store.trash_clip(first)
        result = self.load()
        self.assertEqual((result['imported'], result['duplicates']), (1, 1))
        self.assertEqual(len(self.store.state()['clips']), 2)
        self.assertEqual(self.store.clips[first]['status'], 'deleted')

    def test_http_import_requires_local_host_and_origin(self):
        from desk_server import make_handler
        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args: make_handler(self.store, server.server_port)(*args))
        thread = threading.Thread(target=server.serve_forever); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            data = self.archive()
            for headers in [{'Origin': 'https://evil.test'}, {'Host': 'evil.test'}]:
                req = Request(base + '/api/import-batch', data, {'X-Filename': 'batch.zip', **headers})
                with self.assertRaises(HTTPError) as result: urlopen(req)
                self.assertEqual(result.exception.code, 403); result.exception.close()
            with urlopen(Request(base + '/api/import-batch', data, {'Origin': base, 'X-Filename': 'batch.zip'})) as r:
                self.assertEqual(json.load(r)['imported'], 2)
        finally:
            server.shutdown(); thread.join(); server.server_close()
