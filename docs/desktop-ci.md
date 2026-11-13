# Desktop CI and automatic updates

Push working desktop changes to `tates-cat` on `muudzo/Meme-match`. The workflow
tests the camera logic and reminders, builds and smoke-tests the macOS bundle,
then publishes an immutable ZIP and DMG plus a signed Sparkle appcast.
`main` and pull requests never trigger these self-hosted jobs.

The build runner is this Apple-silicon Mac, registered as `purrpose-mac-arm64`,
with label `purrpose-mac`. It lives in `~/purrpose-runner`, uses its own checkout,
and starts through a user LaunchAgent when you log in. Keep the Mac awake and
logged in during a release. A sleeping or offline Mac leaves jobs queued;
an interrupted job may need rerunning from GitHub Actions.
The Mac jobs select its existing pyenv Python 3.12.10 explicitly; they do not
depend on your interactive terminal's selected Python version.

Tests initially run on the Mac too. Once the Linux runner is registered, set
the repository variable `PURRPOSE_TEST_RUNNER` to `purrpose-tests`. The build
still runs on the Mac; Linux cannot package this macOS app.

## Linux runner

The intended host is `192.168.2.28`. SSH authentication must work before setup.
Use a non-root account with Python 3.12+, Git, and GitHub runner's Linux system
dependencies installed. Do not run the worker itself as root.

Copy `scripts/install_runner.py` to the server. Either authenticate `gh` there,
or supply a fresh repository registration token through stdin using
`--token-stdin`; do not put a PAT or registration token in a command argument.
Run the installer as the worker user. It verifies the official runner archive,
registers the `purrpose-tests` label, and uses passwordless `sudo -n` only to
install/start the systemd service under that user. If that service permission
is unavailable, use `--no-service` and have the administrator install the
service explicitly. A registration token expires after one hour.

After GitHub reports the Linux runner online, run from an authenticated Mac:

```sh
gh variable set PURRPOSE_TEST_RUNNER --repo muudzo/Meme-match --body purrpose-tests
```

The installer currently supports Apple-silicon macOS and x86-64 Linux. Add a
separately verified official runner checksum before using another architecture.

## Update signing and installation

Sparkle 2.10.1 is fetched from its official release with a pinned SHA-256.
Its framework, license, and updater helpers are bundled in the app.
`packaging/updates.json` contains only the public signing key and feed URL.
The private key remains in this Mac's login Keychain under the account
`com.purrpose.desktop`. No private key is committed, exported, or uploaded to
GitHub. Sparkle's `generate_appcast` and `sign_update` tools need Keychain
access; approve their native macOS prompts once. A locked or inaccessible
Keychain stops publishing rather than producing unsigned updates.

Keep a secure Keychain backup. Losing the signing key prevents existing cats
from trusting future releases. Do not regenerate it for each build.

Installed 0.2 builds need a one-time replacement with the updater-enabled app.
After that, Sparkle checks over HTTPS every hour, verifies the signed feed and
archive before extraction, and downloads updates automatically. Background
installation normally completes when the app quits; use the cat's **Check for
updates…** menu to check and install immediately. Your camera starts paused
after a relaunch, and the diary and settings stay outside the app bundle.

Sparkle signatures protect automatic updates. The personal macOS bundle still
uses ad-hoc Apple code signing; Developer ID signing and Apple notarization
have not been configured.

## Manual verification and recovery

```sh
.venv/bin/python scripts/fetch_sparkle.py
.venv/bin/python scripts/build_desktop.py --updates --dmg
dist/Purrpose.app/Contents/MacOS/Purrpose --self-test
gh run list --repo muudzo/Meme-match --branch tates-cat
```

Build numbers increase with the workflow run and attempt. Every app archive
gets a separate `desktop-N` release. Publishing changes the stable
`desktop-updates/appcast.xml` asset last, after its archive has been published.
A failed build leaves the previous update available. To revert a broken app,
revert its source on `tates-cat` and push; CI publishes that code with a newer
build number so installed cats can accept the correction.

Manage the Mac runner with `cd ~/purrpose-runner` followed by `./svc.sh status`,
`./svc.sh stop`, or `./svc.sh start`. To remove it, stop/uninstall its service,
then use GitHub's runner removal flow and `./config.sh remove`. Never expose a
self-hosted runner to untrusted pull-request code: it has the permissions of
its local account.
