"""Appareils Bluetooth connus de BlueZ (D-Bus système), sans GTK : adresse, nom, connecté — et leurs
changements, à l'instant où ils se produisent (signaux D-Bus, comme le `gdbus monitor` de bt-notify.sh :
aucune interrogation régulière)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Gio, GLib

DEVICE = "org.bluez.Device1"


@dataclass
class BtDevice:
    address: str
    name: str
    connected: bool
    path: str
    icon: str = ""                  # « audio-headphones », « input-mouse »… (BlueZ)


def _from_props(path: str, props: dict) -> Optional[BtDevice]:
    if "Address" not in props:
        return None
    return BtDevice(props["Address"], props.get("Alias") or props.get("Name") or props["Address"],
                    bool(props.get("Connected")), path, props.get("Icon") or "")


def _managed(bus) -> dict:
    reply = bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                          None, GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 3000, None)
    return reply.unpack()[0]


def devices() -> list[BtDevice]:
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    out = []
    for path, ifaces in _managed(bus).items():
        d = _from_props(path, ifaces.get(DEVICE, {}))
        if d:
            out.append(d)
    return out


class Watcher:
    """Suit les appareils de BlueZ ; `on_change(BtDevice)` dans la boucle GLib (connexion, déconnexion,
    nouveau nom, appareil apparu). `devices` : chemin D-Bus → BtDevice. Sans BlueZ : liste vide."""

    def __init__(self, on_change: Callable[[BtDevice], None]):
        self.on_change = on_change
        self.devices: dict[str, BtDevice] = {}
        self.adapters: set[str] = set()           # adresses de nos adaptateurs (« cet ordinateur »)
        self._props: dict[str, dict] = {}
        self._subs = []
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            self.bus = None
            return
        sub = self.bus.signal_subscribe
        self._subs = [
            sub("org.bluez", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, DEVICE,
                Gio.DBusSignalFlags.NONE, self._on_props),
            sub("org.bluez", "org.freedesktop.DBus.ObjectManager", "InterfacesAdded", "/", None,
                Gio.DBusSignalFlags.NONE, self._on_added),
            sub("org.bluez", "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", "/", None,
                Gio.DBusSignalFlags.NONE, self._on_removed),
        ]
        try:
            for path, ifaces in _managed(self.bus).items():
                if DEVICE in ifaces:
                    self._store(path, dict(ifaces[DEVICE]))
                address = ifaces.get("org.bluez.Adapter1", {}).get("Address")
                if address:
                    self.adapters.add(address.upper())
        except GLib.Error:
            pass

    def stop(self):
        if self.bus is not None:
            for s in self._subs:
                self.bus.signal_unsubscribe(s)
        self._subs = []

    def _store(self, path, props) -> Optional[BtDevice]:
        self._props[path] = props
        d = _from_props(path, props)
        if d:
            self.devices[path] = d
        return d

    def _on_props(self, _bus, _sender, path, _iface, _signal, params):
        _iface_name, changed, _invalid = params.unpack()
        props = dict(self._props.get(path, {}))
        props.update(changed)
        d = self._store(path, props)
        if d and {"Connected", "Alias", "Name"} & set(changed):
            self.on_change(d)

    def _on_added(self, _bus, _sender, _path, _iface, _signal, params):
        path, ifaces = params.unpack()
        if DEVICE in ifaces:
            d = self._store(path, dict(ifaces[DEVICE]))
            if d:
                self.on_change(d)

    def _on_removed(self, _bus, _sender, _path, _iface, _signal, params):
        path, ifaces = params.unpack()
        if DEVICE in ifaces and path in self.devices:
            d = self.devices.pop(path)
            self._props.pop(path, None)
            d.connected = False
            self.on_change(d)
