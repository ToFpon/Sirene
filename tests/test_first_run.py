"""Premier lancement de Sirène installée : lancement à l'ouverture de session coché d'office, une seule fois.

    python3.12 -m unittest tests.test_first_run
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sirene-first-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")

from sirene import autostart, notify  # noqa: E402
from sirene.app import SireneApp  # noqa: E402
from sirene.settings import settings  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class FirstRunTest(unittest.TestCase):
    def test_once_and_only_installed(self):
        target = os.path.join(TMP, "autostart", "io.github.sirene.Sirene.desktop")
        with mock.patch.object(autostart, "path", lambda: target):
            app = SireneApp()
            with mock.patch.object(notify, "installed", lambda: False):
                app._first_run_autostart()
            self.assertFalse(autostart.enabled(), "lancée des sources : rien")
            with mock.patch.object(notify, "installed", lambda: True):
                app._first_run_autostart()
                self.assertTrue(autostart.enabled(), "premier lancement installée : coché")
                autostart.set_enabled(False)              # l'utilisateur le décoche
                app._first_run_autostart()
                self.assertFalse(autostart.enabled(), "décoché ensuite : il le reste")
            self.assertTrue(settings["autostart_offered"])


if __name__ == "__main__":
    unittest.main()
