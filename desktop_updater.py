"""Small Objective-C bridge to Sparkle's native, signature-verifying updater.

Only packaged macOS applications start the updater. Source previews and camera
tests never load it or contact the update service. Sparkle owns downloading,
verification, installation, preferences, and relaunching; Python never replaces
an installed bundle itself.
"""
import ctypes
from pathlib import Path
import plistlib
import sys


def bundle_for_executable(executable):
    path = Path(executable)
    if path.parent.name != "MacOS" or path.parent.parent.name != "Contents":
        return None
    return path.parent.parent.parent


class DesktopUpdater:
    def __init__(self):
        self.controller = None
        self.error = None
        self._started = False
        if sys.platform != "darwin" or not getattr(sys, "frozen", False):
            return
        bundle = bundle_for_executable(sys.executable)
        if bundle is None:
            self.error = "The app bundle could not be located."
            return
        try:
            with (bundle / "Contents" / "Info.plist").open("rb") as source:
                info = plistlib.load(source)
            if not info.get("SUFeedURL") or not info.get("SUPublicEDKey"):
                return  # A deliberate local build without update support.
            self.framework = ctypes.CDLL(str(bundle / "Contents" / "Frameworks" / "Sparkle.framework" / "Sparkle"))
            self.objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
            self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
            self.objc.objc_getClass.restype = ctypes.c_void_p
            self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
            self.objc.sel_registerName.restype = ctypes.c_void_p
            self._get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", self.objc))
            self._bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", self.objc))
            self._void = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", self.objc))
            self._action = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", self.objc))
            initialize = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", self.objc))
            cls = self.objc.objc_getClass(b"SPUStandardUpdaterController")
            if not cls:
                raise RuntimeError("Sparkle's updater class is unavailable.")
            instance = self._get(cls, self._selector("alloc"))
            self.controller = initialize(instance, self._selector("initWithStartingUpdater:updaterDelegate:userDriverDelegate:"), False, None, None)
            if not self.controller:
                raise RuntimeError("Sparkle could not initialize the updater.")
        except (OSError, ValueError, RuntimeError, plistlib.InvalidFileException) as exc:
            self.error = str(exc)

    def _selector(self, name):
        return self.objc.sel_registerName(name.encode("ascii"))

    def start(self):
        if self.controller and not self._started:
            self._started = True
            self._void(self.controller, self._selector("startUpdater"))

    @property
    def can_check(self):
        if not self.controller or not self._started:
            return False
        updater = self._get(self.controller, self._selector("updater"))
        return bool(self._bool(updater, self._selector("canCheckForUpdates")))

    def check(self):
        if self.can_check:
            self._action(self.controller, self._selector("checkForUpdates:"), None)
