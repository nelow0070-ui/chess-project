import re
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import APP_VERSION


class VersionConsistencyTests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        installer = (PROJECT_DIR / "installer" / "checkss.iss").read_text(
            encoding="utf-8"
        )
        build_script = (PROJECT_DIR / "build-installer.ps1").read_text(
            encoding="utf-8"
        )
        readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")

        installer_version = re.search(
            r'#define MyAppVersion "([^"]+)"',
            installer,
        )
        build_version = re.search(
            r'\$appVersion = "([^"]+)"',
            build_script,
        )

        self.assertIsNotNone(installer_version)
        self.assertIsNotNone(build_version)
        self.assertEqual(installer_version.group(1), APP_VERSION)
        self.assertEqual(build_version.group(1), APP_VERSION)
        self.assertIn(
            f"release\\checkss-Setup-{APP_VERSION}.exe",
            readme,
        )
        self.assertIn(
            "release\\checkss-Setup-$appVersion.exe",
            build_script,
        )


if __name__ == "__main__":
    unittest.main()
