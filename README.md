# Sirène

Settings for HUAWEI FreeBuds earphones (6i, 7i, 4i) on GNOME, in GTK4 / libadwaita — noise control,
gestures, equalizer, battery, dual connect, and auto-pause when an earbud is taken out.

Sirène finds the earphones on its own when they connect, pauses the players when an earbud is taken out, and
waits in the background with an icon in the top bar while they are connected (batteries, noise control). It can
also announce Bluetooth connections, low batteries and volume changes (with the Custom OSD extension).

Website: https://tofmicro.pages-perso.free.fr/Sirene/

## Install

Ubuntu 24.04 / 26.04, Zorin OS 18, Linux Mint 22:

```sh
sudo add-apt-repository ppa:nourpon/sirene
sudo apt update && sudo apt install sirene
```

Other Debian-based distributions (Debian 13…): the .deb of the GitHub Releases, `sudo apt install ./sirene_*_all.deb`.

Close OpenFreebuds or MyBuds first: only one program at a time can talk to the earphones.

Diagnosis from the sources: `python3 -m sirene.probe [--debug]` prints everything the earphones report.

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

Sirène trouve les écouteurs toute seule quand ils se connectent, met les lecteurs en pause quand on retire un
écouteur, et attend en arrière-plan avec une icône dans la barre du haut pendant qu'ils sont connectés (batteries,
contrôle du bruit). Elle peut aussi annoncer les connexions Bluetooth, la batterie faible et le volume (avec
l'extension Custom OSD).

```sh
sudo add-apt-repository ppa:nourpon/sirene
sudo apt update && sudo apt install sirene
```

Fermer d'abord OpenFreebuds ou MyBuds : un seul programme à la fois peut parler aux écouteurs.

Protocole et pilotes repris d'[OpenFreebuds](https://github.com/melianmiko/OpenFreebuds) (melianmiko, GPL-3.0),
FreeBuds 7i par [vicrodh](https://github.com/vicrodh/OpenFreebuds) (pull request #135).
