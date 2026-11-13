"""Updater boundaries must not start native UI or network requests in tests."""
from pathlib import Path
import unittest
from unittest.mock import patch

from desktop_updater import DesktopUpdater, bundle_for_executable


class DesktopUpdaterTests(unittest.TestCase):
    def test_bundle_discovery_requires_macos_bundle_structure(self):
        self.assertEqual(bundle_for_executable("/Applications/Purrpose.app/Contents/MacOS/Purrpose"),
                         Path("/Applications/Purrpose.app"))
        self.assertIsNone(bundle_for_executable("/usr/bin/python3"))

    def test_source_run_never_loads_native_framework(self):
        with patch("desktop_updater.ctypes.CDLL") as load, patch("desktop_updater.sys.frozen", False, create=True):
            updater = DesktopUpdater()
            updater.start()
            updater.check()
            self.assertFalse(updater.can_check)
            load.assert_not_called()

    def test_non_mac_package_does_not_load_framework(self):
        with patch("desktop_updater.sys.platform", "linux"), patch("desktop_updater.sys.frozen", True, create=True), patch("desktop_updater.ctypes.CDLL") as load:
            self.assertFalse(DesktopUpdater().can_check)
            load.assert_not_called()
