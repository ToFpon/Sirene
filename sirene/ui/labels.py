"""Libellés des choix des écouteurs (identifiants du moteur → texte traduit). Un identifiant inconnu (code
que les écouteurs proposent sans qu'on sache son nom, « 4 ») s'affiche tel quel."""

from __future__ import annotations

from ..i18n import tr


def _table():
    return {
        # contrôle du bruit
        "off": tr("Désactivé"),
        "cancellation": tr("Réduction de bruit"),
        "awareness": tr("Transparence"),
        "comfort": tr("Confort"),
        "normal": tr("Normal"),
        "ultra": tr("Ultra"),
        "dynamic": tr("Dynamique"),
        "voice_boost": tr("Voix renforcée"),
        # gestes
        "play_pause": tr("Lecture / pause"),
        "next": tr("Morceau suivant"),
        "previous": tr("Morceau précédent"),
        "assistant": tr("Assistant vocal"),
        "answer": tr("Répondre / raccrocher"),
        "switch_anc": tr("Changer le contrôle du bruit"),
        "volume": tr("Régler le volume"),
        "volume_up": tr("Monter le volume"),
        "volume_down": tr("Baisser le volume"),
        "off_on": tr("Désactivé, réduction"),
        "off_on_awareness": tr("Désactivé, réduction, transparence"),
        "on_awareness": tr("Réduction, transparence"),
        "off_awareness": tr("Désactivé, transparence"),
        # son
        "default": tr("Par défaut"),
        "bass": tr("Basses renforcées"),
        "treble": tr("Aigus renforcés"),
        "voices": tr("Voix"),
        "symphony": tr("Symphonie"),
        "hifi_live": tr("Hi-Fi Live"),
        "connectivity": tr("Priorité à la connexion"),
        "quality": tr("Priorité à la qualité du son"),
    }


_cache: dict = {}


def label(value) -> str:
    if not _cache:
        _cache.update(_table())
    if value is None or value == "":
        return "—"
    return _cache.get(value, str(value))


# Gestes : (propriété, titre) — une ligne par propriété que les écouteurs annoncent.
def gesture_rows():
    return [
        ("double_tap_left", tr("Double tape, écouteur gauche")),
        ("double_tap_right", tr("Double tape, écouteur droit")),
        ("double_tap_in_call", tr("Double tape pendant un appel")),
        ("triple_tap_left", tr("Triple tape, écouteur gauche")),
        ("triple_tap_right", tr("Triple tape, écouteur droit")),
        ("long_tap_left", tr("Appui long, écouteur gauche")),
        ("long_tap_right", tr("Appui long, écouteur droit")),
        ("long_tap_in_call", tr("Appui long pendant un appel")),
        ("noise_control_left", tr("Modes parcourus, écouteur gauche")),
        ("noise_control_right", tr("Modes parcourus, écouteur droit")),
        ("swipe", tr("Glisser sur la tige")),
    ]


def options_key(prop: str) -> str:
    """Propriété → celle qui porte la liste des choix (« double_tap_left » → « double_tap_options »)."""
    if prop.endswith("_in_call"):
        return prop + "_options"
    for side in ("_left", "_right"):
        if prop.endswith(side):
            return prop[: -len(side)] + "_options"
    return prop + "_options"
