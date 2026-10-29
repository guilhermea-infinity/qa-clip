"""Portable human feedback exports, independent of agent handoffs and ticket transitions."""
import copy
import datetime
import html
import re
import tempfile
import zipfile
from pathlib import Path


SHARE_STATUSES = {'draft', 'approved', 'sent', 'fixing', 'fixed', 'verified'}


def select_tickets(store, ids):
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise ValueError('Select at least one request to share')
    with store.lock:
        tickets = []
        for tid in dict.fromkeys(ids):
            t = store.tickets.get(tid)
            if (not t or t.get('status') not in SHARE_STATUSES or t.get('duplicateOf')
                    or store.clips.get(t.get('clip'), {}).get('status') == 'deleted'):
                raise ValueError('A selected request is no longer available. Reopen Share feedback.')
            tickets.append(copy.deepcopy(t))
    return tickets


def stamp(seconds):
    value = max(0, int(float(seconds or 0)))
    return f'{value // 60}:{value % 60:02d}'


def slack_text(tickets):
    groups = {}
    for t in tickets:
        groups.setdefault(t['game'], []).append(t)
    lines = []
    for game, findings in groups.items():
        if lines: lines.append('')
        lines.append(f"{' '.join(game.split())} — playtest feedback")
        for t in findings:
            title = ' '.join(t.get('title', '').split())
            if len(title) > 180:
                title = title[:177].rsplit(' ', 1)[0] + '…'
            draft = ' (draft)' if t['status'] == 'draft' else ''
            lines.append(f'• {title}{draft}')
    return '\n'.join(lines) + '\n'


def feedback_text(tickets):
    lines = [f'Playtest feedback · {len(tickets)} request(s)', '']
    for t in tickets:
        lines += [f"{t['id']} · {t['game']} · {t.get('title', '')}",
                  f"{t.get('kind', 'feedback')} · {t.get('priority', 'normal')} priority · {t['status']}" +
                  (' (not yet approved)' if t['status'] == 'draft' else '')]
        if t.get('version'): lines.append(f"Build: {t['version']}")
        if t.get('moment'): lines.append(f"Video moment: {stamp(t['moment'].get('from'))}–{stamp(t['moment'].get('to'))}")
        for key, label in [('where', 'Where'), ('now', 'Observed'), ('want', 'Expected')]:
            if t.get(key): lines.append(f'{label}: {t[key]}')
        if t.get('steps'):
            lines.append('Steps:')
            lines += [f'{n}. {step}' for n, step in enumerate(t['steps'], 1)]
        for key, label in [('done_when', 'Acceptance'), ('note', 'Note')]:
            if t.get(key): lines.append(f'{label}: {t[key]}')
        if (t.get('quote') or {}).get('text'): lines.append(f"Tester said: {t['quote']['text']}")
        if t.get('checks'):
            lines.append('Needs checking: ' + '; '.join(t['checks']))
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def build_export(store, tickets, include_recordings=True):
    """Use a disk-backed archive: recordings must not be loaded into RAM."""
    archive = tempfile.TemporaryFile()
    base = store.inbox.resolve()
    files, evidence, warnings = {}, {}, []

    def asset(rel, allowed, label):
        if not isinstance(rel, str) or not rel:
            warnings.append(label + ' unavailable')
            return None
        source = (base / rel).resolve()
        if base not in source.parents or source.suffix.lower() not in allowed or not source.is_file():
            warnings.append(label + ' unavailable')
            return None
        if source not in files:
            files[source] = f'media/evidence-{len(files) + 1:03d}{source.suffix.lower()}'
        return files[source]

    try:
        for t in tickets:
            video = asset(t.get('clip'), {'.mp4', '.mov', '.m4v'}, f"{t['id']} recording") if include_recordings else None
            shots = []
            for shot in t.get('shots', []):
                if shot.get('use') is False: continue
                path = asset(shot.get('file'), {'.png', '.jpg', '.jpeg', '.webp'}, f"{t['id']} screenshot")
                if path: shots.append((path, shot))
            evidence[t['id']] = (video, shots)

        text = feedback_text(tickets)
        exported = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        escape = html.escape
        cards = []
        for t in tickets:
            video, shots = evidence[t['id']]
            fields = ''.join(f'<h3>{label}</h3><p>{escape(str(t[key]))}</p>' for key, label in
                             [('where', 'Where'), ('now', 'Observed'), ('want', 'Expected'),
                              ('done_when', 'Acceptance'), ('note', 'Note')] if t.get(key))
            steps = '<h3>Steps</h3><ol>' + ''.join(f'<li>{escape(str(s))}</li>' for s in t['steps']) + '</ol>' if t.get('steps') else ''
            quote = '<blockquote>' + escape(t['quote']['text']) + '</blockquote>' if (t.get('quote') or {}).get('text') else ''
            checks = '<h3>Needs checking</h3><ul>' + ''.join(f'<li>{escape(str(s))}</li>' for s in t['checks']) + '</ul>' if t.get('checks') else ''
            moment = t.get('moment') or {}
            start = max(0, float(moment.get('from') or 0))
            recording = (f'<p>Video moment: {stamp(start)}–{stamp(moment.get("to"))}</p>'
                         f'<video controls preload="metadata" src="{video}#t={start}"></video>'
                         f'<p><a href="{video}">Open recording</a></p>') if video else ''
            images = ''.join(f'<figure><a href="{path}"><img src="{path}" alt="{escape(str(s.get("caption", "Screenshot")))}"></a><figcaption>{stamp(s.get("t"))} · {escape(str(s.get("caption", "")))}</figcaption></figure>' for path, s in shots)
            draft = ' · Not yet approved' if t['status'] == 'draft' else ''
            cards.append(f'<article><small>{escape(t["id"])} · {escape(t["game"])} · {escape(str(t.get("version", "")))}</small><h2>{escape(t.get("title", ""))}</h2><p>{escape(t.get("kind", "feedback"))} · {escape(t.get("priority", "normal"))} priority · {escape(t["status"])}{draft}</p>{fields}{steps}{quote}{checks}{recording}<div class="shots">{images}</div></article>')
        warning_html = '<aside><b>Evidence unavailable</b><ul>' + ''.join(f'<li>{escape(w)}</li>' for w in warnings) + '</ul></aside>' if warnings else ''
        report = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; base-uri 'none'">
