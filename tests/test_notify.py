"""Notifications sans lanceur installé : org.freedesktop.Notifications (comme notify-send), une notification
remplacée par la suivante du même identifiant.

    dbus-run-session -- python3.12 -m unittest tests.test_notify
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gi.repository import Gio, GLib  # noqa: E402

from sirene import notify  # noqa: E402

XML = """<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
</interface></node>"""


def pump(cond, timeout=3):
    ctx, end = GLib.MainContext.default(), time.time() + timeout
    while time.time() < end and not cond():
        ctx.iteration(False)
        time.sleep(0.005)
    return cond()


class FakeApp:
    def get_dbus_connection(self):
        return None

    def send_notification(self, *a):
        raise AssertionError("Gio.Notification : GNOME Shell la refuse sans .desktop installé")


@unittest.skipUnless(os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "bus de session : dbus-run-session")
class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.conn = Gio.DBusConnection.new_for_address_sync(
            Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

        def call(_c, _s, _p, _i, _m, params, inv):
            self.calls.append(params.unpack())
            inv.return_value(GLib.Variant("(u)", (len(self.calls) + 40,)))
        self.conn.register_object("/org/freedesktop/Notifications", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
                                  call, None, None)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", ("org.freedesktop.Notifications", 0)), None, Gio.DBusCallFlags.NONE,
                            2000, None)

    def tearDown(self):
        self.conn.close_sync(None)

    def test_freedesktop_without_desktop_file(self):
        self.assertFalse(notify.installed(), "lancé depuis les sources")
        n = notify.Notifier(FakeApp())
        n.send("bt-x", "HUAWEI FreeBuds 6i", "Connecté", "audio-headphones")
        self.assertTrue(pump(lambda: len(self.calls) == 1 and "bt-x" in n._ids))
        app_name, replaces, icon, title, body = self.calls[0][:5]
        self.assertEqual((app_name, replaces, icon, title, body),
                         ("Sirène", 0, "audio-headphones", "HUAWEI FreeBuds 6i", "Connecté"))
        n.send("bt-x", "HUAWEI FreeBuds 6i", "Déconnecté", "bluetooth-disabled")
        self.assertTrue(pump(lambda: len(self.calls) == 2))
        self.assertEqual(self.calls[1][1], 41, "même appareil : la notification d'avant est remplacée")


if __name__ == "__main__":
    unittest.main()
