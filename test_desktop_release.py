"""A bad appcast must never replace the feed used by installed applications."""
from pathlib import Path
import tempfile
import unittest

from scripts.publish_desktop import SPARKLE, validate_feed


class DesktopReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "appcast.xml"
        self.addCleanup(self.directory.cleanup)

    def write(self, version="111", url="https://example.com/app.zip", signature="signature"):
        self.path.write_text(f'<rss xmlns:sparkle="{SPARKLE}"><channel><item>'
                             f'<sparkle:version>{version}</sparkle:version>'
                             f'<enclosure url="{url}" sparkle:edSignature="{signature}" />'
                             '</item></channel></rss>')

    def test_exact_archive_and_version_are_required(self):
        self.write()
        validate_feed(self.path, build="111", archive_url="https://example.com/app.zip")
        for version, url in [("112", "https://example.com/app.zip"), ("111", "https://example.com/missing.zip")]:
            with self.assertRaises(RuntimeError):
                validate_feed(self.path, build=version, archive_url=url)

    def test_unsigned_enclosure_is_rejected(self):
        self.write(signature="")
        with self.assertRaises(RuntimeError):
            validate_feed(self.path, build="111", archive_url="https://example.com/app.zip")
