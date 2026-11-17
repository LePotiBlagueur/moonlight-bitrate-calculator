"""Journalisation console et rendu des tableaux de résultats."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .config import CODEC_EFFICIENCY, QUALITY_FACTOR, AppConfig
from .iperf import UdpTrial
from .ladder import DIRECTION_LABEL, DirectionProfile, NetworkProfile
from .model import ModeTarget, best_modes, max_video_for_budget, recommend_codec


@dataclass
class Palette:
    reset: str = ""
    dim: str = ""
    bold: str = ""
    green: str = ""
    yellow: str = ""
    red: str = ""
    cyan: str = ""

    @classmethod
    def for_output(cls, enabled: bool) -> "Palette":
        if not enabled or not sys.stdout.isatty():
            return cls()
        return cls(
            reset="\033[0m", dim="\033[2m", bold="\033[1m",
            green="\033[32m", yellow="\033[33m", red="\033[31m", cyan="\033[36m",
        )


class Logger:
    def __init__(self, palette: Palette, verbose: bool = False) -> None:
        self.c = palette
        self.verbose = verbose

    def section(self, text: str) -> None:
        c = self.c
        print(f"\n{c.bold}{c.cyan}── {text} {'─' * max(0, 62 - len(text))}{c.reset}")

    def step(self, text: str) -> None:
        print(f"{self.c.dim}  ·{self.c.reset} {text}")

    def ok(self, text: str) -> None:
        print(f"  {self.c.green}✓{self.c.reset} {text}")

    def warn(self, text: str) -> None:
        print(f"  {self.c.yellow}!{self.c.reset} {text}")

    def error(self, text: str) -> None:
        print(f"  {self.c.red}✗{self.c.reset} {text}")

    def trial(self, t: UdpTrial) -> None:
        c = self.c
        if t.ok:
            mark, color = "✓", c.green
        elif t.sender_limited:
            mark, color = "~", c.yellow
        else:
            mark, color = "✗", c.red
        line = (
            f"  {color}{mark}{c.reset} {t.target_mbps:7.1f} Mbps visés → "
            f"{t.achieved_mbps:7.1f} reçus | perte {t.loss_pct:6.2f} % | "
            f"gigue {t.jitter_ms:5.2f} ms | {t.packets:>8d} paquets"
        )
        if t.note:
            line += f" {c.dim}({t.note}){c.reset}"
        print(line)


# --------------------------------------------------------------------------
# Tableaux
# --------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]], aligns: str = "") -> str:
    aligns = aligns or "l" * len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _visible_len(cell))

    def fmt(cells: list[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            pad = widths[i] - _visible_len(cell)
            out.append(cell + " " * pad if aligns[i] == "l" else " " * pad + cell)
        return "  " + " │ ".join(out)

    sep = "  " + "─┼─".join("─" * w for w in widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def _visible_len(text: str) -> int:
    out, in_esc = 0, False
    for ch in text:
        if in_esc:
            in_esc = ch != "m"
        elif ch == "\033":
            in_esc = True
        else:
            out += 1
    return out


def mtu_report(result, advice, log: "Logger") -> None:
    """Détail d'une sonde de MTU et réglages qui en découlent."""
    c = log.c
    log.section(f"MTU du chemin vers {result.host}")
    rows = [
        ["MTU du chemin (ICMP)",
         f"{result.path_mtu}" if result.path_mtu else "—"],
        ["MTU de la route locale",
         f"{result.route_mtu}" if result.route_mtu else "—"],
        ["Méthode retenue", result.method],
    ]
    print(_table(["Mesure", "Octets"], rows, aligns="lr"))
    if result.note:
        print(f"  {c.dim}{result.note}{c.reset}")
    if result.probes:
        detail = ", ".join(f"{size}{'✓' if ok else '✗'}" for size, ok in result.probes)
        print(f"  {c.dim}Sondes : {detail}{c.reset}")

    if advice is None:
        log.error("MTU indéterminée : gardez une valeur basse "
                  "(datagram_len = 1252, MTU WireGuard = 1280).")
        return

    print()
    rows = [
        ["bench.datagram_len", f"{advice.datagram_len}",
         "taille des datagrammes de mesure"],
        ["Sunshine packet_size", f"{advice.sunshine_packet_size}",
         "à aligner dans la config de Sunshine"],
        ["MTU WireGuard", f"{advice.wireguard_mtu}",
         "si ce chemin EST le tunnel" if advice.through_tunnel
         else "si ce chemin TRANSPORTE le tunnel"],
    ]
    print(_table(["Réglage", "Valeur", "Où"], rows, aligns="lrl"))


def network_report(profile: NetworkProfile, log: Logger) -> None:
    log.section("Synthèse réseau")
    rows = []
    for p in filter(None, [profile.primary, profile.secondary]):
        rows.append([
            DIRECTION_LABEL.get(p.direction, p.direction).split(" (")[0],
            f"{p.tcp_mbps:.1f}" if p.tcp_mbps is not None else "—",
            f"{p.clean_mbps:.1f}",
            f"{p.loss_pct:.2f}" if p.clean_trial else "—",
            f"{p.jitter_ms:.2f}" if p.clean_trial else "—",
        ])
    print(_table(
        ["Sens", "TCP brut (Mbps)", "UDP propre (Mbps)", "Perte (%)", "Gigue (ms)"],
        rows, aligns="lrrrr",
    ))
    if profile.ping:
        print(f"\n  Latence ICMP : {profile.ping.avg_ms:.2f} ms "
              f"(± {profile.ping.mdev_ms:.2f} ms), "
              f"perte {profile.ping.loss_pct:.1f} %")


