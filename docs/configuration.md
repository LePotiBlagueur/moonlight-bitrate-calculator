# Référence de configuration

Toutes les clés du fichier TOML, leur valeur par défaut et ce qu'elles font.

L'ordre de priorité est : **option de ligne de commande** > **profil**
(`[profiles.<nom>]`) > **section de base** > **valeur par défaut**.

Un profil est une surcouche : il ne redéfinit que les clés qu'il cite.

---

## Racine

| Clé | Défaut | Rôle |
|---|---|---|
| `verbose` | `false` | Journal détaillé ; fait aussi remonter la trace complète en cas d'erreur inattendue. |
| `color` | `true` | Couleurs ANSI. Désactivées d'office si la sortie n'est pas un terminal. |
| `pause` | `false` | Attendre une touche avant de rendre la main. Utile au double-clic sous Windows. |

## `[host]` — la machine Sunshine

| Clé | Défaut | Rôle |
|---|---|---|
| `host` | `192.168.1.10` | IP ou nom de l'hôte. C'est aussi la cible de la sonde MTU. |
| `user` | `kwak` | **Nom de compte Windows**, pas le dossier de profil. Voir [troubleshooting.md](troubleshooting.md). |
| `port` | `22` | Port SSH. |
| `key_path` | `~/.ssh/id_moonlight` | Clé privée. Ed25519, RSA et ECDSA sont essayées dans cet ordre. |
| `iperf_path` | `C:\Program Files\iperf3\iperf3.exe` | Chemin d'iperf3 **sur l'hôte**. |
| `remote_os` | `windows` | `windows` ou `unix` : détermine les commandes de nettoyage (`taskkill` ou `pkill`). |
| `iperf_port` | `5201` | Port d'écoute du serveur iperf3. |
| `no_ssh` | `false` | Ne pas piloter l'hôte : suppose un `iperf3 -s` déjà lancé en face. |

## `[bench]` — la mesure

### Exécution

| Clé | Défaut | Rôle |
|---|---|---|
| `iperf_path` | `""` | Chemin d'iperf3 **en local**. Vide = recherché dans le `PATH`. |
| `direction` | `download` | `download` (hôte → client, le sens de la vidéo), `upload`, ou `both`. |
| `duration` | `8` | Durée d'un palier, en secondes. |
| `omit` | `1` | Secondes ignorées en début de palier, le temps que le débit se stabilise. |
| `streams` | `1` | Flux UDP parallèles. **Nécessite iperf3 ≥ 3.2** : les vieux builds Cygwin rendent une sortie vide avec `-P`. |

### Taille des paquets

| Clé | Défaut | Rôle |
|---|---|---|
| `datagram_len` | `1400` | Taille des datagrammes UDP, en octets. Doit tenir dans la MTU moins 28 octets d'en-têtes IP+UDP. |
| `mtu_check` | `true` | Sonder la MTU du chemin avant de mesurer. |
| `mtu_autofit` | `true` | Réduire `datagram_len` s'il dépasse la MTU trouvée. Sans ça, chaque datagramme se fragmente et le taux de perte relevé ne mesure plus que la fragmentation. |

### Cadrage de la recherche

| Clé | Défaut | Rôle |
|---|---|---|
| `tcp_probe` | `true` | Sonde TCP préalable, qui borne la recherche UDP. |
| `tcp_duration` | `6` | Durée de la sonde TCP, en secondes. |
| `tcp_streams` | `4` | Flux TCP parallèles de la sonde. |
| `assumed_ceiling_mbps` | `1000.0` | Plafond supposé quand `tcp_probe = false`. |
| `ladder` | `[0.25, 0.40, 0.55, 0.70, 0.85, 1.00]` | Paliers testés, en fraction du plafond estimé. Les paliers sous 5 Mbps sont ignorés. |
| `refine_steps` | `3` | Itérations de dichotomie après le premier palier en échec. |
| `refine_tolerance` | `0.04` | La dichotomie s'arrête sous cet écart relatif. |

### Critères d'acceptation d'un palier

| Clé | Défaut | Rôle |
|---|---|---|
| `max_loss_pct` | `0.15` | Perte maximale tolérée, en pourcent. |
| `max_jitter_ms` | `3.0` | Gigue maximale tolérée, en millisecondes. |
| `sender_limited_ratio` | `0.90` | Sous ce ratio reçu/visé avec une perte nulle, c'est l'émetteur qui plafonne, pas le réseau. |
| `retry_on_fail` | `true` | Rejouer une fois un palier en échec avant de le déclarer perdu. |

### Latence

| Clé | Défaut | Rôle |
|---|---|---|
| `ping_probe` | `true` | Sonde ICMP d'appoint. Jamais bloquante : un échec est signalé puis ignoré. |
| `ping_count` | `20` | Nombre de paquets ICMP. |

## `[model]` — le calcul du débit

| Clé | Défaut | Rôle |
|---|---|---|
| `codec` | `hevc` | `h264`, `hevc` ou `av1`. Applique un facteur d'efficacité de ×1.00, ×0.75 et ×0.65. |
| `quality` | `balanced` | `saver` (×0.75), `balanced` (×1.00), `high` (×1.25), `max` (×1.50) de la référence Moonlight. |
| `yuv444` | `false` | Flux 4:4:4 : double le débit nécessaire. |
| `hdr` | `false` | Flux HDR : +10 % pour éviter le banding. |
| `fec_overhead` | `0.20` | Surcoût FEC de Sunshine, appliqué par-dessus le débit vidéo. |
| `audio_mbps` | `0.5` | Débit audio réservé. 0.5 en stéréo, ~1.5 en 5.1/7.1. |
| `safety_margin` | `0.85` | Part de la capacité propre mesurée réellement exploitée. |
| `marginal_tolerance` | `0.15` | Au-delà du budget mais sous cette tolérance, un mode est marqué « limite » plutôt qu'« impossible ». |
| `resolutions` | 17 entrées, de 720p à 5K (16:9, 16:10, 21:9, 32:9) | Liste de `["nom", largeur, hauteur]`. Au-delà de 3840x2160, Moonlight plafonne sa référence de débit : ces lignes sont signalées `*` et la valeur est un plancher. |
| `framerates` | `[60, 90, 120, 144, 175]` | Fréquences évaluées. |

## `[profiles.<nom>]`

Contient les mêmes sous-tables `host`, `bench` et `model`, appliquées
par-dessus les sections de base.

```toml
[bench]
duration = 8

[profiles.vpn.bench]
duration = 10          # seule cette clé change ; le reste vient de [bench]

[profiles.vpn.model]
safety_margin = 0.75
```

Un nom de profil inexistant provoque une erreur qui liste ceux qui sont
déclarés. Une clé inconnue est signalée avec son chemin complet
(`[profiles.vpn.bench] nimportequoi`).
