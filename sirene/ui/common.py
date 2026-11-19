"""Briques d'interface partagées (reprises d'Odysseus)."""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402



def shown(text) -> str:
    """Texte affichable par GTK : un nom de fichier non UTF-8 arrive de Python avec des caractères
    de substitution (surrogateescape) que Gtk refuse (UnicodeEncodeError : ligne vide, titre figé).
    Les octets invalides deviennent « � », comme dans Nautilus ; le vrai chemin reste intact ailleurs."""
    if not isinstance(text, str):
        return "" if text is None else str(text)
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")

def toast(widget: Gtk.Widget, text: str, button: str = "", callback: Optional[Callable] = None,
          timeout: int = 4):
    win = widget.get_root() if widget else None
    overlay = getattr(win, "toast_overlay", None)
    if overlay is None:
        return
    t = Adw.Toast.new(text)
    t.set_use_markup(False)          # noms de fichiers et adresses : « & » ou « < » cassaient le balisage
    t.set_timeout(timeout)
    if button and callback:
        t.set_button_label(button)
        t.connect("button-clicked", lambda *_: callback())
    overlay.add_toast(t)

def focus_later(widget: Gtk.Widget):
    """Donne le focus une fois la fenêtre affichée. Jamais GLib.idle_add(widget.grab_focus) :
    grab_focus renvoie True, ce qui fait rappeler la fonction sans fin — le champ reprenait le
    focus en boucle et resélectionnait son texte, chaque lettre tapée remplaçait la précédente."""
    GLib.idle_add(lambda: (widget.grab_focus(), False)[1])

def dialog_parent(widget) -> Optional[Gtk.Window]:
    if widget is None:
        return None
    root = widget.get_root() if isinstance(widget, Gtk.Widget) else None
    return root if isinstance(root, Gtk.Window) else None

class DialogWindow(Adw.Window):
    """Remplace Adw.Dialog (même usage : title, content_width/height, set_child, present(parent),
    close, signal « closed », Échap pour fermer), en fenêtre modale."""

    __gsignals__ = {"closed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, title: str = "", content_width: int = -1, content_height: int = -1, **kw):
        super().__init__(title=title, modal=True, **kw)
        self.set_default_size(content_width, content_height)
        self.connect("close-request", self._on_close_request)
        keys = Gtk.ShortcutController()
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("Escape"),
                                       action=Gtk.CallbackAction.new(lambda *_: (self.close(), True)[1])))
        self.add_controller(keys)

    def _on_close_request(self, *_):
        self.emit("closed")
        return False

    def set_child(self, child):
        self.set_content(child)

    def get_child(self):
        return self.get_content()

    def set_content_width(self, width: int):
        self.set_default_size(width, self.get_default_size()[1])

    def set_content_height(self, height: int):
        self.set_default_size(self.get_default_size()[0], height)

    def force_close(self):
        self.close()

    def present(self, parent=None):
        win = dialog_parent(parent)
        if win is not None and win is not self:
            self.set_transient_for(win)
        super().present()

class AlertDialog(Adw.MessageDialog):
    """Remplace Adw.AlertDialog : Adw.MessageDialog, la boîte de Nautilus 46, large comme elle."""

    def __init__(self, heading: str = "", body: Optional[str] = None, **kw):
        super().__init__(heading=heading, body=body or "", modal=True, **kw)
        if len(heading) + len(body or "") > 50:
            self.set_default_size(600, -1)       # texte sur peu de lignes, comme chez Nautilus

    @classmethod
    def new(cls, heading: str, body: Optional[str] = None) -> "AlertDialog":
        return cls(heading, body)

    def present(self, parent=None):
        win = dialog_parent(parent)
        if win is not None and win is not self:
            self.set_transient_for(win)
        super().present()

