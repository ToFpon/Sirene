"""Diagnostic en ligne de commande, en attendant l'interface : se connecte aux écouteurs, affiche tout ce
qu'ils disent, puis chaque changement (retrait d'un écouteur, batterie, contrôle du bruit…) jusqu'à Ctrl+C.

    python3.12 -m sirene.probe                     # premiers écouteurs pris en charge et connectés
    python3.12 -m sirene.probe CC:B0:A8:AB:43:43   # ceux-là
    python3.12 -m sirene.probe --debug             # + chaque trame échangée (RX / TX)
    python3.12 -m sirene.probe --set anc.mode=cancellation

Ne pas lancer en même temps qu'OpenFreebuds ou MyBuds : un seul programme à la fois sur le canal.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

from .backend import bluez, models
from .backend.device import Device
from .backend.handlers import as_text


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sirene.probe")
    ap.add_argument("address", nargs="?")
    ap.add_argument("--model", help="nom du modèle si le nom Bluetooth n'est pas reconnu")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="GROUPE.PROP=VALEUR")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    found = bluez.devices()
    if args.address:
        found = [d for d in found if d.address.upper() == args.address.upper()]
    else:
        found = [d for d in found if d.connected and models.find(d.name)]
    if not found:
        print("Aucun écouteur pris en charge et connecté. Modèles :", ", ".join(models.MODELS))
        return 1
    bt = found[0]
    model = models.find(args.model or bt.name)
    if model is None:
        print(f"« {bt.name} » n'est pas reconnu ; essayez --model, parmi :", ", ".join(models.MODELS))
        return 1
    print(f"{bt.name} ({bt.address}) — modèle {model.name}, canal {model.channel}")

    started = threading.Event()

    def changed(group, prop, value):
        if started.is_set():
            print(time.strftime("%H:%M:%S"), f"{group}.{prop} = {as_text(value)}", flush=True)

    dev = Device(model, bt.address, on_change=changed)
    try:
        dev.start()
    except OSError as e:
        print("Connexion refusée :", e, "(OpenFreebuds ou MyBuds tourne-t-il déjà ?)")
        return 1
    dev.ready.wait(60)
    for group in sorted(dev.store):
        for prop, value in sorted(dev.store[group].items()):
            print(f"  {group}.{prop} = {as_text(value)}")
    if dev.failed:
        print("Sans réponse :", ", ".join(dev.failed))
    for item in args.set:
        key, _, text = item.partition("=")
        group, _, prop = key.partition(".")
        done = threading.Event()
        dev.set(group, prop, _value(text), done=lambda e: (print("→", key, "erreur :" if e else "fait", e or ""),
                                                           done.set()))
        done.wait(15)
    print("En écoute (Ctrl+C pour quitter)…", flush=True)
    started.set()
    try:
        while dev.alive:
            time.sleep(0.5)
        print("Écouteurs déconnectés.")
    except KeyboardInterrupt:
        pass
    finally:
        if dev.unknown:
            print("Trames non comprises :", *(str(p) for p in dev.unknown.values()), sep="\n  ")
        dev.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