<title>Playtest feedback</title><style>body{{font:16px system-ui;line-height:1.55;background:#f3f4f7;color:#17202b;max-width:960px;margin:32px auto;padding:0 20px;overflow-wrap:anywhere}}article,aside{{background:white;border:1px solid #d9dde5;border-radius:16px;padding:24px;margin:24px 0}}h1,h2{{line-height:1.2}}h3{{font-size:14px;margin-bottom:4px}}p,li,blockquote{{white-space:pre-wrap}}small,figcaption{{color:#576071}}video{{width:100%;max-height:560px;background:#111}}.shots{{display:flex;flex-wrap:wrap;gap:16px}}figure{{margin:12px 0;max-width:320px;min-width:0}}img{{max-width:100%;border-radius:8px}}blockquote{{border-left:3px solid #895be6;padding-left:16px;margin-left:0}}a{{color:#6740ae}}</style>
<h1>Playtest feedback</h1><p>{len(tickets)} request(s) · Exported {escape(exported)}</p><p>Drafts are labelled and have not yet been approved. <a href="feedback.md">Text report</a> · <a href="slack.txt">Slack summary</a></p>{warning_html}{''.join(cards)}</html>'''
        markdown = '# Playtest feedback\n\nExported ' + exported + '\n\n' + text
        for t in tickets:
            video, shots = evidence[t['id']]
            markdown += f'\n## {t["id"]} evidence\n\n'
            if video: markdown += f'[Recording]({video})\n\n'
            for path, _ in shots: markdown += f'![Screenshot]({path})\n\n'
        if warnings: markdown += '\nEvidence unavailable:\n' + '\n'.join('- ' + w for w in warnings) + '\n'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            bundle.writestr('report.html', report)
            bundle.writestr('feedback.md', markdown)
            bundle.writestr('slack.txt', slack_text(tickets))
            bundle.writestr('START-HERE.txt', 'Playtest Demon feedback\n\nExtract this ZIP, then open report.html in your browser.\nKeep the media folder beside the report. No app or login is needed.\n\nFor Slack: attach this ZIP and paste slack.txt into your message.\nIf recordings make the ZIP too large, export again without recordings.\n')
            for source, name in files.items(): bundle.write(source, name)
        archive.seek(0)
        games = {t['game'] for t in tickets}
        title = next(iter(games)) if len(games) == 1 else 'all-games'
        slug = re.sub(r'[^A-Za-z0-9_-]+', '-', title).strip('-')[:60] or 'game'
        return archive, f'playtest-feedback-{slug}-{datetime.date.today().isoformat()}.zip'
    except Exception:
        archive.close()
        raise
