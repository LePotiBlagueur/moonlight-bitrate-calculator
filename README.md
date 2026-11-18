# moonlight-bitrate-calculator

Mesure la capacité **réelle** du lien entre l'hôte Sunshine et le client Moonlight,
puis en déduit le débit à régler — pour **plusieurs résolutions et fréquences
d'images** à la fois.

La mesure est faite en **UDP**, dans le **sens du streaming** (hôte → client),
par paliers croissants affinés par dichotomie : on cherche le débit le plus haut
que le lien encaisse encore sans perte ni gigue, et non le débit maximal
théorique.

## Ce qui change par rapport à la V1

| V1 | V2 |
|---|---|
| Test TCP (4 flux) | Test **UDP** par paliers + dichotomie, perte et gigue réelles |
| Sens client → hôte (l'inverse du streaming) | Sens **hôte → client** (`-R`), celui de la vidéo |
| « 75 % du débit brut » comme débit vidéo | Capacité propre × marge, **FEC et audio déduits** |
| Formule maison `30 Mbps × ratio de pixels` | Formule **exacte de Moonlight** (table de pixels interpolée, racine carrée au-delà de 60 fps) |
| Une seule résolution | **Matrice** résolutions × fréquences, verdict par case |
| Codec ignoré | Efficacité **H.264 / HEVC / AV1** et préréglages de qualité |
| Script monolithique | Paquet testé (91 tests), config TOML, rejeu hors ligne |
| Sortie texte unique | CLI récap dédiée : table, Markdown, CSV, HTML, JSON |
| À lancer avec Python | Exécutables Windows autonomes (`.exe`) |

## Installation

```bash
./install.sh
```

Installe les deux commandes dans votre `PATH` via **pipx** (environnement
isolé, pas de `paramiko` global), ajoute `~/.local/bin` au `PATH` si besoin et
pose les complétions zsh. Idempotent, et réversible par `./install.sh
--uninstall`.

Prérequis : Python ≥ 3.11, `pipx`, et `iperf3` **sur les deux machines**.
Détails, variantes sans installation et mise en place de la clé SSH :
[docs/install.md](docs/install.md).

## Utilisation

```bash
cp config.example.toml config.toml   # adaptez l'IP, l'utilisateur, les chemins
moonlight-bitrate -c config.toml -p lan
```

`config.example.toml` déclare deux profils, `lan` et `vpn` — voir plus bas.

Sans installation : `python __main__.py -c config.toml`
(double-clic sous Windows : la fenêtre reste ouverte à la fin).

Quelques variantes :

```bash
# Tout en ligne de commande, sans fichier de config
moonlight-bitrate --host 192.168.1.10 --user kwak --codec av1 --quality high

# Seulement vos deux modes de jeu, mesure rapide
moonlight-bitrate -c config.toml --resolution 1920x1200 --resolution 2560x1440 \
                  --fps 120 --fps 144 -t 5

# Mesurer aussi le retour (manette, micro)
moonlight-bitrate -c config.toml --direction both

# Serveur iperf3 déjà lancé à la main sur l'hôte (pas de SSH)
moonlight-bitrate --no-ssh --host 192.168.1.10

# Enregistrer la mesure, puis rejouer l'analyse sans retoucher au réseau
moonlight-bitrate -c config.toml --save mesures.json
moonlight-bitrate --load mesures.json --codec av1 --quality max
moonlight-bitrate --load mesures.json --json       # sortie machine
```

## Ce que vous obtenez

```
── Synthèse réseau ───────────────────────────────────────────────
  Sens          │ TCP brut (Mbps) │ UDP propre (Mbps) │ Perte (%) │ Gigue (ms)
  ──────────────┼─────────────────┼───────────────────┼───────────┼───────────
  hôte → client │           940.0 │             446.5 │      0.05 │       1.12

  Latence ICMP : 1.84 ms (± 0.62 ms), perte 0.0 %

── Débit conseillé par mode (Mbps à saisir dans Moonlight) ───
  Résolution     │ Définition │ 60 fps │ 90 fps │ 120 fps │ 144 fps │ 175 fps
  ───────────────┼────────────┼────────┼────────┼─────────┼─────────┼────────
  720p           │ 1280x720   │    8 ✓ │    9 ✓ │    11 ✓ │    12 ✓ │    13 ✓
  800p 16:10     │ 1280x800   │    8 ✓ │   10 ✓ │    12 ✓ │    13 ✓ │    14 ✓
  900p           │ 1600x900   │   11 ✓ │   13 ✓ │    15 ✓ │    17 ✓ │    19 ✓
  1080p          │ 1920x1080  │   15 ✓ │   18 ✓ │    21 ✓ │    23 ✓ │    26 ✓
  1200p 16:10    │ 1920x1200  │   17 ✓ │   21 ✓ │    24 ✓ │    27 ✓ │    29 ✓
  UW 1080p       │ 2560x1080  │   21 ✓ │   26 ✓ │    30 ✓ │    33 ✓ │    37 ✓
  1440p          │ 2560x1440  │   30 ✓ │   37 ✓ │    42 ✓ │    46 ✓ │    51 ✓
  1600p 16:10    │ 2560x1600  │   33 ✓ │   40 ✓ │    46 ✓ │    51 ✓ │    56 ✓
  UW 1440p       │ 3440x1440  │   38 ✓ │   47 ✓ │    54 ✓ │    59 ✓ │    65 ✓
  1800p 16:10    │ 2880x1800  │   40 ✓ │   49 ✓ │    56 ✓ │    62 ✓ │    68 ✓
  1800p          │ 3200x1800  │   44 ✓ │   53 ✓ │    62 ✓ │    67 ✓ │    74 ✓
  UW 1600p       │ 3840x1600  │   46 ✓ │   56 ✓ │    65 ✓ │    71 ✓ │    79 ✓
  SUW 1440p 32:9 │ 5120x1440  │   54 ✓ │   66 ✓ │    76 ✓ │    84 ✓ │    92 ✓
  4K             │ 3840x2160  │   60 ✓ │   73 ✓ │    85 ✓ │    93 ✓ │   102 ✓
  4K 16:10 *     │ 3840x2400  │   60 ✓ │   73 ✓ │    85 ✓ │    93 ✓ │   102 ✓
  5K2K UW *      │ 5120x2160  │   60 ✓ │   73 ✓ │    85 ✓ │    93 ✓ │   102 ✓
  5K *           │ 5120x2880  │   60 ✓ │   73 ✓ │    85 ✓ │    93 ✓ │   102 ✓
  ✓ confortable · ~ limite · ✗ hors budget
  * au-delà de la 4K, Moonlight plafonne sa référence de débit : la valeur affichée est un plancher, pas le besoin réel.

── Mode le plus élevé tenable par taille d'écran ───────────────
  Résolution     │ Définition │ fps max │ Mbps à régler │  Marge │ Codec                 
  ───────────────┼────────────┼─────────┼───────────────┼────────┼───────────────────────
  720p           │ 1280x720   │     175 │            13 │ 23.91× │ HEVC (H.264 au besoin)
  800p 16:10     │ 1280x800   │     175 │            14 │ 22.02× │ HEVC (H.264 au besoin)
  900p           │ 1600x900   │     175 │            19 │ 16.66× │ HEVC (H.264 au besoin)
  1080p          │ 1920x1080  │     175 │            26 │ 12.15× │ HEVC                  
  1200p 16:10    │ 1920x1200  │     175 │            29 │ 10.65× │ HEVC                  
  UW 1080p       │ 2560x1080  │     175 │            37 │  8.54× │ HEVC                  
  1440p          │ 2560x1440  │     175 │            51 │  6.12× │ AV1 ou HEVC           
  1600p 16:10    │ 2560x1600  │     175 │            56 │  5.63× │ AV1 ou HEVC           
  UW 1440p       │ 3440x1440  │     175 │            65 │  4.81× │ AV1 ou HEVC           
  1800p 16:10    │ 2880x1800  │     175 │            68 │  4.63× │ AV1 ou HEVC           
  1800p          │ 3200x1800  │     175 │            74 │  4.23× │ AV1 ou HEVC           
  UW 1600p       │ 3840x1600  │     175 │            79 │  4.00× │ AV1 ou HEVC           
  SUW 1440p 32:9 │ 5120x1440  │     175 │            92 │  3.41× │ AV1 ou HEVC           
  4K             │ 3840x2160  │     175 │           102 │  3.07× │ AV1 ou HEVC           
  4K 16:10 *     │ 3840x2400  │     175 │           102 │  3.07× │ AV1 ou HEVC           
  5K2K UW *      │ 5120x2160  │     175 │           102 │  3.07× │ AV1 ou HEVC           
  5K *           │ 5120x2880  │     175 │           102 │  3.07× │ AV1 ou HEVC           
  Prenez la ligne de votre écran : au-delà du lien, ce sont la dalle et le GPU qui limitent.
  * au-delà de la 4K, Moonlight plafonne sa référence de débit : la valeur affichée est un plancher, pas le besoin réel.
```

Une ligne par taille d'écran : prenez la vôtre, le reste est du
contexte. `✓` confortable · `~` limite · `✗` hors budget.

## Deux liens, deux profils

Le même hôte se joint de deux façons, et les deux ne se mesurent pas pareil.
Un profil est une **surcouche** : il ne redéfinit que les clés qu'il cite, tout
le reste vient des sections de base.

```bash
moonlight-bitrate -c config.toml -p lan    # réseau local
moonlight-bitrate -c config.toml -p vpn    # tunnel WireGuard
moonlight-recap   -c config.toml -p vpn --measure
```

```toml
[bench]
duration = 8
streams = 1

[profiles.lan.bench]
datagram_len = 1400
assumed_ceiling_mbps = 1000.0
max_jitter_ms = 2.0          # un LAN filaire ne doit pas bouger
max_loss_pct = 0.10

[profiles.vpn.bench]
datagram_len = 1380          # voir ci-dessous
assumed_ceiling_mbps = 300.0
max_jitter_ms = 8.0
max_loss_pct = 0.30
duration = 10                # le débit d'un tunnel est plus erratique
refine_steps = 4
ping_probe = false           # l'ICMP ne traverse pas toujours le tunnel

[profiles.vpn.model]
safety_margin = 0.75         # plus de marge : le lien varie d'une minute à l'autre
```

**La taille des datagrammes n'est pas un détail, et ne se devine pas.** Un
datagramme plus gros que la MTU est fragmenté : le taux de perte relevé ne
mesure alors plus le lien mais la fragmentation. L'outil sonde donc la MTU
avant de mesurer et ajuste `datagram_len` tout seul :

```
  · Contrôle de la MTU du chemin
  ✓ MTU du chemin : 1360 octets (méthode : route)
  ! datagram_len = 1380 dépasse la MTU (1360) : chaque datagramme serait
    fragmenté et la perte mesurée ne vaudrait rien. Ramené à 1332.
```

Pour connaître la valeur sans lancer de mesure :

```bash
moonlight-bitrate -c config.toml -p vpn --probe-mtu
```

```
  Mesure                 │ Octets        Réglage              │ Valeur
  ───────────────────────┼───────        ─────────────────────┼───────
  MTU du chemin (ICMP)   │      —        bench.datagram_len   │   1332
  MTU de la route locale │   1360        Sunshine packetsize  │   1316
  Méthode retenue        │  route        MTU WireGuard        │   1360
```

Deux méthodes, parce qu'aucune ne suffit seule :

- **ICMP avec bit « ne pas fragmenter »**, par dichotomie : c'est la vraie MTU
  de bout en bout, mais beaucoup de tunnels et de pare-feu ne répondent pas à
  l'ICMP. Un garde-fou vérifie d'abord que l'hôte répond du tout, sans quoi un
  hôte muet ferait conclure à une MTU minuscule.
- **MTU de la route locale**, lue auprès du noyau : instantanée et toujours
  disponible, mais ce n'est qu'une borne haute — un goulet plus loin sur le
  chemin ne s'y verrait pas.

Quand les deux répondent, c'est la plus basse qui s'applique. `--underlay`
indique que le chemin sondé *transporte* le tunnel au lieu d'être dedans :
l'outil retranche alors les 60 octets d'encapsulation WireGuard pour donner la
MTU à configurer côté tunnel.

L'option `packetsize` de Sunshine se calcule sur la même base, avec 16 octets
de plus à retrancher pour l'en-tête du flux : `MTU − 28 − 16`. S'il dépasse ce
que le tunnel peut porter, chaque trame vidéo se fragmente. Sunshine la laisse
à `0` (automatique) par défaut, ce qui convient tant que le client sait
détecter la MTU — ce n'est pas toujours le cas à travers un VPN.

`mtu_check = false` désactive le contrôle, `mtu_autofit = false` le laisse
avertir sans corriger.

Une option passée en ligne de commande reste prioritaire sur le profil, qui
est lui-même prioritaire sur les sections de base. Un nom de profil inexistant
liste ceux qui sont déclarés.

**Ne réglez pas Moonlight sur une mesure VPN.** Le tunnel donne une capacité
plus basse et beaucoup plus variable : sur l'installation de test, 131 Mbps en
TCP mais seulement ~45 Mbps propres en UDP, avec un même palier qui passe de
3 % à 52 % de perte d'un essai à l'autre. Le profil `vpn` sert à savoir ce que
vous pouvez espérer en déplacement, pas à calibrer le confort à la maison.

## Tableau récapitulatif — `moonlight-recap`

Une CLI dédiée au récap, qui n'a **pas besoin de refaire un test réseau** : elle
part d'un débit connu, d'une mesure enregistrée, ou lance la mesure elle-même.

```bash
moonlight-recap -b 450                      # depuis un débit connu (Mbps)
moonlight-recap --budget 380                # budget déjà net de marge
moonlight-recap --load mesures.json         # depuis une mesure enregistrée
moonlight-recap --measure -c config.toml --save mesures.json   # mesure + récap
```

Cinq sections, toutes activées par défaut (`--sections matrix,codecs` pour
n'en garder que certaines) :

| Section | Contenu |
|---|---|
| `network` | Le lien mesuré : TCP brut, UDP propre, perte, gigue, latence *(si une mesure est disponible)* |
| `matrix` | Matrice résolutions × fps → débit à régler, avec verdict par case |
| `codecs` | Pour chaque résolution, le mode le plus élevé tenable en H.264 / HEVC / AV1 |
| `quality` | Ce que chaque préréglage (`saver` → `max`) permet d'atteindre |
| `best` | Une ligne par taille d'écran : la fréquence la plus haute tenable, le débit à régler et la marge |

Cinq formats de sortie : `table` (défaut, couleurs dans le terminal),
`markdown`, `csv` (séparateur `;`, prêt pour Excel), `html` (page autonome,
thème clair/sombre automatique) et `json`.

```bash
moonlight-recap -b 450 --format html -o recap.html
moonlight-recap -b 450 --format markdown >> notes.md
moonlight-recap -b 450 --format csv -o recap.csv
```

Exemple (`--sections codecs`, lien à 60 Mbps) :

```
── Mode le plus élevé tenable selon le codec (fps · Mbps) ──────
  Résolution     │ Définition │        H.264 │         HEVC │          AV1
  ───────────────┼────────────┼──────────────┼──────────────┼─────────────
  720p           │ 1280x720   │ 175 fps · 17 │ 175 fps · 13 │ 175 fps · 11
  800p 16:10     │ 1280x800   │ 175 fps · 19 │ 175 fps · 14 │ 175 fps · 12
  900p           │ 1600x900   │ 175 fps · 25 │ 175 fps · 19 │ 175 fps · 16
  1080p          │ 1920x1080  │ 175 fps · 34 │ 175 fps · 26 │ 175 fps · 22
  1200p 16:10    │ 1920x1200  │ 175 fps · 39 │ 175 fps · 29 │ 175 fps · 25
  UW 1080p       │ 2560x1080  │ 120 fps · 40 │ 175 fps · 37 │ 175 fps · 32
  1440p          │ 2560x1440  │  60 fps · 40 │  90 fps · 37 │ 144 fps · 40
  1600p 16:10    │ 2560x1600  │            — │  90 fps · 40 │ 120 fps · 40
  UW 1440p       │ 3440x1440  │            — │  60 fps · 38 │  90 fps · 41
  1800p 16:10    │ 2880x1800  │            — │  60 fps · 40 │  60 fps · 34
  1800p          │ 3200x1800  │            — │            — │  60 fps · 38
  UW 1600p       │ 3840x1600  │            — │            — │  60 fps · 40
  SUW 1440p 32:9 │ 5120x1440  │            — │            — │            —
  4K             │ 3840x2160  │            — │            — │            —
  4K 16:10 *     │ 3840x2400  │            — │            — │            —
  5K2K UW *      │ 5120x2160  │            — │            — │            —
  5K *           │ 5120x2880  │            — │            — │            —
  Efficacité relative appliquée : H.264 ×1.00, HEVC ×0.75, AV1 ×0.65
  * au-delà de la 4K, Moonlight plafonne sa référence de débit : la valeur affichée est un plancher, pas le besoin réel.```

Avec un fichier de config, les listes de résolutions et de fréquences du récap
sont celles de `[model]`; en ligne de commande, `--resolution` et `--fps`
(répétables) les remplacent.

## Exécutables Windows (.exe)

Deux binaires autonomes, sans Python à installer :

| Fichier | Rôle |
|---|---|
| `moonlight-bitrate.exe` | Mesure UDP complète + rapport détaillé |
| `moonlight-recap.exe` | Tableau récapitulatif (tous formats) |

Placez un `config.toml` **à côté de l'exe** : lancés par double-clic, les deux
le trouvent tout seuls, enchaînent la mesure et laissent la fenêtre ouverte à la
fin. En ligne de commande ils acceptent exactement les mêmes options que les
versions Python.

### Les obtenir

**Par la CI (recommandé, aucun outil local)** — poussez un tag, ou cliquez sur
*Run workflow* dans l'onglet Actions :

```bash
git tag v2.2.0 && git push origin v2.2.0
```

`.github/workflows/build-windows.yml` lance les tests sous Linux, compile sous
`windows-latest`, vérifie que les deux `.exe` démarrent, puis les publie en
artefact et sur la release.

**Depuis Windows :**

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

**Depuis Linux, via wine :**

```bash
./packaging/build-wine.sh
```

PyInstaller ne sait pas produire un `.exe` depuis un Python Linux : le script
installe un vrai Python Windows dans un préfixe wine (`.wine-build/`) puis y
exécute PyInstaller. Comptez ~400 Mo de téléchargement la première fois.

## Pour aller plus loin

| Document | Contenu |
|---|---|
| [docs/usage.md](docs/usage.md) | Recettes de ligne de commande, codes de sortie. |
| [docs/configuration.md](docs/configuration.md) | Référence de toutes les clés TOML. |
| [docs/architecture.md](docs/architecture.md) | Comment la mesure et le calcul fonctionnent, et pourquoi. |
| [docs/troubleshooting.md](docs/troubleshooting.md) | SSH sous Windows, émetteur qui plafonne, perte erratique, vieux iperf3. |
| [docs/install.md](docs/install.md) | Installation, complétions, désinstallation. |

Les trois pièges SSH de Windows — nom de compte distinct du dossier de profil,
`authorized_keys` en dossier plutôt qu'en fichier, et
`administrators_authorized_keys` pour les comptes administrateur — sont tous
documentés dans la page de dépannage. Ils produisent le même
`Permission denied (publickey)` trompeur.

## Développement

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m unittest discover -s . -p 'test_*.py' -v
```

98 tests, sans accès réseau. Ils couvrent la formule Moonlight calée sur les
valeurs publiées par le projet, les trois formes de JSON UDP d'iperf3, la
convergence des paliers sur un lien simulé, la sonde de MTU, la superposition
des profils, les deux CLI et chaque format de rendu.

Trois garde-fous contre la dérive : toute clé de configuration doit apparaître
dans la référence, toute option de ligne de commande dans les complétions
zsh, et tout lien interne de la documentation doit pointer sur un fichier
existant.
