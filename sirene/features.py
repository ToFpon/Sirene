"""Fonctionnalités facultatives de Sirène, toutes désactivables sans redémarrage.

Chaque fonctionnalité se consulte au moment de l'usage (enabled(id)), jamais à l'import :
Préférences → Fonctionnalités l'active ou la coupe tout de suite. (Repris de Télémaque.)
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import tr
from .settings import settings


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    description: str
    icon: str
    default: bool = True


FEATURES = [
    Feature("auto_pause", tr("Pause au retrait d'un écouteur"),
            tr("Les lecteurs qui jouaient se mettent en pause quand on retire un écouteur, et reprennent quand "
               "on le remet (seulement ceux que Sirène a mis en pause)"),
            "media-playback-pause-symbolic"),
]

BY_ID = {f.id: f for f in FEATURES}


def enabled(fid: str) -> bool:
    f = BY_ID.get(fid)
    if f is None:
        return False
    value = settings["features"].get(fid, f.default)
    return value if isinstance(value, bool) else f.default     # « "no" » écrit à la main ne vaut pas vrai


def set_enabled(fid: str, value: bool):
    feats = dict(settings["features"])
    feats[fid] = bool(value)
    settings["features"] = feats
