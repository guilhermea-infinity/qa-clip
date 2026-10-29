# Install Playtest Demon for your owner

You are installing a macOS playtest desk, an Android capture app if needed, a laptop browser recording session, and/or an iPhone recording import workflow. Complete the checks you can perform, guide the owner through Android permission prompts, and report what you actually verified. Do not claim an end-to-end phone test unless a real clip arrived and produced a ticket.

## 1. Inspect and choose

- Confirm this is macOS. For laptop-only capture, follow [LAPTOP.md](LAPTOP.md) and skip Android tools, installation and permissions. Android capture needs Android 10+. iPhone/iPad uses built-in screen recording and AirDrop; follow [IOS.md](IOS.md) and skip Android installation/permissions. Other laptop operating systems are not supported.
- Inspect `python3`, `brew`, `node`, `ffmpeg`, `ffprobe`, `whisper-cli`, `claude`, `codex`, Java, `git`, `gh`, `adb`, and the Android SDK. Reuse working installations.
- Ask the owner to choose **Codex CLI or Claude Code**, a model or CLI default, the installation directory, and the inbox location if their preferences are not already known. Do not switch providers because one lacks credentials.
- Check for an existing Playtest Demon (formerly QA Clip / QA Demon) installation and `~/Desktop/QA-Inbox`. Preserve data, settings and pairing keys. Back up the existing inbox before migration. Never put it inside the Git repository.
- Inspect `adb devices`. If several devices are connected, select the owner's intended serial explicitly. An `unauthorized` device needs the owner's approval on the phone.

## 2. Install the laptop tools

Clone the repository into an owner-approved directory. From that directory:

```bash
bash scripts/setup-mac.sh --brew
# Laptop-only: bash scripts/setup-mac.sh --brew --laptop
# iOS-only: bash scripts/setup-mac.sh --brew --ios
```

The script installs Homebrew packages and Python dependencies in `.venv`. If Homebrew is missing, guide the owner through its official installation at https://brew.sh; do not assume administrator access. For existing dependencies, omit `--brew` to set up only Python.

If Node.js is missing, install it (`brew install node`). Install only the selected CLI:

```bash
npm install -g @openai/codex
codex login
# OR
npm install -g @anthropic-ai/claude-code
claude auth login
```

The owner completes browser/account sign-in. Never collect passwords, copy credentials, or print token files. Confirm `codex login status` or `claude auth status`.

For voice, reuse an existing whisper.cpp model. Otherwise download the multilingual small model (roughly 466 MB):

```bash
mkdir -p "$HOME/.cache/whisper"
curl -fL --retry 3 https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin \
  -o "$HOME/.cache/whisper/ggml-small.bin"
```

An alternate model path can be supplied with `QA_WHISPER_MODEL`. This environment variable must be present when starting Playtest Demon; a Terminal-only export is not inherited by a later Finder launch. The default cache location works for both.

Run `.venv/bin/python scripts/doctor.py --provider codex` (or `claude`). Resolve required missing tools; explicitly report if voice transcription is unavailable.

## 3. Install the Mac app

Prefer the release’s architecture-matching macOS DMG/app for daily use. Drag it into Applications and open it. Python/Pillow/jsonschema are embedded, so runtime does not depend on the source `.venv`. Install the external tools and owner-selected CLI/login as above. The current app build is Apple Silicon/macOS 14+; build on an Intel Mac for Intel.

If a source-launched desk is running on port 8800, let current work finish and stop that process once before opening the app. Do not kill an unrelated service. Confirm `/api/health` identifies Playtest Demon and the intended inbox. Check the native window loads and the receiver is ready. The owner approves macOS folder/network prompts if shown. Ad-hoc signed updates can ask for Desktop-folder access again; approve the prompt, and reopen the app if its first startup timed out while waiting. A downloaded app is locally signed, not notarized; use System Settings → Privacy & Security → Open Anyway if macOS asks.

Closing the window keeps the desk available through the Dock. Cmd+Q stops the owned desk and receiver. Confirm Quit/relaunch against a disposable inbox before claiming lifecycle verification. Logs are in `~/Library/Logs/Playtest Demon/`. Do not uninstall/reset the app’s data to troubleshoot.

For a source build, run `.venv/bin/python -m pip install -r requirements-mac-build.txt`, then `.venv/bin/python scripts/package-mac.py`. The `.app` in `out/mac/` is movable; keep its Contents intact. Keep source terminal commands available for diagnostics, not as the owner’s daily launch requirement.

