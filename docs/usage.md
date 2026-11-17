# Recettes

Les deux commandes partagent la plupart des options. `moonlight-bitrate`
mesure et rapporte ; `moonlight-recap` produit le tableau récapitulatif, avec
ou sans mesure.

## Le cas courant

```bash
moonlight-bitrate -c ~/.config/moonlight/config.toml -p lan
```

Mesure le lien, affiche la matrice résolutions × fps et la recommandation.

## Connaître la MTU sans mesurer

```bash
moonlight-bitrate -c config.toml -p vpn --probe-mtu
```

Instantané. Donne `bench.datagram_len`, l'option `packetsize` à mettre dans
Sunshine (`MTU − 28 − 16`), et la MTU WireGuard. Ajoutez `--underlay` si le chemin sondé
*transporte* le tunnel au lieu d'être dedans.

## Mesurer une fois, décider plusieurs fois

```bash
moonlight-bitrate -c config.toml -p lan --save ~/mesures-lan.json
moonlight-recap --load ~/mesures-lan.json --codec av1 --quality max
moonlight-recap --load ~/mesures-lan.json --codec h264 --sections best
```

La mesure coûte une minute et sollicite le réseau ; l'analyse est gratuite.
Enregistrez, puis comparez les codecs et les préréglages hors ligne.

## Partager le récapitulatif

```bash
moonlight-recap --load mesures.json --format html -o recap.html
moonlight-recap --load mesures.json --format markdown >> notes.md
moonlight-recap --load mesures.json --format csv  -o recap.csv
moonlight-recap --load mesures.json --format json | jq '.tables[1]'
```

Le journal de mesure part sur stderr, donc une redirection reste propre.

## Cibler quelques modes seulement

```bash
moonlight-recap -b 450 \
  --resolution 1920x1200 --resolution 2560x1440 \
  --fps 120 --fps 144
```

`--resolution` et `--fps` sont répétables et **remplacent** les listes de la
config. Le nom d'affichage se préfixe : `--resolution "UW:3440x1440"`.

## Sans fichier de configuration

```bash
moonlight-bitrate --host 192.168.1.10 --user kwak --key ~/.ssh/id_rsa \
                  --codec av1 --quality high
```

## Sans mesure du tout

```bash
moonlight-recap -b 450        # capacité connue, la marge est appliquée
moonlight-recap --budget 380  # budget déjà net de marge
```

## Mesurer aussi la voie de retour

```bash
moonlight-bitrate -c config.toml -p lan --direction both
```

Le sens client → hôte porte les commandes de manette et le micro : quelques
centaines de kbps, mais sa latence compte.

## Serveur iperf3 lancé à la main

```bash
# sur l'hôte
iperf3 -s
# sur le client
moonlight-bitrate --no-ssh --host 192.168.1.10
```

Évite d'avoir à configurer SSH pour un essai ponctuel.

## Diagnostiquer une mesure décevante

```bash
moonlight-bitrate -c config.toml -p lan -v \
  --max-loss 0.5 --max-jitter 10 --refine 5
```

Desserrer les seuils montre jusqu'où le lien monte avant de s'écrouler.
Resserrer (`--max-loss 0.01`) montre à partir d'où il commence à souffrir.

## Codes de sortie

| Code | Sens |
|---|---|
| `0` | Succès. |
| `1` | Erreur inattendue. |
| `2` | Erreur attendue et expliquée : config invalide, SSH, iperf3, aucune source de débit, aucun palier propre. |
| `130` | Interrompu au clavier. |
