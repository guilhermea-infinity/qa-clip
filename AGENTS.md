# Playtest Demon agent instructions

Playtest Demon is an Android/laptop browser screen recorder plus a macOS review desk, with iPhone/iPad screen-recording imports and local coding-agent fix runs.

## If asked to install

Read `docs/INSTALL-AGENT.md` and follow its verification sequence. Preserve existing clips, drafts, handoffs, provider preferences and pairing keys. The owner chooses the provider/model and completes account sign-in and Android consent. Use the `.venv` runtime. Report real verification separately from inferred behavior.

## If asked to develop

- `android/`: plain Java app, minimum Android API 29, compile SDK 36. Keep `com.infinitygames.qaclip` for compatibility with installed phones.
- `mac/native/`: native AppKit/WebKit window and menu lifecycle. `mac/service.py` is the frozen service/receiver entry point; never invoke the frozen executable as if it were a Python interpreter.
- `scripts/package-mac.py`: movable .app plus ZIP/DMG, embedded Python, no owner data. Verify actual bundled startup/UI/shutdown in an isolated inbox.
- `mac/qa-inbox.py`: USB/Bonjour receiver, complete-file acknowledgement. Every phone request must target this Mac’s stable identity before auth/game/media handling. `desk_identity.py` stores it outside the repo.
- `android/.../MacRoute.java` and `Uploader.java`: explicit per-laptop pairing, identity pinning, and per-clip destination ownership. Never fall back to another discovered Mac or silently adopt/reassign queued clips. Verify `bash scripts/check-routing.sh` with Java on PATH.
- `mac/desk_store.py`: durable queue, ticket state and handoffs; disk mutations use its lock.
- `mac/desk_analyst.py`: one worker, media extraction, transcription and provider adapters. Keep arrivals observable while this worker blocks.
- `mac/desk_server.py`: loopback-only HTTP API, same-origin writes and bounded media paths.
- `mac/desk_runs.py`: approved batch reservations, isolated clones, provider execution, verified publication and protected merge. Repository setup accepts a GitHub URL or optional local clone and only reads metadata/manifests; never execute project scripts during connection. Never silently retry an interrupted agent run or bypass failed checks.
- `mac/desk_import.py`: bounded streaming MOV/MP4 imports with audio, conversion and exact-file deduplication.
- `android/.../Batches.java` and `BatchArchive.java`: phone-only sessions remain outside the Mac outbox. Export only finished clips and allowlisted metadata; never adopt them when pairing or switching modes. `BatchProvider` grants read-only access only to completed batch ZIPs.
- `mac/desk_batch.py`: bounded Android batch imports, complete validation before atomic publication, durable arrival receipts and per-recording deduplication. Preserve Android voice, game/build and press/lookback metadata without importing receiver identity or settings.
- `mac/desk-ui/playtest.*`: standalone browser screen/microphone recorder with overlapping complete containers for lookback. Keep screen sharing owner-consented; never treat arbitrary MediaRecorder timeslices as independent video files. Browser upload timing is validated and trimmed by `desk_import.py`.
- `mac/desk-ui/`: dependency-free browser UI. Preserve in-progress edits and playback across polling.
- `mac/prompts/`: hot-loaded instructions, shared by both providers.

Do not weaken sandbox/tool restrictions to get a provider run working. Do not silently fall back to another provider or model. Never submit real user clips to a different service during tests; use synthetic fixtures. Keep data and auth outside the repository.

Validate meaningful changes with `.venv/bin/python -m unittest discover -s tests -v`. Check frontend syntax (`scripts/check-ui.js`) and recorder lifecycle regressions (`node --test tests/test_capture.js`) and visually exercise changed flows against a disposable inbox. Build Android changes with `./build.sh`. iOS uses the built-in screen recorder plus imports; do not claim a native ReplayKit app is shipped.

For batch changes, `tests/test_batch.py` exercises the APK's real Java ZIP writer against the desktop importer. The dependency-free `BatchInstrumentation` runner under `androidTest/` checks Android storage, routing isolation, metadata stripping and content URI permissions with synthetic media. Build `assembleDebugAndroidTest` and run it only on a disposable emulator, never against an owner's phone/data; the runner changes its test app preferences and creates synthetic batches.

Publish only source, documentation, synthetic screenshots and explicitly intended release APKs/checksums. Never commit `android/local.properties`, `.venv`, `.gradle`, build outputs, inboxes, device keys or signing keys. Do not uninstall an existing phone app without owner approval; its unsent clips may be lost.
