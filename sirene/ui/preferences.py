"""Préférences (Adw.PreferencesWindow : vraie fenêtre, le thème du système s'y applique). Repris de Télémaque."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import autostart, features  # noqa: E402
from ..i18n import LANGUAGE_NAMES, tr  # noqa: E402
from ..settings import settings  # noqa: E402
from .common import combo_row  # noqa: E402


def command_text(cmd: str) -> str:
    """Commande à copier : `sirene …` une fois installée, sinon ce Python et bin/sirene (lancée des sources)."""
    from ..autostart import command
    base = command().rsplit(" --background", 1)[0]
    return base + cmd[len("sirene"):]


def apply_theme():
    Adw.StyleManager.get_default().set_color_scheme({
        "light": Adw.ColorScheme.FORCE_LIGHT,
        "dark": Adw.ColorScheme.FORCE_DARK,
    }.get(settings["theme"], Adw.ColorScheme.DEFAULT))


def _choice(title: str, key: str, labels: list[str], values: list, subtitle: str = "") -> Adw.ComboRow:
    cur = settings[key]
    row = combo_row(title, labels, values.index(cur) if cur in values else 0, subtitle)
    row.connect("notify::selected", lambda r, *_: settings.__setitem__(key, values[r.get_selected()]))
    return row


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent=None):
        super().__init__(title=tr("Préférences"), search_enabled=False, default_width=600, default_height=560,
                         transient_for=parent)
        self.add(self._general())
        self.add(self._features())

    def _general(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title=tr("Général"), icon_name="preferences-system-symbolic", name="general")
        look = Adw.PreferencesGroup(title=tr("Apparence"))
        theme = _choice(tr("Style"), "theme", [tr("Comme le système"), tr("Clair"), tr("Sombre")],
                        ["system", "light", "dark"])
        theme.connect("notify::selected", lambda *_: apply_theme())
        look.add(theme)
        codes = list(LANGUAGE_NAMES)
        look.add(_choice(tr("Langue"), "language", [tr("Comme le système")] + [LANGUAGE_NAMES[c] for c in codes[1:]],
                         codes, tr("Appliquée au prochain démarrage")))
        page.add(look)
        session = Adw.PreferencesGroup(title=tr("Session"))
        auto = Adw.SwitchRow(title=tr("Lancer à l'ouverture de session"), active=autostart.enabled(),
                             subtitle=tr("Sirène démarre sans fenêtre, dans la barre du haut"))
        auto.connect("notify::active", lambda r, *_: autostart.set_enabled(r.get_active()))
        session.add(auto)
        only = Adw.SwitchRow(title=tr("Icône seulement avec les écouteurs"),
                             active=settings["tray_only_connected"],
                             subtitle=tr("Sirène attend en silence et n'apparaît dans la barre du haut que pendant "
                                         "que vos écouteurs sont connectés"))
        only.connect("notify::active", lambda r, *_: settings.__setitem__("tray_only_connected", r.get_active()))
        session.add(only)
        page.add(session)

        buds = Adw.PreferencesGroup(title=tr("Écouteurs"))
        buds.add(_choice(tr("À la connexion des écouteurs"), "on_connect",
                         [tr("Ne rien faire"), tr("Activer la réduction de bruit"), tr("Activer la transparence"),
                          tr("Désactiver le contrôle du bruit"), tr("Ouvrir la fenêtre de Sirène")],
                         ["none", "cancellation", "awareness", "off", "window"]))
        page.add(buds)

        keys = Adw.PreferencesGroup(
            title=tr("Raccourcis clavier"),
            description=tr("Dans Paramètres → Clavier → Raccourcis personnalisés, ajoutez un raccourci avec l'une de "
                           "ces commandes (sous X11 comme sous Wayland)"))
        for cmd, title in (("sirene --anc=next", tr("Mode suivant du contrôle du bruit")),
                           ("sirene --anc=cancellation", tr("Réduction de bruit")),
                           ("sirene --anc=awareness", tr("Transparence")),
                           ("sirene --anc=off", tr("Contrôle du bruit désactivé"))):
            row = Adw.ActionRow(title=title, subtitle=command_text(cmd), subtitle_selectable=True)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text=tr("Copier"))
            copy.add_css_class("flat")
            copy.connect("clicked", lambda b, c=command_text(cmd): (b.get_clipboard().set(c),
                                                                    b.set_icon_name("object-select-symbolic")))
            row.add_suffix(copy)
            keys.add(row)
        page.add(keys)
        return page

    def _features(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title=tr("Fonctionnalités"), icon_name="application-x-addon-symbolic",
                                   name="features")
        group = Adw.PreferencesGroup(description=tr("Chaque fonctionnalité s'active ou se coupe tout de "
                                                    "suite, sans redémarrer Sirène"))
        self.feature_rows = {}
        for f in features.FEATURES:
            row = Adw.SwitchRow(title=f.title, subtitle=f.description, active=features.enabled(f.id))
            row.add_prefix(Gtk.Image(icon_name=f.icon))
            if features.blocked(f.id):                  # composant absent : grisée, la raison reste lisible
                row.set_active(False)
                row.set_subtitle(f.description + "\n⚠ " + f.missing)
                row.set_sensitive(False)
            row.connect("notify::active", lambda r, *_, fid=f.id: features.set_enabled(fid, r.get_active()))
            self.feature_rows[f.id] = row
            group.add(row)
        page.add(group)
        return page
