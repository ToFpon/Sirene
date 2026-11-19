"""Modèles pris en charge : canal RFCOMM et fonctions de chacun (d'après les pilotes d'OpenFreebuds,
FreeBuds 7i : pull request #135). Un modèle est reconnu par le nom Bluetooth des écouteurs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import handlers as h


@dataclass(frozen=True)
class Model:
    name: str
    channel: int                        # canal RFCOMM du service Huawei
    make: Callable[[], list]            # fonctions (nouvelles instances à chaque connexion)
    wear_per_bud: bool = False          # état gauche / droit fiable (2B25 complète)


def _4i():
    return [h.Logs(), h.Info(), h.InEar(), h.Anc(), h.Battery(), h.DoubleTap(), h.LongTap(), h.AutoPause(),
            h.VoiceLanguage()]


def _6i():
    return [h.Info(), h.InEar(wear=True), h.Battery(), h.Anc(levels=True, dynamic=True),
            h.DoubleTap(in_call=True), h.TripleTap(), h.LongTap(right=True), h.Swipe(), h.AutoPause(),
            h.SoundQuality(), h.LowLatency(),
            h.Equalizer(presets=h.BUILT_IN, fake_built_in=True, custom=True),
            h.VoiceLanguage(), h.DualConnect(auto_connect=False)]


def _7i():
    return [h.Info(), h.InEar(wear=True, wear_read=True), h.Battery(),
            h.Anc(levels=True, dynamic=True, voice_boost=True),
            h.DoubleTap(in_call=True), h.TripleTap(), h.LongTap(right=True), h.Swipe(), h.AutoPause(),
            h.SoundQuality(), h.LowLatency(),
            h.Equalizer(presets=h.BUILT_IN, fake_built_in=True, custom=True),
            h.DualConnect(auto_connect=False)]


MODELS = {m.name: m for m in (
    Model("HUAWEI FreeBuds 4i", 16, _4i),
    Model("HUAWEI FreeBuds 6i", 1, _6i),
    Model("HUAWEI FreeBuds 7i", 1, _7i, wear_per_bud=True),
)}
ALIASES = {"HONOR Earbuds 2": "HUAWEI FreeBuds 4i", "HONOR Earbuds 2 SE": "HUAWEI FreeBuds 4i",
           "HONOR Earbuds 2 Lite": "HUAWEI FreeBuds 4i"}


def find(name: str) -> Model | None:
    """Modèle d'après le nom Bluetooth (« HUAWEI FreeBuds 6i »), None s'il n'est pas pris en charge."""
    name = (name or "").strip()
    return MODELS.get(ALIASES.get(name, name))
