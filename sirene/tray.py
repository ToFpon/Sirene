"""Icône dans la barre du haut (repris de Télémaque et d'Ithaca) : protocole StatusNotifierItem, celui des
« AppIndicator » que Zorin / Ubuntu affichent (extension AppIndicator de GNOME Shell).

libayatana-appindicator est en GTK 3 et ne peut pas cohabiter avec GTK 4 dans le même processus : on parle
D-Bus directement (org.kde.StatusNotifierItem + com.canonical.dbusmenu), enregistré auprès de
org.kde.StatusNotifierWatcher ; sans extension, rien ne s'affiche et rien ne casse.

Contenu fourni par l'application : `app.tray_items()` → [(id, propriétés dbusmenu)], `app.tray_text()` (bulle),
`app.tray_activate(id)` ; `update()` republie le menu s'il a changé.
"""

from __future__ import annotations

import os
import re

from gi.repository import Gio, GLib

from . import APP_ID, APP_NAME

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"
ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "icons")
ICON_NAME = APP_ID


def icon_theme_path() -> str:
    """Dossier d'icônes à annoncer : vide si l'icône est installée dans le thème du système (paquet,
    install.sh) ; sinon data/icons (lancé sans installer), qui DOIT garder hicolor/index.theme : sans
    lui, l'extension AppIndicator (St.IconTheme, logique de GTK 3) ne trouve rien (vu dans Ithaca)."""
    for base in [GLib.get_user_data_dir(), *GLib.get_system_data_dirs()]:
        icons = os.path.join(base, "icons", "hicolor")
        if os.path.exists(os.path.join(icons, "scalable", "apps", ICON_NAME + ".svg")) and \
                os.path.exists(os.path.join(icons, "symbolic", "apps", ICON_NAME + "-symbolic.svg")):
            return ""
    return ICONS_DIR


def menu_label(text: str) -> str:
    """L'extension AppIndicator retire le premier « _ » suivi d'autre chose qu'un « _ » (lettre de
    raccourci) : on double exactement celui-là (repris d'Ithaca)."""
    return re.sub(r"_(?=[^_])", "__", text, count=1)


ITEM_XML = """<node><interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
  <property name="IconName" type="s" access="read"/><property name="IconThemePath" type="s" access="read"/>
  <property name="AttentionIconName" type="s" access="read"/><property name="OverlayIconName" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/><property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/><property name="WindowId" type="i" access="read"/>
  <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
  <signal name="NewIcon"/><signal name="NewTitle"/><signal name="NewToolTip"/>
  <signal name="NewStatus"><arg name="status" type="s"/></signal>
</interface></node>"""

MENU_XML = """<node><interface name="com.canonical.dbusmenu">
  <property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout"><arg type="i" name="parentId" direction="in"/><arg type="i" name="recursionDepth" direction="in"/>
    <arg type="as" name="propertyNames" direction="in"/><arg type="u" name="revision" direction="out"/>
    <arg type="(ia{sv}av)" name="layout" direction="out"/></method>
  <method name="GetGroupProperties"><arg type="ai" name="ids" direction="in"/><arg type="as" name="propertyNames" direction="in"/>
    <arg type="a(ia{sv})" name="properties" direction="out"/></method>
  <method name="GetProperty"><arg type="i" name="id" direction="in"/><arg type="s" name="name" direction="in"/>
    <arg type="v" name="value" direction="out"/></method>
  <method name="Event"><arg type="i" name="id" direction="in"/><arg type="s" name="eventId" direction="in"/>
    <arg type="v" name="data" direction="in"/><arg type="u" name="timestamp" direction="in"/></method>
  <method name="EventGroup"><arg type="a(isvu)" name="events" direction="in"/><arg type="ai" name="idErrors" direction="out"/></method>
  <method name="AboutToShow"><arg type="i" name="id" direction="in"/><arg type="b" name="needUpdate" direction="out"/></method>
  <method name="AboutToShowGroup"><arg type="ai" name="ids" direction="in"/><arg type="ai" name="updatesNeeded" direction="out"/>
    <arg type="ai" name="idErrors" direction="out"/></method>
  <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
  <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})" name="updatedProps"/><arg type="a(ias{sv})" name="removedProps"/></signal>
</interface></node>"""


def item(label: str, enabled: bool = True, radio=None) -> dict:
    """Entrée du menu ; radio = None (simple) ou état coché (bouton radio)."""
    props = {"label": GLib.Variant("s", menu_label(label))}
    if not enabled:
        props["enabled"] = GLib.Variant("b", False)
    if radio is not None:
        props["toggle-type"] = GLib.Variant("s", "radio")
        props["toggle-state"] = GLib.Variant("i", 1 if radio else 0)
    return props


SEPARATOR = {"type": GLib.Variant("s", "separator")}


