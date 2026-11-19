"""Fonctionnalités facultatives de Sirène, toutes désactivables sans redémarrage.

Chaque fonctionnalité se consulte au moment de l'usage (enabled(id)), jamais à l'import :
Préférences → Fonctionnalités l'active ou la coupe tout de suite. (Repris de Télémaque.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .i18n import tr
from .settings import settings


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    description: str
    icon: str
    default: bool = True
    available: Optional[Callable[[], bool]] = None    # composant indispensable présent ? (sinon grisée)
    missing: str = ""                                 # ce qu'il faut installer


def _osd_available() -> bool:
    from .volume_osd import available
    return available()


FEATURES = [
    Feature("auto_pause", tr("Pause au retrait d'un écouteur"),
            tr("Les lecteurs qui jouaient se mettent en pause quand on retire un écouteur, et reprennent quand "
               "on le remet (seulement ceux que Sirène a mis en pause)"),
            "media-playback-pause-symbolic"),
    Feature("tray", tr("Icône dans la barre du haut"),
            tr("Batterie et contrôle du bruit à portée de clic ; fermer la fenêtre laisse Sirène en arrière-plan "
               "(extension AppIndicator, présente sur Zorin et Ubuntu)"),
            "view-app-grid-symbolic"),
    Feature("notify_connect", tr("Prévenir des connexions Bluetooth"),
            tr("Une notification quand un appareil Bluetooth se connecte ou se déconnecte (écouteurs, souris, "
               "téléphone…), comme bt-notify"),
            "bluetooth-active-symbolic"),
    Feature("battery_alert", tr("Prévenir quand la batterie est faible"),
            tr("Une notification quand un écouteur passe sous 20 %, puis sous 10 %"),
            "battery-caution-symbolic"),
    Feature("volume_osd", tr("Afficher le volume"),
            tr("L'encart du volume de GNOME à chaque changement, pendant que les écouteurs sont connectés (geste "
               "de glisser compris), comme bt-notify"),
            "audio-volume-high-symbolic", available=_osd_available,
            missing=tr("Demande l'extension GNOME « Custom OSD » (extensions.gnome.org) et pactl")),
]

BY_ID = {f.id: f for f in FEATURES}


def enabled(fid: str) -> bool:
    f = BY_ID.get(fid)
    if f is None:
        return False
    value = settings["features"].get(fid, f.default)
    return value if isinstance(value, bool) else f.default     # « "no" » écrit à la main ne vaut pas vrai


def blocked(fid: str) -> bool:
    f = BY_ID.get(fid)
    return f is not None and f.available is not None and not f.available()


def set_enabled(fid: str, value: bool):
    feats = dict(settings["features"])
    feats[fid] = bool(value)
    settings["features"] = feats
