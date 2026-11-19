"""Appareils Bluetooth connus de BlueZ (D-Bus système), sans GTK : adresse, nom, connecté."""

from __future__ import annotations

from dataclasses import dataclass

from gi.repository import Gio, GLib


@dataclass
class BtDevice:
    address: str
    name: str
    connected: bool
    path: str


def devices() -> list[BtDevice]:
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    reply = bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                          None, GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 3000, None)
    out = []
    for path, ifaces in reply.unpack()[0].items():
        d = ifaces.get("org.bluez.Device1")
        if d and "Address" in d:
            out.append(BtDevice(d["Address"], d.get("Alias") or d.get("Name") or d["Address"],
                                bool(d.get("Connected")), path))
    return out
