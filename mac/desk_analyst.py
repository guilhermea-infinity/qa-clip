"""The analyst: a background worker that drafts tickets for every new clip.

For each clip: frames every 0.5 s and an overview sheet (ffmpeg), the tester's words (whisper-cli), then one fresh
headless CLI run (Claude Code or Codex) that looks at the frames and returns tickets as JSON. Each clip gets its own
run, so a confusing clip never leaks into the next one. Runs use the selected CLI login.
"""
import copy
import json
import math
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from desk_store import now_iso, remove_tree

HERE = Path(__file__).resolve().parent
RED = (229, 36, 59)

SCHEMA = {
    "type": "object",
    "properties": {
        "clip_summary": {"type": "string", "description": "One or two sentences: what happens in the clip."},
        "tickets": {"type": "array", "maxItems": 5, "items": {
            "type": "object",
            "properties": {
                "kind": {"enum": ["bug", "change", "polish", "crash", "idea"]},
                "priority": {"enum": ["high", "normal", "low"]},
                "title": {"type": "string"},
                "where": {"type": "string"},
                "now": {"type": "string"},
                "want": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "done_when": {"type": "string"},
                "quote": {"type": "object", "properties": {"text": {"type": "string"}, "t": {"type": "number"}},
                          "required": ["text", "t"]},
                "moment": {"type": "object", "properties": {"from": {"type": "number"}, "to": {"type": "number"}},
                           "required": ["from", "to"]},
                "shots": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                    "type": "object",
                    "properties": {"t": {"type": "number"}, "caption": {"type": "string"},
                                   "box": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
                    "required": ["t", "caption"]}},
                "checks": {"type": "array", "items": {"type": "string"}},
                "confidence": {"enum": ["high", "medium", "low"]},
                "duplicate_of": {"type": ["string", "null"]},
            },
            "required": ["kind", "priority", "title", "where", "now", "want", "done_when", "moment", "shots",
                         "confidence"],
        }},
    },
    "required": ["clip_summary", "tickets"],
}

WHISPER_MODELS = [
    "~/.cache/whisper/ggml-medium.bin",
    "~/.cache/whisper/ggml-small.bin",
    "~/Library/Application Support/superwhisper/ggml-small.bin",
    "~/.whisper-models/ggml-base.en.bin",
]


def find(name, *extra):
    for p in (shutil.which(name), *extra):
        if p and os.path.exists(os.path.expanduser(p)):
            return os.path.expanduser(p)
    return None


def find_tools():
    model = next((os.path.expanduser(m) for m in [os.environ.get("QA_WHISPER_MODEL", ""), *WHISPER_MODELS] if os.path.exists(os.path.expanduser(m))), None)
    return {
        "ffmpeg": find("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"),
        "ffprobe": find("ffprobe", "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"),
        "whisper": find("whisper-cli", "/opt/homebrew/bin/whisper-cli", "/usr/local/bin/whisper-cli"),
        "whisper_model": model,
        "codex": find("codex", "~/.local/bin/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex"),
        "claude": find("claude", "~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude",
                       "~/.claude/local/claude"),
    }


def child_env():
    """Run claude as if from a fresh terminal, even when the desk was started from inside Claude Code."""
    env = dict(os.environ)
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(k, None)
    return env


