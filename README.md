# 😈 Playtest Demon

**Play the game. Describe the change. Approve a request. Let your agent implement it in a PR. Playtest again.**

On Android, Playtest Demon keeps a configurable **0–30 second lookback** (10 seconds suggested) before you press Volume Up and keeps recording until you press it again. Your voice goes with the video. The Playtest Demon desktop app receives clips over USB or Wi-Fi, analyses them through **Codex CLI or Claude Code**, and turns findings into editable tickets.

**Previously called QA Clip / QA Desk / QA Demon.** Updates install over the existing Android app; keep your app data. Existing inboxes, pairing, and the `QA Desk.command` launcher continue to work.

**Laptop browser recorder · Android 10+ recorder · iPhone / iPad recording imports · macOS desk · Python 3.10+ · your own CLI login**

![The live video queue](docs/images/videos.png)

## The workflow

1. **Capture and speak.** On your laptop, click **Start playtest session**, paste the game link, share its tab/window and record your voice. **Start clip → Finish & send** includes the same 0–30 second lookback ([laptop guide](docs/LAPTOP.md)). On Android, start a Playtest Demon session on Android and play your game. Press **Volume Up** when you see something; press again to finish. **Volume Down** discards an active clip. On iPhone/iPad, record the screen with Microphone On, AirDrop to your Mac and use **Import recording** ([iOS guide](docs/IOS.md)).
2. **Follow the queue.** Videos appear automatically after transfer completes, even while another video is being analysed. The Live feed shows queued, extracting, transcribing, analysing, ready, and failed clips. Search by game, filter by status, pause the queue, or retry a failed clip.
3. **Review one ticket.** Watch the relevant moment, edit the finding, inspect screenshots, then approve, reject, or leave it for later. Edits save automatically. Approval and rejection have Undo.
4. **Run a batch.** Approved requests collect by game. Paste your GitHub game repository link, review the detected branch/checks and fixing CLI/model/effort, then click **Send batch to agent**. Each batch gets a fresh clone, a `playtest/…` branch, approved evidence, verification and a PR. Copy prompt remains available and does not submit or consume the batch.
5. **Merge and playtest again.** Follow progress and logs in **Fix runs**. Review the PR or opt this game into automatic merge through required GitHub checks. After merge, fixes appear in a playtest checklist. Choose **Verified in game** or **Still needs work** to reopen the request. [Fix-run guide](docs/FIX-RUNS.md) explains setup, limits and recovery.

![One ticket at a time](docs/images/review.png)

![Approved batches](docs/images/batches.png)

Analysis runs **one video at a time**, in arrival order. Receiving, queue updates, and ticket review continue independently. Quitting Playtest Demon stops processing; unfinished work is queued again on the next launch. Closing only its Mac window keeps it running. Pausing lets the current analysis finish and holds subsequent videos.

## Record on Android without a laptop

On Android **0.7.0 or newer**, choose **Playtest mode → Record & share**. No Mac pairing, Wi-Fi or CLI account is needed on the phone.

1. Choose your game and start a session. Approve Android screen recording and microphone access as usual.
2. Play and use **Volume Up** to start a clip, speak your feedback, then press it again to save. Lookback and **Volume Down** discard work as before.
3. Stop the session. Tap **Share a saved batch**, choose the session, then use Android’s share sheet to send its ZIP through Slack, email or another file-sharing app.
4. The recipient opens **Playtest Demon 0.7.0+ on their Mac**, clicks **Import batch**, and selects the ZIP. The game names, voice, build version and reaction/lookback timing travel with the recordings. Their configured analyst processes the clips through the normal review flow; a paused queue stays paused.

Each phone-only session is a separate batch. Saved batches survive restarts, remain on the phone after sharing and never enter the automatic Mac upload queue—even if you later pair a laptop or switch modes. Previously queued laptop-sync clips retain their original destination. The phone does not analyse recordings; the recipient needs the usual desktop tools and CLI login.

Batch ZIPs contain only recordings and their recording metadata, with no pairing keys, receiver identity or CLI settings. Import validates the whole batch before publishing it to the queue. Repeated or concurrent imports skip recordings already received; an explicitly reimported recording in trash becomes a new queue item. Limits: 100 clips / 2 GB per ZIP, 750 MB and 10 minutes per imported recording. Large sessions appear as numbered parts in the share picker; share and import each part. Share only recordings and microphone audio you intend the recipient to receive. Batches are kept in Android’s app storage and consume space until you remove the app’s data; the app does not automatically delete them after sharing.

