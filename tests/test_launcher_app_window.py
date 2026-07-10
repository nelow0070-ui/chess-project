import os
import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import launcher


class LauncherAppWindowTests(unittest.TestCase):
    def test_open_app_window_uses_browser_app_mode(self):
        url = "http://127.0.0.1:5000"
        executable = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

        with (
            mock.patch.object(launcher.sys, "platform", "win32"),
            mock.patch.object(
                launcher,
                "browser_app_candidates",
                return_value=[executable],
            ),
            mock.patch.object(launcher.os.path, "exists", return_value=True),
            mock.patch.object(launcher.subprocess, "Popen") as popen,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertTrue(launcher.open_app_window(url))

        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command, [executable, f"--app={url}", "--new-window"])

    def test_open_app_window_respects_browser_override(self):
        with (
            mock.patch.object(launcher.sys, "platform", "win32"),
            mock.patch.object(launcher, "browser_app_candidates") as candidates,
            mock.patch.dict(os.environ, {"CHECKSS_OPEN_BROWSER": "1"}, clear=True),
        ):
            self.assertFalse(launcher.open_app_window("http://127.0.0.1:5000"))

        candidates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
