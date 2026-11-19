"""Préférences persistantes (JSON dans ~/.config/sirene). Seules les valeurs choisies par l'utilisateur sont
écrites : une valeur par défaut corrigée plus tard s'applique à tous ceux qui n'y ont pas touché.
(Repris de Télémaque.)"""

from __future__ import annotations

import json
import os
from typing import Any

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "sirene")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS: dict[str, Any] = {
    "theme": "system",              # system, light, dark
    "language": "system",           # system, fr, en, de (appliqué au prochain démarrage)
    "window_width": 560,
    "window_height": 760,
    "window_maximized": False,
    "features": {},                 # fonctionnalités activées / désactivées (voir features.py)
}


def _fits(value, default) -> bool:
    """Valeur du bon type (un settings.json abîmé ou écrit à la main ne doit rien casser)."""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


class Settings:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self.data: dict[str, Any] = {}
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data = {k: v for k, v in loaded.items() if k in DEFAULTS and _fits(v, DEFAULTS[k])}
        except (OSError, ValueError):
            pass
        self._listeners = []

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        if self[key] == value:
            return
        self.data[key] = value
        self.save()
        for cb in list(self._listeners):
            cb(key, value)

    def connect(self, cb):
        self._listeners.append(cb)

    def disconnect(self, cb):
        if cb in self._listeners:
            self._listeners.remove(cb)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


settings = Settings()
