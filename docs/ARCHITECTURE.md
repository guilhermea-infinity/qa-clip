# How Playtest Demon works

## Capture and transfer

The Android MediaProjection foreground service buffers encoded screen frames. A Volume Up press retains the configured 0–30 seconds (default 10) and begins the marked recording; the next press finishes it. Accessibility listens for the hardware buttons. Microphone audio accompanies the screen; internal game audio is not captured.

The uploader retries local clips through the last endpoint, Bonjour (`_qaclip._tcp`), and USB reverse forwarding to port 8799. Each request has a device key and clip metadata. Unknown Wi-Fi keys require an owner-approved pairing dialog; loopback connections through USB are trusted. The receiver writes a `.part` file, checks its length, renames it, writes metadata, and appends to `inbox.jsonl` before acknowledging. Only completed arrivals enter the analysis queue. Streaming transfer hashes and the fsynced arrival log deduplicate Android retries after an acknowledgement loss, including concurrent transfers; temporary filenames are unique.

For nonzero lookback, the ring starts at the newest keyframe at or before the requested boundary. At zero, no pre-roll is retained: the muxer waits for a newly requested sync frame and sets the press offset to zero. Changing lookback/voice requires stopping the session. Game selection is snapshotted when the clip starts; changing it later cannot relabel a clip in progress.

`desk_games.py` merges game names in `games.json` under an OS file lock plus a thread lock. Both desktop and receiver use it. Names are case-insensitively deduplicated and are separate from filesystem-safe clip folders. Authenticated receiver `/games` GET/POST syncs the phone’s cached/offline additions; unapproved phones cannot read or change the list. An explicit `game` metadata field takes precedence over automatic app labels.

## Queue and analysis

The inbox watcher scans the arrival log every second independently of the single analysis worker. `Store` persists transitions to `Tickets/clips.json` with atomic replacement, guarded by an RLock. On startup, interrupted working clips return to queued. The desktop process holds a lock per inbox to prevent two desks from editing the same queue.

States: queued → working → done or failed. Retry moves failed/skipped/done clips to queued; already queued/working clips cannot be retried. Redo with a hint rejects only that clip's unapproved drafts. Provider auth errors put a clip back in the queue until sign-in succeeds.

The worker snapshots provider/model/effort settings at the start of each clip, extracts frames at 2 fps, creates a labelled contact sheet, and optionally transcribes audio with whisper.cpp. It sends the prompt and evidence to Claude Code (`-p`, Read/Glob tools) or Codex (`exec`, read-only sandbox, JSON schema and image attachment). Both CLI results are validated against the ticket schema. ffmpeg exports selected screenshots, Pillow adds evidence boxes, and Store writes reviewable drafts.

`desk_models.py` discovers capabilities with Codex app-server `model/list` or Claude’s stream-JSON initialize control response. No inference prompt is sent. Only model metadata is retained; account details are discarded. Discovery is time-bounded, cached per provider, and runs outside the queue lock. Effort options come from capabilities and are validated server-side, then passed as Claude `--effort` or Codex `model_reasoning_effort`. A failed model never silently falls back.

There is intentionally no worker pool. This keeps model usage bounded, draft IDs sequential, and duplicate detection aware of previous clips. A long analysis never blocks receiving or reviewing other work.

## Review and handoff

The loopback HTTP server exposes state, settings, ticket transitions, handoffs and byte-range media playback. The browser polls state every 1.5 seconds and preserves the active form instead of rebuilding it on each update. Settings and queue pause persist per inbox.

`desk_share.py` provides read-only teammate exports, independently of agent handoffs. The UI flushes edits before opening the selection dialog; `POST /api/share-preview` validates explicit request IDs and returns a compact Slack summary (game heading and one bullet per finding). Detailed feedback remains in the HTML and Markdown reports; slack.txt uses the same short summary. `GET /api/share.zip` snapshots those requests under the Store lock, then builds a temporary disk-backed ZIP outside the lock and streams it to the client. Approved, draft, sent, fixing, fixed and verified requests can be selected; rejected, deleted and linked duplicate findings are excluded. The archive contains an escaped, script-free HTML report, Markdown, Slack text and only selected screenshots plus optional recordings. Evidence paths resolve inside the inbox, must have an allowed media extension, and are renamed to relative portable paths. Missing/unsafe evidence is reported. Exports never mark requests sent, reserve batches or copy settings, raw provider output or credentials. WKDownload uses an NSSavePanel in the native app; browsers use their normal attachment download handling.

Ticket states: draft → approved/rejected; either can return to draft. An exported handoff moves its approved tickets to sent; Undo restores them. Handoff filenames include a unique ID, avoiding collisions for repeated exports in the same minute. Handoffs are local Markdown, not remote messages or GitHub issues.

## Boundaries

The receiver is reachable on the local network; the review server is loopback-only and checks Host/Origin. Media paths must stay inside the inbox. Pairing uses device keys, but Wi-Fi transport is not encrypted; use a trusted network or USB. The selected provider receives extracted images/transcript/context. Local logs and inbox files may contain private content and are excluded from Git.

## Phone-only recording batches

Android's **Record & share** mode snapshots a local session into `batches/<UUID>/`, separate from `outbox/` and `sent/`. Recordings keep the same volume-button triggers, voice and lookback. Mode changes and sharing wait until the recorder and final save are finished. The uploader does not discover/reach/sync while this mode is selected; switching modes never adopts standalone recordings into a laptop route. Pairing and old outbox ownership remain intact.

