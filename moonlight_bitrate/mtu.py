"""Découverte de la MTU du chemin et réglages qui en découlent.

Deux méthodes, de la plus fiable à la plus approximative :

1. ICMP avec bit « ne pas fragmenter » : vraie MTU de bout en bout, mais
   beaucoup de tunnels et de pare-feu bloquent l'ICMP.
2. Route locale (Linux) : le noyau connaît la MTU de l'interface de sortie.
   Instantané et toujours disponible, mais ce n'est qu'une borne haute — un
   goulet plus loin sur le chemin ne s'y verra pas.
"""

from __future__ import annotations

import platform
import re
import socket
import subprocess
from dataclasses import dataclass, field

# En-têtes à retrancher d'une MTU pour obtenir la charge utile.
IPV4_HEADER = 20
IPV6_HEADER = 40
UDP_HEADER = 8
ICMP_HEADER = 8

# Encapsulation WireGuard : en-tête IP + UDP + 32 octets de protocole.
WG_OVERHEAD_V4 = IPV4_HEADER + UDP_HEADER + 32  # 60
WG_OVERHEAD_V6 = IPV6_HEADER + UDP_HEADER + 32  # 80

# Plancher IPv4 garanti par la RFC 791 ; 1280 est le plancher IPv6, valeur
# qui passe partout en mobilité.
MIN_MTU = 576
SAFE_MOBILE_MTU = 1280
MAX_MTU = 9000

_TOO_BIG = re.compile(
    r"too long|trop (?:long|grand)|frag(?:ment)?|besoin.*fragment|"
    r"doit être fragmenté|packet needs to be fragmented|message too long",
    re.IGNORECASE,
)


@dataclass
class MtuResult:
    host: str
    path_mtu: int | None = None          # MTU du chemin, en-têtes IP inclus
    route_mtu: int | None = None         # MTU de l'interface de sortie locale
    method: str = "indisponible"         # "icmp" | "route" | "indisponible"
    probes: list[tuple[int, bool]] = field(default_factory=list)
    note: str = ""

    @property
    def effective_mtu(self) -> int | None:
        """La contrainte réelle : le plus petit des deux si les deux existent."""
        values = [v for v in (self.path_mtu, self.route_mtu) if v]
        return min(values) if values else None


# --------------------------------------------------------------------------
# Méthode 1 : ICMP avec DF
# --------------------------------------------------------------------------


def _ping_df(host: str, payload: int, windows: bool, timeout: float = 3.0) -> bool:
    """Envoie un écho ICMP non fragmentable de `payload` octets utiles."""
    if windows:
        cmd = ["ping", "-n", "1", "-w", "2000", "-f", "-l", str(payload), host]
    else:
        cmd = ["ping", "-c", "1", "-W", "2", "-M", "do", "-s", str(payload), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if proc.returncode == 0:
        # Windows renvoie 0 même quand il annonce « paquet à fragmenter ».
        return not _TOO_BIG.search((proc.stdout or "") + (proc.stderr or ""))
    return False


def discover_icmp(host: str, lo: int = MIN_MTU, hi: int = 1500,
                  windows: bool | None = None,
                  probe=_ping_df) -> MtuResult:
    """Dichotomie sur la taille utile ICMP pour trouver la MTU du chemin."""
    if windows is None:
        windows = platform.system() == "Windows"
    result = MtuResult(host=host)
    overhead = IPV4_HEADER + ICMP_HEADER

    # L'hôte répond-il seulement à l'ICMP ? Sans ce garde-fou, un hôte muet
    # ferait conclure à une MTU minuscule.
    if not probe(host, 64, windows):
        result.note = ("L'hôte ne répond pas à l'ICMP : méthode inapplicable "
                       "(fréquent dans un tunnel ou derrière un pare-feu).")
        return result

    if probe(host, hi - overhead, windows):
        result.probes.append((hi, True))
        result.path_mtu, result.method = hi, "icmp"
        result.note = f"Aucune réduction détectée jusqu'à {hi} octets."
        return result
    result.probes.append((hi, False))

    low, high = lo, hi  # low passe, high échoue
    while high - low > 1:
        middle = (low + high) // 2
        ok = probe(host, middle - overhead, windows)
        result.probes.append((middle, ok))
        if ok:
            low = middle
        else:
            high = middle

    result.path_mtu, result.method = low, "icmp"
    return result


# --------------------------------------------------------------------------
# Méthode 2 : MTU de la route locale (Linux)
# --------------------------------------------------------------------------

_IP_MTU = 14              # <linux/in.h>
_IP_MTU_DISCOVER = 10
_IP_PMTUDISC_DO = 2


def route_mtu(host: str, port: int = 5201) -> int | None:
    """MTU que le noyau associe à la route vers `host`, sans émettre de trafic."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    try:
        sock.setsockopt(socket.IPPROTO_IP, _IP_MTU_DISCOVER, _IP_PMTUDISC_DO)
        sock.connect((host, port))
        value = sock.getsockopt(socket.IPPROTO_IP, _IP_MTU)
        return value if MIN_MTU <= value <= MAX_MTU else None
    except OSError:
        return None
    finally:
        sock.close()


def discover(host: str, port: int = 5201, windows: bool | None = None,
             probe=_ping_df) -> MtuResult:
    """Combine les deux méthodes ; retient la contrainte la plus basse."""
    result = discover_icmp(host, windows=windows, probe=probe)
    result.route_mtu = route_mtu(host, port)
    if result.path_mtu is None and result.route_mtu:
        result.method = "route"
        result.note = (result.note + " "
                       "Repli sur la MTU de la route locale : c'est une borne "
                       "haute, un goulet plus loin ne s'y verrait pas.").strip()
    return result


# --------------------------------------------------------------------------
# Traduction en réglages
# --------------------------------------------------------------------------


@dataclass
class MtuAdvice:
    mtu: int
    datagram_len: int        # pour bench.datagram_len (iperf3 -l)
    sunshine_packet_size: int
    wireguard_mtu: int       # si CE chemin est le transport du tunnel
    through_tunnel: bool


def advise(mtu: int, through_tunnel: bool = True,
           ipv6: bool = False) -> MtuAdvice:
    """Réglages déduits d'une MTU.

    `through_tunnel` dit si la MTU mesurée est celle vue *à l'intérieur* du
    tunnel (cas courant : on mesure l'hôte à travers WireGuard). Sinon c'est
    celle du transport, et c'est elle qui sert à dimensionner le tunnel.
    """
    ip_header = IPV6_HEADER if ipv6 else IPV4_HEADER
    payload = mtu - ip_header - UDP_HEADER
    overhead = WG_OVERHEAD_V6 if ipv6 else WG_OVERHEAD_V4
    return MtuAdvice(
        mtu=mtu,
        datagram_len=payload,
        sunshine_packet_size=payload,
        wireguard_mtu=(mtu if through_tunnel else mtu - overhead),
        through_tunnel=through_tunnel,
    )


def fits(datagram_len: int, mtu: int, ipv6: bool = False) -> bool:
    """Un datagramme de cette taille passe-t-il sans fragmentation ?"""
    ip_header = IPV6_HEADER if ipv6 else IPV4_HEADER
    return datagram_len + ip_header + UDP_HEADER <= mtu