def _verdict_cell(t: ModeTarget, c: Palette) -> str:
    if t.verdict == "ok":
        return f"{c.green}{t.advised_mbps:5.0f} ✓{c.reset}"
    if t.verdict == "marginal":
        return f"{c.yellow}{t.advised_mbps:5.0f} ~{c.reset}"
    return f"{c.dim}    — ✗{c.reset}"


def matrix_report(matrix: list[ModeTarget], cfg: AppConfig, budget: float,
                  log: Logger) -> None:
    m = cfg.model
    c = log.c
    log.section("Débit conseillé par mode (Mbps à saisir dans Moonlight)")
    print(f"  Codec {m.codec.upper()} · préréglage « {m.quality} » "
          f"(×{QUALITY_FACTOR.get(m.quality, 1.0):.2f} de la référence Moonlight, "
          f"×{CODEC_EFFICIENCY.get(m.codec, 1.0):.2f} pour le codec)"
          + (" · 4:4:4" if m.yuv444 else "") + (" · HDR" if m.hdr else ""))
    print(f"  Budget réseau utilisable : {c.bold}{budget:.1f} Mbps{c.reset} "
          f"→ vidéo max {max_video_for_budget(budget, m):.1f} Mbps "
          f"(FEC {m.fec_overhead * 100:.0f} % + audio {m.audio_mbps:.1f} Mbps déduits)\n")

    framerates = sorted(m.framerates)
    headers = ["Résolution", "Définition"] + [f"{f} fps" for f in framerates]
    rows = []
    by_key = {(t.width, t.height, t.fps): t for t in matrix}
    for name, w, h in m.resolutions:
        row = [name, f"{w}x{h}"]
        for fps in framerates:
            t = by_key.get((w, h, fps))
            row.append(_verdict_cell(t, c) if t else "")
        rows.append(row)
    print(_table(headers, rows, aligns="ll" + "r" * len(framerates)))
    print(f"\n  {c.green}✓{c.reset} confortable   "
          f"{c.yellow}~{c.reset} limite (micro-saccades possibles)   "
          f"{c.dim}✗{c.reset} au-delà du lien")


def detail_report(matrix: list[ModeTarget], log: Logger, limit: int = 12) -> None:
    log.section("Détail du calcul (modes tenables, les plus exigeants d'abord)")
    feasible = sorted(
        [t for t in matrix if t.verdict in ("ok", "marginal")],
        key=lambda t: t.pixel_rate, reverse=True,
    )[:limit]
    if not feasible:
        log.error("Aucun mode ne tient dans le budget mesuré.")
        return
    rows = [[
        t.label,
        f"{t.reference_mbps:.1f}",
        f"{t.video_mbps:.1f}",
        f"{t.link_mbps:.1f}",
        f"{t.headroom:.2f}×",
        "limite" if t.verdict == "marginal" else "ok",
    ] for t in feasible]
    print(_table(
        ["Mode", "Réf. Moonlight", "Vidéo visée", "Besoin réseau", "Marge", "Verdict"],
        rows, aligns="lrrrrl",
    ))


def recommendation(matrix: list[ModeTarget], log: Logger) -> None:
    c = log.c
    log.section("Recommandation")
    top = best_modes(matrix, limit=3)
    if not top:
        fallback = sorted(
            [t for t in matrix if t.verdict == "marginal"],
            key=lambda t: t.pixel_rate, reverse=True,
        )
        if fallback:
            t = fallback[0]
            log.warn(f"Lien juste : {t.label} à {t.advised_mbps:.0f} Mbps, sans marge.")
        else:
            log.error(
                "Le lien mesuré ne couvre aucun mode testé. Vérifiez le Wi-Fi, "
                "passez en Ethernet, ou abaissez model.quality / la résolution."
            )
        return

    first = top[0]
    print(f"  {c.bold}{c.green}{first.width}x{first.height} @ {first.fps} fps "
          f"— {first.advised_mbps:.0f} Mbps{c.reset}")
    print(f"  Codec : {recommend_codec(first.advised_mbps, first.width, first.height)}")
    print(f"  Marge réseau : {first.headroom:.2f}× le besoin réel")
    if len(top) > 1:
        print(f"\n  {c.dim}Alternatives :{c.reset}")
        for t in top[1:]:
            print(f"    · {t.label} fps → {t.advised_mbps:.0f} Mbps "
                  f"(marge {t.headroom:.2f}×)")


def warnings_report(profile: NetworkProfile, log: Logger) -> None:
    p = profile.primary
    issues = []
    if p.sender_limited:
        issues.append(
            "L'émetteur a plafonné avant le réseau : la capacité affichée est un "
            "plancher, pas la vraie limite du lien."
        )
    if p.ceiling_not_reached:
        issues.append(
            "Aucun palier n'a saturé le lien : augmentez bench.assumed_ceiling_mbps "
            "ou le dernier échelon de bench.ladder."
        )
    if p.tcp_mbps and p.clean_mbps and p.clean_mbps < p.tcp_mbps * 0.5:
        issues.append(
            f"L'UDP propre ({p.clean_mbps:.0f} Mbps) est bien en dessous du TCP "
            f"({p.tcp_mbps:.0f} Mbps) : typique d'un Wi-Fi, d'une mise en file "
            "d'attente agressive ou d'un émetteur UDP lent."
        )
    if profile.ping and profile.ping.avg_ms > 15:
        issues.append(
            f"Latence élevée ({profile.ping.avg_ms:.0f} ms) : le débit ne sera pas "
            "le facteur limitant du ressenti."
        )
    if profile.ping and profile.ping.mdev_ms > 5:
        issues.append(
            f"Latence instable (± {profile.ping.mdev_ms:.0f} ms) : prévoyez une "
            "marge plus large (model.safety_margin)."
        )
    if not issues:
        return
    log.section("Points d'attention")
    for text in issues:
        log.warn(text)
