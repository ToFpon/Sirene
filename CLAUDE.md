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
- Tout texte visible passe par `tr()` / `ntr()`. Après modification : `python3 tools/update-pot.py`, compléter
  `data/locale/en.po` et `de.po`, puis `msgfmt -c --statistics` et `msgcmp`. Ossature (i18n, settings, features,
  ui/common, préférences) reprise de Télémaque.
- Dialogues : de vraies fenêtres (`common.AlertDialog`, `common.DialogWindow`, `Adw.PreferencesWindow`,
  `Adw.AboutWindow`). Thème du système : `data/base.css` ne fait que de la mise en page.
- Chaque fonctionnalité facultative est dans `sirene/features.py` (auto_pause, tray, notify_connect, battery_alert,
  volume_osd) et se consulte au moment de l'usage. `available` / `missing` : composant absent → interrupteur grisé
  avec la raison (`features.blocked`).
- Toute fonction passée à `idle_add` / `timeout_add` renvoie False (sauf répétition voulue).
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

## Interface

- `app.py` : `SireneApp` (instance unique). Suit BlueZ (`bluez.Watcher` : PropertiesChanged / InterfacesAdded /
  Removed, AUCUNE interrogation) ; écouteurs pris en charge connectés → `Device` ouvert dans un fil (2, 5, 10 s de
  plus si le canal refuse : il n'est pas toujours prêt juste après la connexion ; puis page « Impossible de
  joindre », avec Réessayer — souvent OpenFreebuds ou MyBuds qui tient le canal) ; partis → canal fermé ; canal
  fermé par les écouteurs alors que BlueZ les dit connectés → rouvert. Jamais de tentative vers un absent.
  Valeurs du moteur → `idle_add(_on_change, …, prêt)`. PIÈGE vu au test : « prêt » se lit AU MOMENT de l'annonce
  (fil du moteur) ; lu dans l'idle_add, dev.ready est déjà posé et le « pas portés » d'office du démarrage
  déclenchait pause puis reprise. Valeurs arrivées avant `_opened` : non relayées, la page relit tout.
  Écriture : `set_value` → `Device.set` ; échec (pas de réponse) → toast et la ligne reprend la vraie valeur.
- `backend/autopause.py` : MPRIS, la logique de lola-autopause.sh (lecteur par lecteur, seuls ceux que nous avons
  mis en pause reprennent), appels D-Bus dans un fil. Retrait = `state.in_ear` vrai → faux (les deux portés →
  un retiré), seulement après le démarrage.
- Arrière-plan et barre du haut (fonctionnalité `tray`, active par défaut) : `sirene/tray.py` = StatusNotifierItem
  + dbusmenu de Télémaque / Ithaca, généralisé (`app.tray_items()` / `tray_text()` / `tray_activate()`, entrées
  radio pour le contrôle du bruit, `update()` republie si le menu a changé). Bulle et première ligne :
  « FreeBuds 6i — G 100 % · D 100 % · Boîtier 67 % » (un écouteur à 0 % = rangé, omis). Fermer la fenêtre
  la CACHE s'il y a une barre (icône acceptée, ou org.kde.StatusNotifierWatcher présent : `tray_bar_present`),
  sinon quitte. Réglage `tray_only_connected` (vrai par défaut, demande de Tof : « démarrer seulement à la
  connexion des écouteurs ») : Sirène tourne dès l'ouverture de session (aucune interrogation, rien ne coûte), mais
  l'icône n'apparaît que pendant que des écouteurs pris en charge sont connectés (`_sync_tray`, à chaque état).
  Un vrai démarrage « à la connexion » demanderait de toute façon un programme qui écoute BlueZ.
  PIÈGE vu chez Tof : l'icône restait après la déconnexion, jusqu'à la sortie de Sirène — l'extension AppIndicator
  suit le nom UNIQUE de la connexion qui a enregistré l'icône ; rendre le nom « org.kde.StatusNotifierItem-… » ne
  suffit pas. L'icône a donc SA connexion au bus de session (`Tray.show`), fermée par `hide` : l'icône s'en va
  tout de suite. Testé : la fausse barre d'ui_smoke vérifie que ce nom unique disparaît (échoue sur l'ancien code). `--background` (lancement
  à l'ouverture de session — COCHÉ D'OFFICE au premier lancement de Sirène installée (`_first_run_autostart`,
  réglage `autostart_offered`, une seule fois, toast dans la fenêtre ; vu chez Tof : l'option des Préférences
  passait inaperçue, Sirène ne démarrait pas avec la session), `autostart.py` : ~/.config/autostart, `sirene --background` installé, sinon ce
  Python + bin/sirene) : pas de fenêtre. Icônes `data/icons/hicolor` (index.theme OBLIGATOIRE, cf. Ithaca) ;
  couleur corail (Odysseus bleu, Ithaca violet, Nausicaa orange, Calypso turquoise, Télémaque vert).
