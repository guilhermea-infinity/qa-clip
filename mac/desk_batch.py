"""Import portable Android recording batches without adopting the sender's pairing or settings."""
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
import zlib
from pathlib import Path

from desk_games import game_name, games

MAX_BATCH_BYTES = 2 * 1024 * 1024 * 1024
MAX_CLIP_BYTES = 750 * 1024 * 1024
MAX_CLIPS = 100


def number(entry, key, low, high, default=0):
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid recording {key}')
    return round(value, 3)


def inspect_video(probe, path):
    result = subprocess.run([probe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                             '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('A batch recording is unreadable. Nothing was imported.')
    try:
        info = json.loads(result.stdout)
        duration = float(info.get('format', {}).get('duration', 0))
        streams = info.get('streams', [])
        if not math.isfinite(duration) or not 0 < duration <= 600 or not any(s.get('codec_type') == 'video' for s in streams):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Each batch recording must be a readable video under 10 minutes') from None
    return duration, any(s.get('codec_type') == 'audio' for s in streams)


def import_batch(store, stream, length, filename):
    if not isinstance(filename, str) or Path(filename).suffix.lower() != '.zip':
        raise ValueError('Choose a Playtest Demon recording batch ZIP')
    if not 0 < length <= MAX_BATCH_BYTES:
        raise ValueError('Choose a batch under 2 GB')
    probe = shutil.which('ffprobe')
    if not probe:
        raise ValueError('Install ffmpeg before importing recording batches')
    imports = store.inbox / 'Imports'; imports.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.batch-import-', dir=imports) as temp:
        temp = Path(temp)
        archive = temp / 'batch.zip'
        with archive.open('wb') as out:
            left = length
            while left:
                chunk = stream.read(min(left, 1 << 20))
                if not chunk: raise ValueError('Upload was interrupted. Retry the same batch.')
                out.write(chunk); left -= len(chunk)
        stage = temp / 'ready'; stage.mkdir()
        prepared = []
        try:
            with zipfile.ZipFile(archive) as batch:
                infos = batch.infolist()
                names = [i.filename for i in infos]
                if (not 2 <= len(infos) <= MAX_CLIPS + 1 or len(set(names)) != len(names)
                        or 'manifest.json' not in names):
                    raise ValueError('This is not a Playtest Demon recording batch')
                if any(i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16) or i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for i in infos):
                    raise ValueError('Unsupported batch archive')
                if any(i.file_size > MAX_CLIP_BYTES for i in infos) or sum(i.file_size for i in infos) > MAX_BATCH_BYTES:
                    raise ValueError('Batch expands beyond the recording size limit')
                if batch.getinfo('manifest.json').file_size > 256 * 1024:
                    raise ValueError('Batch manifest is too large')
                manifest = json.loads(batch.read('manifest.json'))
                if not isinstance(manifest, dict) or manifest.get('format') != 'playtest-demon-batch' or type(manifest.get('version')) is not int or manifest['version'] != 1:
                    raise ValueError('Unsupported batch format. Export it from Playtest Demon on Android.')
                bid = manifest.get('batchId')
                if not isinstance(bid, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', bid):
                    raise ValueError('Invalid batch identity')
                entries = manifest.get('clips')
                if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_CLIPS or not all(isinstance(e, dict) for e in entries):
                    raise ValueError('A batch must contain 1–100 recordings')
                paths = [e.get('file') for e in entries]
                if any(not isinstance(p, str) or not re.fullmatch(r'clips/\d{3}\.mp4', p) for p in paths) or len(set(paths)) != len(paths) or set(names) != {'manifest.json', *paths}:
                    raise ValueError('Batch contents do not match its recording list')
                for i, entry in enumerate(entries):
                    game = game_name(entry.get('game'))
                    pressed = number(entry, 'pressedAtSecond', 0, 45)
                    lookback = number(entry, 'lookbackSeconds', 0, 30)
                    path = stage / f'{i + 1:03d}.mp4'
                    digest = hashlib.sha256()
                    with batch.open(entry['file']) as source, path.open('wb') as out:
                        while chunk := source.read(1 << 20):
                            digest.update(chunk); out.write(chunk)
                    duration, voice = inspect_video(probe, path)
                    if pressed > duration + .5:
                        raise ValueError('A recording has invalid press timing')
                    meta = {'game': game, 'appLabel': game, 'platform': 'Android', 'sourceBatchId': bid,
                            'clipSeconds': round(duration, 3), 'pressedAtSecond': pressed, 'lookbackSeconds': lookback,
                            'voice': voice, 'originalName': entry['file']}
                    for field in ('appLabel', 'app', 'appVersion', 'pressedAt', 'size', 'device', 'android'):
                        if isinstance(entry.get(field), str): meta[field] = entry[field][:200]
                    identity = [game, meta.get('pressedAt'), pressed, lookback, digest.hexdigest()]
                    meta['importHash'] = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                    prepared.append((path, meta))
        except (zipfile.BadZipFile, EOFError, UnicodeError, json.JSONDecodeError, NotImplementedError, zlib.error) as exc:
            raise ValueError('Batch is damaged or incomplete. Nothing was imported.') from exc

        with store.lock:
            # Reconcile receipts first: a crash after publishing the files is safely recoverable.
            store.sync_inbox()
            existing = {c.get('meta', {}).get('importHash'): rel for rel, c in store.clips.items() if c.get('status') != 'deleted'}
            folder_name = f'batch-{time.time_ns()}-{uuid.uuid4().hex[:8]}'
            arrivals, duplicates = [], 0
            for path, meta in prepared:
                if meta['importHash'] in existing:
                    duplicates += 1; path.unlink(); continue
                rel = f'Imports/{folder_name}/{path.name}'
                meta['file'] = rel
                path.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False))
                arrivals.append(meta); existing[meta['importHash']] = rel
            if arrivals:
                # One atomic directory publication exposes every validated recording together.
                (stage / 'arrivals.json').write_text(json.dumps(arrivals, ensure_ascii=False))
                for path in stage.iterdir():
                    with path.open('rb') as handle: os.fsync(handle.fileno())
                games(store.inbox, {m['game'] for m in arrivals})
                os.replace(stage, imports / folder_name)
                store.sync_inbox()
            return {'imported': len(arrivals), 'duplicates': duplicates, 'batchId': bid,
                    'games': sorted({m['game'] for _, m in prepared})}
