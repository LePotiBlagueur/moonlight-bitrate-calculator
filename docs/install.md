# Installation

## Dans le `PATH` (recommandé)

```bash
./install.sh
```

Le script :

1. vérifie Python ≥ 3.11 et signale l'absence d'`iperf3` ;
2. installe le paquet avec **pipx**, qui lui crée un environnement isolé —
   pas de conflit avec les paquets système, et `paramiko` n'est pas installé
   globalement ;
3. ajoute `~/.local/bin` au `PATH` si nécessaire, dans un bloc délimité de
   votre fichier de démarrage ;
4. installe les complétions zsh dans `~/.local/share/zsh/site-functions` et
   ajoute ce dossier au `fpath` ;
5. vérifie que les deux commandes répondent.

Il est idempotent : relancez-le après chaque modification du code pour mettre
l'installation à jour.

```bash
./install.sh --uninstall
```

retire le paquet, les complétions et le bloc ajouté au fichier de démarrage.

## Les complétions

Une fois installées, `moonlight-bitrate -<Tab>` liste les options avec leur
description, et `-p <Tab>` complète les **noms de profils lus dans votre
fichier de configuration** — celui passé par `-c`, ou `./config.toml` s'il
existe dans le dossier courant.

## Sans rien installer

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
moonlight-bitrate --help
```

Ou, sans environnement du tout, depuis le dossier du dépôt :

```bash
python __main__.py --help
python __main__.py recap -b 450
```

## Prérequis sur l'hôte

`iperf3` doit être installé sur la machine Sunshine, et accessible au chemin
indiqué par `host.iperf_path`. Une version **3.7 ou plus récente** est
fortement conseillée : voir [troubleshooting.md](troubleshooting.md).

L'accès SSH se fait par clé. Si vous partez de zéro :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_moonlight
ssh-copy-id -i ~/.ssh/id_moonlight.pub <compte>@<hôte>
```

Sous Windows, `ssh-copy-id` n'existe pas et plusieurs pièges attendent :
voir la section SSH de [troubleshooting.md](troubleshooting.md).

## Exécutables Windows

Pour un `.exe` autonome sans Python, voir la section « Exécutables Windows »
du [README](../README.md).
