"""Pause au retrait d'un écouteur, par MPRIS (D-Bus de session) — la logique de lola-autopause.sh de Tof :
chaque lecteur est regardé à part (« playerctl status » sans -p ne voyait que le premier : avec Brave + VLC
ouverts, VLC n'était jamais mis en pause) ; au retour, seuls les lecteurs que NOUS avons mis en pause
reprennent, jamais un lecteur que l'utilisateur avait arrêté lui-même.

Appels D-Bus faits dans un fil (un lecteur qui ne répond pas ne fige pas la fenêtre)."""

from __future__ import annotations

import logging
import threading

from gi.repository import Gio, GLib

log = logging.getLogger("sirene.autopause")

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
TIMEOUT_MS = 1000


class AutoPause:
    def __init__(self, bus=None):
        self._bus = bus
        self.paused: list[str] = []          # lecteurs mis en pause par nous
        self._lock = threading.Lock()

    def bus(self):
        if self._bus is None:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return self._bus

    def players(self) -> list[str]:
        reply = self.bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                     "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                                     TIMEOUT_MS, None)
        return sorted(n for n in reply.unpack()[0] if n.startswith(PREFIX))

    def status(self, name: str) -> str:
        reply = self.bus().call_sync(name, PATH, "org.freedesktop.DBus.Properties", "Get",
                                     GLib.Variant("(ss)", (PLAYER, "PlaybackStatus")), GLib.VariantType("(v)"),
                                     Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
        return reply.unpack()[0]

    def _call(self, name: str, method: str):
        self.bus().call_sync(name, PATH, PLAYER, method, None, None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)

    # --- synchrones (dans un fil) ---

    def pause_playing(self) -> list[str]:
        with self._lock:
            done = []
            try:
                names = self.players()
            except GLib.Error as e:
                log.info("lecteurs introuvables : %s", e.message)
                return []
            for name in names:
                try:
                    if self.status(name) == "Playing":
                        self._call(name, "Pause")
                        done.append(name)
                except GLib.Error as e:
                    log.info("%s : %s", name, e.message)
            self.paused = done
            return done

    def resume_paused(self) -> list[str]:
        with self._lock:
            done = []
            for name in self.paused:
                try:
                    self._call(name, "Play")
                    done.append(name)
                except GLib.Error as e:          # lecteur fermé entre-temps
                    log.info("%s : %s", name, e.message)
            self.paused = []
            return done

    # --- pour l'interface ---

    def pause_later(self):
        threading.Thread(target=self.pause_playing, name="sirene-pause", daemon=True).start()

    def resume_later(self):
        threading.Thread(target=self.resume_paused, name="sirene-reprise", daemon=True).start()
