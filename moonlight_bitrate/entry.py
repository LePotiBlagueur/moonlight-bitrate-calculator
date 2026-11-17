"""Points d'entrée des exécutables gelés (PyInstaller) et du double-clic.

Lancé sans argument depuis l'Explorateur Windows, l'outil cherche un
`config.toml` à côté de l'exécutable, enchaîne la mesure et le récapitulatif,
et garde la fenêtre ouverte.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Dossier de l'exécutable gelé, ou du paquet en mode source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_config() -> str | None:
    for name in ("config.toml", "config.example.toml"):
        candidate = app_dir() / name
        if candidate.exists():
            return str(candidate)
    return None


def _interactive() -> bool:
    """Vrai pour un exécutable gelé lancé sans argument sous Windows.

    En mode source (`pip install -e .`), les commandes gardent leur
    comportement normal : pas d'argument = aide ou erreur explicite.
    """
    return getattr(sys, "frozen", False) and sys.platform == "win32"


def _default_argv(extra: list[str]) -> list[str]:
    argv = list(extra)
    config = find_config()
    if config:
        argv = ["-c", config] + argv
    else:
        print("Aucun config.toml trouvé à côté de l'exécutable : "
              "valeurs par défaut utilisées.\n"
              "Copiez config.example.toml en config.toml pour régler "
              "l'IP et le compte SSH de l'hôte.\n")
    return argv + ["--pause"]


def _announce(what: str) -> None:
    print(f"Lancé sans argument : {what}.")
    print("Ajoutez --help pour voir toutes les options.\n")


def bench_main(argv: list[str] | None = None) -> int:
    from .cli import main

    args = list(sys.argv[1:] if argv is None else argv)
    if not args and _interactive():
        _announce("mesure réseau complète puis rapport")
        args = _default_argv([])
    return main(args)


def recap_main(argv: list[str] | None = None) -> int:
    from .recap_cli import main

    args = list(sys.argv[1:] if argv is None else argv)
    if not args and _interactive():
        _announce("mesure réseau puis tableau récapitulatif")
        args = _default_argv(["--measure"])
    return main(args)


if __name__ == "__main__":
    raise SystemExit(bench_main())
