"""Lancement à l'ouverture de session : fichier .desktop écrit puis retiré.

    python3.12 -m unittest tests.test_autostart
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sirene import autostart  # noqa: E402


class AutostartTest(unittest.TestCase):
    def test_write_and_remove(self):
        tmp = tempfile.mkdtemp()
        target = os.path.join(tmp, "autostart", "io.github.sirene.Sirene.desktop")
        try:
            with mock.patch.object(autostart, "path", lambda: target):
                self.assertFalse(autostart.enabled())
                autostart.set_enabled(True)
                self.assertTrue(autostart.enabled())
                text = open(target, encoding="utf-8").read()
                self.assertIn("--background", text)
                self.assertIn("bin/sirene", text, "lancé depuis les sources : le lanceur du dépôt")
                autostart.set_enabled(False)
                self.assertFalse(autostart.enabled())
                autostart.set_enabled(False)                # déjà retiré : rien
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
