"""Affichage du volume à chaque changement, pendant que les écouteurs sont connectés — repris de bt-notify.sh de
Tof : `pactl subscribe` (événements « 'change' on sink », LC_ALL=C), puis `pactl get-sink-volume @DEFAULT_SINK@`,
affiché par l'extension GNOME « Custom OSD » (neuromorph/custom-osd, extensions.gnome.org) : clé `showosd` =
« aléa,icône,texte,niveau » (l'aléa force le changement de valeur ; l'extension découpe aux virgules).

GNOME Shell n'offre pas d'autre moyen d'afficher SON encart à une application ; une fenêtre à nous ne pourrait
pas se placer sous Wayland. Sans l'extension : la fonctionnalité est grisée (Préférences).
"""

from __future__ import annotations

import logging
import os
import random
import re
import shutil
from typing import Callable, Optional

from gi.repository import Gio, GLib

log = logging.getLogger("sirene.osd")

SCHEMA_ID = "org.gnome.shell.extensions.custom-osd"
UUID = "custom-osd@neuromorph"


def _schema_dirs() -> list[str]:
    out = [os.path.join(GLib.get_user_data_dir(), "gnome-shell", "extensions", UUID, "schemas")]
    out += [os.path.join(d, "gnome-shell", "extensions", UUID, "schemas") for d in GLib.get_system_data_dirs()]
    return out


SCHEMA_DIRS = _schema_dirs           # remplaçable par les tests


def osd_settings(backend=None) -> Optional[Gio.Settings]:
    """Réglages de l'extension (schéma installé avec le système, sinon dans le dossier de l'extension)."""
    default = Gio.SettingsSchemaSource.get_default()
    schema = default.lookup(SCHEMA_ID, True) if default else None
    for d in ([] if schema else SCHEMA_DIRS()):
        if os.path.exists(os.path.join(d, "gschemas.compiled")):
            try:
                src = Gio.SettingsSchemaSource.new_from_directory(d, default, False)
            except GLib.Error:
                continue
            schema = src.lookup(SCHEMA_ID, False)
            if schema:
                break
    if schema is None or not schema.has_key("showosd"):
        return None
    return Gio.Settings.new_full(schema, backend, None)


def available() -> bool:
    return shutil.which("pactl") is not None and osd_settings() is not None


def osd_command(icon: str, text: str, percent: int) -> str:
    text = text.replace(",", " ")                       # l'extension découpe aux virgules
    return f"{random.randint(1, 32767)},{icon},{text},{min(percent, 100) / 100:.2f}"


def parse_volume(text: str) -> Optional[int]:
    """« Volume: front-left: 45000 /  69% / -9.60 dB, … » → 69."""
    m = re.search(r"(\d+)%", text)
    return int(m.group(1)) if m else None


class VolumeWatcher:
    """`pactl subscribe` lu dans la boucle GLib ; `on_volume(pourcentage)` à chaque changement réel du volume."""

    def __init__(self, on_volume: Callable[[int], None], pactl: str = "pactl"):
        self.on_volume = on_volume
        self.pactl = pactl
        self._proc = None
        self._cancel = None
        self._reading = False
        self._again = False
        self.last: Optional[int] = None

    def start(self):
        if self._proc is not None:
            return
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        launcher.setenv("LC_ALL", "C", True)             # messages en anglais quelle que soit la langue
        try:
            self._proc = launcher.spawnv([self.pactl, "subscribe"])
        except GLib.Error as e:
            log.info("pactl : %s", e.message)
            return
        self._cancel = Gio.Cancellable()
        self._lines = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._next_line()
        self._read_volume()                             # point de départ (pas d'affichage)

    def stop(self):
        if self._proc is None:
            return
        self._cancel.cancel()
        self._proc.force_exit()
        self._proc = None
        self.last = None

    def _next_line(self):
        self._lines.read_line_async(GLib.PRIORITY_DEFAULT, self._cancel, self._on_line, self._proc)

    def _on_line(self, stream, res, proc):
        try:
            raw, _ = stream.read_line_finish(res)
        except GLib.Error:
            return
        if raw is None or proc is not self._proc:
            return                                      # pactl arrêté
        line = bytes(raw).decode("utf-8", "replace")
        if "'change' on sink " in line:
            self._read_volume()
        self._next_line()

    def _read_volume(self):
        if self._reading:                               # rafale d'événements : une seule lecture à la fois
            self._again = True
            return
        self._reading = True
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        launcher.setenv("LC_ALL", "C", True)
        try:
            p = launcher.spawnv([self.pactl, "get-sink-volume", "@DEFAULT_SINK@"])
        except GLib.Error:
            self._reading = False
            return
        p.communicate_utf8_async(None, None, self._on_volume_read, self.last is None)

    def _on_volume_read(self, p, res, first):
        self._reading = False
        try:
            _ok, out, _err = p.communicate_utf8_finish(res)
        except GLib.Error:
            out = ""
        level = parse_volume(out or "")
        if level is not None and self._proc is not None:
            changed = level != self.last
            self.last = level
            if changed and not first:
                self.on_volume(level)
        if self._again:
            self._again = False
            self._read_volume()
