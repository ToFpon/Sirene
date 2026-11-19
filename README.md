# Sirène

Settings for HUAWEI FreeBuds earphones (6i, 7i, 4i) on GNOME, in GTK4 / libadwaita — noise control,
gestures, equalizer, battery, dual connect, and auto-pause when an earbud is taken out.

*Work in progress: the engine (protocol and every function of these models) is written and tested against
recorded frames; the interface comes next.*

Try the engine on real earphones (close OpenFreebuds or MyBuds first: only one program at a time can talk
to them):

```sh
python3 -m sirene.probe            # everything the earphones report, then every change, until Ctrl+C
python3 -m sirene.probe --debug    # plus every frame exchanged
```

## Credits

The HUAWEI protocol and per-model drivers come from [OpenFreebuds](https://github.com/melianmiko/OpenFreebuds)
by melianmiko (GPL-3.0), FreeBuds 7i support by [vicrodh](https://github.com/vicrodh/OpenFreebuds)
(pull request #135). Rewritten without asyncio for a GTK application.

## License

GPL-3.0-or-later.

---

# Sirène (français)

Réglages des écouteurs HUAWEI FreeBuds (6i, 7i, 4i) sous GNOME, en GTK4 / libadwaita : contrôle du bruit,
gestes, égaliseur, batterie, double connexion, et pause quand on retire un écouteur.

*En cours : le moteur (protocole et toutes les fonctions de ces modèles) est écrit et testé sur des trames
enregistrées ; l'interface arrive ensuite.*

Essayer le moteur sur de vrais écouteurs (fermer d'abord OpenFreebuds ou MyBuds : un seul programme à la fois) :

```sh
python3 -m sirene.probe            # tout ce que disent les écouteurs, puis chaque changement, jusqu'à Ctrl+C
python3 -m sirene.probe --debug    # + chaque trame échangée
```

Protocole et pilotes repris d'[OpenFreebuds](https://github.com/melianmiko/OpenFreebuds) (melianmiko, GPL-3.0),
FreeBuds 7i par [vicrodh](https://github.com/vicrodh/OpenFreebuds) (pull request #135).
