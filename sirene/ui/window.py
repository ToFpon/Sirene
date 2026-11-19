"""Fenêtre principale : écouteurs absents / connexion en cours / page des écouteurs.

La page ne connaît que l'application (`app.device`, `app.set_value`) : chaque ligne se construit une fois et
se tient à jour par `changed(groupe, propriété)` ; une ligne reste cachée tant que les écouteurs n'ont pas
donné la valeur (modèle sans ce geste, fonction qui n'a pas répondu)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..i18n import tr  # noqa: E402
from ..settings import settings  # noqa: E402
from .common import _combo_list_factory, clear_box, shown  # noqa: E402
from .labels import gesture_rows, label, options_key  # noqa: E402

INVALID = Gtk.INVALID_LIST_POSITION


class Battery(Gtk.Box):
    """Une pile : icône, « Gauche », niveau, petite barre ; « porté / retiré » pour un écouteur."""

    def __init__(self, title: str, icon: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.add_css_class("card")
        self.add_css_class("battery-tile")
        self.icon = Gtk.Image(icon_name=icon, pixel_size=32)
        self.title = Gtk.Label(label=title)
        self.title.add_css_class("dim-label")
        self.value = Gtk.Label(label="—")
        self.value.add_css_class("title-3")
        self.bar = Gtk.LevelBar(min_value=0, max_value=100)
        self.state = Gtk.Label()
        self.state.add_css_class("caption")
        self.state.add_css_class("dim-label")
        for w in (self.icon, self.title, self.value, self.bar, self.state):
            self.append(w)

    def show_level(self, level, charging):
        if level is None:
            self.value.set_label("—")
            self.bar.set_value(0)
            return
        text = f"{level} %"
        if charging:
            text += " ⚡"
        self.value.set_label(text)
        self.bar.set_value(level)


class DevicePage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.app = app
        self._updaters: dict[tuple, list] = {}
        self.page = Adw.PreferencesPage()
        self.set_child(self.page)
        self._build()

    # --- outils ---

    def dev_get(self, group, prop, default=None):
        dev = self.app.device
        return dev.get(group, prop, default) if dev else default

    def _on(self, keys, fn):
        for key in keys:
            self._updaters.setdefault(key, []).append(fn)

    def changed(self, group, prop):
        for fn in self._updaters.get((group, prop), []):
            fn()

    def refresh_all(self):
        seen = set()
        for fns in self._updaters.values():
            for fn in fns:
                if fn not in seen:
                    seen.add(fn)
                    fn()

    def _combo(self, group, prop, title, opts=None, subtitle=""):
        opts = opts or prop + "_options"
        row = Adw.ComboRow(title=title, visible=False)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_list_factory(_combo_list_factory(row))
        state = {"values": None, "guard": False}

        def refresh():
            value = self.dev_get(group, prop)
            values = list(self.dev_get(group, opts) or [])
            if value is not None and value not in values:
                values.append(value)
            row.set_visible(bool(values) and value is not None)
            state["guard"] = True
            if values != state["values"]:
                state["values"] = values
                row.set_model(Gtk.StringList.new([label(v) for v in values]))
            row.set_selected(values.index(value) if value in values else INVALID)
            state["guard"] = False

        def chosen(*_):
            i = row.get_selected()
            if state["guard"] or not state["values"] or i == INVALID or i >= len(state["values"]):
                return
            value = state["values"][i]
            if value != self.dev_get(group, prop):
                self.app.set_value(group, prop, value, refresh)

        row.connect("notify::selected", chosen)
        self._on([(group, prop), (group, opts)], refresh)
        return row

    def _switch(self, group, prop, title, subtitle=""):
        row = Adw.SwitchRow(title=title, visible=False)
        if subtitle:
            row.set_subtitle(subtitle)
        state = {"guard": False}

        def refresh():
            value = self.dev_get(group, prop)
            row.set_visible(value is not None)
            state["guard"] = True
            row.set_active(bool(value))
            state["guard"] = False

        def toggled(*_):
            if not state["guard"] and row.get_active() != bool(self.dev_get(group, prop)):
                self.app.set_value(group, prop, row.get_active(), refresh)

        row.connect("notify::active", toggled)
        self._on([(group, prop)], refresh)
        return row

    def _group(self, title, rows, description=""):
        g = Adw.PreferencesGroup(title=title)
        if description:
            g.set_description(description)
        for r in rows:
            g.add(r)

        def sync():                                     # groupe caché si aucune ligne n'est visible
            g.set_visible(any(r.get_visible() for r in rows))
        for r in rows:
            r.connect("notify::visible", lambda *_: sync())
        sync()
        self.page.add(g)
        return g

    # --- page ---

    def _build(self):
        # En tête : nom et piles
        self.head = Adw.PreferencesGroup()
        self.name = Gtk.Label(xalign=0)
        self.name.add_css_class("title-2")
        self.firmware = Gtk.Label(xalign=0)
        self.firmware.add_css_class("dim-label")
        tiles = Gtk.Box(spacing=12, homogeneous=True, margin_top=12)
        self.left = Battery(tr("Gauche"), "audio-headphones-symbolic")
        self.right = Battery(tr("Droit"), "audio-headphones-symbolic")
        self.case = Battery(tr("Boîtier"), "battery-symbolic")
        for t in (self.left, self.right, self.case):
            tiles.append(t)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.name)
        box.append(self.firmware)
        box.append(tiles)
        self.head.add(box)
        self.page.add(self.head)
        self._on([("battery", k) for k in ("left", "right", "case", "charging_left", "charging_right",
                                           "charging_case")] + [("state", k) for k in ("left", "right", "in_ear")]
                 + [("info", "software")], self._refresh_head)

        # Contrôle du bruit
        self.anc_buttons: dict[str, Gtk.ToggleButton] = {}
        self.anc_row = Adw.ActionRow(title=tr("Mode"), visible=False)
        self.anc_box = Gtk.Box(valign=Gtk.Align.CENTER)
        self.anc_box.add_css_class("linked")
        self.anc_row.add_suffix(self.anc_box)
        self._anc_guard = False
        self._on([("anc", "mode"), ("anc", "mode_options")], self._refresh_anc)
        self._group(tr("Contrôle du bruit"), [self.anc_row, self._combo("anc", "level", tr("Niveau"))])

        # Gestes
        self._group(tr("Gestes"), [self._combo("action", prop, title, opts=options_key(prop))
                                   for prop, title in gesture_rows()])

        # Son
        self._group(tr("Son"), [
            self._combo("sound", "eq_preset", tr("Égaliseur"), opts="eq_options"),
            self._combo("sound", "quality", tr("Priorité")),
            self._switch("config", "low_latency", tr("Faible latence"),
                         tr("Moins de décalage entre l'image et le son (jeux, vidéos), au prix de la qualité")),
        ])

        # Port des écouteurs
        self._group(tr("Port des écouteurs"), [
            self._switch("config", "auto_pause", tr("Détection du port"),
                         tr("Les écouteurs signalent quand on les retire : la pause automatique en a besoin")),
        ])

        # Double connexion
        self.dc_devices = Adw.PreferencesGroup(title=tr("Appareils connus"), visible=False)
        self._dc_rows = []
        self._group(tr("Double connexion"), [
            self._switch("dual_connect", "enabled", tr("Connexion à deux appareils"),
                         tr("Rester relié au téléphone et à l'ordinateur à la fois")),
        ])
        self.page.add(self.dc_devices)
        self._on([("dual_connect", "devices")], self._refresh_dc)

        # Langue des messages vocaux, infos
        self._group(tr("Messages vocaux"), [self._combo("service", "language", tr("Langue"))])
        self.info_rows = {}
        rows = []
        for key, title in (("model", tr("Modèle")), ("software", tr("Micrologiciel")),
                           ("hardware", tr("Matériel")), ("serial", tr("Numéro de série")),
                           ("serial_left", tr("Numéro de série, gauche")),
                           ("serial_right", tr("Numéro de série, droit"))):
            r = Adw.ActionRow(title=title, visible=False, subtitle_selectable=True)
            r.add_css_class("property")
            self.info_rows[key] = r
            rows.append(r)
            self._on([("info", key)], lambda key=key: self._refresh_info(key))
        self._group(tr("À propos des écouteurs"), rows)

    def _refresh_head(self):
        dev = self.app.device
        self.name.set_label(shown(dev.model.name) if dev else "")
        self.firmware.set_label(shown(self.dev_get("info", "software", "")))
        self.firmware.set_visible(bool(self.dev_get("info", "software")))
        for tile, side in ((self.left, "left"), (self.right, "right"), (self.case, "case")):
            tile.show_level(self.dev_get("battery", side), self.dev_get("battery", f"charging_{side}"))
            if side == "case":
                continue
            worn = self.dev_get("state", side)
            tile.state.set_label("" if worn is None else tr("Porté") if worn else tr("Retiré"))

    def _refresh_anc(self):
        mode = self.dev_get("anc", "mode")
        options = self.dev_get("anc", "mode_options") or []
        self.anc_row.set_visible(bool(options))
        if list(self.anc_buttons) != options:
            clear_box(self.anc_box)
            self.anc_buttons = {}
            first = None
            for opt in options:
                b = Gtk.ToggleButton(label=label(opt))
                if first is None:
                    first = b
                else:
                    b.set_group(first)
                b.connect("toggled", self._anc_toggled, opt)
                self.anc_box.append(b)
                self.anc_buttons[opt] = b
        self._anc_guard = True
        for opt, b in self.anc_buttons.items():
            b.set_active(opt == mode)
        self._anc_guard = False

    def _anc_toggled(self, button, opt):
        if self._anc_guard or not button.get_active() or opt == self.dev_get("anc", "mode"):
            return
        self.app.set_value("anc", "mode", opt, self._refresh_anc)

    def _refresh_dc(self):
        devices = self.dev_get("dual_connect", "devices") or {}
        for r in self._dc_rows:
            self.dc_devices.remove(r)
        self._dc_rows = []
        for d in devices.values():
            sub = tr("En lecture") if d.get("playing") else tr("Connecté") if d.get("connected") else tr("Pas connecté")
            r = Adw.ActionRow(title=shown(d.get("name") or d.get("mac", "")), subtitle=sub)
            r.add_prefix(Gtk.Image(icon_name="computer-symbolic" if d.get("connected") else "network-offline-symbolic"))
            self.dc_devices.add(r)
            self._dc_rows.append(r)
        self.dc_devices.set_visible(bool(devices))

    def _refresh_info(self, key):
        value = self.dev_get("info", key)
        row = self.info_rows[key]
        row.set_visible(bool(value))
        row.set_subtitle(shown(value or ""))


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_default_size(settings["window_width"], settings["window_height"])
        if settings["window_maximized"]:
            self.maximize()
        self.connect("close-request", self._on_close)

        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append(tr("Préférences"), "app.preferences")
        menu.append(tr("À propos de Sirène"), "app.about")
        menu.append(tr("Quitter"), "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text=tr("Menu principal")))

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.none_page = Adw.StatusPage(icon_name="audio-headphones-symbolic", title=tr("Aucun écouteur connecté"),
                                        description=tr("Connectez vos FreeBuds en Bluetooth : Sirène les trouve "
                                                       "toute seule. Modèles pris en charge : FreeBuds 4i, 6i et 7i."))
        self.busy_page = Adw.StatusPage(icon_name="audio-headphones-symbolic")
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
        self.busy_page.set_child(spinner)
        self.fail_page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        retry = Gtk.Button(label=tr("Réessayer"), halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_: app.retry())
        self.fail_page.set_child(retry)
        self.device_page = DevicePage(app)
        for name, page in (("none", self.none_page), ("busy", self.busy_page), ("fail", self.fail_page),
                           ("device", self.device_page)):
            self.stack.add_named(page, name)

        self.toast_overlay = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toast_overlay)
        self.set_content(view)
        self.show_state()

    def show_state(self):
        state, name, detail = self.app.state, self.app.bt_name, self.app.fail_detail
        if state == "busy":
            self.busy_page.set_title(tr("Connexion à {0}…").format(shown(name)))
        elif state == "fail":
            self.fail_page.set_title(tr("Impossible de joindre {0}").format(shown(name)))
            self.fail_page.set_description(detail)
        elif state == "device":
            self.device_page.refresh_all()
        self.stack.set_visible_child_name(state)

    def changed(self, group, prop):
        self.device_page.changed(group, prop)

    def _on_close(self, *_):
        maximized = self.is_maximized()
        settings["window_maximized"] = maximized
        if not maximized:
            w, h = self.get_default_size()
            settings["window_width"], settings["window_height"] = w, h
        return False