class Tray:
    def __init__(self, app):
        self.app = app
        self.conn = None
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._ids: list[int] = []
        self.revision = 1
        self.registered = False          # accepté par un StatusNotifierWatcher
        self.item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        self.menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._watch = 0
        self._last = None

    @property
    def active(self) -> bool:
        return self.conn is not None

    def show(self):
        """L'icône a SA connexion au bus de session : la fermer la retire tout de suite. Vu chez Tof : sur la
        connexion de l'application, rendre le nom ne suffisait pas — l'extension AppIndicator suit le nom unique
        de la connexion, l'icône restait après le départ des écouteurs, jusqu'à la sortie de Sirène."""
        if self.conn is not None:
            return
        try:
            conn = Gio.DBusConnection.new_for_address_sync(
                Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
            conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                           GLib.Variant("(su)", (self.name, 4)), GLib.VariantType("(u)"),  # 4 : DO_NOT_QUEUE
                           Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error:
            return                              # pas de bus de session : pas d'icône
        self._on_bus(conn, self.name)

    def hide(self):
        conn, self.conn = self.conn, None
        self._ids, self._watch = [], 0
        self.registered = False
        if conn is not None:
            conn.close(None, None, None)        # nom unique et nom de l'icône disparaissent : l'icône s'en va

    def _on_bus(self, conn, _name):
        self.conn = conn
        self._ids = [conn.register_object(ITEM_PATH, self.item_info, self._on_item_call, self._on_item_get, None),
                     conn.register_object(MENU_PATH, self.menu_info, self._on_menu_call, self._on_menu_get, None)]
        self._register()
        # la barre (l'extension) redémarre : on se réenregistre
        self._watch = conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                            "/org/freedesktop/DBus", WATCHER, Gio.DBusSignalFlags.NONE,
                                            lambda *a: self._register())

    def _register(self):
        if self.conn is None:
            return

        def done(conn, res):
            try:
                conn.call_finish(res)
                ok = True
            except GLib.Error:
                ok = False                       # pas de barre AppIndicator : rien ne s'affiche
            if conn is self.conn:                # réponse d'une connexion déjà fermée (icône cachée entre-temps)
                self.registered = ok
        self.conn.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                       GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, 3000, None, done)

    def _on_item_get(self, _conn, _sender, _path, _iface, prop):
        values = {
            "Category": GLib.Variant("s", "Hardware"), "Id": GLib.Variant("s", "sirene"),
            "Title": GLib.Variant("s", APP_NAME), "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", ICON_NAME),
            "IconThemePath": GLib.Variant("s", icon_theme_path()),
            "AttentionIconName": GLib.Variant("s", ""), "OverlayIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (APP_ID, [], APP_NAME, self.app.tray_text())),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH), "WindowId": GLib.Variant("i", 0),
        }
        return values.get(prop)

    def _on_item_call(self, _conn, _sender, _path, _iface, method, params, inv):
        if method == "Activate":
            GLib.idle_add(lambda: (self.app.show_window(), False)[1])
        inv.return_value(None)

    def _layout(self) -> GLib.Variant:
        children = [GLib.Variant("(ia{sv}av)", (i, props, [])) for i, props in self.app.tray_items()]
        return GLib.Variant("(u(ia{sv}av))", (self.revision, (0, {"children-display": GLib.Variant("s", "submenu")},
                                                                children)))

    def _on_menu_get(self, _conn, _sender, _path, _iface, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"),
                "IconThemePath": GLib.Variant("as", [d for d in [icon_theme_path()] if d])}.get(prop)

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, inv):
        if method == "GetLayout":
            inv.return_value(self._layout())
        elif method == "GetGroupProperties":
            ids, _names = params.unpack()
            props = [(i, p) for i, p in self.app.tray_items() if not ids or i in ids]
            inv.return_value(GLib.Variant("(a(ia{sv}))", (props,)))
        elif method == "GetProperty":
            i, name = params.unpack()
            value = dict(self.app.tray_items()).get(i, {}).get(name, GLib.Variant("s", ""))
            inv.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            i, event, _data, _ts = params.unpack()
            if event == "clicked":
                GLib.idle_add(lambda: (self.app.tray_activate(i), False)[1])
            inv.return_value(None)
        elif method == "EventGroup":
            for i, event, _data, _ts in params.unpack()[0]:
                if event == "clicked":
                    GLib.idle_add(lambda i=i: (self.app.tray_activate(i), False)[1])
            inv.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            inv.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            inv.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            inv.return_value(None)

    def update(self):
        """Menu et bulle republiés seulement s'ils ont changé."""
        if self.conn is None:
            return
        now = repr([(i, {k: v.unpack() for k, v in p.items()}) for i, p in self.app.tray_items()]) + \
            self.app.tray_text()
        if now == self._last:
            return
        self._last = now
        self.revision += 1
        self.conn.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                              GLib.Variant("(ui)", (self.revision, 0)))
        self.conn.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip", None)