def alert(parent: Gtk.Widget, heading: str, body: str = "", responses=(("ok", "OK"),),
          default: str = "", destructive: str = "", suggested: str = "",
          callback: Optional[Callable[[str], None]] = None, extra: Optional[Gtk.Widget] = None):
    d = AlertDialog.new(heading, body or None)
    for rid, label in responses:
        d.add_response(rid, label)
    if destructive:
        d.set_response_appearance(destructive, Adw.ResponseAppearance.DESTRUCTIVE)
    if suggested:
        d.set_response_appearance(suggested, Adw.ResponseAppearance.SUGGESTED)
    if default:
        d.set_default_response(default)
        d.set_close_response(responses[0][0])
    if extra is not None:
        d.set_extra_child(extra)
    if callback:
        d.connect("response", lambda _d, r: callback(r))
    d.present(parent)
    return d

def error(parent: Gtk.Widget, heading: str, body: str = ""):
    alert(parent, heading, body)


def copy_to_clipboard(widget: Gtk.Widget, text: str):
    widget.get_clipboard().set(shown(text))

def combo_row(title: str, labels: list[str], selected: int = 0, subtitle: str = "") -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_list_factory(_combo_list_factory(row))
    row.set_selected(max(0, min(selected, len(labels) - 1)))
    return row

def _combo_list_factory(row: Adw.ComboRow) -> Gtk.SignalListItemFactory:
    """Liste déroulante d'un Adw.ComboRow : celle de libadwaita abrège les choix longs
    (« Intelligent (bei mehreren E… ») ; ici, texte entier et même coche pour le choix actuel."""
    boxes: list = []

    def setup(_f, li):
        box = Gtk.Box(spacing=6)
        box._label = Gtk.Label(xalign=0, hexpand=True)
        box._check = Gtk.Image(icon_name="object-select-symbolic")
        box.append(box._label)
        box.append(box._check)
        box._pos = -1
        boxes.append(box)
        li.set_child(box)

    def bind(_f, li):
        box = li.get_child()
        box._pos = li.get_position()
        box._label.set_label(li.get_item().get_string())
        box._check.set_opacity(1 if box._pos == row.get_selected() else 0)

    def refresh(*_):
        for box in boxes:
            box._check.set_opacity(1 if box._pos == row.get_selected() else 0)

    f = Gtk.SignalListItemFactory()
    f.connect("setup", setup)
    f.connect("bind", bind)
    row.connect("notify::selected", refresh)
    return f


def clear_box(box: Gtk.Widget):
    while (c := box.get_first_child()) is not None:
        box.remove(c)

def popup_menu(parent: Gtk.Widget, model, x: float, y: float) -> Gtk.PopoverMenu:
    """Menu contextuel. Un seul menu par widget, gardé et réutilisé (comme Nautilus), jamais détruit à
    la fermeture : fermé par Échap, la souris encore dessus, GTK 4.14 gardait une entrée du menu
    détruit comme widget sous le pointeur, et la mise en page suivante de la fenêtre plantait
    (gtk_window_native_layout → gdk_surface_request_motion sur une surface nulle)."""
    pop = getattr(parent, "_sirene_popover", None)
    if pop is None or pop.get_parent() is not parent:
        pop = Gtk.PopoverMenu.new_from_model(model)
        pop.set_parent(parent)
        pop.set_has_arrow(False)
        pop.set_halign(Gtk.Align.START)
        parent._sirene_popover = pop
        # widget retiré pour de bon (panneau fermé, ligne de résultats supprimée) : menu détaché avec
        # lui, sinon GTK signale un enfant encore attaché quand il le libère
        parent.connect("unrealize", _drop_popover)
    else:
        pop.set_menu_model(model)
    r = Gdk.Rectangle()
    r.x, r.y, r.width, r.height = int(x), int(y), 1, 1
    pop.set_pointing_to(r)
    pop.popup()
    return pop

def _drop_popover(parent: Gtk.Widget):
    pop = getattr(parent, "_sirene_popover", None)
    if pop is not None and pop.get_parent() is parent:
        pop.unparent()
    parent._sirene_popover = None