def run(cmd, timeout=120, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def mmss(t):
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


class Analyst(threading.Thread):
    def __init__(self, store, tools, say, notify, stop=None):
        super().__init__(daemon=True)
        self.store, self.tools, self.say, self.notify = store, tools, say, notify
        self.stop = stop or threading.Event()
        self.auth_key = None
        self.process = None
        self.process_lock = threading.Lock()
        self.auth_checked = 0

    # ---- the loop ----

    def run(self):
        while not self.stop.is_set():
            try:
                config = self.store.config()
                rel = self.store.next_queued()
                if rel and not config["paused"] and self.signed_in(config):
                    self.analyse(rel, config)
                    continue
            except Exception as e:  # never let the worker die
                self.say(f"Analyst error: {e}")
            self.stop.wait(2)

    def signed_in(self, config):
        """Do not consume clips while the selected CLI is missing or signed out."""
        provider = config["provider"]
        key = (provider, config["model"])
        if self.auth_key != key:
            self.auth_key = key
            self.auth_checked = 0
            self.store.flags.pop("auth", None)
        flags = self.store.flags
        if flags.get("auth") == "ok":
            return True
        if time.time() - self.auth_checked < 10:
            return False
        self.auth_checked = time.time()
        self.tools = find_tools()
        flags["tools"] = {k: bool(v) for k, v in self.tools.items()}
        if not self.tools[provider]:
            flags["auth"] = "missing"
            return False
        try:
            args = ["auth", "status"] if provider == "claude" else ["login", "status"]
            result = subprocess.run([self.tools[provider], *args], capture_output=True, text=True,
                                    timeout=30, env=child_env())
            ok = json.loads(result.stdout).get("loggedIn") is True if provider == "claude" else result.returncode == 0
        except Exception:
            ok = False
        flags["auth"] = "ok" if ok else "signed-out"
        return ok

    # ---- one clip ----

    def analyse(self, rel, config=None):
        config = config or self.store.config()
        provider, model = config["provider"], config["model"]
        st = self.store
        c = st.clips[rel]
        clip = st.inbox / rel
        meta = dict(c.get("meta") or {})
        meta.update({k: v for k, v in (_read(clip.with_suffix(".json")) or {}).items() if v not in (None, "")})
        game = meta.get("game") or meta.get("appLabel") or meta.get("app") or "Unknown app"
        work = st.work / rel.replace("/", " - ").removesuffix(".mp4")
        st.set_clip(rel, status="working", startedAt=time.time(), step="Extracting frames", error=None, provider=provider, model=model or "CLI default", effort=config.get("effort", ""))
        self.say(f"Analysing {rel}")
        t0 = time.time()
        try:
            if not clip.exists():
                raise RuntimeError("the clip file is gone")
            if not (self.tools["ffmpeg"] and self.tools["ffprobe"]):
                raise RuntimeError("ffmpeg isn't installed (brew install ffmpeg)")
            remove_tree(work)
            (work / "frames").mkdir(parents=True)
            dur, w, h = self.probe(clip)
            pressed = float(meta["pressedAtSecond"]) if meta.get("pressedAtSecond") is not None else min(10.0, dur)
            self.frames(clip, work)
            step = self.sheet(work, dur, pressed, w, h)

            # Path.glob also matches dotfiles: skip AppleDouble ._ sidecars on exFAT/network inboxes.
            preview = str(sorted((work / "frames").glob("t*.jpg"))[0].relative_to(st.inbox))
            st.set_clip(rel, step="Transcribing audio", preview=preview)
            transcript = self.transcribe(clip, work) if meta.get("voice", True) else None

            st.set_clip(rel, step=f"{'Claude' if provider == 'claude' else 'Codex'} is analysing")
            prompt = self.prompt(meta, game, dur, w, h, pressed, step, transcript, c.get("hint"))
            (work / "prompt.md").write_text(prompt)
            data = self.ask_provider(prompt, work, provider, model, config.get("effort", ""))

            st.set_clip(rel, step="Writing tickets")
            ids = self.make_tickets(data, rel, clip, meta, game, dur, w, h)
            st.set_clip(rel, status="done", doneAt=time.time(), tickets=c.get("tickets", []) + ids, step=None,
                        summary=data.get("clip_summary"), seconds=round(time.time() - t0))
            self.say(f"Drafted {', '.join(ids)} from {rel} in {round(time.time() - t0)} s")
            try:
                self.notify("Playtest Demon", f"{len(ids)} ticket{'s' if len(ids) != 1 else ''} to review · {game}")
            except OSError:
                pass
        except Exception as e:
            if self.stop.is_set():
                return  # remains working on disk; startup will requeue it
            msg = str(e)
            if "authenticat" in msg.lower() or "login" in msg.lower() or "oauth" in msg.lower():
                st.flags["auth"] = "signed-out"
                st.set_clip(rel, status="queued", step=None)  # wait for sign-in instead of failing
                self.say(f"{provider} needs sign-in. The clip will wait.")
                return
            st.set_clip(rel, status="failed", error=msg[:500], step=None)
            self.say(f"Couldn't analyse {rel}: {msg[:300]}")

    def probe(self, clip):
        out = run([self.tools["ffprobe"], "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=width,height:format=duration", "-of", "json", str(clip)])
        d = json.loads(out)
        s = d["streams"][0]
        return float(d["format"]["duration"]), int(s["width"]), int(s["height"])

    def frames(self, clip, work):
        fd = work / "frames"
        run([self.tools["ffmpeg"], "-v", "error", "-i", str(clip), "-vf", "fps=2,scale='min(720,iw)':-2",
             "-q:v", "3", str(fd / "%05d.jpg")], timeout=300)
        for f in sorted(fd.glob("[0-9]*.jpg")):
            t = (int(f.stem) - 1) * 0.5
            f.rename(fd / f"t{t:05.1f}.jpg")

    def sheet(self, work, dur, pressed, w, h):
        """One labelled tile every `step` seconds, at most 32 tiles, so one image shows the whole clip."""
        step = max(1, math.ceil(dur / 32))
        times = [float(t) for t in range(0, int(dur) + 1, step)]
        files = [(t, work / "frames" / f"t{t:05.1f}.jpg") for t in times]
        files = [(t, f) for t, f in files if f.exists()]
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            shutil.copy(files[len(files) // 2][1], work / "sheet.jpg")
            return step
        portrait = h >= w
        tw = 160 if portrait else 300
        th = round(tw * h / w)
        cols = 8 if portrait else 4
        rows = math.ceil(len(files) / cols)
        img = Image.new("RGB", (cols * tw + (cols - 1) * 4, rows * th + (rows - 1) * 4), (40, 40, 44))
        try:
            font = ImageFont.load_default(size=22)
        except Exception:
            font = ImageFont.load_default()
        d = ImageDraw.Draw(img)
        for i, (t, f) in enumerate(files):
            x, y = (i % cols) * (tw + 4), (i // cols) * (th + 4)
            img.paste(Image.open(f).convert("RGB").resize((tw, th)), (x, y))
            label = f"{t:g}s"
            bw = d.textlength(label, font=font) + 12
            d.rectangle((x, y + th - 30, x + bw, y + th), fill=RED if t >= pressed else (20, 20, 22))
            d.text((x + 6, y + th - 28), label, fill=(255, 255, 255), font=font)
        img.save(work / "sheet.jpg", quality=85)
        return step

    def transcribe(self, clip, work):
        if not (self.tools["whisper"] and self.tools["whisper_model"]):
            return None
        wav = work / "voice.wav"
        try:
            run([self.tools["ffmpeg"], "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        except RuntimeError:
            return None  # no audio track
        model = self.tools["whisper_model"]
        lang = "en" if model.endswith(".en.bin") else "auto"
        run([self.tools["whisper"], "-m", model, "-l", lang, "-ml", "60", "-sow", "-oj", "-of",
             str(work / "transcript"), "-np", "-f", str(wav)], timeout=600)
        wav.unlink(missing_ok=True)
        segs = (_read(work / "transcript.json") or {}).get("transcription", [])
        out = [{"from": s["offsets"]["from"] / 1000, "to": s["offsets"]["to"] / 1000, "text": s["text"].strip()}
               for s in segs if s.get("text", "").strip() and s["text"].strip() not in ("[BLANK_AUDIO]", "[MUSIC]")]
        return out

    def prompt(self, meta, game, dur, w, h, pressed, step, transcript, hint):
        tpl = (HERE / "prompts" / "analyst.md").read_text()
        if transcript:
            said = "\n".join(f"- {s['from']:.1f} to {s['to']:.1f} s: \"{s['text']}\"" for s in transcript)
        elif transcript is None:
            said = "(transcript unavailable: audio may be absent, or local transcription is not configured; do not invent a quote)"
        else:
            said = "(the tester didn't say anything)"
        open_t = [t for t in self.store.tickets.values() if t["game"] == game and t["status"] in ("draft", "approved", "sent")]
        open_t = sorted(open_t, key=lambda t: t["id"])[-40:]
        opens = "\n".join(f"- {t['id']} ({t['status']}): {t['title']}" for t in open_t) or "(none)"
        hint = (f"\nThe tester rejected your first draft of this clip and said: \"{hint}\". Use that.\n") if hint else ""
        fill = {
            "platform": meta.get("platform", "Android"),
            "capture_instructions": "This is an imported recording. There was no hardware button press, lookback, or Playtest Demon REC overlay. Read the entire overview and follow the spoken request timings; 0 seconds is the start, not a reaction trigger." if meta.get("platform") in ("iOS", "Imported") else "The tester used laptop browser screen capture with a Start clip control and configurable lookback. pressed_at_second marks their reaction; earlier footage can show the bug. There is no Android recorder overlay." if meta.get("platform") == "Browser" else "The tester used the Android volume-button recorder and its configured lookback.",
            "game": game, "app": meta.get("app", "?"), "version": meta.get("appVersion") or meta.get("version") or "?",
            "device": meta.get("device", "?"), "android": meta.get("android") or meta.get("platform", "?"),
            "length": f"{dur:.1f}", "width": str(min(720, w)), "height": str(round(h * min(720, w) / w)),
            "pressed": f"{pressed:g}", "pressed_at": meta.get("pressedAt", "?"), "step": str(step),
            "transcript": said, "open_tickets": opens, "hint": hint,
        }
        for k, v in fill.items():
            tpl = tpl.replace("{{" + k + "}}", str(v))
        return tpl

    def ask_provider(self, prompt, work, provider, model, effort=""):
        binary = self.tools.get(provider)
        if not binary:
            raise RuntimeError(f"The {provider} command isn't installed")
        if provider == "claude":
            cmd = [binary, "-p", "--tools", "Read,Glob", "--allowedTools", "Read,Glob",
                   "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
                   "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
        else:
            schema = strict_schema(SCHEMA)
            (work / "schema.json").write_text(json.dumps(schema))
            cmd = [binary, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                   "--output-schema", str(work / "schema.json"),
                   "--output-last-message", str(work / "answer.json"), "--image", str(work / "sheet.jpg")]
            prompt += "\nThe attached image is sheet.jpg. Use view_image for individual local frames. Return only ticket JSON."
        if effort:
            cmd += ["--effort", effort] if provider == "claude" else ["-c", f'model_reasoning_effort="{effort}"']
        if model:
            cmd += ["--model", model]
        if provider == "codex":
            cmd += ["-"]  # terminate image arguments; prompt is read from stdin
        try:
            r = self.run_provider(cmd, prompt, work)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{provider} took more than 15 minutes. Retry this clip or choose another model.")
        (work / f"{provider}.log").write_text(r.stdout + "\n" + r.stderr)
        if r.returncode:
            raise RuntimeError(f"{provider} failed: {(r.stderr or r.stdout).strip()[-400:]}")
        try:
            if provider == "codex":
                data = json.loads((work / "answer.json").read_text())
            else:
                res = json.loads(r.stdout)
                if res.get("is_error"):
                    raise RuntimeError(f"Claude: {str(res.get('result'))[:400]}")
                data = res.get("structured_output")
                if not isinstance(data, dict):
                    txt = str(res.get("result", ""))
                    data = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
            from jsonschema import validate
            validate(data, SCHEMA)
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"{provider} did not return valid ticket JSON: {exc}") from exc
        return data

    def cancel_provider(self):
        with self.process_lock:
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def run_provider(self, cmd, prompt, work):
        with self.process_lock:
            if self.stop.is_set():
                raise RuntimeError("Playtest Demon stopped; this clip will resume on restart")
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, cwd=work, env=child_env(), start_new_session=True)
            self.process = process
        try:
            stdout, stderr = process.communicate(prompt, timeout=900)
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            self.cancel_provider()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise
        finally:
            with self.process_lock:
                self.process = None

    # ---- tickets ----

    def make_tickets(self, data, rel, clip, meta, game, dur, w, h):
        st = self.store
        drafts = list(data.get("tickets") or [])[:5]
        if not drafts:  # still give the tester a card, so every clip ends up somewhere
            drafts = [{"kind": "idea", "priority": "low", "title": "Nothing found in this clip",
                       "where": "", "now": data.get("clip_summary", ""), "want": "", "done_when": "",
                       "moment": {"from": max(0, float(meta.get("pressedAtSecond") or 15) - 4),
                                  "to": float(meta.get("pressedAtSecond") or 15)},
                       "shots": [], "confidence": "low",
                       "checks": ["The analyst couldn't tell what to report. Watch the clip and write it, or reject."]}]
        ids = []
        base = time.time()
        for i, d in enumerate(drafts):
            tid = st.new_ticket_id(game)
            tdir = st.root / tid
            tdir.mkdir(parents=True, exist_ok=True)
            shots = []
            for j, s in enumerate((d.get("shots") or [])[:3], 1):
                t = min(max(0.0, round(float(s.get("t", 0)) * 2) / 2), max(0.0, dur - 0.05))
                clean = tdir / f"shot-{j}-clean.png"
                try:
                    run([self.tools["ffmpeg"], "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
                         "-frames:v", "1", str(clean)])
                except RuntimeError:
                    continue
                box = s.get("box") if isinstance(s.get("box"), list) and len(s["box"]) == 4 else None
                marked = tdir / f"shot-{j}.png"
                if not (box and mark(clean, marked, box, min(720, w))):
                    shutil.copy(clean, marked)
                    box = None
                shots.append({"file": f"Tickets/{tid}/shot-{j}.png", "clean": f"Tickets/{tid}/shot-{j}-clean.png",
                              "t": t, "caption": str(s.get("caption", "")).strip(), "box": box, "use": True})
            checks = [str(x) for x in d.get("checks") or [] if str(x).strip()]
            dup = d.get("duplicate_of")
            if dup and dup in st.tickets:
                checks.insert(0, f"Looks like {dup} ({st.tickets[dup]['title']}). Reject this one if it's the same.")
            q = d.get("quote") or {}
            m = d.get("moment") or {}
            t = {
                "id": tid, "status": "draft", "order": base + i / 1000, "created": now_iso(),
                "game": game, "app": meta.get("app"), "version": meta.get("appVersion") or meta.get("version"),
                "device": meta.get("device"), "android": meta.get("android"), "platform": meta.get("platform", "Android"),
                "clip": rel, "pressedAtSecond": meta.get("pressedAtSecond"), "clipSeconds": round(dur, 1), "frame": [w, h],
                "kind": d.get("kind", "change"), "priority": d.get("priority", "normal"),
                "title": str(d.get("title", "")).strip()[:200],
                "where": str(d.get("where", "")).strip(), "now": str(d.get("now", "")).strip(),
                "want": str(d.get("want", "")).strip(), "done_when": str(d.get("done_when", "")).strip(),
                "steps": [str(x).strip() for x in d.get("steps") or [] if str(x).strip()],
                "quote": {"text": str(q.get("text", "")).strip(), "t": float(q.get("t") or 0)} if q.get("text") else None,
                "moment": {"from": float(m.get("from") or 0), "to": float(m.get("to") or 0)},
                "shots": shots, "checks": checks, "confidence": d.get("confidence", "medium"),
                "duplicate_of": dup if dup in st.tickets else None, "note": "",
                "summary": data.get("clip_summary", ""),
                "provider": st.clips[rel].get("provider"), "model": st.clips[rel].get("model"), "effort": st.clips[rel].get("effort", ""),
            }
            st.save_ticket(t)
            ids.append(tid)
        return ids


def mark(src, dst, box, frame_w):
    """Draw the analyst's red box on a full-size screenshot. False if the box makes no sense."""
    try:
        from PIL import Image, ImageDraw
        img = Image.open(src).convert("RGB")
        k = img.width / frame_w
        x0, y0, x1, y1 = [float(v) * k for v in box]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 4 or y1 - y0 < 4 or x1 > img.width * 1.05 or y1 > img.height * 1.05:
            return False
        pad = 8 * k
        r = (max(2, x0 - pad), max(2, y0 - pad), min(img.width - 3, x1 + pad), min(img.height - 3, y1 + pad))
        ImageDraw.Draw(img).rounded_rectangle(r, radius=12 * k, outline=RED, width=max(3, round(5 * k)))
        img.save(dst)
        return True
    except Exception:
        return False


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def strict_schema(schema):
    """Codex structured outputs require closed objects and all properties required."""
    result = copy.deepcopy(schema)
    def visit(node):
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
            for child in node.get("properties", {}).values():
                visit(child)
        if "items" in node:
            visit(node["items"])
    visit(result)
    # A null box means the analyst could not confidently locate the element.
    box = result["properties"]["tickets"]["items"]["properties"]["shots"]["items"]["properties"]["box"]
    box["type"] = ["array", "null"]
    return result
