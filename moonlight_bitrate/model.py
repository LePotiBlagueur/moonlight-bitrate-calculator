"""Modèle de débit : référence Moonlight, surcoûts réseau, faisabilité."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import CODEC_EFFICIENCY, QUALITY_FACTOR, ModelConfig

# Table de référence de Moonlight (StreamingPreferences::getDefaultBitrate) :
# pixels -> facteur de débit, interpolé linéairement entre deux points.
_RES_TABLE: list[tuple[int, float]] = [
    (640 * 360, 1.0),
    (854 * 480, 2.0),
    (1280 * 720, 5.0),
    (1920 * 1080, 10.0),
    (2560 * 1440, 20.0),
    (3840 * 2160, 40.0),
]


# Dernière entrée du tableau : au-delà, Moonlight ne prolonge pas la pente.
# Sa sentinelle {-1, -1} renvoie le facteur précédent (« Never go above the
# highest resolution entry »), donc la référence plafonne à 40 au-dessus de
# la 4K. On reproduit ce plafond, et les tableaux signalent les lignes
# concernées : la valeur y est un plancher, pas un besoin réel.
TABLE_MAX_PIXELS = _RES_TABLE[-1][0]


def resolution_factor(width: int, height: int) -> float:
    pixels = width * height
    if pixels <= _RES_TABLE[0][0]:
        return _RES_TABLE[0][1]
    for (p0, f0), (p1, f1) in zip(_RES_TABLE, _RES_TABLE[1:]):
        if pixels <= p1:
            return f0 + (pixels - p0) * (f1 - f0) / (p1 - p0)
    return _RES_TABLE[-1][1]


def reference_is_clamped(width: int, height: int) -> bool:
    """Vrai si Moonlight plafonne sa référence pour cette définition."""
    return width * height > TABLE_MAX_PIXELS


def framerate_factor(fps: int) -> float:
    """Au-delà de 60 fps, le besoin croît en racine carrée, pas linéairement."""
    effective = fps if fps <= 60 else math.sqrt(fps / 60.0) * 60.0
    return effective / 30.0


def moonlight_default_mbps(width: int, height: int, fps: int,
                           yuv444: bool = False) -> float:
    """Débit par défaut de Moonlight, en Mbps (référence H.264/HEVC 4:2:0)."""
    value = resolution_factor(width, height) * framerate_factor(fps)
    if yuv444:
        value *= 2.0
    return value


@dataclass
class ModeTarget:
    name: str
    width: int
    height: int
    fps: int
    reference_mbps: float   # référence Moonlight, avant codec/qualité
    video_mbps: float       # débit vidéo visé (codec + préréglage qualité)
    link_mbps: float        # besoin réseau total (vidéo + FEC + audio)
    verdict: str            # "ok" | "marginal" | "no"
    advised_mbps: float     # débit à saisir dans Moonlight
    headroom: float         # budget / besoin réseau
    clamped: bool = False   # référence plafonnée par Moonlight (> 4K)

    @property
    def pixel_rate(self) -> int:
        return self.width * self.height * self.fps

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height} @ {self.fps}"


def link_need(video_mbps: float, m: ModelConfig) -> float:
    """Débit réseau réellement consommé par un flux vidéo donné."""
    return video_mbps * (1.0 + m.fec_overhead) + m.audio_mbps


def max_video_for_budget(budget_mbps: float, m: ModelConfig) -> float:
    """Débit vidéo maximal tenable dans un budget réseau."""
    return max((budget_mbps - m.audio_mbps) / (1.0 + m.fec_overhead), 0.0)


def budget_from_capacity(clean_mbps: float, m: ModelConfig) -> float:
    return clean_mbps * m.safety_margin


def target_video_mbps(width: int, height: int, fps: int, m: ModelConfig) -> float:
    base = moonlight_default_mbps(width, height, fps, m.yuv444)
    base *= QUALITY_FACTOR.get(m.quality, 1.0)
    base *= CODEC_EFFICIENCY.get(m.codec, 1.0)
    if m.hdr:
        # Le HDR10 demande ~10 % de plus pour éviter le banding.
        base *= 1.10
    return base


def evaluate_mode(name: str, width: int, height: int, fps: int,
                  budget_mbps: float, m: ModelConfig) -> ModeTarget:
    reference = moonlight_default_mbps(width, height, fps, m.yuv444)
    video = target_video_mbps(width, height, fps, m)
    need = link_need(video, m)

    if need <= budget_mbps:
        verdict = "ok"
    elif need <= budget_mbps * (1.0 + m.marginal_tolerance):
        verdict = "marginal"
    else:
        verdict = "no"

    # On ne propose jamais plus que ce que le lien encaisse.
    advised = min(video, max_video_for_budget(budget_mbps, m))
    advised = max(advised, 0.0)

    return ModeTarget(
        name=name, width=width, height=height, fps=fps,
        reference_mbps=reference, video_mbps=video, link_mbps=need,
        verdict=verdict, advised_mbps=advised,
        headroom=(budget_mbps / need) if need > 0 else 0.0,
        clamped=reference_is_clamped(width, height),
    )


def build_matrix(budget_mbps: float, m: ModelConfig) -> list[ModeTarget]:
    return [
        evaluate_mode(name, w, h, fps, budget_mbps, m)
        for (name, w, h) in m.resolutions
        for fps in sorted(m.framerates)
    ]


def best_fps(resolution: tuple[str, int, int], budget_mbps: float,
             m: ModelConfig, accept_marginal: bool = False) -> ModeTarget | None:
    """Fréquence la plus haute tenable pour une définition donnée."""
    name, w, h = resolution
    allowed = ("ok", "marginal") if accept_marginal else ("ok",)
    for fps in sorted(m.framerates, reverse=True):
        mode = evaluate_mode(name, w, h, fps, budget_mbps, m)
        if mode.verdict in allowed:
            return mode
    return None


def best_per_resolution(
    matrix: list[ModeTarget], accept_marginal: bool = True,
) -> list[tuple[tuple[str, int, int], ModeTarget | None]]:
    """Pour chaque taille d'écran de la matrice, le mode le plus élevé tenable.

    L'ordre des définitions est préservé, et une taille hors budget renvoie
    None plutôt que d'être omise : la ligne doit rester visible.
    """
    order: list[tuple[str, int, int]] = []
    groups: dict[tuple[str, int, int], list[ModeTarget]] = {}
    for t in matrix:
        key = (t.name, t.width, t.height)
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(t)

    out = []
    for key in order:
        pool = [t for t in groups[key] if t.verdict == "ok"]
        if not pool and accept_marginal:
            pool = [t for t in groups[key] if t.verdict == "marginal"]
        out.append((key, max(pool, key=lambda t: t.fps) if pool else None))
    return out


def recommend_codec_short(advised_mbps: float, width: int, height: int) -> str:
    """Codec conseillé, en version courte pour une colonne de tableau."""
    pixels = width * height
    if pixels >= 2560 * 1440 or advised_mbps >= 50:
        return "AV1 ou HEVC"
    if advised_mbps >= 25:
        return "HEVC"
    return "HEVC (H.264 au besoin)"
