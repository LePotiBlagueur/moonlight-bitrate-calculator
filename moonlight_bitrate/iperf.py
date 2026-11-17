"""Exécution locale d'iperf3 et extraction robuste des métriques JSON."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any


class IperfError(RuntimeError):
    pass


@dataclass
class UdpTrial:
    """Résultat d'un palier UDP."""

    target_mbps: float
    achieved_mbps: float
    loss_pct: float
    jitter_ms: float
    packets: int
    lost_packets: int
    out_of_order: int = 0
    direction: str = "download"
    ok: bool = False
    sender_limited: bool = False
    note: str = ""

    @property
    def delivery_ratio(self) -> float:
        if self.target_mbps <= 0:
            return 0.0
        return self.achieved_mbps / self.target_mbps


@dataclass
class TcpResult:
    mbps: float
    retransmits: int = 0
    direction: str = "download"


@dataclass
class PingResult:
    avg_ms: float
    mdev_ms: float
    loss_pct: float
    samples: int = 0


def _run(cmd: list[str], timeout: float) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise IperfError(f"iperf3 introuvable : {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise IperfError(f"iperf3 n'a pas répondu en {timeout:.0f} s") from exc

    stdout = proc.stdout or ""
    # iperf3 -J écrit du JSON sur stdout même en cas d'erreur applicative.
    start = stdout.find("{")
    if start == -1:
        raise IperfError(
            f"Sortie iperf3 illisible (code {proc.returncode}).\n"
            f"stdout: {stdout.strip()[:400]}\nstderr: {(proc.stderr or '').strip()[:400]}"
        )
    try:
        data = json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise IperfError(f"JSON iperf3 invalide : {exc}") from exc

    if isinstance(data.get("error"), str):
        raise IperfError(f"iperf3 : {data['error']}")
    return data


def _base_cmd(cfg_path: str, host: str, port: int, duration: int, omit: int,
              reverse: bool) -> list[str]:
    cmd = [cfg_path, "-c", host, "-p", str(port), "-t", str(duration), "-J"]
    if omit > 0:
        cmd += ["-O", str(omit)]
    if reverse:
        cmd.append("-R")
    return cmd


# --------------------------------------------------------------------------
# TCP
# --------------------------------------------------------------------------


def run_tcp(iperf: str, host: str, port: int, duration: int, streams: int,
            reverse: bool) -> TcpResult:
    cmd = _base_cmd(iperf, host, port, duration, 1, reverse)
    if streams > 1:
        cmd += ["-P", str(streams)]
    data = _run(cmd, timeout=duration + 25)
    end = data.get("end", {})
    summary = end.get("sum_received") or end.get("sum_sent") or {}
    bps = float(summary.get("bits_per_second", 0.0))
    retr = int((end.get("sum_sent") or {}).get("retransmits", 0) or 0)
    return TcpResult(
        mbps=bps / 1e6,
        retransmits=retr,
        direction="download" if reverse else "upload",
    )


# --------------------------------------------------------------------------
# UDP
# --------------------------------------------------------------------------


def _udp_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Récupère le résumé côté récepteur, quelle que soit la version d'iperf3."""
    end = data.get("end", {})
    for key in ("sum", "sum_received"):
        block = end.get(key)
        if isinstance(block, dict) and block.get("packets"):
            return block
    # Repli : agrégation manuelle des flux.
    streams = end.get("streams") or []
    agg: dict[str, Any] = {
        "bits_per_second": 0.0,
        "packets": 0,
        "lost_packets": 0,
        "jitter_ms": 0.0,
    }
    seen = 0
    for stream in streams:
        udp = stream.get("udp") if isinstance(stream, dict) else None
        if not isinstance(udp, dict):
            continue
        seen += 1
        agg["bits_per_second"] += float(udp.get("bits_per_second", 0.0))
        agg["packets"] += int(udp.get("packets", 0) or 0)
        agg["lost_packets"] += int(udp.get("lost_packets", 0) or 0)
        agg["jitter_ms"] = max(agg["jitter_ms"], float(udp.get("jitter_ms", 0.0) or 0.0))
    if not seen:
        raise IperfError("Aucune statistique UDP dans la réponse d'iperf3.")
    if agg["packets"]:
        agg["lost_percent"] = 100.0 * agg["lost_packets"] / agg["packets"]
    return agg


def run_udp(iperf: str, host: str, port: int, target_mbps: float, duration: int,
            omit: int, streams: int, datagram_len: int, reverse: bool) -> UdpTrial:
    """Un palier UDP à `target_mbps` (débit total, réparti sur les flux)."""
    per_stream = max(target_mbps / max(streams, 1), 0.1)
    cmd = _base_cmd(iperf, host, port, duration, omit, reverse)
    cmd += ["-u", "-b", f"{per_stream:.3f}M", "-l", str(datagram_len)]
    if streams > 1:
        cmd += ["-P", str(streams)]

    data = _run(cmd, timeout=duration + omit + 30)
    summary = _udp_summary(data)

    packets = int(summary.get("packets", 0) or 0)
    lost = int(summary.get("lost_packets", 0) or 0)
    loss_pct = summary.get("lost_percent")
    if loss_pct is None:
        loss_pct = (100.0 * lost / packets) if packets else 0.0

    achieved_bps = float(summary.get("bits_per_second", 0.0))
    # En UDP, bits_per_second du résumé correspond au trafic reçu ; on retire
    # explicitement la part perdue si la version d'iperf3 rapporte l'émis.
    achieved_mbps = achieved_bps / 1e6

    return UdpTrial(
        target_mbps=target_mbps,
        achieved_mbps=achieved_mbps,
        loss_pct=float(loss_pct),
        jitter_ms=float(summary.get("jitter_ms", 0.0) or 0.0),
        packets=packets,
        lost_packets=lost,
        out_of_order=int(summary.get("out_of_order", 0) or 0),
        direction="download" if reverse else "upload",
    )


# --------------------------------------------------------------------------
# Latence ICMP (sonde d'appoint, jamais bloquante)
# --------------------------------------------------------------------------

_PING_RTT = re.compile(
    r"=\s*([\d.]+)\s*/\s*([\d.]+)\s*/\s*([\d.]+)(?:\s*/\s*([\d.]+))?"
)
_PING_LOSS = re.compile(r"([\d.]+)\s*%\s*(?:packet loss|perte|loss)")


def run_ping(host: str, count: int, windows: bool) -> PingResult | None:
    cmd = ["ping", "-n" if windows else "-c", str(count), host]
    if not windows:
        cmd[1:1] = ["-i", "0.2"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * 1.5 + 20, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    loss = 0.0
    m = _PING_LOSS.search(out)
    if m:
        loss = float(m.group(1))
    m = _PING_RTT.search(out)
    if m:
        avg = float(m.group(2))
        mdev = float(m.group(4)) if m.group(4) else 0.0
        return PingResult(avg_ms=avg, mdev_ms=mdev, loss_pct=loss, samples=count)
    # Windows francophone / anglophone : « Moyenne = 3ms » / « Average = 3ms »
    m = re.search(r"(?:Average|Moyenne)\s*=\s*(\d+)\s*ms", out)
    if m:
        return PingResult(avg_ms=float(m.group(1)), mdev_ms=0.0, loss_pct=loss,
                          samples=count)
    return None