## 4. Build and install Android (skip for iOS)

Use Android Studio's SDK Manager to install Android SDK Platform 36 and Build Tools 35.0.0. Its usual macOS SDK location is `~/Library/Android/sdk`. Set `ANDROID_HOME` if different. With command-line SDK tools already available, the equivalent is:

```bash
sdkmanager 'platform-tools' 'platforms;android-36' 'build-tools;35.0.0'
```

The owner must accept Android SDK licenses. Do not blindly pipe “yes” into license prompts.

```bash
./build.sh
./mac/install-phone.sh DEVICE_SERIAL
```

Alternatively, download the versioned APK and checksum file from this repository's GitHub Release, verify it using `shasum -a 256`, place it in `out/`, and use `install-phone.sh`. An APK alone does not require Java or the full SDK; only adb is needed for USB installation.

If Android reports `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, the installed app uses a different signing key. Stop before uninstalling: that would erase unsent clips. Ask the owner to export/send the clips first or use an APK built with the original signing key. Keep the same local debug key for future local upgrades.

## 5. Pair the intended laptop and guide Android permissions (skip for iOS)

Install Mac/Android **0.6.1+ together**. In the Mac’s Live feed, click **Pair Android**. Have the owner enter that code in the phone’s **Mac · tap to pair** row. Never choose a laptop merely because Bonjour discovers it, its name matches, or it previously approved the phone. The full receiver identity is pinned after the explicit code match. Verify phone name/code correspond to this Mac. A Wi-Fi phone still needs approval on its chosen Mac. If that Mac goes offline, clips stay queued; do not route them elsewhere to make a test pass.

Updating the APK preserves saved clips, the app package/signing key and capture preferences. Existing installations require this one-time explicit pairing instead of inheriting a potentially wrong old address. Already addressed queued clips retain their original destination; old unaddressed clips are adopted only by the owner’s explicit pairing choice. Do not move/delete a coworker’s inbox to compensate for old misrouting.

These are owner actions, not permissions an agent should silently grant:

1. Enable Developer options and USB debugging; approve the Mac's debugging fingerprint.
2. In Playtest Demon, enable “Playtest Demon volume buttons” in Accessibility settings.
3. If Android blocks Accessibility for a sideloaded app, open Settings → Apps → Playtest Demon → ⋮ → Allow restricted settings, then retry.
4. Grant microphone and notification permissions when prompted.
5. Tap Start session and approve screen capture. Choose the whole screen when offered so the game is included.

Do not disable platform protections or change unrelated accessibility services.

## 6. Start and verify the full loop

For a prebuilt app install, open Playtest Demon.app from Applications; use the commands below only for source launches. For laptop capture, use **Start playtest session** and the real-screen verification in [LAPTOP.md](LAPTOP.md), then verify review/approval below. Browser screen/microphone permission and the choice of shared surface are owner actions. Do not substitute a synthetic canvas test for a real permission/capture test.

```bash
./Playtest\ Demon.command --provider codex
# OR: ./Playtest\ Demon.command --provider claude --model sonnet
```

Use `--inbox /absolute/path` for a custom inbox. Open http://127.0.0.1:8800. If the port is occupied, identify the existing process before changing it. Only one desk may manage a given inbox.

- Confirm Live feed loads. Open analyst settings, refresh the installed CLI’s model list, and confirm the owner’s provider, model, and supported effort. Keep CLI default if preferred; do not silently substitute an unlisted saved model.
- Add a harmless test game by name on either device and verify it appears on the other. Select it on the phone; desktop selection filters the workspace independently.
- Explain Lookback: 0–30 seconds before the first press, 10 suggested to catch bugs noticed moments after they happen. Use 0 for no pre-roll. Change it before starting the session. The session must run long enough to fill the requested window.
- Ask the owner to record a harmless 5–10 second clip: Volume Up, describe one visible change request, then Volume Up again.
- Confirm the phone finishes sending and a card appears in Videos. New cards should continue appearing while another clip is analysed.
- Confirm the card moves through extraction, transcription and provider analysis to Ready to review, or shows a specific actionable error.
- Open Review. Confirm the selected game label, lookback/press timing, video playback, the spoken quote if audio is enabled, screenshots and editable fields.
- With the owner's test ticket, verify edit → approve → Approved batches → preview/copy. Copying does not submit the batch. To connect a game, verify `gh auth status`, paste its GitHub link, click **Check repository**, review the detected branch/checks and the owner's chosen fixing model, then **Connect game**. No local clone is required, and connecting does not execute project code or start a batch. For a separately authorized fixing run, follow [FIX-RUNS.md](FIX-RUNS.md): send an approved test batch and inspect its PR. Leave auto-merge off unless the owner opts in. Do not substitute another repo or publish unapproved findings.
- If Wi-Fi is desired, disconnect USB, approve the new phone pairing dialog on the Mac, and repeat. Some office Wi-Fi blocks local discovery; USB remains a valid fallback.
- Stop the test session on the phone. Explain how to start the next one.

For iOS verification, record a harmless spoken request with the system microphone enabled, AirDrop it, import the MOV in the desk, and verify transcription, review, approval and the batch. A synthetic MOV check is not a physical iPhone test.

## 7. Leave a clear handover

Give the owner the repository path, inbox path, chosen CLI/model, exact launch command and any unverified items. Opening Playtest Demon.app from Applications is the daily launch path and remembers provider/model settings. Closing its window keeps receiving; Cmd+Q stops it. For a source-only launch, keep Terminal open and use Ctrl+C to stop. The browser's Pause queue control is persistent and does not stop the receiver.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing CLI / sign-in banner | Run the selected CLI's login command in Terminal; make sure it is on PATH. Queue checks again automatically. |
| Model failure or usage limit | Read the card's error; choose a valid vision model or wait for account quota, then Retry. |
| No spoken quote | Check mic permission, `whisper-cli`, its model, and `QA_WHISPER_MODEL`. |
| App exits because port 8799 is occupied | Identify the listener and its exact inbox/parent before acting. Stop only a confirmed orphan receiver for this inbox; never kill an unrelated service. Upgrade to 0.6.5+ so managed receivers exit if their desk disappears. |
| No USB arrival | Mac/Android 0.6.1+, correct pairing code, `adb devices`, cable/authorization, receiver port 8799, `adb -s SERIAL reverse tcp:8799 tcp:8799`. |
| No Wi-Fi arrival | Correct pairing code and Mac/Android 0.6.1+, same trusted network, Mac firewall approval, phone-approval dialog, Bonjour allowed. Try USB. |
| Clip waits on phone | Keep Playtest Demon running and the Mac awake. The phone retries automatically. |
| Empty review | Videos may still be processing or the queue may be paused. Review has only unapproved drafts. |
| Interrupted fix run | Work stays in `AgentRuns/`. Recover publication for a verified commit, or return the requests to approval and start a new batch. Never rerun/publish silently. |
| No fixing PR | Check repository settings, GitHub login, test output and the run log. Failed checks or unaddressed requests stop publication. |
| Auto-merge refused | Require branch checks, enable repository auto-merge and check GitHub permissions. Do not bypass protections. |
| iPhone import fails | Trim below 10 min / 750 MB, use MOV/MP4, and verify ffmpeg. |
| Interrupted analysis | Restart Playtest Demon; working clips become queued. Check `.work/` logs if it repeatedly fails. |
| Python import error | Rerun `bash scripts/setup-mac.sh` and launch through Playtest Demon.command, which uses `.venv`. |

Data lives outside Git. Back up the inbox separately. Delete neither the inbox nor `~/.config/qa-clip/devices.json` as a troubleshooting shortcut.

Keep `~/.config/qa-clip/identity.json` with this laptop when updating. Never copy a receiver identity/pairing configuration into shared ZIPs or another tester’s installation.
## Phone-only recording and batch recipients

Android 0.7.0+ can use **Playtest mode → Record & share** without a laptop, Mac pairing or a CLI login on the phone. Keep the normal Android accessibility/microphone/screen-recording consent steps. Each session is saved on the phone; after stopping, **Share a saved batch** opens Android's share sheet. Large sessions have numbered parts. Never clear app data or uninstall to upgrade: the saved batches and unsent laptop clips would be lost.

The recipient needs Playtest Demon **Mac 0.7.0+**, ffmpeg and their chosen signed-in analyst CLI. Use **Import batch** with the shared ZIP; game names and Android reaction/lookback context come from the archive. The recipient's provider, model, queue pause and pairing configuration remain their own. Validate using a synthetic batch first. No recording is sent to an AI provider by exporting on the phone; analysis happens on the recipient's Mac after import (or after they resume a paused queue).
