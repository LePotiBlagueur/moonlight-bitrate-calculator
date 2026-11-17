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
| Script monolithique | Paquet testé (74 tests), config TOML, rejeu hors ligne |
| Sortie texte unique | CLI récap dédiée : table, Markdown, CSV, HTML, JSON |
| À lancer avec Python | Exécutables Windows autonomes (`.exe`) |

## Installation

Sur **les deux machines** : [iperf3](https://iperf.fr/iperf-download.php) ≥ 3.7.

Sur la machine cliente (celle qui lance l'outil) :

```bash
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate sous Windows
pip install -e .
```

Accès SSH par clé vers l'hôte (sinon utilisez `--no-ssh`) :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_moonlight
ssh-copy-id -i ~/.ssh/id_moonlight.pub falaa@192.168.1.10
```

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
moonlight-bitrate --host 192.168.1.10 --user falaa --codec av1 --quality high

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

── Débit conseillé par mode (Mbps à saisir dans Moonlight) ───────
  Résolution  │ Définition │  60 fps │  90 fps │ 120 fps │ 144 fps
  ────────────┼────────────┼─────────┼─────────┼─────────┼────────
  1080p       │ 1920x1080  │    15 ✓ │    18 ✓ │    21 ✓ │    23 ✓
  1200p 16:10 │ 1920x1200  │    17 ✓ │    21 ✓ │    24 ✓ │    27 ✓
  1440p       │ 2560x1440  │    30 ✓ │    37 ✓ │    42 ✓ │    46 ✓
  4K          │ 3840x2160  │    60 ✓ │    73 ✓ │    85 ✓ │    93 ✓
```

`✓` confortable · `~` limite · `✗` hors budget.

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

**La taille des datagrammes n'est pas un détail.** WireGuard ajoute 60 octets
d'encapsulation et prend une MTU de 1420 par défaut, soit 1420 − 20 (IP) − 8
(UDP) = 1392 octets utiles. Un `datagram_len` de 1400 dans le tunnel fait
fragmenter chaque paquet, et le taux de perte mesuré devient du bruit. 1380
laisse une marge.

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
| `best` | Les cinq meilleurs modes confortables, classés par charge de pixels |

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
  Résolution  │ Définition │        H.264 │         HEVC │          AV1
  ────────────┼────────────┼──────────────┼──────────────┼─────────────
  1080p       │ 1920x1080  │ 144 fps · 31 │ 144 fps · 23 │ 144 fps · 20
  1440p       │ 2560x1440  │  60 fps · 40 │  90 fps · 37 │ 144 fps · 40
  1600p 16:10 │ 2560x1600  │            — │  90 fps · 40 │ 120 fps · 40
  UW 1440p    │ 3440x1440  │            — │  60 fps · 38 │  90 fps · 41
  4K          │ 3840x2160  │            — │            — │            —
```

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
git tag v2.1.0 && git push origin v2.1.0
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

## Comment le chiffre est obtenu

1. **Sonde TCP** (facultative) pour cadrer la recherche, puis **paliers UDP**
   croissants : 25 %, 40 %, 55 %… du plafond estimé.
2. Un palier est « propre » si perte ≤ `max_loss_pct` **et** gigue ≤
   `max_jitter_ms` **et** si l'émetteur a bien généré le débit demandé.
3. **Dichotomie** entre le dernier palier propre et le premier en échec
   (3 itérations, arrêt à 4 % d'écart).
4. Budget réseau = capacité propre × `safety_margin` (0,85 par défaut).
5. Débit vidéo max = (budget − audio) ÷ (1 + FEC) — Sunshine ajoute ~20 % de
   FEC par-dessus la vidéo, et l'audio Opus passe dans le même tuyau.
6. Besoin de chaque mode = référence Moonlight × facteur qualité × efficacité du
   codec, puis comparaison au budget.

La référence Moonlight est sa propre formule : table de facteurs par nombre de
pixels (360p→1, 480p→2, 720p→5, 1080p→10, 1440p→20, 2160p→40) interpolée
linéairement, multipliée par `fps/30` jusqu'à 60 fps puis `√(fps/60)×60/30`
au-delà. D'où 1080p60 = 20 Mbps, 1440p60 = 40 Mbps, 4K60 = 80 Mbps.

Efficacité codec appliquée au besoin : H.264 ×1.00, HEVC ×0.75, AV1 ×0.65.
Préréglages qualité : `saver` ×0.75, `balanced` ×1.00, `high` ×1.25, `max` ×1.50.

## Dépannage SSH sous Windows

Trois pièges, tous rencontrés sur une vraie installation, qui produisent le même
`Permission denied (publickey)` trompeur.

**1. Le nom de compte n'est pas le dossier de profil.** `C:\Users\falaa` peut
très bien appartenir au compte `kwak`. Un mauvais nom d'utilisateur est rejeté
*avant* toute vérification de clé, ce qui ressemble à s'y méprendre à un
problème de clé. Le journal tranche :

```powershell
Get-WinEvent -LogName "OpenSSH/Operational" -MaxEvents 10 |
  Select-Object TimeCreated, Message | Format-List
```

`Invalid user <nom>` = mauvais compte. Le bon nom vient de `whoami` sur l'hôte,
ou de `Get-LocalUser` (colonne `Enabled`).

**2. `authorized_keys` doit être un fichier, pas un dossier.** Un répertoire du
même nom contenant des `.pub` n'est jamais lu.

**3. Pour un compte administrateur, sshd ignore `~/.ssh/authorized_keys`** et ne
lit que `C:\ProgramData\ssh\administrators_authorized_keys` (règle
`Match Group administrators` de `sshd_config`). En console élevée :

```powershell
$k = Get-Content C:\Users\<profil>\.ssh\authorized_keys -Raw
Set-Content -Path C:\ProgramData\ssh\administrators_authorized_keys `
            -Value $k -Encoding ascii
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r `
       /grant *S-1-5-32-544:F /grant *S-1-5-18:F
```

`Set-Content` écrit dans le fichier existant, là où `Copy-Item` le remplace et
échoue sur les ACL. Les SID évitent les noms de groupes localisés. N'écrivez
jamais ce fichier avec `>` ou `Out-File` : PowerShell 5.1 produit de l'UTF-16 et
sshd ne lit plus rien.

## Version d'iperf3 sur l'hôte

L'outil interroge `iperf3 --version` au démarrage et prévient si le build est
ancien. Les binaires Windows qui traînent depuis des années sont souvent en
**3.1.4 (Cygwin, 2016)** : le cadencement de `-b` y est grossier et les flux UDP
parallèles (`-P`) rendent une sortie vide. La capacité mesurée reste exploitable
mais pessimiste. Une 3.7+ depuis [iperf.fr](https://iperf.fr/iperf-download.php)
change nettement la précision.

## Si l'outil annonce « émetteur saturé »

iperf3 compilé sous Cygwin (les binaires Windows) plafonne souvent bien avant
le lien en UDP. Dans ce cas la capacité affichée est un **plancher**. Remèdes :

```toml
[bench]
streams = 4           # répartir sur plusieurs flux
datagram_len = 8900   # trames jumbo si le réseau les accepte
```

## Développement

```bash
python -m unittest discover -s tests -v
```

Les 74 tests couvrent la formule Moonlight (valeurs de référence publiées), le
parsing des trois formes de JSON UDP d'iperf3, la convergence de la recherche
par paliers sur un lien simulé, les surcharges des deux CLI, chaque format de
rendu du récap, la logique de double-clic des exécutables, et la
détection de version d'iperf3 (calée sur la sortie d'un hôte réel en 3.1.4)
et la superposition des profils.

## Structure

```
moonlight_bitrate/
  config.py   dataclasses, chargement TOML, surcharges
  remote.py   serveur iperf3 distant par SSH (contexte auto-nettoyant)
  iperf.py    exécution d'iperf3, parsing JSON robuste, sonde ICMP
  ladder.py   recherche de la capacité UDP propre (paliers + dichotomie)
  model.py    formule Moonlight, FEC/audio, faisabilité par mode
  report.py   journal console et tableaux
  cli.py      arguments, orchestration, JSON
  recap.py    tableaux récapitulatifs et rendus (texte/MD/CSV/HTML/JSON)
  recap_cli.py  commande `moonlight-recap`
  entry.py    points d'entrée des .exe (double-clic, config voisine)
packaging/    spec PyInstaller et scripts de build
.github/workflows/build-windows.yml   construction des .exe en CI
```
