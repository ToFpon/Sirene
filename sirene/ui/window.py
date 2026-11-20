"""Fenêtre principale : écouteurs absents / connexion en cours / page des écouteurs.

La page ne connaît que l'application (`app.device`, `app.set_value`) : chaque ligne se construit une fois et
se tient à jour par `changed(groupe, propriété)` ; une ligne reste cachée tant que les écouteurs n'ont pas
donné la valeur (modèle sans ce geste, fonction qui n'a pas répondu)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..i18n import tr  # noqa: E402
from ..settings import settings  # noqa: E402
from .common import _combo_list_factory, alert, clear_box, shown  # noqa: E402
from .labels import gesture_rows, label, options_key  # noqa: E402

INVALID = Gtk.INVALID_LIST_POSITION
BANDS = ("32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")   # Hz, égaliseur Huawei à 10 bandes
EQ_RANGE = 60                                                          # dixièmes de dB : ±6 dB (comme AI Life)


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


def _db(tenths) -> str:
    v = tenths / 10
    return ("+" if v > 0 else "") + (f"{v:.1f}".rstrip("0").rstrip(".") or "0")


class DevicePage(Gtk.Box):
    """Onglets (demande de Tof) : État (piles, contrôle du bruit, port), Gestes, Son, Appareil (double connexion,
    langue, infos). Un onglet sans aucune ligne visible (modèle sans ces fonctions) est caché."""

    TABS = ("status", "gestures", "sound", "device")

    def __init__(self, app):
        super().__init__(vexpand=True)
        self.app = app
        self._updaters: dict[tuple, list] = {}
        self.pages: dict[str, tuple] = {}
        self.stack = Adw.ViewStack(vexpand=True, hexpand=True)      # Adw.ViewStack est « final » : on le porte
        self.append(self.stack)
        for name, title, icon in (("status", tr("État"), "io.github.sirene.Sirene-symbolic"),
                                  ("gestures", tr("Gestes"), "input-touchpad-symbolic"),
                                  ("sound", tr("Son"), "audio-volume-high-symbolic"),
                                  ("device", tr("Appareil"), "preferences-system-symbolic")):
            page = Adw.PreferencesPage()
            tab = self.stack.add_titled_with_icon(page, name, title, icon)
            self.pages[name] = (page, tab, [])
        self.page = None                                # onglet en cours de construction (_build)
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

    def _add(self, group):
        """Groupe ajouté à l'onglet en cours ; l'onglet suit la visibilité de ses groupes."""
        page, tab, groups = self.pages[self.page]
        page.add(group)
        groups.append(group)
        group.connect("notify::visible", lambda *_: tab.set_visible(any(g.get_visible() for g in groups)))
        tab.set_visible(any(g.get_visible() for g in groups))

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
        self._add(g)
        return g

    # --- page ---

    def _build(self):
        self.page = "status"
        # En tête : nom et piles
        self.head = Adw.PreferencesGroup()
        self.name = Gtk.Label(xalign=0)
        self.name.add_css_class("title-2")
        self.firmware = Gtk.Label(xalign=0)
        self.firmware.add_css_class("dim-label")
        tiles = Gtk.Box(spacing=12, homogeneous=True, margin_top=12)
        self.left = Battery(tr("Gauche"), "sirene-earbud-left-symbolic")
        self.right = Battery(tr("Droit"), "sirene-earbud-right-symbolic")
        self.case = Battery(tr("Boîtier"), "sirene-case-symbolic")
        for t in (self.left, self.right, self.case):
            tiles.append(t)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.name)
        box.append(self.firmware)
        box.append(tiles)
        self.head.add(box)
        self._add(self.head)
        self._on([("battery", k) for k in ("left", "right", "case", "charging_left", "charging_right",
                                           "charging_case")] + [("state", k) for k in ("left", "right", "in_ear")]
                 + [("info", "software")], self._refresh_head)

        # Contrôle du bruit
        self.anc_buttons: dict[str, Gtk.ToggleButton] = {}
        # Boutons liés sur toute la largeur, textes abrégés si la place manque : en suffixe d'une ligne, ils
        # imposaient leur largeur à la fenêtre (débordement en fenêtre étroite)
        self.anc_box = Gtk.Box(homogeneous=True, visible=False, margin_bottom=12)
        self.anc_box.add_css_class("linked")
        self.anc_row = self.anc_box
        self._anc_guard = False
        self._on([("anc", "mode"), ("anc", "mode_options")], self._refresh_anc)
        self._group(tr("Contrôle du bruit"), [self.anc_row, self._combo("anc", "level", tr("Niveau"))])

        # Port des écouteurs
        self._group(tr("Port des écouteurs"), [
            self._switch("config", "auto_pause", tr("Détection du port"),
                         tr("Les écouteurs signalent quand on les retire : la pause automatique en a besoin")),
        ])

        # Gestes : un groupe par geste
        self.page = "gestures"
        rows = {prop: self._combo("action", prop, title, opts=options_key(prop)) for prop, title in gesture_rows()}
        for title, props in ((tr("Tapes"), ("double_tap_left", "double_tap_right", "double_tap_in_call",
                                            "triple_tap_left", "triple_tap_right")),
                             (tr("Appui long"), ("long_tap_left", "long_tap_right", "long_tap_in_call",
                                                 "noise_control_left", "noise_control_right")),
                             (tr("Glisser"), ("swipe",))):
            self._group(title, [rows[p] for p in props])

        # Son
        self.page = "sound"
        self._group(tr("Son"), [
            self._combo("sound", "eq_preset", tr("Égaliseur"), opts="eq_options"),
            self._combo("sound", "quality", tr("Priorité")),
            self._switch("config", "low_latency", tr("Faible latence"),
                         tr("Moins de décalage entre l'image et le son (jeux, vidéos), au prix de la qualité")),
        ])
        self._build_equalizer()

        # Appareil : double connexion, langue des messages, infos
        self.page = "device"
        self.dc_devices = Adw.PreferencesGroup(title=tr("Appareils connus"), visible=False)
        self._dc_rows = []
        self._group(tr("Double connexion"), [
            self._switch("dual_connect", "enabled", tr("Connexion à deux appareils"),
                         tr("Rester relié au téléphone et à l'ordinateur à la fois")),
        ])
        self._add(self.dc_devices)
        self._on([("dual_connect", "devices"), ("dual_connect", "preferred")], self._refresh_dc)

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
                b = Gtk.ToggleButton(child=Gtk.Label(label=label(opt), ellipsize=3), hexpand=True,
                                     tooltip_text=label(opt))
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
        ours = {a.replace(":", "").lower() for a in getattr(self.app.watcher, "adapters", ())}
        preferred = self.dev_get("dual_connect", "preferred")
        for mac, d in devices.items():
            this = mac.lower() in ours
            sub = tr("En lecture") if d.get("playing") else tr("Connecté") if d.get("connected") else tr("Pas connecté")
            if this:
                sub = tr("Cet ordinateur") + " · " + sub
            r = Adw.ActionRow(title=shown(d.get("name") or mac), subtitle=sub)
            r.add_prefix(Gtk.Image(icon_name="computer-symbolic" if this else "phone-symbolic"))
            star = Gtk.ToggleButton(icon_name="starred-symbolic" if mac == preferred else "non-starred-symbolic",
                                    active=mac == preferred, valign=Gtk.Align.CENTER,
                                    tooltip_text=tr("Appareil préféré (reconnecté en priorité)"))
            star.add_css_class("flat")
            star.connect("toggled", lambda b, mac=mac: b.get_active() and self.app.set_value(
                "dual_connect", "preferred", mac, self._refresh_dc))
            r.add_suffix(star)
            if not this:                    # se déconnecter soi-même couperait Sirène des écouteurs
                c = Gtk.Button(label=tr("Déconnecter") if d.get("connected") else tr("Connecter"),
                               valign=Gtk.Align.CENTER)
                c.connect("clicked", lambda _b, mac=mac, on=not d.get("connected"): self.app.set_value(
                    "dual_connect", f"{mac}:connected", on))
                r.add_suffix(c)
                forget = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                    tooltip_text=tr("Oublier cet appareil…"))
                forget.add_css_class("flat")
                forget.connect("clicked", lambda _b, mac=mac, name=d.get("name") or mac: self._ask_forget(mac, name))
                r.add_suffix(forget)
            self.dc_devices.add(r)
            self._dc_rows.append(r)
        self.dc_devices.set_visible(bool(devices))

    # --- égaliseur personnalisé ---

    def _build_equalizer(self):
        """Préréglages à soi (3 au plus) : 10 bandes de -6 à +6 dB, entendues tout de suite ; « Enregistrer » les
        garde, « Annuler » remet les valeurs d'avant (comme OpenFreebuds / AI Life)."""
        g = Adw.PreferencesGroup(title=tr("Égaliseur personnalisé"), visible=False)
        new = Adw.ActionRow(title=tr("Nouveau préréglage"),
                            subtitle=tr("À partir du préréglage choisi, jusqu'à 3 préréglages à vous"))
        b = Gtk.Button(label=tr("Créer…"), valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self._ask_new_preset())
        new.add_suffix(b)
        new.set_activatable_widget(b)
        g.add(new)

        self.eq_box = Gtk.Box(spacing=4, homogeneous=True, margin_top=12, visible=False)
        self.eq_box.add_css_class("card")
        self.eq_box.add_css_class("eq-bands")
        self.eq_scales, self.eq_values = [], []
        self._eq_guard = False
        self._eq_timer = 0
        for hz in BANDS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            value = Gtk.Label(label="0")
            value.add_css_class("caption")
            value.add_css_class("numeric")
            scale = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, inverted=True, vexpand=True, height_request=170,
                              adjustment=Gtk.Adjustment(lower=-EQ_RANGE, upper=EQ_RANGE, step_increment=5,
                                                        page_increment=10))
            scale.set_has_origin(False)                 # ±6 dB autour de 0 : pas de remplissage depuis le bas
            scale.add_mark(0, Gtk.PositionType.LEFT, None)
            scale.set_tooltip_text(hz + " Hz")
            scale.connect("value-changed", self._eq_moved)
            name = Gtk.Label(label=hz)
            name.add_css_class("caption")
            name.add_css_class("dim-label")
            for w in (value, scale, name):
                col.append(w)
            self.eq_box.append(col)
            self.eq_scales.append(scale)
            self.eq_values.append(value)
        g.add(self.eq_box)

        self.eq_unsaved = Adw.ActionRow(title=tr("Modifications non enregistrées"), visible=False)
        cancel = Gtk.Button(label=tr("Annuler"), valign=Gtk.Align.CENTER)
        cancel.connect("clicked", lambda *_: self.app.set_value("sound", "eq_saved", False))
        save = Gtk.Button(label=tr("Enregistrer"), valign=Gtk.Align.CENTER)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self.app.set_value("sound", "eq_saved", True))
        self.eq_unsaved.add_suffix(cancel)
        self.eq_unsaved.add_suffix(save)
        g.add(self.eq_unsaved)

        self.eq_delete = Adw.ActionRow(title=tr("Supprimer ce préréglage"), visible=False)
        d = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text=tr("Supprimer…"))
        d.add_css_class("flat")
        d.connect("clicked", lambda *_: self._ask_delete_preset())
        self.eq_delete.add_suffix(d)
        g.add(self.eq_delete)
        self.eq_group = g
        self._add(g)
        self._on([("sound", k) for k in ("eq_rows", "eq_saved", "eq_max_custom", "eq_preset")], self._refresh_eq)

    def _refresh_eq(self):
        rows = self.dev_get("sound", "eq_rows")
        self.eq_group.set_visible(bool(self.dev_get("sound", "eq_max_custom")))
        self.eq_box.set_visible(rows is not None)
        self.eq_delete.set_visible(rows is not None)
        self.eq_unsaved.set_visible(rows is not None and self.dev_get("sound", "eq_saved") is False)
        if rows is not None and not self._eq_timer:            # pas pendant qu'on fait glisser
            self._eq_guard = True
            for scale, label_, v in zip(self.eq_scales, self.eq_values, rows):
                scale.set_value(v)
                label_.set_label(_db(v))
            self._eq_guard = False

    def _eq_moved(self, scale):
        i = self.eq_scales.index(scale)
        self.eq_values[i].set_label(_db(round(scale.get_value())))
        if self._eq_guard:
            return
        if self._eq_timer:
            GLib.source_remove(self._eq_timer)
        self._eq_timer = GLib.timeout_add(300, self._eq_send)      # un envoi après le dernier mouvement

    def _eq_send(self):
        self._eq_timer = 0
        rows = [int(round(s.get_value())) for s in self.eq_scales]
        if rows != self.dev_get("sound", "eq_rows"):
            self.app.set_value("sound", "eq_rows", rows, self._refresh_eq)
        return False

    def _ask_new_preset(self):
        entry = Gtk.Entry(text=tr("Mon préréglage"), activates_default=True, max_length=24)

        def done(response):
            name = entry.get_text().strip()
            if response == "create" and name:
                self.app.set_value("sound", "eq_preset", name)
        alert(self, tr("Nouveau préréglage"), tr("Il part des réglages du préréglage choisi."),
              responses=(("cancel", tr("Annuler")), ("create", tr("Créer"))), default="create",
              suggested="create", callback=done, extra=entry)

    def _ask_delete_preset(self):
        name = label(self.dev_get("sound", "eq_preset"))

        def done(response):
            if response == "delete":
                self.app.set_value("sound", "eq_rows", None)
        alert(self, tr("Supprimer « {0} » ?").format(name), tr("Le préréglage est retiré des écouteurs."),
              responses=(("cancel", tr("Annuler")), ("delete", tr("Supprimer"))), default="cancel",
              destructive="delete", callback=done)

    def _ask_forget(self, mac, name):
        def done(response):
            if response == "forget":
                self.app.set_value("dual_connect", f"{mac}:unpair", True)
        alert(self, tr("Oublier « {0} » ?").format(shown(name)),
              tr("Les écouteurs ne s'y connecteront plus ; il faudra les associer de nouveau."),
              responses=(("cancel", tr("Annuler")), ("forget", tr("Oublier"))), default="cancel",
              destructive="forget", callback=done)

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
        self.set_size_request(360, 420)                # taille minimale : exigée par les points de rupture
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
        self.none_page = Adw.StatusPage(icon_name="io.github.sirene.Sirene-symbolic", title=tr("Aucun écouteur connecté"),
                                        description=tr("Connectez vos FreeBuds en Bluetooth : Sirène les trouve "
                                                       "toute seule. Modèles pris en charge : FreeBuds 4i, 6i et 7i."))
        self.busy_page = Adw.StatusPage(icon_name="io.github.sirene.Sirene-symbolic")
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

        # Onglets : sélecteur dans l'en-tête, barre du bas si la fenêtre est étroite (comme les applications GNOME)
        self.title = Adw.WindowTitle(title=APP_NAME)
        self.switcher = Adw.ViewSwitcher(stack=self.device_page.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.device_page.stack)
        header.set_title_widget(self.title)
        self._narrow = False
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 480sp"))
        narrow.connect("apply", lambda *_: self._set_narrow(True))
        narrow.connect("unapply", lambda *_: self._set_narrow(False))
        self.add_breakpoint(narrow)

        self.toast_overlay = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toast_overlay)
        view.add_bottom_bar(self.switcher_bar)
        self.header = header
        self.set_content(view)
        self.show_state()

    def _set_narrow(self, narrow):
        self._narrow = narrow
        self._sync_switcher()

    def _sync_switcher(self):
        tabs = self.app.state == "device"
        self.header.set_title_widget(self.switcher if tabs and not self._narrow else self.title)
        self.switcher_bar.set_reveal(tabs and self._narrow)

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
        self._sync_switcher()

    def changed(self, group, prop):
        self.device_page.changed(group, prop)

    def _on_close(self, *_):
        maximized = self.is_maximized()
        settings["window_maximized"] = maximized
        if not maximized:
            w, h = self.get_default_size()
            settings["window_width"], settings["window_height"] = w, h
        return self.app.window_closing()            # True : cachée, Sirène reste dans la barre