`Batches` creates a ZIP using the JVM-testable `BatchArchive` writer: `manifest.json` (`format: playtest-demon-batch`, version 1, UUID and per-clip metadata) plus `clips/001.mp4` etc. Metadata uses an explicit allowlist without pairing keys or receiver IDs. The non-exported `BatchProvider` grants selected share targets read-only access to a completed cached ZIP; it cannot open arbitrary paths or write files. Original recordings are retained after sharing and no successful-delivery claim is made for opening the share sheet.

The desktop **Import batch** path streams to a temporary directory (2 GB / 100 clips), validates the manifest, unique exact ZIP members, paths, entry types, expanded sizes, actual video/audio and timing, then publishes one complete directory atomically. No arbitrary archive extraction or sender settings are accepted. The durable `Imports/batch-*/arrivals.json` receipt lets `Store.sync_inbox` recover all clips after an interruption without relying on a partially appended shared log. Per-recording hashes include the original game/timing and content; concurrent imports deduplicate under the Store lock. Queue state, trash and the selected analyst are preserved. These imports are Android recordings, so the analyst retains volume-button/lookback interpretation.

## iOS / desktop import

`POST /api/import` streams bounded raw MOV/MP4/M4V bytes into a temporary folder. Host/Origin checks apply before reading. SHA-256 detects identical imports, including concurrent submissions. ffprobe requires a video track and a duration below 10 minutes; ffmpeg converts to H.264/AAC MP4 with faststart while retaining audio. Under the Store lock, the completed file, sidecar and fsynced arrival log are written before queue discovery. No interrupted upload is queued. A hash of an item in recoverable trash does not prevent the owner importing it again.

Imported metadata identifies iOS/Imported and a zero press offset. The analyst prompt explicitly excludes Android trigger/lookback/REC-overlay assumptions. The system recorder is the shipped iOS capture mechanism; there is no native iOS executable in this repository.

## Fix batches

`desk_runs.Runs` owns a separate single worker and durable `Tickets/runs.json`. `POST /api/run` reserves approved requests under Store’s lock and persists their immutable snapshot; states proceed queued → preparing → fixing → testing → publishing → pr_ready → merge_queued → merged. Unaddressed requests pause in needs_review. Owner answers are durable run metadata; an explicit continuation queues the same run/working tree/branch and archives each review/result without changing the approved snapshot. Failed/cancelled legacy runs with saved questions can continue after validating unchanged approvals, exclusive repository ownership and unchanged branch/base history. Failures/interruption stay reserved for explicit recovery, continuation or cancellation. An open PR/active or unresolved failed run blocks new runs for that repository. Startup reconciles reservations and marks interrupted work, without rerunning an agent.

Each run clones the remote base into `AgentRuns/<ID>/repo`, copies selected evidence, invokes its configured CLI and requires every request to be accounted for. The desk reruns the configured checks and verifies the agent did not switch branches/commits. It removes evidence/helpers, creates a commit, pushes only the new branch and creates/reuses the PR by head branch. Saved verified commits can recover publication without another inference.

PR refresh records GitHub state; merge requires the original commit and required status checks and delegates to GitHub auto-merge without admin bypass. Merged requests become fixed; only human playtest confirmation makes them verified. Closed PRs return requests to approved. Reopening a fix retains its previous run ID.

## Review recovery

Trash is a durable soft deletion of a clip and its requests. Restoring returns their prior states; originals remain on disk. Active/submitted evidence cannot be trashed. Duplicate suggestions compare titles and provider hints; linking is human-controlled, scoped to a game, and reversible. A duplicate retains its own ticket/evidence and links to a canonical request. Copying a prompt is a pure export and no longer marks requests sent; older handoff state remains readable/reversible.

Receiver contact contains only device display name, transport and timestamp, separate from pairing keys. Desk process health, receiver availability and recent authenticated phone contact are separate UI signals. Estimates use the median duration of the last ten completed clips after at least three samples; the UI shows a range with an uncertainty explanation.

## Native Mac app

`mac/native/PlaytestDemon.swift` provides an AppKit window, persistent WKWebView, Dock/app menu, file chooser, clipboard/edit menus and external-link routing to the browser. Its service runs with stdout/stderr redirected to `~/Library/Logs/Playtest Demon/desk.log`, so daily launch does not open Terminal. Closing the window keeps the process alive; Quit stops its owned service. The app checks a bounded `/api/health` identity/inbox response before connecting and never treats an unrelated listener as the desk.

`mac/service.py` is frozen with PyInstaller into an independent executable with Python/Pillow/jsonschema, UI and prompt assets. Receiver subprocesses re-exec the frozen service in `--receiver` mode; source launches keep the Python script path. The receiver has its own process group, handles SIGTERM and cleans up Bonjour. Desk-managed receivers also watch their actual parent desk PID and shut down if it disappears, including after SIGKILL, so an orphan cannot occupy the receiver port and prevent the next app launch. Standalone receiver launches remain independent. The frozen entry monitors its native app parent so an unexpectedly closed app does not leave its service running indefinitely.

`scripts/package-mac.py` builds the architecture-native .app, preserves runtime symlinks in a ZIP, and creates a DMG with an Applications shortcut. Source, inboxes and CLI credentials are not needed/copied into the runtime bundle. External ffmpeg/whisper/model/CLI/git/adb tools remain installation prerequisites. Native startup, WebKit UI and shutdown are smoke-tested with a disposable inbox. Release signing is ad-hoc; production notarization requires an Apple developer identity.
