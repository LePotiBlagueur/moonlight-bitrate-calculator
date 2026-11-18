# Comment le chiffre est obtenu

## 1. La MTU, avant tout le reste

Un datagramme plus gros que la MTU est fragmenté par IP. Si un seul fragment
se perd, le datagramme entier est perdu : le taux de perte relevé ne mesure
alors plus le lien mais la fragmentation. Tout commence donc par la MTU.

Deux méthodes, parce qu'aucune ne suffit seule :

- **ICMP avec bit « ne pas fragmenter »**, par dichotomie sur la taille utile.
  C'est la vraie MTU de bout en bout. Beaucoup de tunnels et de pare-feu ne
  répondent pas à l'ICMP ; un garde-fou vérifie d'abord que l'hôte répond du
  tout, sans quoi un hôte muet ferait conclure à une MTU minuscule.
- **MTU de la route locale**, lue auprès du noyau via `IP_MTU` sur une socket
  UDP connectée en `IP_PMTUDISC_DO`. Instantanée, aucun trafic émis, mais
  c'est une **borne haute** : un goulet plus loin ne s'y verrait pas.

Quand les deux répondent, la plus basse s'applique.

Les réglages en découlent : `bench.datagram_len` vaut `MTU − 28` (en-têtes IP
et UDP), et l'option `packetsize` de Sunshine `MTU − 28 − 16`, les 16 octets
supplémentaires étant l'en-tête du flux. Sunshine la laisse à `0`
(automatique) par défaut ; la fixer n'est utile que quand le client ne détecte
pas correctement la MTU, ce qui arrive à travers un VPN.

## 2. Le sens de la mesure

Le flux vidéo va de l'hôte vers le client. La mesure utilise donc `-R`
(reverse), et c'est le client qui reçoit — comme en jeu. Mesurer dans l'autre
sens donnerait l'upload du client, qui n'a rien à voir.

## 3. Cadrage par TCP

Une sonde TCP courte, multi-flux, donne un ordre de grandeur. Elle sert
uniquement à borner la recherche UDP : inutile de tester 25 Mbps par 25 Mbps
jusqu'à 1 Gbps quand le lien plafonne à 90.

## 4. L'échelle UDP

Des paliers croissants, par défaut 25 %, 40 %, 55 %, 70 %, 85 % et 100 % du
plafond estimé. Un palier est retenu si **trois** conditions tiennent :

| Condition | Pourquoi |
|---|---|
| perte ≤ `max_loss_pct` | Au-delà, l'image se dégrade visiblement. |
| gigue ≤ `max_jitter_ms` | La gigue vide le tampon de réception et saccade. |
| reçu/visé ≥ `sender_limited_ratio` | Sinon c'est l'émetteur qui plafonne, pas le lien. |

Cette troisième condition est ce qui distingue un lien saturé d'un iperf3
Windows qui ne sait pas générer le débit demandé — deux situations qui
produisent des chiffres identiques si on ne regarde que le débit reçu.

Un palier en échec est rejoué une fois avant d'être déclaré perdu : sur un
lien bruité, un seul essai ne prouve rien.

## 5. Dichotomie

Entre le dernier palier propre et le premier en échec, trois itérations par
défaut, arrêt à 4 % d'écart relatif. Sur un lien simulé, la convergence tombe
à moins de 3 % de la capacité réelle.

## 6. Du débit au réglage

```
budget réseau   = capacité propre × safety_margin
vidéo maximale  = (budget − audio) ÷ (1 + fec_overhead)
```

Sunshine ajoute de la FEC par-dessus le flux vidéo (20 % par défaut) et
l'audio Opus passe dans le même tuyau. Le débit que vous saisissez dans
Moonlight est celui de la **vidéo seule** : si vous réglez 50 Mbps, le lien en
voit 60,5. C'est l'erreur que fait tout calcul qui compare naïvement le débit
réglé à la bande passante mesurée.

## 7. Le besoin de chaque mode

La référence est la formule de Moonlight elle-même
(`StreamingPreferences::getDefaultBitrate`) :

```
facteur de résolution : interpolation linéaire sur le nombre de pixels
    360p → 1    480p → 2    720p → 5
   1080p → 10  1440p → 20  2160p → 40
   au-delà de 3840x2160 : plafonné à 40 (comme Moonlight)

facteur de fréquence :  fps ≤ 60  →  fps / 30
                        fps > 60  →  √(fps / 60) × 60 / 30

débit = facteur de résolution × facteur de fréquence
```

D'où 1080p60 = 20 Mbps, 1440p60 = 40, 4K60 = 80. Au-delà de 60 fps le besoin
croît en racine carrée, pas linéairement : passer de 60 à 120 fps ne double
pas le débit nécessaire, il le multiplie par ~1,41.

Le tableau s'arrête à la 4K, et la sentinelle du code amont renvoie alors le
dernier facteur : une 5K reçoit par défaut le même débit qu'une 4K. On
reproduit ce plafond plutôt que de prolonger la pente — c'est bien ce que
Moonlight proposera — mais les lignes concernées sont marquées `*` dans les
tableaux : la valeur y est un plancher, pas le besoin réel d'une 5K.

Deux facteurs s'appliquent ensuite :

- **codec** — H.264 ×1.00, HEVC ×0.75, AV1 ×0.65, à qualité équivalente ;
- **préréglage** — `saver` ×0.75, `balanced` ×1.00, `high` ×1.25, `max` ×1.50.

Puis `yuv444` double et `hdr` ajoute 10 %.

Un mode est **confortable** si son besoin réseau tient dans le budget,
**limite** s'il le dépasse de moins de `marginal_tolerance`, **impossible**
au-delà. Le débit conseillé n'excède jamais ce que le lien encaisse.

## Organisation du code

```
moonlight_bitrate/
  config.py      dataclasses, TOML, profils, surcharges
  mtu.py         MTU du chemin (ICMP + route) et réglages déduits
  remote.py      serveur iperf3 distant par SSH, détection de version
  iperf.py       exécution d'iperf3, parsing JSON tolérant, sonde ICMP
  ladder.py      recherche de la capacité propre (paliers + dichotomie)
  model.py       formule Moonlight, FEC/audio, faisabilité par mode
  report.py      journal console et tableaux
  recap.py       tableaux récapitulatifs et rendus
  cli.py         commande moonlight-bitrate
  recap_cli.py   commande moonlight-recap
  entry.py       points d'entrée des exécutables Windows
```

Le parsing JSON d'iperf3 essaie trois formes successives (`end.sum`,
`end.sum_received`, puis agrégation manuelle des flux) parce que la structure
a changé selon les versions. Validé sur une sortie réelle d'iperf 3.1.4.
