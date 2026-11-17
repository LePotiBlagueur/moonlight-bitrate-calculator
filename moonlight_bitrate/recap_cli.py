"""`moonlight-recap` : tableau récapitulatif, avec ou sans mesure réseau."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import CODEC_EFFICIENCY, QUALITY_FACTOR, AppConfig, load_config
from .iperf import IperfError
from .model import budget_from_capacity
from .recap import RENDERERS, SECTIONS, build_recap, render_text
from .remote import RemoteError
from .report import Logger, Palette


def _resolution(text: str) -> tuple[str, int, int]:
    name, _, dims = text.rpartition(":")
    try:
        w, h = (int(part) for part in dims.lower().split("x", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Résolution invalide : {text!r} (attendu LARGEURxHAUTEUR)"
        ) from exc
    return (name or f"{h}p", w, h)


def _sections(text: str) -> list[str]:
    if text.strip().lower() == "all":
        return list(SECTIONS)
    wanted = [part.strip().lower() for part in text.split(",") if part.strip()]
    unknown = [s for s in wanted if s not in SECTIONS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Section inconnue : {', '.join(unknown)} "
            f"(disponibles : {', '.join(SECTIONS)}, all)"
        )
    return wanted


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moonlight-recap",
        description="Tableau récapitulatif des réglages Moonlight : matrice "
                    "résolutions × fps, comparatif codecs et préréglages. "
                    "Fonctionne depuis une mesure enregistrée, un débit connu, "
                    "ou une mesure à la volée.",
        epilog="Exemples :\n"
               "  moonlight-recap -b 450\n"
               "  moonlight-recap --load mesures.json --format html -o recap.html\n"
               "  moonlight-recap --measure -c config.toml --save mesures.json\n"
               "  moonlight-recap -c config.toml -p vpn --measure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-c", "--config", help="Fichier de configuration TOML")
    p.add_argument("-p", "--profile",
                   help="Profil [profiles.<nom>] à appliquer (ex. : lan, vpn)")

    src = p.add_argument_group("source du débit (une seule)")
    g = src.add_mutually_exclusive_group()
    g.add_argument("-b", "--bandwidth", type=float, metavar="MBPS",
                   help="Capacité UDP propre connue, en Mbps (aucun test réseau)")
    g.add_argument("--budget", type=float, metavar="MBPS",
                   help="Budget réseau déjà net de marge (ignore --safety)")
    g.add_argument("--load", metavar="FICHIER",
                   help="Mesures enregistrées par moonlight-bitrate --save")
    g.add_argument("--measure", action="store_true",
                   help="Lancer la mesure UDP maintenant (SSH + iperf3)")
    src.add_argument("--save", metavar="FICHIER",
                     help="Avec --measure : enregistrer les mesures brutes")

    g = p.add_argument_group("mesure (avec --measure)")
    g.add_argument("--host", help="IP ou nom de l'hôte Sunshine")
    g.add_argument("--user", help="Compte SSH sur l'hôte")
    g.add_argument("--ssh-port", type=int, help="Port SSH")
    g.add_argument("--key", help="Clé privée SSH")
    g.add_argument("--remote-iperf", help="Chemin d'iperf3 sur l'hôte")
    g.add_argument("--remote-os", choices=["windows", "unix"],
                   help="Système de l'hôte (commandes de nettoyage)")
    g.add_argument("--iperf-port", type=int, help="Port du serveur iperf3")
    g.add_argument("--no-ssh", action="store_true",
                   help="`iperf3 -s` déjà lancé sur l'hôte")
    g.add_argument("--local-iperf", help="Chemin d'iperf3 en local")
    g.add_argument("--direction", choices=["download", "upload", "both"],
                   help="Sens mesuré (défaut : download)")
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
    g.add_argument("--no-ping", action="store_true", help="Sauter la sonde ICMP")

    g = p.add_argument_group("modèle")
    g.add_argument("--codec", choices=sorted(CODEC_EFFICIENCY),
                   help="Codec du tableau principal (défaut : hevc)")
    g.add_argument("--quality", choices=sorted(QUALITY_FACTOR, key=QUALITY_FACTOR.get),
                   help="Préréglage de qualité (défaut : balanced)")
    g.add_argument("--yuv444", action="store_true", help="Flux 4:4:4")
    g.add_argument("--hdr", action="store_true", help="Flux HDR")
    g.add_argument("--fec", type=float, dest="fec_overhead",
                   help="Surcoût FEC de Sunshine (0.20 = 20 %%)")
    g.add_argument("--audio", type=float, dest="audio_mbps",
                   help="Débit audio réservé (Mbps)")
    g.add_argument("--safety", type=float, dest="safety_margin",
                   help="Part de la capacité réellement exploitée (défaut : 0.85)")
    g.add_argument("--resolution", action="append", dest="resolutions",
                   type=_resolution, metavar="LxH",
                   help="Résolution à inclure (répétable, remplace la liste)")
    g.add_argument("--fps", action="append", dest="framerates", type=int,
                   help="Fréquence à inclure (répétable, remplace la liste)")

    g = p.add_argument_group("sortie")
    g.add_argument("-f", "--format", default="table",
                   choices=["table", "markdown", "csv", "html", "json"],
                   help="Format du récapitulatif (défaut : table)")
    g.add_argument("-o", "--out", metavar="FICHIER",
                   help="Écrire dans un fichier au lieu de la sortie standard")
    g.add_argument("--sections", type=_sections, default=list(SECTIONS),
                   metavar="LISTE",
                   help=f"Sections à inclure parmi {', '.join(SECTIONS)} (défaut : all)")
    g.add_argument("--no-color", action="store_true")
    g.add_argument("--pause", action="store_true",
                   help="Attendre une touche avant de fermer (double-clic Windows)")
    g.add_argument("-v", "--verbose", action="store_true")
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
        "local_iperf": "iperf_path", "direction": "direction",
        "duration": "duration", "streams": "streams",
        "datagram_len": "datagram_len", "max_loss_pct": "max_loss_pct",
        "max_jitter_ms": "max_jitter_ms",
        "assumed_ceiling_mbps": "assumed_ceiling_mbps",
    }
    for arg, attr in bench_map.items():
        value = getattr(args, arg, None)
        if value is not None:
            setattr(cfg.bench, attr, value)
    if args.no_tcp_probe:
        cfg.bench.tcp_probe = False
    if args.no_ping:
        cfg.bench.ping_probe = False
    for arg in ("codec", "quality", "fec_overhead", "audio_mbps", "safety_margin"):
        value = getattr(args, arg, None)
        if value is not None:
            setattr(cfg.model, arg if arg != "codec" else "codec", value)
    if args.yuv444:
        cfg.model.yuv444 = True
    if args.hdr:
        cfg.model.hdr = True
    if args.resolutions:
        cfg.model.resolutions = args.resolutions
    if args.framerates:
        cfg.model.framerates = args.framerates
    if args.no_color:
        cfg.color = False
    if args.verbose:
        cfg.verbose = True
    if args.pause:
        cfg.pause = True
    return cfg


def resolve_source(cfg: AppConfig, args: argparse.Namespace, log: Logger):
    """Retourne (capacité Mbps, budget Mbps, profil ou None, libellé de source)."""
    if args.budget is not None:
        if args.budget <= 0:
            raise ValueError("--budget doit être strictement positif.")
        return args.budget / cfg.model.safety_margin, args.budget, None, \
            f"budget fourni ({args.budget:.1f} Mbps, marge déjà appliquée)"

    if args.bandwidth is not None:
        if args.bandwidth <= 0:
            raise ValueError("--bandwidth doit être strictement positif.")
        return (args.bandwidth, budget_from_capacity(args.bandwidth, cfg.model),
                None, f"débit fourni ({args.bandwidth:.1f} Mbps)")

    if args.load:
        from .cli import profile_from_dict

        data = json.loads(Path(args.load).read_text("utf-8"))
        profile = profile_from_dict(data)
        capacity = profile.primary.clean_mbps
        stamp = data.get("timestamp", "")
        label = f"mesures {args.load}" + (f" du {stamp}" if stamp else "")
        return capacity, budget_from_capacity(capacity, cfg.model), profile, label

    if args.measure:
        from .cli import profile_to_dict
        from .ladder import measure
        from .remote import remote_server

        with remote_server(cfg, log):
            profile = measure(cfg, log)
        if args.save:
            Path(args.save).write_text(
                json.dumps(profile_to_dict(profile, cfg), indent=2,
                           ensure_ascii=False),
                encoding="utf-8",
            )
            log.ok(f"Mesures enregistrées dans {args.save}")
        capacity = profile.primary.clean_mbps
        return (capacity, budget_from_capacity(capacity, cfg.model), profile,
                f"mesure UDP de {cfg.host.host}")

    raise ValueError(
        "Aucune source de débit. Utilisez --bandwidth, --budget, --load ou "
        "--measure (voir --help)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = apply_overrides(load_config(args.config, args.profile), args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2

    # Le journal de mesure part sur stderr pour ne pas polluer un export redirigé.
    to_stdout = args.format == "table" and not args.out
    log = Logger(Palette.for_output(cfg.color and to_stdout), cfg.verbose)
    code = 0
    try:
        capacity, budget, profile, source = resolve_source(cfg, args, log)
        if budget <= 0:
            log.error("Budget réseau nul : aucun réglage ne peut être conseillé.")
            return 2

        sections = list(args.sections)
        if profile is None and "network" in sections:
            sections.remove("network")

        recap = build_recap(cfg, budget, capacity, profile, sections, source,
                            plain=args.format in ("csv", "json"))

        if args.format == "table":
            text = render_text(recap, Palette.for_output(cfg.color and not args.out))
        else:
            text = RENDERERS[args.format](recap)

        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Récapitulatif écrit dans {args.out}")
        else:
            print(text)
    except KeyboardInterrupt:
        log.warn("Interrompu par l'utilisateur.")
        code = 130
    except (RemoteError, IperfError, ValueError) as exc:
        log.error(str(exc))
        code = 2
    except ModuleNotFoundError as exc:
        log.error(f"Dépendance manquante : {exc.name} (pip install paramiko)")
        code = 2
    except Exception as exc:
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
