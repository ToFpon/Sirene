# Sirène — notes de travail

Réglages des écouteurs Huawei FreeBuds (6i, 7i, 4i) en GTK4 / libadwaita, en Python, dans la famille
d'Odysseus, Nausicaa, Calypso, Télémaque et Ithaca (même ossature à venir : i18n, réglages, fonctionnalités,
vrais dialogues, icône de la barre, tests, paquet). Idée de Tof : remplacer OpenFreebuds (Qt) + sa bidouille
d'auto-pause et de notifications (`bt-notify.sh`) par une seule application GNOME en .deb.
Nom : dans l'Odyssée, Ulysse bouche à la cire les oreilles de son équipage contre le chant des Sirènes —
les premiers écouteurs à réduction de bruit.

## Règles

- Répondre à Tof en français, tutoiement, avis francs. Messages de commit en français.
- Cible : Zorin OS 18.1 (Ubuntu 24.04, GNOME 46, X11, GTK 4.14, libadwaita 1.5, Python 3.12). Pas d'API plus
  récente (pas d'Adw.Dialog, Adw.AlertDialog…). Paquets apt seulement.
- Travail directement sur main (comme les autres applications de Tof).
- Le `python3` du bac à sable n'a pas `gi` : utiliser `python3.12`.
- Reprise d'OpenFreebuds (melianmiko/OpenFreebuds, GPL-3.0 ; FreeBuds 7i : pull request #135 de vicrodh,
  fork vicrodh/OpenFreebuds, branche feature/freebuds-7i) : protocole et pilotes réécrits, à créditer dans
  debian/copyright, le README et « À propos ».
- Périmètre voulu par Tof : toutes les fonctions d'OpenFreebuds pour ses modèles ; PAS les mouvements de tête
  des 7i (ni l'audio spatial, ni la réduction sur un seul écouteur : pull request #139, pas encore acceptée).

## Architecture (moteur, sans GTK)

- `backend/protocol.py` : trame = `5A | longueur (2) | 00 | commande (2) | paramètres (type, taille, valeur)… |
  CRC-16 XMODEM (2)` ; longueur = 00 + commande + paramètres. `Packet.read(cmd, types)` (valeurs vides, réponse =
  même commande), `Packet.write`. `FrameReader` : découpe le flux, se recale sur le 5A suivant (trame fausse,
  octet perdu). `str(pkt)` = écriture du journal de MyBuds (« cmd=2B25 p1=01 p2=00 ») : captures comparables.
  CRC vérifié sur de vraies trames des 7i (`test_protocol`).
- `backend/handlers.py` : une classe par fonction (Info, Battery, InEar, Anc, AutoPause, LowLatency,
  SoundQuality, VoiceLanguage, DoubleTap, TripleTap, LongTap, Swipe, Equalizer, DualConnect, Logs). `init(dev)`
  demande l'état (bloquant, fil de travail) ; `on_packet` lit ce que les écouteurs envoient (fil de lecture,
  JAMAIS de demande bloquante dedans : on attendrait sa propre lecture → `dev.later`) ; `set` écrit.
  Valeurs en types Python, choix en identifiants (« cancellation », « play_pause »…) traduits par l'interface.
  Repris tel quel d'OpenFreebuds, validé chez eux sur les vrais écouteurs : mode ANC écrit « mode, FF » ;
  préréglages Symphonie / Hi-Fi Live envoyés comme personnalisés sous le nom « 200 » / « 201 » (un nom de plus
  de 24 octets : les 7i ignorent l'écriture sans répondre) ; LowLatency relu 1 s après l'écriture.
  Corrigé au passage : l'appui long « pendant un appel » lisait p2 au lieu de p4.
- `backend/models.py` : modèle reconnu par le nom Bluetooth ; canal RFCOMM (6i, 7i : 1 ; 4i : 16) et fonctions.
- `backend/device.py` : `Device` = socket RFCOMM (`socket.AF_BLUETOOTH`, rien à installer), fil de lecture, fil
  de travail (une demande à la fois : les écouteurs n'en traitent qu'une), valeurs (`store`), `on_change` appelé
  depuis ces fils (l'interface passera par idle_add). Fonction sans réponse : réessayée (3 fois), notée dans
  `failed`, les autres démarrent quand même. Trames inconnues gardées dans `unknown` (diagnostic).
- `backend/bluez.py` : appareils de BlueZ par D-Bus (adresse, nom, connecté).
- `sirene/probe.py` : diagnostic en ligne de commande (`python3.12 -m sirene.probe [MAC] [--debug] [--set
  groupe.prop=valeur]`) — tout ce que disent les écouteurs, puis chaque changement. Premier essai réel chez Tof.

## Port des écouteurs et auto-pause (vu chez Tof, novembre 2026)

- Trame 2B25 : p1 = gauche, p2 = droit (01 porté, 00 retiré). 7i : y répondent sur demande et l'annoncent pour
  les deux écouteurs (auto-pause validée par Tof avec l'AppImage du fork d'OpenFreebuds). 6i : l'annoncent
  d'elles-mêmes mais p1 reste à 01 — le gauche n'est JAMAIS signalé (ni par 2B25, ni par une autre trame, ni par
  AVRCP : `btmon` muet, même sans programme connecté). Micrologiciel ; rien à faire côté PC.
- 4i : font la pause elles-mêmes (AVRCP), sans programme. Le réglage dans les écouteurs : 2B11 lecture /
  2B10 écriture (p1 = 1 activé), vu à 01 sur les 6i de Tof.
- Puce Bluetooth de Tof : MediaTek MT7922 (0e8d:7922) ; elle transmet bien les gestes (hors de cause).

## Tests

```sh
python3.12 -m unittest discover -s tests        # trames + fonctions contre de faux écouteurs (socketpair)
python3 -m pyflakes sirene tests
```

`tests/fake_buds.py` : faux écouteurs qui répondent d'après un modèle {trame demandée : [réponses]} (comme le
banc d'essai d'OpenFreebuds) et envoient des trames spontanées (`push`). Trames réelles : 7i (tests de la
pull request #135, capturées depuis AI Life), 6i (captures de MyBuds chez Tof). Pas d'écouteurs dans le bac à
sable : les essais réels sont faits par Tof.

## Feuille de route

1. FAIT : squelette, protocole, toutes les fonctions des 4i / 6i / 7i, connexion, diagnostic.
2. Essai réel de `sirene.probe` sur les 6i de Tof (puis les 7i à Noël).
3. Interface GTK4 (ossature de Télémaque) : page de l'appareil (batterie, contrôle du bruit, gestes, égaliseur,
   double connexion, réglages), suivi de BlueZ (connexion / déconnexion, sans boucle sur un appareil absent).
4. Auto-pause par MPRIS (lecteurs qui jouaient seulement, comme lola-autopause), icône de la barre avec la
   batterie, alerte batterie faible, action à la connexion, raccourcis globaux (X11).
5. Reprise de `bt-notify.sh` : notifications de connexion et affichage du volume.
6. Paquet, PPA, site.
