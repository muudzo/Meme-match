#!/usr/bin/env python3
"""Publish an immutable app archive, then replace the signed update feed.

The private key stays in this Mac's login Keychain, never in GitHub or a file.
The feed changes only after the release's complete assets are publicly served.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "muudzo/Meme-match"
FEED_TAG = "desktop-updates"
SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def validate_feed(path, *, build, archive_url):
    feed = ET.parse(path)
    item = feed.find("./channel/item")
    if item is None or item.findtext(f"{{{SPARKLE}}}version") != build:
        raise RuntimeError("The generated feed does not describe this app build.")
    enclosure = item.find("enclosure")
    if enclosure is None or enclosure.get("url") != archive_url or not enclosure.get(f"{{{SPARKLE}}}edSignature"):
        raise RuntimeError("The feed is missing this immutable archive's URL or signature.")


def run(arguments, **kwargs):
    return subprocess.run([str(arg) for arg in arguments], check=True, **kwargs)


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/tates-cat":
        raise RuntimeError("Publishing is restricted to the tates-cat branch of the configured repository.")
    commit = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise RuntimeError("Expected a full commit SHA.")
    app = ROOT / "dist" / "Purrpose.app"
    with (app / "Contents" / "Info.plist").open("rb") as source:
        info = plistlib.load(source)
    build = info["CFBundleVersion"]
    if not build.isdecimal():
        raise RuntimeError("The build number must be numeric.")
    tag = f"desktop-{build}"
    archive_name = f"Purrpose-{build}-arm64.zip"
    release_directory = ROOT / "dist" / "release"
    # Each build gets its own directory; generate_appcast cannot pick a stale app.
    release_directory = release_directory / build
    release_directory.mkdir(parents=True, exist_ok=False)
    archive = release_directory / archive_name
    run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive])
    download_prefix = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    run([ROOT / "build/sparkle/bin/generate_appcast", "--account", "com.purrpose.desktop",
         "--download-url-prefix", download_prefix, "--maximum-deltas", "0", release_directory], timeout=180)
    feed = release_directory / "appcast.xml"
    validate_feed(feed, build=build, archive_url=download_prefix + archive_name)
    # Verify with the same Sparkle binary before making anything discoverable.
    run([ROOT / "build/sparkle/bin/sign_update", "--verify", "--account", "com.purrpose.desktop", feed], timeout=60)
    notes = release_directory / "notes.md"
    notes.write_text(f"Purrpose {info['CFBundleShortVersionString']} (build {build}), Apple silicon.\n\n"
                     f"Source: {commit}\n\nCamera starts paused after relaunch. "
                     "This personal build uses ad-hoc Apple code signing and signed Sparkle updates.\n")
    run(["gh", "release", "create", tag, archive, ROOT / "dist/Purrpose.dmg",
         "--repo", REPOSITORY, "--target", commit, "--title", f"Purrpose {info['CFBundleShortVersionString']} · {build}",
         "--notes-file", notes, "--latest=false"])
    existing = subprocess.run(["gh", "release", "view", FEED_TAG, "--repo", REPOSITORY],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if existing.returncode:
        run(["gh", "release", "create", FEED_TAG, "--repo", REPOSITORY, "--target", commit,
             "--title", "Purrpose automatic updates", "--notes", "Signed update feed for the desktop cat.", "--latest=false"])
    # One replace happens last. A stale cached feed still points to an intact,
    # immutable release, and an interrupted publication cannot point to no app.
    run(["gh", "release", "upload", FEED_TAG, feed, "--clobber", "--repo", REPOSITORY])
    print(f"Published {tag}; automatic update feed now points to build {build}.")


if __name__ == "__main__":
    main()
