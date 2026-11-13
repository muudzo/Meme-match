# Purrpose

A small desktop cat that reacts with you while you work. Activate it, leave it beside your other windows, and let its expressions and occasional gentle prompts remind you to check in with yourself.

Purrpose is a native, transparent, draggable desktop widget. It stays above ordinary application windows, uses the camera in the background while activated, and runs locally. You do not need to keep a browser or dashboard open.

## Install the desktop app

The macOS build is **`dist/Purrpose.dmg`**. Open the disk image, drag **Purrpose.app** to **Applications**, and open it. The standalone app includes Python, its camera dependencies, and the face model.

The current package is a local development build, signed ad hoc rather than notarized with an Apple Developer certificate. If macOS requires approval, review the app in **System Settings → Privacy & Security**. This build targets the architecture of the Mac that built it; the current development machine is Apple silicon.

Your cat starts asleep with the camera off. Click it to activate tracking, then allow camera access when macOS asks. Permission belongs to **Purrpose** when using the packaged app, or to your terminal/Python host when running the source.

## Use the widget

| Action | What happens |
| --- | --- |
| Click the sleeping cat | Activates background camera tracking |
| Click the active cat | Acknowledges a prompt and resets its reminder |
| Drag the cat | Moves it beside your work |
| Right-click the cat | Opens its controls |
| Use the menu-bar cat icon | Opens the same controls without finding the widget |
| **Pause camera** | Stops tracking and lets the cat sleep |
| **I'm here** | Dismisses a prompt and resets the check-in interval |
| **I drifted—reset** | Records your own acknowledgement that you drifted and resets the reminder |
| **Take a 5-minute break** | Pauses the camera and starts a rest countdown |
| **Snooze break reminder** | Delays it for five more minutes of work |
| **Reminder settings** | Adjusts the reminder interval and the cat's size in a native dialog |
| **Today's reflection** | Opens a native summary with report export |
| **Reset position** | Brings the cat back into view |
| **Quit** | Releases the camera and exits the app |

The cat mirrors visible facial reactions: smiles, raised eyebrows, a wink, an open mouth, lowered mouth corners, or sustained closed eyes. It also recognizes both hands: an open palm makes it wave, thumbs-up makes it cheer, a fist gets a paw bump, a peace sign gets a wink, and the I-love-you sign gets a heart. Keep your hand inside the camera's view and hold a gesture briefly. The caption shows the recognized cue; facial and body reactions can happen together.

Recognition runs at up to 12 frames per second with a short confirmation window, so brief reactions survive while single-frame noise is filtered out.

The cat can offer a soft check-in after a sustained visible cue or your chosen interval, with cooldowns between prompts. Clicking it is enough to acknowledge a prompt. No-face periods, stale camera observations, and paused tracking suppress cue-based prompts.

## Breaks and your daily reminder

After 25 minutes of active work, the cat offers a 5-minute break. This timer is independent of face detection, so looking away does not reset it. Click the break prompt to pause tracking and start the rest countdown, or right-click to snooze it for five minutes. When the rest ends, click the cat to reactivate tracking; the camera never restarts by itself. A sleeping computer is not counted as additional work time.

The daily reminder defaults to **16:20 in Europe/Amsterdam**, with the text **“4:20 — roll a joint.”** It works while camera tracking is paused and appears once per local day. Reminder settings let you edit its text and time or turn it off, as well as change the work/break durations. Purrpose must be running for reminders to appear. A short catch-up window handles waking or reopening the app near the scheduled time without showing stale reminders late at night.

**A prompt is an invitation to notice, not a verdict that you are distracted.** A camera cannot tell whether you are lost in thought, concentrating, or how you feel. Explicit **I drifted—reset** acknowledgements are your own reports; facial observations remain labeled as visible expressions.

The widget stays above ordinary windows. Other apps' exclusive fullscreen modes and operating-system surfaces may control which windows can appear over them. Purrpose does not install a login item or start the camera automatically when you sign in.

## Run from source

Use Python 3.12 and create a virtual environment in this checkout:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python fetch_models.py
.venv/bin/python desktop.py
```

The first model download installs both the face and hand models and needs an internet connection. Once installed, recognition works locally without an API key or cloud service. If the camera does not open, allow access in macOS camera settings and close another app using the webcam. Camera details shows the latest detected face and hand cue and reports a missing hand model explicitly.

For an isolated test diary:

```bash
.venv/bin/python desktop.py --data-dir /tmp/purrpose-test
```

The native entry point also provides `--self-test`, `--demo POSE`, and `--screenshot PATH` for no-camera verification and previews. See `.venv/bin/python desktop.py --help` for the current options.

## Build the installable app

Build on macOS using the environment above:

```bash
.venv/bin/python scripts/build_desktop.py --dmg
```

Outputs:

- `dist/Purrpose.app` — standalone desktop app.
- `dist/Purrpose.dmg` — drag-to-Applications disk image.

Omit `--dmg` to build only the app. Use `--dmg-only` to recreate the disk image from an existing app without rebuilding. The build script validates the app's camera permission metadata, accessory-app settings, bundled model, and code signature. It never installs dependencies or changes an app already in Applications.

The package uses a one-folder app bundle through [PyInstaller](https://pyinstaller.org/en/stable/spec-files.html). This retains the model and native camera/Qt libraries inside the application rather than requiring the source checkout at runtime. Build on the target Mac architecture; an Apple-silicon build is not presented as a universal Intel/ARM package.

## Local records and camera behavior

The native app stores settings and its diary under your macOS application-support directory, normally `~/Library/Application Support/Purrpose`. `--data-dir` overrides that location. Camera frames are processed in memory and discarded; photographs, video, and audio are not saved or uploaded.

The camera is active only after you activate the cat. It continues processing while you use other applications. Pausing or quitting stops the worker and releases the camera. Closing a reflection or settings dialog does not pause the cat.

Reflections summarize the records actually collected, distinguish visible expressions from your own check-ins, and leave camera gaps unobserved. They do not describe application usage, read your work, diagnose your mood, or claim to measure attention. Finder-launched app diagnostics are written to `~/Library/Logs/Purrpose/runtime.log`; model cache files use `~/Library/Caches/Purrpose`.

## Tests

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python desktop.py --self-test
```

The desktop tests cover camera activation and pause, transparent floating-window behavior, expression reactions, reminder cooldowns, stale/no-face observations, recognition stability, geometry, and local diary persistence. Automated tests use synthetic camera observations; live camera behavior requires a manual check after activation.

## Source layout

| File | Purpose |
| --- | --- |
| `desktop.py` | Native desktop cat, controls, dialogs, and application lifecycle |
| `desktop_behavior.py` | Expression reactions and gentle reminder timing |
| `desktop_reminders.py` | Work/rest countdowns and local-time daily reminders |
| `desktop_journal.py` | Local log of prompts, acknowledgements, and reported resets |
| `companion_camera.py` | Local MediaPipe camera worker |
| `companion_store.py` | Durable diary, settings, and reflection data |
| `recognition_state.py` | Stable signals and aspect-corrected geometry |
| `packaging/Purrpose.spec` | Standalone macOS app bundle configuration |
| `packaging/cat.svg` | Source icon used to generate the application icon |
| `scripts/build_desktop.py` | App icon, build, signature validation, and optional DMG |

## License

The source is MIT licensed; see [LICENSE](LICENSE). Qt, MediaPipe, OpenCV, and other bundled dependencies retain their own licenses. Meme images are not included in the desktop widget's application bundle.
