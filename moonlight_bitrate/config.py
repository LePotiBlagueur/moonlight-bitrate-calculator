"""Configuration : valeurs par défaut, fichier TOML, surcharges CLI."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


DEFAULT_RESOLUTIONS: list[tuple[str, int, int]] = [
    ("720p", 1280, 720),
    ("900p", 1600, 900),
    ("1080p", 1920, 1080),
    ("1200p 16:10", 1920, 1200),
    ("1440p", 2560, 1440),
    ("1600p 16:10", 2560, 1600),
    ("UW 1440p", 3440, 1440),
    ("4K", 3840, 2160),
]

DEFAULT_FRAMERATES: list[int] = [60, 90, 120, 144]


@dataclass
class HostConfig:
    """Hôte Sunshine distant (celui qui encode et envoie la vidéo)."""

    host: str = "192.168.1.10"
    # Nom de COMPTE Windows, pas le dossier de profil : les deux diffèrent
    # souvent, et sshd rejette un nom inconnu avant même de lire une clé.
    user: str = "kwak"
    port: int = 22
    key_path: str = "~/.ssh/id_moonlight"
    # Chemin d'iperf3 sur la machine distante (Windows : chemin absolu).
    iperf_path: str = r"C:\Program Files\iperf3\iperf3.exe"
    # Windows par défaut : on utilise taskkill pour le nettoyage.
    remote_os: str = "windows"  # "windows" | "unix"
    iperf_port: int = 5201
    # Si True, on suppose qu'un `iperf3 -s` tourne déjà en face : pas de SSH.
    no_ssh: bool = False


@dataclass
class BenchConfig:
    """Paramètres de la mesure réseau."""

    # Chemin d'iperf3 en local ; vide => détection automatique.
    iperf_path: str = ""
    # Sens testé. Le streaming va de l'hôte vers le client : "download".
    direction: str = "download"  # "download" | "upload" | "both"
    duration: int = 8  # secondes par palier
    omit: int = 1  # secondes ignorées en début de palier (slow start)
    streams: int = 1  # flux UDP parallèles (augmenter si l'émetteur plafonne)
    datagram_len: int = 1400  # octets, à garder sous la MTU
    # Vérifier la MTU du chemin avant de mesurer (instantané via la route,
    # complété par une sonde ICMP quand l'hôte y répond).
    mtu_check: bool = True
    # Réduire automatiquement datagram_len s'il dépasse la MTU trouvée.
    # Sans ça, chaque datagramme se fragmente et le taux de perte mesuré ne
    # reflète plus que la fragmentation.
    mtu_autofit: bool = True
    # Sonde TCP préalable pour borner la recherche UDP.
    tcp_probe: bool = True
    tcp_duration: int = 6
    tcp_streams: int = 4
    # Si pas de sonde TCP, plafond supposé du lien.
    assumed_ceiling_mbps: float = 1000.0
    # Paliers UDP : fractions du plafond estimé, en ordre croissant.
    ladder: list[float] = field(
        default_factory=lambda: [0.25, 0.40, 0.55, 0.70, 0.85, 1.00]
    )
    refine_steps: int = 3  # itérations de dichotomie après le premier échec
    refine_tolerance: float = 0.04  # on arrête si l'écart relatif est < 4 %
    # Critères d'acceptation d'un palier.
    max_loss_pct: float = 0.15
    max_jitter_ms: float = 3.0
    # En dessous de ce ratio atteint/visé, l'émetteur (et non le réseau) plafonne.
    sender_limited_ratio: float = 0.90
    retry_on_fail: bool = True  # rejouer une fois un palier en échec
    # Sonde de latence ICMP (facultative, non bloquante).
    ping_probe: bool = True
    ping_count: int = 20


@dataclass
class ModelConfig:
    """Modèle de calcul du débit vidéo nécessaire."""

    codec: str = "hevc"  # "h264" | "hevc" | "av1"
    quality: str = "balanced"  # "saver" | "balanced" | "high" | "max"
    yuv444: bool = False
    hdr: bool = False
    # Surcoût FEC de Sunshine (20 % par défaut côté Sunshine).
    fec_overhead: float = 0.20
    # Audio Opus : 0.5 Mbps en stéréo, ~1.5 Mbps en 5.1/7.1.
    audio_mbps: float = 0.5
    # Marge de sécurité appliquée à la capacité propre mesurée.
    safety_margin: float = 0.85
    # Tolérance pour marquer un mode « limite » plutôt qu'« impossible ».
    marginal_tolerance: float = 0.15
    resolutions: list[tuple[str, int, int]] = field(
        default_factory=lambda: list(DEFAULT_RESOLUTIONS)
    )
    framerates: list[int] = field(default_factory=lambda: list(DEFAULT_FRAMERATES))


@dataclass
class AppConfig:
    host: HostConfig = field(default_factory=HostConfig)
    bench: BenchConfig = field(default_factory=BenchConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    verbose: bool = False
    color: bool = True
    pause: bool = False
    # Nom du profil appliqué par-dessus la configuration de base, s'il y en a un.
    active_profile: str | None = None

    # --- helpers -----------------------------------------------------------

    def resolved_key_path(self) -> Path:
        return Path(os.path.expanduser(self.host.key_path))

    def local_iperf(self) -> str:
        if self.bench.iperf_path:
            return os.path.expanduser(self.bench.iperf_path)
        found = shutil.which("iperf3") or shutil.which("iperf3.exe")
        if found:
            return found
        # Dernier recours : chemin Windows classique.
        return r"C:\Program Files\iperf3\iperf3.exe"


CODEC_EFFICIENCY: dict[str, float] = {
    # Débit requis pour une qualité équivalente, relatif à H.264.
    "h264": 1.00,
    "hevc": 0.75,
    "av1": 0.65,
}

QUALITY_FACTOR: dict[str, float] = {
    "saver": 0.75,
    "balanced": 1.00,
    "high": 1.25,
    "max": 1.50,
}


# --------------------------------------------------------------------------
# Chargement TOML
# --------------------------------------------------------------------------


def _apply(section: Any, data: dict[str, Any], path: str) -> None:
    known = {f.name for f in fields(section)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Clé inconnue dans la config : [{path}] {key}")
        current = getattr(section, key)
        if is_dataclass(current):
            _apply(current, value, f"{path}.{key}")
        else:
            setattr(section, key, value)


def _apply_layer(cfg: AppConfig, data: dict[str, Any], origin: str) -> None:
    """Applique une couche de configuration (base, puis profil) sur `cfg`."""
    for section_name in ("host", "bench", "model"):
        if section_name in data:
            _apply(getattr(cfg, section_name), data[section_name],
                   f"{origin}{section_name}")
    # Clés racine (verbose, color, pause…)
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    _apply(cfg, scalars, origin.rstrip("."))


def _read_toml(path: str | os.PathLike[str]) -> dict[str, Any]:
    file = Path(os.path.expanduser(str(path)))
    if not file.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {file}")
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("tomllib indisponible : Python 3.11+ requis pour --config")
    with file.open("rb") as fh:
        return tomllib.load(fh)


def list_profiles(path: str | os.PathLike[str] | None) -> list[str]:
    """Noms des profils déclarés dans le fichier, triés."""
    if path is None:
        return []
    profiles = _read_toml(path).get("profiles") or {}
    return sorted(profiles) if isinstance(profiles, dict) else []


def load_config(path: str | os.PathLike[str] | None,
                profile: str | None = None) -> AppConfig:
    """Charge la configuration, en appliquant éventuellement un profil.

    Un profil est une surcouche : `[profiles.vpn.bench]` ne remplace que les
    clés qu'il cite, le reste vient de `[bench]`.
    """
    cfg = AppConfig()
    if path is None:
        if profile:
            raise ValueError(
                f"Le profil « {profile} » exige un fichier de configuration (-c)."
            )
        return cfg

    data = _read_toml(path)
    profiles = data.pop("profiles", {}) or {}
    if not isinstance(profiles, dict):
        raise ValueError("La section [profiles] doit contenir des sous-tables.")

    _apply_layer(cfg, data, "")

    if profile:
        if profile not in profiles:
            available = ", ".join(sorted(profiles)) or "aucun profil déclaré"
            raise ValueError(
                f"Profil inconnu : « {profile} ». Disponibles : {available}."
            )
        _apply_layer(cfg, profiles[profile], f"profiles.{profile}.")
        cfg.active_profile = profile

    # Les résolutions arrivent en listes TOML : on normalise en tuples.
    cfg.model.resolutions = [
        (str(r[0]), int(r[1]), int(r[2])) for r in cfg.model.resolutions
    ]
    cfg.model.framerates = [int(f) for f in cfg.model.framerates]
    return cfg
