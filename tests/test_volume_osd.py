"""Affichage du volume : lecture de pactl (faux pactl) et commande de l'extension Custom OSD (vrai schéma
compilé dans un dossier jetable, réglages en mémoire).

    python3.12 -m unittest tests.test_volume_osd
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gi.repository import Gio, GLib  # noqa: E402

from sirene import volume_osd  # noqa: E402

SCHEMA = """<schemalist><schema id="org.gnome.shell.extensions.custom-osd"
 path="/org/gnome/shell/extensions/custom-osd/"><key type="s" name="showosd"><default>''</default></key>
</schema></schemalist>"""

FAKE_PACTL = """#!/bin/bash
# faux pactl : « subscribe » rejoue des événements, « get-sink-volume » lit le volume dans un fichier
if [ "$1" = subscribe ]; then
  [ "$LC_ALL" = C ] || echo "Événement « change » sur destination #57"
  while true; do
    if [ -f "$DIR/event" ]; then cat "$DIR/event"; rm -f "$DIR/event"; fi
    sleep 0.05
  done
fi
echo "Volume: front-left: 45000 / $(cat "$DIR/vol")% / -9.60 dB,   front-right: 45000 / $(cat "$DIR/vol")% / -9.60 dB"
"""


def pump(cond, timeout=5):
    ctx, end = GLib.MainContext.default(), time.time() + timeout
    while time.time() < end and not cond():
        ctx.iteration(False)
        time.sleep(0.005)
    return cond()


class FormatTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(volume_osd.parse_volume("Volume: front-left: 45000 /  69% / -9.60 dB"), 69)
        self.assertIsNone(volume_osd.parse_volume(""))

    def test_command(self):
        cmd = volume_osd.osd_command("audio-headphones-symbolic", "Buds, Pro", 150)
        _rand, icon, text, level = cmd.split(",")
        self.assertEqual((icon, text, level), ("audio-headphones-symbolic", "Buds  Pro", "1.00"),
                         "virgule retirée (l'extension découpe), niveau plafonné à 100 %")


class OsdSettingsTest(unittest.TestCase):
    def test_schema_from_extension_folder(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, "custom-osd.gschema.xml"), "w") as fh:
                fh.write(SCHEMA)
            subprocess.run(["glib-compile-schemas", tmp], check=True)
            saved = volume_osd.SCHEMA_DIRS
            volume_osd.SCHEMA_DIRS = lambda: ["/nulle/part", tmp]
            try:
                s = volume_osd.osd_settings(Gio.memory_settings_backend_new())
                self.assertIsNotNone(s)
                s.set_string("showosd", "1,icon,Buds,0.42")
                self.assertEqual(s.get_string("showosd"), "1,icon,Buds,0.42")
            finally:
                volume_osd.SCHEMA_DIRS = saved
        finally:
            shutil.rmtree(tmp)

    def test_absent(self):
        saved = volume_osd.SCHEMA_DIRS
        volume_osd.SCHEMA_DIRS = lambda: ["/nulle/part"]
        try:
            self.assertIsNone(volume_osd.osd_settings())
        finally:
            volume_osd.SCHEMA_DIRS = saved


class WatcherTest(unittest.TestCase):
    def test_only_real_changes(self):
        tmp = tempfile.mkdtemp()
        try:
            pactl = os.path.join(tmp, "pactl")
            with open(pactl, "w") as fh:
                fh.write(FAKE_PACTL)
            os.chmod(pactl, os.stat(pactl).st_mode | stat.S_IEXEC)
            os.environ["DIR"] = tmp
            with open(os.path.join(tmp, "vol"), "w") as fh:
                fh.write("69")
            seen = []
            w = volume_osd.VolumeWatcher(seen.append, pactl=pactl)
            w.start()
            self.assertTrue(pump(lambda: w.last == 69), "volume de départ lu")
            self.assertEqual(seen, [], "pas d'affichage au démarrage")

            def event(vol, kind="sink"):
                with open(os.path.join(tmp, "vol"), "w") as fh:
                    fh.write(str(vol))
                with open(os.path.join(tmp, "event"), "w") as fh:
                    fh.write(f"Event 'change' on {kind} #57\n" * 3)       # rafale
            event(75)
            self.assertTrue(pump(lambda: seen == [75]), seen)
            event(75)
            pump(lambda: False, 0.4)
            self.assertEqual(seen, [75], "même volume : rien")
            event(80, kind="source")
            pump(lambda: False, 0.4)
            self.assertEqual(seen, [75], "micro (source) : rien")
            w.stop()
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
