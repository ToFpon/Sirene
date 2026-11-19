"""Lancement à l'ouverture de session : ~/.config/autostart/<APP_ID>.desktop, Sirène démarré en arrière-plan
(`--background` : pas de fenêtre, seulement l'icône de la barre). Installé : la commande `sirene` ; lancé depuis
les sources : ce Python et bin/sirene (chemins absolus)."""

from __future__ import annotations

import os
import shlex
import shutil
import sys

from gi.repository import GLib

from . import APP_ID, APP_NAME

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path() -> str:
    return os.path.join(GLib.get_user_config_dir(), "autostart", APP_ID + ".desktop")


def command() -> str:
    installed = shutil.which("sirene")
    if installed and not os.path.realpath(installed).startswith(ROOT):
        return "sirene --background"
    return shlex.join([sys.executable, os.path.join(ROOT, "bin", "sirene"), "--background"])


def enabled() -> bool:
    return os.path.exists(path())


def set_enabled(on: bool):
    p = path()
    if not on:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Application\n"
                 f"Name={APP_NAME}\nIcon={APP_ID}\nExec={command()}\n"
                 "Terminal=false\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n")
    os.replace(tmp, p)
