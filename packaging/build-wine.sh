#!/usr/bin/env bash
# Build croisé Linux -> Windows via wine.
# Nécessite wine, et d'autoriser l'exécution de l'installeur Python Windows.
#
#   ./packaging/build-wine.sh
#
# PyInstaller ne sait pas produire un .exe depuis un Python Linux : on installe
# un vrai Python Windows dans un préfixe wine, et on y exécute PyInstaller.
set -euo pipefail

PYVER="${PYVER:-3.12.8}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/.wine-build}"
export WINEPREFIX="$BUILD/prefix"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="

command -v wine >/dev/null || { echo "wine est requis." >&2; exit 1; }
mkdir -p "$BUILD"

if [ ! -f "$WINEPREFIX/drive_c/Py312/python.exe" ]; then
  echo "== Préfixe wine =="
  wineboot -u
  [ -f "$BUILD/python-installer.exe" ] || curl -fsSL -o "$BUILD/python-installer.exe" \
    "https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
  echo "== Installation de Python $PYVER (Windows) =="
  wine "$BUILD/python-installer.exe" /quiet InstallAllUsers=1 \
       TargetDir='C:\Py312' Include_test=0 Include_doc=0 Include_tcltk=0
  sleep 5
fi

PY='C:\Py312\python.exe'
echo "== Dépendances =="
wine "$PY" -m pip install --no-warn-script-location --upgrade pip wheel
wine "$PY" -m pip install --no-warn-script-location pyinstaller paramiko

echo "== PyInstaller =="
cd "$ROOT"
wine "$PY" -m PyInstaller --clean --noconfirm \
     --distpath dist --workpath "$BUILD/work" packaging/moonlight.spec

cp -f config.example.toml README.md dist/ 2>/dev/null || true
echo
echo "Exécutables prêts :"
ls -lh dist/*.exe
