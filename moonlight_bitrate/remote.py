"""Pilotage du serveur iperf3 distant via SSH (contexte auto-nettoyant)."""

from __future__ import annotations

import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import AppConfig


class RemoteError(RuntimeError):
    pass


_VERSION_RE = re.compile(r"iperf\s+(\d+)\.(\d+)(?:\.(\d+))?")

# En deçà, les mesures UDP sont nettement moins fiables (cadencement de -b,
# statistiques en mode inversé). 3.7 est le premier palier vraiment sain.
MIN_RECOMMENDED = (3, 7)
# Les flux UDP parallèles ne sont pas exploitables sur les anciens builds
# Cygwin : le client rend une sortie vide au lieu d'un rapport.
MIN_PARALLEL_UDP = (3, 2)


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Extrait (majeur, mineur, correctif) de la sortie d'`iperf3 --version`."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


def version_warnings(version: tuple[int, int, int] | None,
                     streams: int) -> list[str]:
    """Avertissements à produire pour une version d'iperf3 distante donnée."""
    if version is None:
        return ["Version d'iperf3 distante indéterminée : vérifiez host.iperf_path."]
    issues = []
    label = ".".join(str(n) for n in version)
    if version < MIN_RECOMMENDED:
        issues.append(
            f"iperf3 {label} sur l'hôte : build ancien. Le cadencement UDP et les "
            "statistiques en mode inversé y sont approximatifs ; la capacité "
            f"mesurée sera pessimiste. Mettez à jour vers {MIN_RECOMMENDED[0]}."
            f"{MIN_RECOMMENDED[1]}+ (https://iperf.fr/iperf-download.php)."
        )
    if streams > 1 and version < MIN_PARALLEL_UDP:
        issues.append(
            f"iperf3 {label} ne gère pas les flux UDP parallèles (sortie vide "
            "avec -P). Gardez bench.streams = 1 ou mettez iperf3 à jour."
        )
    return issues


def _load_key(path: Path):
    import paramiko

    if not path.exists():
        raise RemoteError(
            f"Clé privée introuvable : {path}\n"
            "Générez-la avec : ssh-keygen -t ed25519 -f ~/.ssh/id_moonlight"
        )
    errors = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(str(path))
        except Exception as exc:  # type de clé non reconnu
            errors.append(f"{cls.__name__}: {exc}")
    raise RemoteError("Clé privée illisible.\n  " + "\n  ".join(errors))


def port_is_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class RemoteServer:
    """Démarre `iperf3 -s` sur l'hôte Sunshine et le coupe en sortie."""

    def __init__(self, cfg: AppConfig, log) -> None:
        self.cfg = cfg
        self.log = log
        self.client = None
        self._channels = None

    # -- commandes selon l'OS distant ---------------------------------------

    def _kill_cmd(self) -> str:
        if self.cfg.host.remote_os == "windows":
            return "taskkill /IM iperf3.exe /F"
        return "pkill -f 'iperf3 -s' || true"

    def _version_cmd(self) -> str:
        path = self.cfg.host.iperf_path
        return f'"{path}" --version' if self.cfg.host.remote_os == "windows" \
            else f"{path!r} --version"

    def _start_cmd(self) -> str:
        path = self.cfg.host.iperf_path
        port = self.cfg.host.iperf_port
        if self.cfg.host.remote_os == "windows":
            return f'"{path}" -s -p {port}'
        return f"{path!r} -s -p {port}"

    # -- cycle de vie --------------------------------------------------------

    def start(self) -> None:
        import paramiko

        hc = self.cfg.host
        self.log.step(f"Connexion SSH à {hc.user}@{hc.host}:{hc.port}")
        key = _load_key(self.cfg.resolved_key_path())

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hc.host, port=hc.port, username=hc.user, pkey=key,
                timeout=10, auth_timeout=10, banner_timeout=15,
                look_for_keys=False, allow_agent=False,
            )
        except Exception as exc:
            raise RemoteError(f"Connexion SSH impossible : {exc}") from exc
        self.client = client

        version = parse_version(self._exec(self._version_cmd()))
        if version:
            self.log.ok("iperf3 distant : " + ".".join(str(n) for n in version))
        for issue in version_warnings(version, self.cfg.bench.streams):
            self.log.warn(issue)

        self.log.step("Nettoyage des instances iperf3 résiduelles")
        self._exec(self._kill_cmd())
        time.sleep(0.5)

        self.log.step(f"Démarrage du serveur iperf3 distant (port {hc.iperf_port})")
        # Conservé comme processus de premier plan : le canal reste ouvert
        # tant que la session SSH vit, le serveur accepte donc tous les paliers.
        self._channels = client.exec_command(self._start_cmd())

        for attempt in range(12):
            time.sleep(0.75)
            if port_is_open(hc.host, hc.iperf_port):
                self.log.ok(f"Serveur iperf3 à l'écoute sur {hc.host}:{hc.iperf_port}")
                return
            if attempt == 3:
                self.log.step("…en attente de l'ouverture du port")
        stderr = self._drain_stderr()
        raise RemoteError(
            f"Le serveur distant n'écoute pas sur le port {hc.iperf_port}."
            + (f"\nSortie distante : {stderr}" if stderr else "")
        )

    def _exec(self, command: str) -> str:
        assert self.client is not None
        _, out, err = self.client.exec_command(command)
        data = out.read().decode("utf-8", "ignore")
        err.read()
        return data

    def _drain_stderr(self) -> str:
        if not self._channels:
            return ""
        try:
            chan = self._channels[2]
            if chan.channel.recv_stderr_ready():
                return chan.read().decode("utf-8", "ignore").strip()[:500]
        except Exception:
            pass
        return ""

    def stop(self) -> None:
        if self.client is None:
            return
        self.log.step("Arrêt du serveur iperf3 distant")
        try:
            self._exec(self._kill_cmd())
        except Exception as exc:
            self.log.warn(f"Nettoyage distant incomplet : {exc}")
        finally:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None


@contextmanager
def remote_server(cfg: AppConfig, log) -> Iterator[RemoteServer | None]:
    """Contexte : serveur distant géré, ou rien si `no_ssh`."""
    if cfg.host.no_ssh:
        log.step("Mode --no-ssh : on suppose un `iperf3 -s` déjà lancé en face")
        if not port_is_open(cfg.host.host, cfg.host.iperf_port):
            raise RemoteError(
                f"Rien n'écoute sur {cfg.host.host}:{cfg.host.iperf_port}. "
                "Lancez `iperf3 -s` sur l'hôte Sunshine ou retirez --no-ssh."
            )
        yield None
        return

    server = RemoteServer(cfg, log)
    try:
        server.start()
        yield server
    finally:
        server.stop()