- Notifications (`sirene/notify.py`) : PIÈGE vu chez Tof (aucune notification) — GNOME Shell REFUSE en silence les
  Gio.Notification d'une application sans .desktop installé (lookup_app(<id>.desktop) → InvalidAppError). Sans
  lanceur installé : org.freedesktop.Notifications (comme notify-send de bt-notify), remplacement par identifiant ;
  installé (`data/io.github.sirene.Sirene.desktop`) : Gio.Notification. Testé : `test_notify` (faux serveur).
  Contenu : connexion / déconnexion de TOUT appareil Bluetooth (`notify_connect`, comme
  bt-notify ; état connu au démarrage = pas de notification), batterie faible (`battery_alert`) : un écouteur sous
  20 % puis sous 10 %, une fois par seuil, réarmé au-dessus de 30 % ; 0 % ignoré (rangé dans le boîtier).
- Affichage du volume (`volume_osd`, comme bt-notify ; `sirene/volume_osd.py`) : `pactl subscribe` (LC_ALL=C, lu
  dans la boucle GLib, seulement pendant que les écouteurs sont connectés), « 'change' on sink » → `pactl
  get-sink-volume @DEFAULT_SINK@` (une lecture à la fois, rafales regroupées), affiché par l'extension « Custom OSD »
  (neuromorph/custom-osd, celle de Tof) : clé `showosd` = « aléa,icône,texte,niveau » (l'extension découpe aux
  virgules : retirées du nom ; niveau plafonné à 1). Schéma pris dans le système ou dans le dossier de l'extension
  (~/.local/share/gnome-shell/extensions/custom-osd@neuromorph/schemas). Volume de départ non affiché. GNOME ne
  donne pas son encart aux applications ; une fenêtre à nous ne se placerait pas sous Wayland. Testé :
  `test_volume_osd` (faux pactl, vrai schéma compilé, réglages en mémoire), étape `volume_affiche` d'ui_smoke.
