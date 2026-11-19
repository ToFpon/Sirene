"""Pause au retrait contre de vrais lecteurs MPRIS (faux, sur le bus de session) :

    dbus-run-session -- python3.12 -m unittest tests.test_autopause
"""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gi.repository import Gio, GLib  # noqa: E402

from sirene.backend.autopause import AutoPause  # noqa: E402

XML = """<node><interface name="org.mpris.MediaPlayer2.Player">
<method name="Play"/><method name="Pause"/><property name="PlaybackStatus" type="s" access="read"/>
</interface></node>"""


class Player:
    def __init__(self, name, status):
        self.status = status
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        # une connexion par lecteur : chacun son nom
        self.conn = Gio.DBusConnection.new_for_address_sync(
            Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        self.conn.register_object("/org/mpris/MediaPlayer2", info, self._call, self._get, None)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", (name, 0)), None, Gio.DBusCallFlags.NONE, 2000, None)

    def _call(self, _c, _s, _p, _i, method, _params, inv):
        self.status = {"Play": "Playing", "Pause": "Paused"}[method]
        inv.return_value(None)

    def _get(self, *_args):
        return GLib.Variant("s", self.status)

    def close(self):
        self.conn.close_sync(None)


def run(fn):
    """Les lecteurs vivent dans ce processus : l'appel part d'un fil, la boucle GLib répond."""
    out = []
    t = threading.Thread(target=lambda: out.append(fn()))
    t.start()
    ctx = GLib.MainContext.default()
    while t.is_alive():
        ctx.iteration(False)
    return out[0]


@unittest.skipUnless(os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "bus de session : dbus-run-session")
class AutoPauseTest(unittest.TestCase):
    def test_only_playing_paused_and_resumed(self):
        vlc = Player("org.mpris.MediaPlayer2.vlc", "Playing")
        brave = Player("org.mpris.MediaPlayer2.brave", "Stopped")       # le cas de lola-autopause
        ithaca = Player("org.mpris.MediaPlayer2.ithaca", "Paused")      # arrêté par l'utilisateur
        try:
            ap = AutoPause()
            self.assertEqual(run(ap.pause_playing), ["org.mpris.MediaPlayer2.vlc"])
            self.assertEqual((vlc.status, brave.status, ithaca.status), ("Paused", "Stopped", "Paused"))
            self.assertEqual(run(ap.resume_paused), ["org.mpris.MediaPlayer2.vlc"])
            self.assertEqual((vlc.status, ithaca.status), ("Playing", "Paused"), "Ithaca reste en pause")
            self.assertEqual(run(ap.resume_paused), [], "une seule reprise")
        finally:
            for p in (vlc, brave, ithaca):
                p.close()

    def test_player_gone_before_resume(self):
        vlc = Player("org.mpris.MediaPlayer2.vlc2", "Playing")
        ap = AutoPause()
        run(ap.pause_playing)
        vlc.close()
        self.assertEqual(run(ap.resume_paused), [], "lecteur fermé entre-temps : rien, sans erreur")


if __name__ == "__main__":
    unittest.main()