## Install with your agent

Give Codex or Claude Code this prompt:

> Install Playtest Demon from https://github.com/guilhermea-infinity/playtest-demon on my Mac and Android phone. Read AGENTS.md and docs/INSTALL-AGENT.md first. Inspect existing tools and preserve my clips and settings. Ask which CLI and model I want to use, install the missing dependencies, download the current prebuilt Android APK (or build it if needed), and install it on my chosen USB-connected phone. Walk me through the Android permissions and verify a short test clip reaches Playtest Demon and becomes a reviewable ticket. Leave me the launch command and explain anything you could not verify.

The detailed [agent installation runbook](docs/INSTALL-AGENT.md) includes prerequisites, exact commands, human permission steps, verification, and recovery. iPhone/iPad imports use Apple’s built-in recorder; no iOS app installation is required. Windows and Linux desktops are not supported.

## Open it like a Mac app

Download the **macOS app / DMG** from [Releases](https://github.com/guilhermea-infinity/playtest-demon/releases). Open the DMG, drag **Playtest Demon.app** into **Applications**, and double-click it. The desk opens in its own window with a Dock icon; no Terminal command or browser tab is required for daily use.

The app includes Python, Pillow and jsonschema. On a new Mac, ffmpeg, whisper with its voice model, the chosen CLI/login, and GitHub/Android tools still need the [initial setup](docs/INSTALL-AGENT.md). The current downloadable app is for **Apple Silicon, macOS 14+**; Intel users can build it on an Intel Mac using the packaging script below. It is locally signed; another Mac may need **System Settings → Privacy & Security → Open Anyway** because it is not Apple-notarized.

Close the window to keep receiving in the background; click the Dock icon to bring it back. **⌘Q / Playtest Demon → Quit** stops the desk and its receiver. The app warns about in-progress work and unsaved edits. Use its menu to open the inbox, logs or browser version. Logs live in `~/Library/Logs/Playtest Demon/`; data remains in `~/Desktop/QA-Inbox` and existing phone pairing/model choices are reused.

## Playtest a browser game on your laptop

![Laptop playtest session setup](docs/images/laptop.png)

Click **Start playtest session** in Live feed. It opens a recorder page in your default browser. Choose a game (or type a new one), paste the game URL, and use **Open game**. Start the session and choose the game tab/window in the sharing prompt. Voice is enabled by default; the 10-second suggested lookback catches the bug before you react.

Use **Start clip**, describe the change, then **Finish & send**. Clips go straight into the same analysis → human review → approved batch flow. **Float controls** keeps the buttons above the game where Document Picture-in-Picture is available (tested in Chrome). Otherwise keep the recorder window beside the game. Controls and the ⌥⇧C shortcut work in the recorder/floating window, not globally inside a game tab. No extension or Android phone is required.

Each tester currently needs their own running local Playtest Demon installation and CLI sign-in. This is local recording/analysis, not a hosted collection link. The Mac desk is still macOS-only, even though the recording UI uses browser APIs. See [laptop setup, privacy, limits and testing](docs/LAPTOP.md).

## Manual quick start (source / agents)

```bash
git clone https://github.com/guilhermea-infinity/playtest-demon.git
cd playtest-demon
bash scripts/setup-mac.sh --brew
```

This uses Homebrew for Python, ffmpeg, whisper.cpp, GitHub CLI, Java 21 and Android platform tools, and creates an isolated `.venv`. Install [Homebrew](https://brew.sh/) first if needed. For laptop-only use, run `bash scripts/setup-mac.sh --brew --laptop` to skip Android tools. For iOS-only use, run `bash scripts/setup-mac.sh --brew --ios` to skip Android tools. Without `--brew`, the script installs only the Python dependencies.

Install and sign in to **one** provider:

```bash
# OpenAI / ChatGPT through Codex CLI
npm install -g @openai/codex
codex login

# Or Claude Code
npm install -g @anthropic-ai/claude-code
claude auth login
```

The npm commands require Node.js; `brew install node` if absent. See the [Codex CLI documentation](https://developers.openai.com/codex/cli/) and [Claude Code setup](https://code.claude.com/docs/en/setup) for other installation methods.

Launch your chosen provider:

```bash
./Playtest\ Demon.command --provider codex
# or
./Playtest\ Demon.command --provider claude --model sonnet
```

The source launcher opens **http://127.0.0.1:8800** and keeps its Terminal window open. For daily use, open **Playtest Demon.app** from Applications instead. Stop a source-launched desk once before switching to the app so the app can own the background service.

**Choose a model:** open analyst settings at the top right. Playtest Demon reads the installed CLI’s model catalog and shows each model’s supported reasoning efforts. Choose **Use CLI configured default** to keep your CLI configuration, or select a listed model and effort. **Refresh models** reloads the catalog (normally cached for five minutes). Models and capabilities vary by CLI version and account; a catalog entry is not a guarantee of quota or access. Discovery does not send a clip or inference prompt. If discovery fails, the page explains why and preserves your saved choice. Settings apply to the next video; the current analysis keeps its original provider, model, and effort. No API key is needed with supported subscription login.

**Choose a game:** on Android, tap the game name; use **+ Add game**, type one name, and you’re done. The Mac has the same quick-add flow. Names sync with your paired Mac over USB or Wi-Fi, and phone additions work offline. The phone’s selected game labels new clips; **Detect automatically** uses the foreground app’s name. Playtest Demon’s game picker filters videos, reviews, and handoffs without stopping the queue or changing the phone’s selection. Existing clips keep their original attribution.

**Catch bugs after they happen:** the phone’s **Lookback** slider keeps 0–30 seconds before the first Volume Up press. **10 seconds is suggested** because it gives you time to notice a bug and react, without adding too much footage. This can capture a one-off bug you cannot reproduce. Set 0 to start recording only when you press; longer windows use more memory. Lookback starts buffering only after screen-sharing consent and stops with the session. Change it before starting a session. The actual lead-in may be shorter just after starting, or slightly longer to begin on a playable video keyframe.

### Enable voice transcription

Voice is transcribed locally by whisper.cpp before analysis. Install a multilingual model for your preferred balance of speed and accuracy:

```bash
mkdir -p "$HOME/.cache/whisper"
curl -fL --retry 3 \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin \
  -o "$HOME/.cache/whisper/ggml-small.bin"
```

This downloads roughly 466 MB. Alternatively set `QA_WHISPER_MODEL=/absolute/path/to/ggml-model.bin`. Existing medium/small models in the documented cache locations are detected automatically. Without whisper or its model, visual analysis still works, but spoken instructions are unavailable to the analyst.

### Install on Android

For a prebuilt APK, download it from [Releases](https://github.com/guilhermea-infinity/playtest-demon/releases), verify the published SHA-256, and put it in `out/`. Or build locally:

1. Install Android Studio, then SDK Platform **36** and Build Tools **35.0.0** in SDK Manager. Java 21 was installed by the setup script.
2. Set `ANDROID_HOME` if the SDK is not at `~/Library/Android/sdk`.
3. On your phone, enable Developer options and USB debugging. Connect by USB and approve the computer's debugging prompt.

```bash
./build.sh
./mac/install-phone.sh
# With multiple phones: ./mac/install-phone.sh SERIAL
```

On the phone:

- On the Mac, click **Pair Android**. On the phone, tap **Mac · tap to pair** and enter this laptop’s code. Each coworker uses their own laptop’s code.
- Enable **Playtest Demon volume buttons** in Accessibility settings. If blocked for a sideloaded app, use Settings → Apps → Playtest Demon → ⋮ → **Allow restricted settings**, then return to Accessibility.
- Allow microphone access and notifications when requested.
- Choose a game and your lookback window (10 seconds suggested).
- Tap **Start session** and approve Android's screen-sharing prompt. Choose the whole screen when Android offers a choice.
- Open your game. Press Volume Up to start a clip, speak about the issue, and press Volume Up again to send it.

First click **Pair Android** on your Mac, then tap **Mac · tap to pair** on the phone and enter that Mac’s eight-character code. Install **0.6.1 or newer on both the Mac and Android phone**; earlier phone versions cannot safely share an office network. The phone uses Bonjour, its saved address or USB (`adb reverse`) only to locate that same pinned Mac identity. It never falls back to a colleague’s laptop. A new Wi-Fi phone still requires approval on its chosen Mac; USB approval is automatic only after the destination matches. Already addressed clips retain their original Mac when pairing changes. Old unaddressed clips are assigned only when the owner explicitly enters a pairing code. Clips wait on the phone if its paired Mac is offline, and only become sent after the Mac acknowledges the complete transfer. The last 20 sent clips remain on the phone.

## Recovery and duplicates

A recording’s trash button moves it and its requests out of the queue. **History & trash → Restore recording** brings them back; files remain on disk. Evidence used by a submitted batch cannot be trashed. Trash does not free disk space; back up and manage the inbox separately.

Review highlights likely repeat requests. **Link duplicate** removes the extra finding from approval while preserving its observation and screenshots. Approved batches include linked evidence. **Separate / restore** reverses the link. Suggestions need human judgment and do not silently discard tickets. Exact repeated imports and Android transfer retries are deduplicated automatically. Redo requires a correction and preserves approved requests; a submitted batch is locked.

The feed distinguishes **Desk online**, **receiver ready**, and the last authenticated **phone contact**. A ready receiver alone does not mean a phone is connected. Estimates use the median of recent completed analyses, appear after three samples, and show a range rather than a promise.

## Review controls

### Share feedback with your team

Click **Share feedback** at the top of the workspace to export feedback for the selected game (or all games). **Share feedback** on an approved-batch card selects that game’s approved requests, even when the game picker is set to All games. **Share request** on a review ticket selects that finding. Choose which requests to include; approved requests are selected initially when available, and drafts are clearly labelled **not yet approved**.

Use **Copy for Slack** for a short message: the game name and one bullet per finding. Drafts are labelled. Use **Download ZIP** for the full observations, expected behavior, reproduction steps, acceptance criteria and evidence, then attach the ZIP to your Slack message. The Mac app offers a save dialog; the browser version downloads the file. Sharing does not post to Slack or change ticket approvals, batches or fix runs.

Your teammate extracts the ZIP and opens **report.html** in a browser. No Playtest Demon installation, login or connection to your Mac is required. The archive also includes **feedback.md**, **slack.txt**, selected screenshots and, by default, recordings. Turn off **Include video recordings** for a smaller attachment. Recordings shared by multiple requests appear once. Dropped screenshots are excluded, and missing evidence is listed in the report. Only select feedback and recordings you intend to share; the recordings retain their audio.

| Action | Control |
| --- | --- |
| Approve and move on | **A**, or **⌘ Enter / Ctrl Enter** while editing |
| Reject | **R**, with Undo |
| Leave for later | **L** |
| Move between tickets | Previous / Next |
| Reanalyse with a correction | “Redo this clip with a hint” |
| Inspect a screenshot | Click it; Escape closes it |
| Remove a screenshot from the handoff | Drop, or Use to restore |

Letter shortcuts only operate in Review, outside text fields and dialogs. Redo replaces that clip's unapproved drafts while preserving already approved tickets.

## Commands and diagnostics

```bash
.venv/bin/python scripts/doctor.py --provider codex
.venv/bin/python mac/qa-desk.py --help
.venv/bin/python -m unittest discover -s tests -v
```

| Option | Effect |
| --- | --- |
| `--provider claude\|codex` | Select and save a provider; resets the model to CLI default unless supplied |
| `--model MODEL` | Select and save an explicit model; `--model ""` restores CLI default |
| `--inbox DIR` | Use a different data directory |
| `--paused` | Start receiving without starting new analyses |
| `--from-now` | Skip previously unseen clips already in the inbox; does not erase existing work |
| `--no-inbox` | Use an independently running receiver |
| `--port N` | Change the local review port (default 8800) |
| `--no-open` | Start without opening a browser |

A failed analysis shows its error and a Retry button. If sign-in expires, clips wait until the selected CLI is signed in. Unknown models and quota errors remain visible rather than silently falling back to another provider. Full CLI output and extracted evidence are retained in `Tickets/.work/` for diagnosis.

## Files, privacy, and backup

Code and data live separately:

```text
playtest-demon/
  android/                Java Android recorder (no third-party app libraries)
  mac/                    receiver, queue, analyst, server, UI
  mac/prompts/            ticket and handoff instructions
  scripts/                setup and prerequisite checker
  tests/                  queue, provider, review and HTTP regression tests
  docs/INSTALL-AGENT.md   complete installation runbook
  out/                    locally built APKs (ignored by Git)

~/Desktop/QA-Inbox/
  <Game>/                 videos and metadata
  inbox.jsonl             completed clip arrivals
  Tickets/clips.json      durable queue
  games.json              shared game names (phone + Mac)
  Tickets/settings.json   provider, model, effort and pause preference
  Tickets/<ID>/           ticket.json and screenshots
  Tickets/.work/          extracted frames, transcript, prompt, provider output
  Handoffs/               earlier saved prompts
  Imports/                imported iOS/desktop recordings
  Tickets/repositories.json game-to-repository and fixing-agent settings
  Tickets/runs.json       durable batch lifecycle and PR status
  AgentRuns/<RUN-ID>/     approved snapshot, isolated clone, logs and PR body
  .receiver.json          last authenticated Android contact (no pairing keys)
```

Approved Wi-Fi phone keys are stored in `~/.config/qa-clip/devices.json`. The stable per-laptop receiver identity and pairing code live in `~/.config/qa-clip/identity.json`. Preserve both during upgrades, and never copy them to a colleague’s installation or include them in a shared app/archive. CLI credentials remain in each CLI's own storage. **Do not commit inbox data, pairing keys, credentials, APK signing keys, or machine-specific SDK paths.** The repository's `.gitignore` excludes generated files and local configuration; your inbox needs its own backup.

Videos are transferred locally over plain HTTP; use trusted Wi-Fi or USB. The review server only listens on loopback. **Selected frames, transcript and ticket context are sent to the chosen AI provider through its CLI**, under that provider's terms and account settings. Codex runs in its read-only sandbox; Claude gets only Read and Glob tools. Model output is validated before ticket generation. Copying a prompt leaves its tickets approved. **Send batch to agent** runs the selected fixing CLI locally and publishes changes to the connected GitHub repository as a PR; it does not create GitHub issues. Evidence is copied into an ignored run workspace for the agent and removed before the commit. Credentials are not copied into the batch. Repo scripts and verification commands run on your Mac: connect a repository you trust. See [fix-run boundaries](docs/FIX-RUNS.md). Earlier handed-off prompts remain in History and can be returned to approval.

## Current limits

- The Android recorder requires Android 10 or newer. Volume-button capture was originally tested on an OPPO A16 / Android 11. Other manufacturers may intercept the buttons differently.
- Android requires screen-sharing consent each session. On Android 15+, locking the phone ends capture.
- Captures use the session's initial size/orientation, at 720 px wide in portrait. Start the session in the game's orientation; rotation during recording can letterbox the video.
- Android clips cap at three minutes. iOS/imported clips cap at 10 minutes and 750 MB; trim long sessions in Photos first. iOS imports have no rolling lookback or hardware-button trigger. Android Audio is from the microphone; game audio is not captured.
- Screens are analysed as sampled frames plus a transcript, not as native video input. Brief animation or timing bugs may be missed and should be checked by the reviewer.
- One analysis at a time. Long clips and local transcription can take several minutes; provider runs time out after 15 minutes.
- Builds are debug APKs for sideloading, not Play Store releases. Locally built APKs use your machine's debug signing key. A signature mismatch must not be “fixed” by uninstalling without the owner's approval; uninstalling deletes phone-side clips.

## Build the Mac app

On a Mac with Xcode command-line tools installed:

```bash
.venv/bin/python -m pip install -r requirements-mac-build.txt
.venv/bin/python scripts/package-mac.py
```

The output is `out/mac/Playtest Demon.app`, an architecture-named ZIP and a drag-to-Applications DMG. The app runs independently of the source folder and `.venv`; it packages only code/runtime, with no inbox, CLI credentials, phone keys or signing secrets. It is ad-hoc signed for local use; Developer ID signing/notarization needs your Apple developer identity. Build on each target Mac architecture. Packaging requires Python 3.10+ and a Python runtime compatible with macOS 14+.

## Development

For a synthetic UI demo without provider usage, run `.venv/bin/python scripts/demo.py --inbox /tmp/qa-clip-demo`, then `./Playtest\ Demon.command --inbox /tmp/qa-clip-demo --no-inbox --paused --port 8812`. Use a fresh directory; the demo never overwrites an existing inbox.

Read [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md). CI runs the Python regression tests, validates frontend JavaScript syntax and builds the Android APK. The [architecture guide](docs/ARCHITECTURE.md) explains the transfer protocol and lifecycle.

MIT license for project code. The Gradle wrapper retains its original Apache-2.0 notices.
