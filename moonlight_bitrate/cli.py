"""Point d'entrée en ligne de commande."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import CODEC_EFFICIENCY, QUALITY_FACTOR, AppConfig, load_config
from .iperf import IperfError, PingResult, UdpTrial
from .ladder import DirectionProfile, NetworkProfile, measure
from .model import build_matrix, budget_from_capacity
from .remote import RemoteError, remote_server
from .report import (
    Logger,
    Palette,
    detail_report,
    matrix_report,
    network_report,
    recommendation,
    warnings_report,
)


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------


def _resolution(text: str) -> tuple[str, int, int]:
    """« 2560x1440 » ou « UW:3440x1440 »."""
    name, _, dims = text.rpartition(":")
    try:
        w, h = (int(part) for part in dims.lower().split("x", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Résolution invalide : {text!r} (attendu LARGEURxHAUTEUR)"
        ) from exc
    return (name or f"{h}p", w, h)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moonlight-bitrate",
        description="Mesure UDP du lien Sunshine → Moonlight et calcul du débit "
                    "optimal pour plusieurs résolutions et fréquences d'images.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-c", "--config", help="Fichier de configuration TOML")
    p.add_argument("-p", "--profile",
                   help="Profil [profiles.<nom>] à appliquer par-dessus la config "
                        "(ex. : lan, vpn)")

    g = p.add_argument_group("hôte distant")
    g.add_argument("--host", help="IP ou nom de l'hôte Sunshine")
    g.add_argument("--user", help="Compte SSH sur l'hôte")
    g.add_argument("--ssh-port", type=int, help="Port SSH")
    g.add_argument("--key", help="Clé privée SSH")
    g.add_argument("--remote-iperf", help="Chemin d'iperf3 sur l'hôte")
    g.add_argument("--remote-os", choices=["windows", "unix"],
                   help="Système de l'hôte (commandes de nettoyage)")
    g.add_argument("--iperf-port", type=int, help="Port du serveur iperf3")
    g.add_argument("--no-ssh", action="store_true",
                   help="Ne pas piloter l'hôte : `iperf3 -s` déjà lancé en face")

    g = p.add_argument_group("mesure")
    g.add_argument("--local-iperf", help="Chemin d'iperf3 en local")
    g.add_argument("--direction", choices=["download", "upload", "both"],
                   help="Sens mesuré (download = sens du streaming)")
    g.add_argument("-t", "--duration", type=int, help="Durée d'un palier (s)")
    g.add_argument("--streams", type=int, help="Flux UDP parallèles")
    g.add_argument("--length", type=int, dest="datagram_len",
                   help="Taille des datagrammes UDP (octets)")
    g.add_argument("--no-tcp-probe", action="store_true",
                   help="Sauter la sonde TCP de cadrage")
    g.add_argument("--ceiling", type=float, dest="assumed_ceiling_mbps",
                   help="Plafond supposé sans sonde TCP (Mbps)")
    g.add_argument("--max-loss", type=float, dest="max_loss_pct",
                   help="Perte maximale tolérée par palier (%%)")
    g.add_argument("--max-jitter", type=float, dest="max_jitter_ms",
                   help="Gigue maximale tolérée par palier (ms)")
    g.add_argument("--refine", type=int, dest="refine_steps",
                   help="Itérations de dichotomie après le premier échec")
    g.add_argument("--no-ping", action="store_true", help="Sauter la sonde ICMP")

    g = p.add_argument_group("modèle de débit")
    g.add_argument("--codec", choices=sorted(CODEC_EFFICIENCY),
                   help="Codec utilisé par le flux")
    g.add_argument("--quality", choices=sorted(QUALITY_FACTOR, key=QUALITY_FACTOR.get),
                   help="Préréglage de qualité visé")
    g.add_argument("--yuv444", action="store_true", help="Flux 4:4:4 (double le débit)")
    g.add_argument("--hdr", action="store_true", help="Flux HDR (+10 %%)")
    g.add_argument("--fec", type=float, dest="fec_overhead",
                   help="Surcoût FEC de Sunshine (0.20 = 20 %%)")
    g.add_argument("--audio", type=float, dest="audio_mbps",
                   help="Débit audio réservé (Mbps)")
    g.add_argument("--safety", type=float, dest="safety_margin",
                   help="Part de la capacité propre réellement utilisée")
    g.add_argument("--resolution", action="append", dest="resolutions",
                   type=_resolution, metavar="LxH",
                   help="Résolution à évaluer (répétable, remplace la liste)")
    g.add_argument("--fps", action="append", dest="framerates", type=int,
                   help="Fréquence d'images à évaluer (répétable)")

    g = p.add_argument_group("sortie")
    g.add_argument("--save", metavar="FICHIER",
                   help="Écrire les mesures brutes en JSON")
    g.add_argument("--load", metavar="FICHIER",
                   help="Rejouer l'analyse sur des mesures enregistrées")
    g.add_argument("--json", action="store_true",
                   help="Sortie machine (JSON) au lieu des tableaux")
    g.add_argument("-v", "--verbose", action="store_true")
    g.add_argument("--no-color", action="store_true")
    g.add_argument("--pause", action="store_true",
                   help="Attendre une touche avant de fermer (double-clic Windows)")
    return p


def apply_overrides(cfg: AppConfig, args: argparse.Namespace) -> AppConfig:
    host_map = {
        "host": "host", "user": "user", "ssh_port": "port", "key": "key_path",
        "remote_iperf": "iperf_path", "remote_os": "remote_os",
        "iperf_port": "iperf_port",
    }
    for arg, attr in host_map.items():
        value = getattr(args, arg, None)
        if value is not None:
            setattr(cfg.host, attr, value)
    if args.no_ssh:
        cfg.host.no_ssh = True

    bench_map = {
        "local_iperf": "iperf_path", "direction": "direction", "duration": "duration",
        "streams": "streams", "datagram_len": "datagram_len",
        "assumed_ceiling_mbps": "assumed_ceiling_mbps", "max_loss_pct": "max_loss_pct",
        "max_jitter_ms": "max_jitter_ms", "refine_steps": "refine_steps",
    }
    for arg, attr in bench_map.items():
        value = getattr(args, arg, None)
        if value is not None:
            setattr(cfg.bench, attr, value)
    if args.no_tcp_probe:
        cfg.bench.tcp_probe = False
    if args.no_ping:
        cfg.bench.ping_probe = False

    model_map = {
        "codec": "codec", "quality": "quality", "fec_overhead": "fec_overhead",
        "audio_mbps": "audio_mbps", "safety_margin": "safety_margin",
    }
    for arg, attr in model_map.items():
        value = getattr(args, arg, None)
        if value is not None:
            setattr(cfg.model, attr, value)
    if args.yuv444:
        cfg.model.yuv444 = True
    if args.hdr:
        cfg.model.hdr = True
    if args.resolutions:
        cfg.model.resolutions = args.resolutions
    if args.framerates:
        cfg.model.framerates = args.framerates

    if args.verbose:
        cfg.verbose = True
    if args.no_color:
        cfg.color = False
    if args.pause:
        cfg.pause = True
    return cfg


# --------------------------------------------------------------------------
# Sérialisation des mesures
# --------------------------------------------------------------------------


def profile_to_dict(profile: NetworkProfile, cfg: AppConfig) -> dict:
    return {
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": cfg.host.host,
        "profile": cfg.active_profile,
        "bench": asdict(cfg.bench),
        "primary": asdict(profile.primary),
        "secondary": asdict(profile.secondary) if profile.secondary else None,
        "ping": asdict(profile.ping) if profile.ping else None,
    }


def _profile_from_dict(data: dict | None) -> DirectionProfile | None:
    if not data:
        return None
    trials = [UdpTrial(**t) for t in data.get("trials", [])]
    clean = data.get("clean_trial")
    return DirectionProfile(
        direction=data["direction"],
        tcp_mbps=data.get("tcp_mbps"),
        tcp_retransmits=data.get("tcp_retransmits", 0),
        ceiling_mbps=data.get("ceiling_mbps", 0.0),
        clean_mbps=data.get("clean_mbps", 0.0),
        clean_trial=UdpTrial(**clean) if clean else None,
        trials=trials,
        sender_limited=data.get("sender_limited", False),
        ceiling_not_reached=data.get("ceiling_not_reached", False),
    )


def profile_from_dict(data: dict) -> NetworkProfile:
    primary = _profile_from_dict(data.get("primary"))
    if primary is None:
        raise ValueError("Fichier de mesures invalide : bloc « primary » manquant.")
    ping = data.get("ping")
    return NetworkProfile(
        primary=primary,
        secondary=_profile_from_dict(data.get("secondary")),
        ping=PingResult(**ping) if ping else None,
    )


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------


def run(cfg: AppConfig, args: argparse.Namespace, log: Logger) -> int:
    if cfg.active_profile:
        log.step(f"Profil actif : {cfg.active_profile}")
    if args.load:
        log.step(f"Lecture des mesures enregistrées : {args.load}")
        profile = profile_from_dict(json.loads(Path(args.load).read_text("utf-8")))
    else:
        with remote_server(cfg, log):
            profile = measure(cfg, log)

    if args.save:
        Path(args.save).write_text(
            json.dumps(profile_to_dict(profile, cfg), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.ok(f"Mesures enregistrées dans {args.save}")

    capacity = profile.primary.clean_mbps
    if capacity <= 0:
        log.error(
            "Aucun palier UDP n'est passé. Le lien est saturé, trop instable, ou "
            "le premier palier est déjà trop haut : baissez --ceiling ou le premier "
            "échelon de bench.ladder."
        )
        return 2

    budget = budget_from_capacity(capacity, cfg.model)
    matrix = build_matrix(budget, cfg.model)

    if args.json:
        payload = profile_to_dict(profile, cfg)
        payload["budget_mbps"] = round(budget, 2)
        payload["modes"] = [
            {**asdict(t), "advised_mbps": round(t.advised_mbps, 1)} for t in matrix
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    network_report(profile, log)
    matrix_report(matrix, cfg, budget, log)
    detail_report(matrix, log)
    recommendation(matrix, log)
    warnings_report(profile, log)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = apply_overrides(load_config(args.config, args.profile), args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2

    log = Logger(Palette.for_output(cfg.color), cfg.verbose)
    code = 1
    try:
        code = run(cfg, args, log)
    except KeyboardInterrupt:
        log.warn("Interrompu par l'utilisateur.")
        code = 130
    except (RemoteError, IperfError) as exc:
        log.error(str(exc))
        code = 2
    except ModuleNotFoundError as exc:
        log.error(f"Dépendance manquante : {exc.name} (pip install paramiko)")
        code = 2
    except Exception as exc:  # garde-fou : on ne ferme jamais sur une trace nue
        log.error(f"Erreur inattendue : {exc}")
        if cfg.verbose:
            raise
        code = 1
    finally:
        if cfg.pause:
            try:
                input("\nAppuyez sur ENTRÉE pour fermer…")
            except EOFError:
                pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
