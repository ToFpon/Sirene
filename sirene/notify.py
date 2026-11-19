"""Notifications du bureau.

PIÈGE vu chez Tof : GNOME Shell REFUSE en silence les Gio.Notification d'une application sans fichier .desktop
installé (notificationDaemon.js : lookup_app(<id>.desktop) échoue → InvalidAppError) — Sirène lancée depuis les
sources n'en affichait aucune. Sans lanceur installé, on passe donc par org.freedesktop.Notifications, comme
`notify-send` (ce qu'utilisait bt-notify.sh) ; installé, par Gio.Notification (nom et icône de l'application,
regroupées dans le centre de notifications).
"""

from __future__ import annotations

import logging

from gi.repository import Gio, GLib

from . import APP_ID, APP_NAME

log = logging.getLogger("sirene.notify")


def installed() -> bool:
    try:
        return Gio.DesktopAppInfo.new(APP_ID + ".desktop") is not None
    except TypeError:
        return False


class Notifier:
    def __init__(self, app):
        self.app = app
        self._ids: dict[str, int] = {}           # notre identifiant → numéro rendu par le serveur (remplacement)

    def send(self, nid: str, title: str, body: str, icon: str, transient: bool = False):
        """transient : affichée normalement mais pas gardée dans la liste des notifications, comme
        `notify-send -e -u normal` de bt-notify (connexions Bluetooth). Vu chez Tof : en priorité BASSE, GNOME ne
        l'affichait pas, il la rangeait directement dans la liste. Gio.Notification n'a pas d'« éphémère » :
        ces notifications passent toujours par org.freedesktop.Notifications."""
        if installed() and not transient:
            n = Gio.Notification.new(title)
            n.set_body(body)
            n.set_icon(Gio.ThemedIcon.new(icon))
            self.app.send_notification(nid, n)
            return
        try:
            bus = self.app.get_dbus_connection() or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return

        def done(conn, res):
            try:
                self._ids[nid] = conn.call_finish(res).unpack()[0]
            except GLib.Error as e:
                log.info("notification refusée : %s", e.message)
        bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                 "Notify", GLib.Variant("(susssasa{sv}i)", (APP_NAME, self._ids.get(nid, 0), icon, title, body, [], {
                     "desktop-entry": GLib.Variant("s", APP_ID),
                     "urgency": GLib.Variant("y", 1),                                # normale (-u normal)
                     "transient": GLib.Variant("b", transient)}, -1)),               # -e de notify-send
                 GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None, done)
