#!/usr/bin/env python3
"""Install a repository-scoped GitHub runner as the current, non-root user.

Run with Python 3.12+. Uses gh's existing login, or a short-lived registration
token on stdin (--token-stdin). Never supplies tokens in process arguments.
Linux service installation uses sudo only to install a systemd unit whose
process runs as this user. macOS uses a per-user LaunchAgent.
"""
import argparse
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

REPOSITORY = "muudzo/Meme-match"
VERSION = "2.338.2"
PACKAGES = {
    ("Darwin", "arm64"): ("osx-arm64", "25a065af409ffa317ab4d5a3b614dd15fc9c40f2172bc1b35a1b1258e919a388"),
    ("Linux", "x86_64"): ("linux-x64", "baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.home() / "purrpose-runner")
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--no-service", action="store_true")
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Run as the dedicated runner user, never root.")
    system = platform.system()
    package, checksum = PACKAGES[(system, platform.machine())]
    directory = args.directory.expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if not (directory / "config.sh").exists():
        if any(directory.iterdir()):
            parser.error("The destination contains files but no runner; choose an empty directory.")
        url = f"https://github.com/actions/runner/releases/download/v{VERSION}/actions-runner-{package}-{VERSION}.tar.gz"
        print(f"Downloading official runner {VERSION} ({package})", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise RuntimeError("Runner checksum mismatch; refusing to unpack.")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(directory, filter="data")
    if not (directory / ".runner").exists():
        if args.token_stdin:
            import sys
            token = sys.stdin.read().strip()
        else:
            result = subprocess.run(["gh", "api", "--method", "POST", f"repos/{REPOSITORY}/actions/runners/registration-token"],
                                    check=True, text=True, capture_output=True)
            token = json.loads(result.stdout)["token"]
        if not token:
            raise RuntimeError("No registration token supplied.")
        environment = dict(os.environ, ACTIONS_RUNNER_INPUT_TOKEN=token)
        subprocess.run(["./config.sh", "--unattended", "--url", f"https://github.com/{REPOSITORY}",
                        "--name", "purrpose-mac-arm64" if system == "Darwin" else "purrpose-linux",
                        "--labels", "purrpose-mac" if system == "Darwin" else "purrpose-tests",
                        "--work", "_work"], cwd=directory, env=environment, check=True)
        del environment["ACTIONS_RUNNER_INPUT_TOKEN"]
        token = None
    else:
        configuration = json.loads((directory / ".runner").read_text())
        if configuration.get("gitHubUrl", "").rstrip("/") != f"https://github.com/{REPOSITORY}":
            raise RuntimeError("This runner is already registered to a different repository.")
    if not args.no_service:
        prefix = ["sudo", "-n"] if system == "Linux" else []
        if not (directory / ".service").exists():
            subprocess.run(prefix + ["./svc.sh", "install"] + ([getpass.getuser()] if system == "Linux" else []),
                           cwd=directory, check=True)
        subprocess.run(prefix + ["./svc.sh", "start"], cwd=directory, check=True)
        subprocess.run(prefix + ["./svc.sh", "status"], cwd=directory, check=True)
    print(f"Runner ready in {directory}. Work is limited by .github/workflows/desktop.yml.")


if __name__ == "__main__":
    main()