- `ui/window.py` : pages « aucun écouteur », « connexion… », « impossible de joindre », page des écouteurs
  (`DevicePage`) en ONGLETS (demande de Tof) — État (piles, contrôle du bruit, port), Gestes (tapes, appui long,
  glisser), Son, Appareil (double connexion, langue, infos) ; `Adw.ViewStack` (classe « final » : porté par un
  Gtk.Box, `device_page.stack`), sélecteur dans l'en-tête, `Adw.ViewSwitcherBar` en bas sous 480 sp (point de
  rupture : la fenêtre DOIT avoir une taille minimale, sinon « does not have a minimum size » en boucle) ; onglet
  caché s'il n'a aucune ligne. Contrôle du bruit = boutons liés sur toute la largeur, textes abrégés (en suffixe
  d'une ligne, ils élargissaient la fenêtre). Contenu : piles gauche / droit / boîtier (+ porté / retiré), contrôle du bruit (boutons liés) et niveau,
  gestes, son (égaliseur, priorité, faible latence), détection du port, double connexion (+ appareils connus),
  langue des messages, infos. Lignes construites une fois, tenues à jour par `changed(groupe, prop)`, cachées
  tant que les écouteurs n'ont pas donné la valeur ; groupe caché si toutes ses lignes le sont. Code inconnu
  (triple tape « 4 », « 5 », « 6 » des 6i) montré tel quel. `ui/labels.py` : identifiants → textes.

- Égaliseur personnalisé (onglet Son, si `eq_max_custom` > 0) : « Créer… » (nom ≤ 24 octets, part du préréglage
  choisi : `Equalizer._select` d'un nom inconnu, numéro 100 et suivants), 10 bandes 32 Hz → 16 kHz de -60 à +60
  dixièmes de dB (comme OpenFreebuds), entendues tout de suite : un seul envoi 300 ms après le dernier mouvement
  (`_eq_send`) ; « Modifications non enregistrées » → Enregistrer (`eq_saved` vrai) / Annuler (faux = valeurs
  d'avant) ; « Supprimer ce préréglage » (`eq_rows` None). Préréglage intégré : pas de bandes.
- Action à la connexion des écouteurs (Préférences → Général → Écouteurs, réglage `on_connect` : rien, réduction,
  transparence, désactivé, ouvrir la fenêtre ; l'« automatisation » d'OpenFreebuds) : une fois par connexion
  Bluetooth (`_action_for`, posé par `_open` sauf réouverture du canal), dès que les écouteurs sont prêts
  (événement device.ready, ou déjà prêts à `_opened`).
- Raccourcis clavier : `sirene --anc=off|cancellation|awareness|next`, transmis à l'instance qui tourne
  (GApplication) sans fenêtre ; à brancher dans les raccourcis personnalisés de GNOME (X11 ET Wayland, plutôt que
  des raccourcis globaux X11 comme OpenFreebuds). Préférences : les commandes à copier (`command_text` : ce Python
  + bin/sirene lancé des sources). Code de retour 1 sans écouteurs.
- Double connexion (onglet Appareil) : par appareil connu, étoile = préféré, Connecter / Déconnecter, Oublier…
  (confirmation). « Cet ordinateur » = adresse d'un de NOS adaptateurs (`bluez.Watcher.adapters`) : ni
  Déconnecter ni Oublier (on se couperait des écouteurs).

## Port des écouteurs et auto-pause (vu chez Tof, novembre 2026)

- Trame 2B25 : p1 = gauche, p2 = droit (01 porté, 00 retiré). 7i : y répondent sur demande et l'annoncent pour
  les deux écouteurs (auto-pause validée par Tof avec l'AppImage du fork d'OpenFreebuds). 6i : l'annoncent
  d'elles-mêmes ; chez Tof, le gauche n'est signalé (p1 = 00) que posé dans le BOÎTIER (contact de charge), jamais
  retiré de l'oreille (ni 2B25, ni autre trame, ni AVRCP : `btmon` muet, même sans programme). Avis de Tof, partagé :
  capteur de port du gauche de SA paire en panne (matériel), pas une limite du modèle. Rien à faire côté PC.
- 4i : font la pause elles-mêmes (AVRCP), sans programme. Le réglage dans les écouteurs : 2B11 lecture /
  2B10 écriture (p1 = 1 activé), vu à 01 sur les 6i de Tof.
- Puce Bluetooth de Tof : MediaTek MT7922 (0e8d:7922) ; elle transmet bien les gestes (hors de cause).

## Tests

```sh
python3.12 -m unittest discover -s tests        # trames + fonctions contre de faux écouteurs (socketpair)
dbus-run-session -- python3.12 -m unittest discover -s tests       # + MPRIS (faux lecteurs), notifications
dbus-run-session -- xvfb-run -a python3.12 tests/ui_smoke.py      # + barre du haut (fausse barre) ; sans bus : sautée
xvfb-run -a python3.12 tests/ui_smoke.py         # interface + faux BlueZ + faux 6i : « Aucune erreur. »
LANGUAGE=en … ; LANGUAGE=de …
python3 -m pyflakes sirene tests tools
```

Captures : `xvfb-run -a -s "-screen 0 1280x2400x24" python3.12 tools/screenshot.py SORTIE.png [--dark] [--empty]
[--size=LxH] [--scroll=PIXELS]` (faux 6i aux valeurs de Tof ; taille posée par le settings.json jetable).

`tests/fake_buds.py` : faux écouteurs qui répondent d'après un modèle {trame demandée : [réponses]} (comme le
banc d'essai d'OpenFreebuds) et envoient des trames spontanées (`push`). Trames réelles : 7i (tests de la
pull request #135, capturées depuis AI Life), 6i (captures de MyBuds chez Tof). Pas d'écouteurs dans le bac à
sable : les essais réels sont faits par Tof.

## Feuille de route

1. FAIT : squelette, protocole, toutes les fonctions des 4i / 6i / 7i, connexion, diagnostic.
2. Essai réel de `sirene.probe` sur les 6i de Tof (puis les 7i à Noël).
3. FAIT (0.0.1, à essayer chez Tof) : interface, suivi de BlueZ, pause au retrait par MPRIS.
   FAIT ensuite : égaliseur personnalisé et actions de la double connexion (ci-dessous).
4. FAIT (0.0.2) : icône de la barre (batterie, contrôle du bruit), arrière-plan, lancement à l'ouverture de
   session, notifications de connexion, alerte batterie faible ; puis action à la connexion et raccourcis
   clavier (`--anc`).
5. FAIT : reprise de `bt-notify.sh` (notifications, affichage du volume par Custom OSD) — Sirène remplace toute
   la bidouille de Tof.
6. FAIT (0.1.0, à publier sur l'accord de Tof) : paquet, workflow, PPA, site.

## Publication (comme Télémaque)

Paquet, commande et module : `sirene` (nom libre chez Debian, absent de noble ; vérifié avant la 0.1.0).
PPA `ppa:nourpon/sirene` (créé par Tof) : `tools/ppa.sh` chez Tof (noble puis resolute, garde-fou « à » en fin de
ligne du changelog, puis le site par `tools/site.sh`, dossier Sirene des pages perso Free). Nouvelle version :
version dans `sirene/__init__.py`, `debian/sirene.1`, `<release>` de la fiche AppStream, entrée de
`debian/changelog` (« X~noble1 », date RÉELLE — `date -R`), commit « Version X » sur main :
`.github/workflows/release-deb.yml` publie le .deb dans les Releases (seulement pour un commit « Version… »).
Publier seulement avec l'accord explicite de Tof (« on publie »). Dépendances : python3-gi, GTK 4.14,
libadwaita 1.5, bluez ; Recommends : gnome-shell-extension-appindicator, pulseaudio-utils (pactl, volume).
Code privé dans /usr/share/sirene, lanceur `/usr/bin/python3 -P -c …` (debian/bin/sirene). Installé, le .desktop
existe : notifications par Gio.Notification, lancement à l'ouverture de session par `sirene --background`.
Site : `site/index.html` (anglais, tons corail ; Odysseus bleu, Ithaca violet, Nausicaa orange, Calypso turquoise,
Télémaque vert), captures de `site/img/` en anglais (`LANGUAGE=en … tools/screenshot.py site/img/dark.png --dark
--size=620x760`, gestures `--tab=gestures`, device `--tab=device`, light sans `--dark`) ; version dans la pastille
et l'accroche, à tenir à jour. Paquet vérifié ici : dpkg-buildpackage (binaire et source), lintian sans remarque,
appstreamcli validate (note pédante), installé puis lancé.
