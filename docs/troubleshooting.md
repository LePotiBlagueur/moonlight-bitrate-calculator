# Dépannage

## `Permission denied (publickey)` alors que la clé est en place

Trois causes distinctes donnent le même message. Le journal de sshd sur l'hôte
tranche en une commande :

```powershell
Get-WinEvent -LogName "OpenSSH/Operational" -MaxEvents 10 |
  Select-Object TimeCreated, Message | Format-List
```

### `Invalid user <nom>` — mauvais nom de compte

Le dossier de profil n'est pas le nom de compte. `C:\Users\falaa` peut très
bien appartenir au compte `kwak`. Un mauvais nom est rejeté **avant** toute
vérification de clé, ce qui ressemble à s'y méprendre à un problème de clé.

```powershell
whoami                                              # nom qualifié exact
Get-LocalUser | Select-Object Name, Enabled         # comptes utilisables
```

### `authorized_keys` est un dossier

OpenSSH lit `~/.ssh/authorized_keys` comme un **fichier texte**, une clé par
ligne. Un répertoire du même nom contenant des `.pub` n'est jamais consulté.

```powershell
cd $env:USERPROFILE\.ssh
Get-Content .\authorized_keys\*.pub | Set-Content -Encoding ascii .\ak.tmp
Remove-Item -Recurse -Force .\authorized_keys
Rename-Item .\ak.tmp authorized_keys
```

### Compte administrateur

Pour un membre du groupe Administrateurs, sshd **ignore**
`~/.ssh/authorized_keys` et ne lit que
`C:\ProgramData\ssh\administrators_authorized_keys` — c'est la règle
`Match Group administrators` du `sshd_config` par défaut sous Windows.

En console élevée :

```powershell
$k = Get-Content C:\Users\<profil>\.ssh\authorized_keys -Raw
Set-Content -Path C:\ProgramData\ssh\administrators_authorized_keys `
            -Value $k -Encoding ascii
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r `
       /grant *S-1-5-32-544:F /grant *S-1-5-18:F
```

`Set-Content` écrit *dans* le fichier existant ; `Copy-Item` le remplace et
échoue sur les ACL. Les SID (`*S-1-5-32-544` = Administrateurs,
`*S-1-5-18` = SYSTEM) évitent les noms de groupes localisés.

N'écrivez **jamais** ce fichier avec `>` ou `Out-File` : PowerShell 5.1 produit
de l'UTF-16 et sshd ne lit plus rien.

---

## « L'émetteur ne tient pas la cadence demandée »

iperf3 a généré nettement moins que le débit visé, sans perte. Ce n'est pas le
réseau qui sature, c'est l'émetteur. La capacité affichée est un **plancher**.

Les binaires Windows d'iperf3 sont compilés sous Cygwin et plafonnent souvent
loin sous la vitesse du lien en UDP. Remèdes, dans l'ordre :

1. Mettre iperf3 à jour sur l'hôte (3.7+).
2. `bench.streams = 2` ou `4` — **seulement** avec iperf3 ≥ 3.2.
3. `bench.datagram_len = 8900` si le réseau accepte les trames jumbo.

---

## « iperf3 X.Y sur l'hôte : build ancien »

Les binaires qui traînent depuis des années sont souvent en **3.1.4 (Cygwin,
2016)**. Le cadencement de `-b` y est grossier, `-P` rend une sortie vide en
UDP, et `retransmits` est absent des rapports TCP. La mesure reste exploitable
mais pessimiste. Une 3.7+ depuis <https://iperf.fr/iperf-download.php> change
nettement la précision.

---

## Perte élevée et erratique

Si le même palier passe de 3 % à 50 % de perte d'un essai à l'autre, cherchez
dans cet ordre :

1. **Fragmentation.** `--probe-mtu` : si `datagram_len` dépasse la MTU, le
   taux de perte ne mesure plus que la fragmentation. `mtu_autofit` corrige
   automatiquement, mais vérifiez qu'il n'a pas été désactivé.
2. **Mise en file d'attente.** Un écart important entre TCP brut et UDP propre
   est la signature d'un tunnel, d'un Wi-Fi ou d'un routeur qui écrête.
3. **Wi-Fi.** Mesurez en filaire pour trancher.

---

## « Aucun palier n'a saturé le lien »

Tous les paliers sont passés : le lien est plus rapide que ce qui a été testé.
Relevez `bench.assumed_ceiling_mbps`, ou le dernier échelon de `bench.ladder`.

---

## « Rien n'écoute sur <hôte>:5201 »

Avec `--no-ssh`, l'outil suppose un `iperf3 -s` déjà lancé. Lancez-le, ou
retirez `--no-ssh` pour qu'il s'en charge par SSH.

---

## La sonde MTU ne trouve rien

Les deux méthodes ont échoué : l'hôte ne répond pas à l'ICMP **et** le noyau
ne connaît pas de MTU pour cette route (hors Linux, notamment). Gardez une
valeur basse et sûre :

```toml
[bench]
datagram_len = 1252    # MTU 1280, le plancher qui passe partout
```
