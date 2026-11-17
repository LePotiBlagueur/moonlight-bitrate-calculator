"""Recherche de la capacité UDP « propre » par paliers + dichotomie."""

from __future__ import annotations

import platform
from dataclasses import dataclass, field

from .config import AppConfig
from .iperf import PingResult, UdpTrial, run_ping, run_tcp, run_udp

DIRECTION_LABEL = {
    "download": "hôte → client (sens du streaming vidéo)",
    "upload": "client → hôte (sens des commandes/manette)",
}


@dataclass
class DirectionProfile:
    direction: str
    tcp_mbps: float | None = None
    tcp_retransmits: int = 0
    ceiling_mbps: float = 0.0
    clean_mbps: float = 0.0
    clean_trial: UdpTrial | None = None
    trials: list[UdpTrial] = field(default_factory=list)
    sender_limited: bool = False
    ceiling_not_reached: bool = False

    @property
    def jitter_ms(self) -> float:
        return self.clean_trial.jitter_ms if self.clean_trial else 0.0

    @property
    def loss_pct(self) -> float:
        return self.clean_trial.loss_pct if self.clean_trial else 0.0


@dataclass
class NetworkProfile:
    primary: DirectionProfile
    secondary: DirectionProfile | None = None
    ping: PingResult | None = None


def _evaluate(trial: UdpTrial, cfg: AppConfig) -> UdpTrial:
    b = cfg.bench
    low_loss = trial.loss_pct <= b.max_loss_pct
    low_jitter = trial.jitter_ms <= b.max_jitter_ms
    delivered = trial.delivery_ratio >= b.sender_limited_ratio

    if not delivered and low_loss:
        # Le réseau n'a rien jeté : c'est l'émetteur qui ne suit pas.
        trial.sender_limited = True
        trial.ok = False
        trial.note = "émetteur saturé"
        return trial

    trial.ok = low_loss and low_jitter
    if not trial.ok:
        reasons = []
        if not low_loss:
            reasons.append(f"perte {trial.loss_pct:.2f} % > {b.max_loss_pct:.2f} %")
        if not low_jitter:
            reasons.append(f"gigue {trial.jitter_ms:.2f} ms > {b.max_jitter_ms:.1f} ms")
        trial.note = ", ".join(reasons)
    return trial


def _probe_direction(cfg: AppConfig, log, direction: str) -> DirectionProfile:
    reverse = direction == "download"
    host, port = cfg.host.host, cfg.host.iperf_port
    iperf = cfg.local_iperf()
    b = cfg.bench
    profile = DirectionProfile(direction=direction)

    log.section(f"Mesure {direction} — {DIRECTION_LABEL.get(direction, direction)}")

    # 1. Sonde TCP : borne haute de la recherche UDP.
    if b.tcp_probe:
        log.step(f"Sonde TCP ({b.tcp_duration} s, {b.tcp_streams} flux)")
        tcp = run_tcp(iperf, host, port, b.tcp_duration, b.tcp_streams, reverse)
        profile.tcp_mbps = tcp.mbps
        profile.tcp_retransmits = tcp.retransmits
        log.ok(f"Capacité TCP brute : {tcp.mbps:.1f} Mbps"
               + (f" ({tcp.retransmits} retransmissions)" if tcp.retransmits else ""))
        ceiling = max(tcp.mbps * 1.05, 10.0)
    else:
        ceiling = b.assumed_ceiling_mbps
        log.step(f"Pas de sonde TCP : plafond supposé {ceiling:.0f} Mbps")
    profile.ceiling_mbps = ceiling

    # 2. Paliers UDP croissants.
    rates = sorted({round(ceiling * f, 2) for f in b.ladder if ceiling * f >= 5.0})
    last_good = 0.0
    first_bad = 0.0

    for rate in rates:
        trial = _evaluate(
            run_udp(iperf, host, port, rate, b.duration, b.omit,
                    b.streams, b.datagram_len, reverse),
            cfg,
        )
        profile.trials.append(trial)
        log.trial(trial)

        if trial.sender_limited:
            profile.sender_limited = True
            # Ce qui est passé est passé proprement : on le capitalise.
            last_good = max(last_good, trial.achieved_mbps)
            log.warn(
                "L'émetteur ne tient pas la cadence demandée (iperf3 Windows/Cygwin "
                "plafonne souvent en UDP). Augmentez bench.streams ou "
                "bench.datagram_len pour aller plus haut."
            )
            break

        if trial.ok:
            last_good = rate
            continue

        if b.retry_on_fail:
            log.step(f"Nouvel essai du palier {rate:.1f} Mbps pour confirmation")
            retry = _evaluate(
                run_udp(iperf, host, port, rate, b.duration, b.omit,
                        b.streams, b.datagram_len, reverse),
                cfg,
            )
            profile.trials.append(retry)
            log.trial(retry)
            if retry.ok:
                last_good = rate
                continue
        first_bad = rate
        break
    else:
        profile.ceiling_not_reached = True

    # 3. Dichotomie entre le dernier palier propre et le premier en échec.
    if first_bad and b.refine_steps > 0:
        lo, hi = last_good, first_bad
        log.step(f"Affinage par dichotomie entre {lo:.1f} et {hi:.1f} Mbps")
        for _ in range(b.refine_steps):
            if hi <= 0 or (hi - lo) / hi < b.refine_tolerance:
                break
            mid = round((lo + hi) / 2, 2)
            if mid <= lo or mid >= hi:
                break
            trial = _evaluate(
                run_udp(iperf, host, port, mid, b.duration, b.omit,
                        b.streams, b.datagram_len, reverse),
                cfg,
            )
            profile.trials.append(trial)
            log.trial(trial)
            if trial.sender_limited:
                profile.sender_limited = True
                lo = max(lo, trial.achieved_mbps)
                break
            if trial.ok:
                lo = mid
            else:
                hi = mid
        last_good = lo

    profile.clean_mbps = last_good
    clean_trials = [t for t in profile.trials if t.ok]
    if clean_trials:
        profile.clean_trial = max(clean_trials, key=lambda t: t.target_mbps)

    if profile.ceiling_not_reached and last_good:
        log.warn(
            f"Aucun palier n'a échoué : le lien tient au moins {last_good:.1f} Mbps. "
            "Relevez bench.assumed_ceiling_mbps (ou la sonde TCP) pour trouver la "
            "vraie limite."
        )
    return profile


def measure(cfg: AppConfig, log) -> NetworkProfile:
    directions = (
        ["download", "upload"] if cfg.bench.direction == "both"
        else [cfg.bench.direction]
    )
    profiles = [_probe_direction(cfg, log, d) for d in directions]

    ping = None
    if cfg.bench.ping_probe:
        log.step(f"Sonde de latence ICMP ({cfg.bench.ping_count} paquets)")
        ping = run_ping(cfg.host.host, cfg.bench.ping_count,
                        windows=platform.system() == "Windows")
        if ping:
            log.ok(f"Latence {ping.avg_ms:.2f} ms (± {ping.mdev_ms:.2f} ms), "
                   f"perte ICMP {ping.loss_pct:.1f} %")
        else:
            log.warn("Sonde ICMP indisponible (ignorée).")

    return NetworkProfile(
        primary=profiles[0],
        secondary=profiles[1] if len(profiles) > 1 else None,
        ping=ping,
    )
