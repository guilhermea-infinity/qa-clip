"""Tickets on disk. Everything lives under the inbox folder, so it is plain files you can open in Finder.

  QA-Inbox/Tickets/clips.json        each clip from inbox.jsonl: queued, working, done or failed
  QA-Inbox/Tickets/RL-001/           one folder per ticket: ticket.json + shot-N.png (red box) + shot-N-clean.png
  QA-Inbox/Tickets/.work/<clip>/     the analyst's frames, overview sheet, transcript and raw output
  QA-Inbox/Handoffs/*.md             every prompt you copied for the programmer agent
"""
import copy
import datetime
import difflib
import hashlib
import statistics
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import desk_handoff
from desk_games import games, game_name
from desk_models import validate_effort

KINDS = ("bug", "change", "polish", "crash", "idea")
PRIORITIES = ("high", "normal", "low")
TEXT_FIELDS = ("title", "where", "now", "want", "done_when", "note")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json(path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def prefix_for(game):
    """Ranch Legacy -> RL, Idle Dot Shooter -> IDS, Enigmic -> EN."""
    words = re.findall(r"[A-Za-z0-9]+", game or "")
    if len(words) >= 2:
        return "".join(w[0] for w in words)[:3].upper()
    return (words[0][:2] if words else "QA").upper()


class Store:
    def __init__(self, inbox):
        self.inbox = Path(inbox)
        self.root = self.inbox / "Tickets"
        self.handoff_dir = self.inbox / "Handoffs"
        self.work = self.root / ".work"
        for d in (self.root, self.handoff_dir, self.work):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = {"provider": "claude", "model": "", "paused": False, "effort": "", **read_json(self.root / "settings.json", {})}
        self.flags = {}  # auth state and the like, shown as banners in the page
        self.clips = read_json(self.root / "clips.json", {})
        self.handoffs = read_json(self.root / "handoffs.json", [])
        self.tickets = {}
        for f in self.root.glob("*/ticket.json"):
            t = read_json(f, None)
            if t and t.get("id"):
                self.tickets[t["id"]] = t
        for c in self.clips.values():  # a run cut off by a restart goes back in the queue
            if c.get("status") == "working":
                c["status"] = "queued"
        for rel, c in self.clips.items():
            meta = c.get('meta', {})
            if not meta.get('game'):
                path = (self.inbox / rel).resolve()
                sidecar = read_json(path.with_suffix('.json'), {}) if self.inbox.resolve() in path.parents else {}
                label = sidecar.get('game') or sidecar.get('appLabel') or next((t['game'] for t in self.tickets.values() if t.get('clip') == rel and t.get('game')), None) or meta.get('appLabel') or meta.get('app')
                if isinstance(label, str) and label.strip():
                    meta['game'] = ' '.join(label.split())[:80]
        self._save_clips()
        games(self.inbox, {t['game'] for t in self.tickets.values() if t.get('game')} |
              {c['meta'].get('game') or c['meta'].get('appLabel') or c['meta'].get('app') for c in self.clips.values() if c.get('meta') and (c['meta'].get('game') or c['meta'].get('appLabel') or c['meta'].get('app'))})

    # ---- clips ----

    def rename_game(self, old, new):
        old, new = game_name(old), game_name(new)
        with self.lock:
            self.sync_inbox()
            if old == new:
                return {'game': new, 'clips': 0, 'tickets': 0}
            if old not in games(self.inbox):
                if new in games(self.inbox): return {'game': new, 'clips': 0, 'tickets': 0}
                raise ValueError('Choose an existing game')
            affected = {rel: c for rel, c in self.clips.items() if (c.get('meta', {}).get('game') or c.get('meta', {}).get('appLabel') or c.get('meta', {}).get('app') or rel.split('/')[0]) == old}
            if any(c.get('status') == 'working' for c in affected.values()):
                raise ValueError('Let this game’s current analysis finish before renaming it')
            active = {'queued', 'preparing', 'fixing', 'testing', 'publishing', 'recovering', 'continuing', 'retesting', 'needs_review', 'failed', 'interrupted', 'pr_ready', 'merge_queued'}
            if any(r.get('game') == old and r.get('status') in active for r in read_json(self.root / 'runs.json', [])):
                raise ValueError('Finish or return this game’s active fixing batch before renaming it')
            repos = read_json(self.root / 'repositories.json', {})
            if old in repos and new in repos and repos[old] != repos[new]:
                raise ValueError('The destination game already has a different repository connection')
            tickets = {tid: t for tid, t in self.tickets.items() if t.get('game') == old}
            sidecars = {}
            for rel in affected:
                path = (self.inbox / rel).resolve().with_suffix('.json')
                if self.inbox.resolve() in path.parents and path.is_file():
                    meta = read_json(path, None)
                    if not isinstance(meta, dict):
                        raise ValueError('A recording’s metadata is unreadable. Restore it before renaming the game.')
                    sidecars[str(path.relative_to(self.inbox.resolve()))] = meta
            backup = self.root / 'Game renames'; backup.mkdir(exist_ok=True)
            write_json(backup / (str(time.time_ns()) + '.json'), {'from': old, 'to': new, 'clips': affected, 'tickets': tickets, 'sidecars': sidecars, 'repositories': repos})
            for rel, c in affected.items(): c.setdefault('meta', {})['game'] = new
            for rel, meta in sidecars.items():
                meta['game'] = new; write_json(self.inbox / rel, meta)
            for t in tickets.values():
                t['game'] = new; self.save_ticket(t)
            if old in repos:
                repos[new] = repos.pop(old); write_json(self.root / 'repositories.json', repos)
            self._save_clips()
            games(self.inbox, [new], rename=(old, new))
            self.flags.setdefault('renamedGames', {})[old] = new
            return {'game': new, 'clips': len(affected), 'tickets': len(tickets)}

    def _save_clips(self):
        write_json(self.root / "clips.json", self.clips)

    def sync_inbox(self, skip_existing=False):
        """Queue every clip in inbox.jsonl that hasn't been seen. Returns how many were new."""
        log = self.inbox / "inbox.jsonl"
        try:
            lines = log.read_text().splitlines()
        except FileNotFoundError:
            lines = []
        for receipt in sorted((self.inbox / 'Imports').glob('batch-*/arrivals.json')):
            if receipt.stat().st_size > 1 << 20:
                continue
            arrivals = read_json(receipt, [])
            if isinstance(arrivals, list) and len(arrivals) <= 100:
                lines.extend(json.dumps(m) for m in arrivals)
        new = 0
        with self.lock:
            for line in lines:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if not isinstance(m, dict):
                    continue
                rel = m.get("file")
                if not isinstance(rel, str) or not rel or rel in self.clips:
                    continue
                path = (self.inbox / rel).resolve()
                if self.inbox.resolve() not in path.parents or path.suffix.lower() != ".mp4":
                    continue
                self.clips[rel] = {"status": "skipped" if skip_existing else "queued", "meta": m,
                                   "queuedAt": time.time(), "tickets": []}
                new += 1
            if new:
                self._save_clips()
        return new

    def next_queued(self):
        with self.lock:
            q = [(c.get("queuedAt", 0), rel) for rel, c in self.clips.items() if c.get("status") == "queued"]
            return min(q)[1] if q else None

    def set_clip(self, rel, **kw):
        with self.lock:
            self.clips.setdefault(rel, {}).update(kw)
            self._save_clips()

    def retry_clip(self, rel, hint=None):
        """Queue a clip again. With a hint, the drafts it made are put aside and the analyst is told what was wrong."""
        with self.lock:
            c = self.clips.get(rel)
            if not c or c.get("status") in ("working", "queued", "deleted"):
                return False
            if any(t.get("runId") for t in self.tickets.values() if t.get("clip") == rel):
                return False
            if hint is None and any(t.get("status") in ("draft", "approved", "sent", "fixing", "fixed") for t in self.tickets.values() if t.get("clip") == rel):
                return False
            if hint is not None:
                for tid in c.get("tickets", []):
                    t = self.tickets.get(tid)
                    if t and t["status"] == "draft":
                        t["status"] = "rejected"
                        t["rejectedWhy"] = "redone"
                        self.save_ticket(t)
                c["hint"] = hint.strip()[:1000]
            c.update(status="queued", queuedAt=time.time(), error=None)
            self._save_clips()
            return True

    def configure(self, fields):
        # Capability discovery can involve a CLI startup. Never hold the queue lock while waiting.
        if fields.get('effort'):
            previous = self.config()
            provider = fields.get('provider', previous['provider'])
            model = fields.get('model', previous['model'])
            if (provider, model, fields['effort']) != (previous['provider'], previous['model'], previous.get('effort', '')):
                validate_effort(provider, model, fields['effort'])
        with self.lock:
            provider = fields.get("provider", self.settings["provider"])
            model = fields.get("model", self.settings["model"])
            effort = fields.get("effort", "" if provider != self.settings['provider'] or model != self.settings['model'] else self.settings.get('effort', ''))
            if not isinstance(effort, str) or effort not in ('', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
                raise ValueError('Invalid effort level')
            paused = fields.get("paused", self.settings["paused"])
            if provider not in ("claude", "codex"):
                raise ValueError("Choose Claude Code or Codex CLI")
            if not isinstance(model, str) or len(model) > 120 or any(c.isspace() for c in model):
                raise ValueError("Model must be a model ID without spaces, or blank for the CLI default")
            if not isinstance(paused, bool):
                raise ValueError("Paused must be true or false")
            self.settings = {"provider": provider, "model": model, "effort": effort, "paused": paused}
            write_json(self.root / "settings.json", self.settings)
            self.flags.pop("auth", None)
            return dict(self.settings)

    def config(self):
        with self.lock:
            return dict(self.settings)

    def watch_inbox(self, stop):
        # Discovery must continue while a provider spends minutes on an older clip.
        while not stop.wait(1):
            try:
                self.sync_inbox()
            except OSError as exc:
                self.flags["inbox_error"] = str(exc)
            else:
                self.flags.pop("inbox_error", None)

    # ---- tickets ----

    def new_ticket_id(self, game):
        p = prefix_for(game)
        with self.lock:
            used = [int(m.group(1)) for k in self.tickets for m in [re.fullmatch(re.escape(p) + r"-(\d+)", k)] if m]
            used += [int(m.group(1)) for d in self.root.iterdir() for m in [re.fullmatch(re.escape(p) + r"-(\d+)", d.name)] if m]
            return f"{p}-{max(used, default=0) + 1:03d}"

    def save_ticket(self, t):
        with self.lock:
            d = self.root / t["id"]
            d.mkdir(exist_ok=True)
            t["updated"] = now_iso()
            write_json(d / "ticket.json", t)
            self.tickets[t["id"]] = t

    def update_ticket(self, tid, fields):
        with self.lock:
            t = self.tickets.get(tid)
            if not t or t.get("runId"):
                return None
            for k in TEXT_FIELDS:
                if isinstance(fields.get(k), str):
                    t[k] = fields[k][:4000]
            if fields.get("kind") in KINDS:
                t["kind"] = fields["kind"]
            if fields.get("priority") in PRIORITIES:
                t["priority"] = fields["priority"]
            if isinstance(fields.get("steps"), list):
                t["steps"] = [str(s)[:500] for s in fields["steps"] if str(s).strip()][:20]
            if isinstance(fields.get("quote"), str) and isinstance(t.get("quote"), dict):
                t["quote"]["text"] = fields["quote"][:2000]
            if isinstance(fields.get("useShots"), list):
                keep = {str(s) for s in fields["useShots"]}
                for s in t.get("shots", []):
                    s["use"] = s["file"] in keep
            self.save_ticket(t)
            return t

    def set_status(self, tid, status):
        allowed = {"fixed": ("verified", "draft"), "verified": ("draft",), "draft": ("approved", "rejected"), "approved": ("draft", "rejected"), "rejected": ("draft",)}
        with self.lock:
            t = self.tickets.get(tid)
            if not t or t.get("runId") or status not in allowed.get(t["status"], ()):
                return None
            if status == "approved" and not all(str(t.get(k, "")).strip() for k in ("title", "want", "done_when")):
                return None
            t["status"] = status
            if status == "approved":
                t["approvedAt"] = now_iso()
            if status == "draft":
                t.pop("duplicateOf", None)
                t["order"] = time.time()  # back in the queue, at the end
            self.save_ticket(t)
            return t

    def later(self, tid):
        with self.lock:
            t = self.tickets.get(tid)
            if t and t["status"] == "draft":
                t["order"] = time.time()
                self.save_ticket(t)
            return t

    # ---- hand-offs ----

    def trays(self):
        """Approved tickets waiting to go to the programmer, one tray per game."""
        with self.lock:
            by = {}
            for t in sorted(self.tickets.values(), key=lambda t: (t.get("approvedAt") or "", t["id"])):
                if t["status"] == "approved":
                    by.setdefault(t["game"], []).append(t)
            return [{"game": g, "ids": [t["id"] for t in ts], "tickets": [{"id": t["id"], "title": t["title"]} for t in ts],
                     "prompt": desk_handoff.render(ts, self.inbox)}
                    for g, ts in sorted(by.items())]

    def handoff(self, game, ids):
        with self.lock:
            ts = [self.tickets[i] for i in ids if i in self.tickets and self.tickets[i]["status"] == "approved"
                  and self.tickets[i]["game"] == game]
            if not ts:
                return None
            prompt = desk_handoff.render(ts, self.inbox)
            n = len(self.handoffs) + 1
            when = datetime.datetime.now()
            safe_game = re.sub(r"[^\w .()-]", "_", game)[:80]
            name = f"H-{n:03d} {when:%Y-%m-%d %H.%M} {safe_game} ({len(ts)}).md"
            (self.handoff_dir / name).write_text(prompt)
            rec = {"id": f"H-{n:03d}", "game": game, "tickets": [t["id"] for t in ts], "file": f"Handoffs/{name}",
                   "at": now_iso(), "titles": [t["title"] for t in ts]}
            self.handoffs.append(rec)
            write_json(self.root / "handoffs.json", self.handoffs)
            for t in ts:
                t["status"] = "sent"
                t["sentIn"] = rec["id"]
                t["sentAt"] = rec["at"]
                self.save_ticket(t)
            return rec

    def undo_handoff(self, hid):
        with self.lock:
            rec = next((h for h in self.handoffs if h["id"] == hid and not h.get("undone")), None)
            if not rec:
                return None
            for tid in rec["tickets"]:
                t = self.tickets.get(tid)
                if t and t["status"] == "sent" and t.get("sentIn") == hid:
                    t["status"] = "approved"
                    t.pop("sentIn", None)
                    t.pop("sentAt", None)
                    self.save_ticket(t)
            rec["undone"] = now_iso()
            write_json(self.root / "handoffs.json", self.handoffs)
            return rec

    def handoff_text(self, hid):
        rec = next((h for h in self.handoffs if h["id"] == hid), None)
        if not rec:
            return None
        try:
            return (self.inbox / rec["file"]).read_text()
        except Exception:
            return None

    # ---- recoverable deletion, duplicate evidence and estimates ----

    def trash_clip(self, rel, restore=False):
        with self.lock:
            c = self.clips.get(rel)
            if not c:
                raise ValueError("Video not found")
            linked = [t for t in self.tickets.values() if t.get("clip") == rel]
            if c.get("status") == "working" or any(t.get("runId") or t.get("status") == "sent" for t in linked):
                raise ValueError("This video is in active analysis or a submitted batch. Keep its evidence until the batch is finished.")
            if restore:
                if c.get("status") != "deleted":
                    raise ValueError("Video is not in trash")
                c["status"] = c.pop("previousStatus", "skipped")
                for t in linked:
                    if t.get("status") == "deleted":
                        t["status"] = t.pop("previousStatus", "draft")
                        self.save_ticket(t)
            else:
                if c.get("status") == "deleted":
                    return True
                c.update(previousStatus=c["status"], status="deleted", deletedAt=now_iso())
                for t in linked:
                    t.update(previousStatus=t["status"], status="deleted")
                    self.save_ticket(t)
            self._save_clips()
            return True

    def duplicate_candidates(self, tid):
        with self.lock:
            t = self.tickets.get(tid)
            if not t:
                return []
            result = []
            text = lambda x: re.sub(r"[^a-z0-9 ]", "", x.get("title", "").lower())
            for other in self.tickets.values():
                if other["id"] == tid or other["game"] != t["game"] or other.get("runId") or other["status"] in ("deleted", "rejected", "duplicate"):
                    continue
                score = difflib.SequenceMatcher(None, text(t), text(other)).ratio()
                if score >= .78 or t.get("duplicate_of") == other["id"]:
                    result.append({"id": other["id"], "title": other["title"], "status": other["status"], "score": round(score, 2)})
            return sorted(result, key=lambda x: x["score"], reverse=True)[:5]

    def link_duplicate(self, tid, target):
        with self.lock:
            t, other = self.tickets.get(tid), self.tickets.get(target)
            if not t or not other or tid == target or t["game"] != other["game"]:
                raise ValueError("Choose another ticket in the same game")
            if t["status"] not in ("draft", "approved") or t.get("runId") or other.get("runId") or other["status"] in ("deleted", "rejected", "duplicate"):
                raise ValueError("These tickets cannot be combined")
            t.update(status="duplicate", duplicateOf=target)
            self.save_ticket(t)
            return t

    def unlink_duplicate(self, tid):
        with self.lock:
            t = self.tickets.get(tid)
            if not t or t["status"] != "duplicate":
                raise ValueError("Ticket is not a duplicate")
            t.update(status="draft", order=time.time())
            t.pop("duplicateOf", None)
            self.save_ticket(t)
            return t

    def timing(self):
        recent = sorted([c for c in self.clips.values() if c.get("seconds") and c.get("status") == "done"], key=lambda c: c.get("doneAt", 0))[-10:]
        return {"sampleCount": len(recent), "typicalSeconds": round(statistics.median(c["seconds"] for c in recent)) if recent else None}

    # ---- the page's view of everything ----

    def state(self):
        with self.lock:
            ts = list(self.tickets.values())
            drafts = sorted((t for t in ts if t["status"] == "draft"), key=lambda t: (t.get("order", 0), t["id"]))
            rejected = sorted((t for t in ts if t["status"] == "rejected" and t.get("rejectedWhy") != "redone"),
                              key=lambda t: t.get("updated", ""), reverse=True)[:30]
            working = next(({"clip": rel, **{k: c.get(k) for k in ("step", "startedAt", "meta")}}
                            for rel, c in self.clips.items() if c.get("status") == "working"), None)
            failed = [{"clip": rel, "error": c.get("error"), "game": (c.get("meta") or {}).get("game") or (c.get("meta") or {}).get("app")}
                      for rel, c in self.clips.items() if c.get("status") == "failed"]
            clips = []
            for rel, c in sorted(self.clips.items(), key=lambda item: item[1].get("queuedAt", 0), reverse=True):
                if c.get("status") == "deleted":
                    continue
                linked = [t for t in ts if t.get("clip") == rel]
                clips.append({"clip": rel, **c, "draftIds": [t["id"] for t in linked if t["status"] == "draft"],
                              "ticketCount": len([t for t in linked if t.get("rejectedWhy") != "redone"])})
            return copy.deepcopy({
                "clips": clips,
                "settings": self.settings,
                "games": games(self.inbox),
                "drafts": [{**t, "duplicateCandidates": self.duplicate_candidates(t["id"])} for t in drafts],
                "trays": self.trays(),
                "sent": [h for h in reversed(self.handoffs) if not h.get("undone")][:12],
                "rejected": [{"id": t["id"], "title": t["title"], "game": t["game"]} for t in rejected],
                "working": working,
                "queued": sum(1 for c in self.clips.values() if c.get("status") == "queued"),
                "failed": failed,
                "flags": dict(self.flags),
                "tickets": ts,
                "trash": [{"clip": rel, "game": c.get("meta", {}).get("game") or c.get("meta", {}).get("app"), "deletedAt": c.get("deletedAt")} for rel, c in self.clips.items() if c.get("status") == "deleted"],
                "timing": self.timing(),
                "receiver": read_json(self.inbox / ".receiver.json", {}),
                "repositories": read_json(self.root / "repositories.json", {}),
                "runs": read_json(self.root / "runs.json", []),
            })


def remove_tree(path):
    shutil.rmtree(path, ignore_errors=True)
