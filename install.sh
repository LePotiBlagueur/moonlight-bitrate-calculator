#!/usr/bin/env bash
# Installe moonlight-bitrate et moonlight-recap dans le PATH, avec les
# complétions zsh. Idempotent : relancez-le après une modification du code.
#
#   ./install.sh              installe ou met à jour
#   ./install.sh --uninstall  retire tout
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
COMP_DIR="$HOME/.local/share/zsh/site-functions"
MARKER="# >>> moonlight-bitrate >>>"
END_MARKER="# <<< moonlight-bitrate <<<"

say()  { printf '\033[36m==\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

rc_file() {
  case "${SHELL##*/}" in
    zsh)  echo "$HOME/.zshrc" ;;
    bash) echo "$HOME/.bashrc" ;;
    *)    echo "$HOME/.profile" ;;
  esac
}

uninstall() {
  say "Désinstallation"
  if command -v pipx >/dev/null 2>&1; then
    pipx uninstall moonlight-bitrate-calculator >/dev/null 2>&1 \
      && ok "paquet pipx retiré" || warn "paquet pipx absent"
  fi
  rm -f "$COMP_DIR/_moonlight-bitrate" "$COMP_DIR/_moonlight-recap"
  ok "complétions retirées"
  local rc; rc="$(rc_file)"
  if [ -f "$rc" ] && grep -qF "$MARKER" "$rc"; then
    sed -i "/$(printf '%s' "$MARKER" | sed 's/[]\/$*.^[]/\\&/g')/,/$(printf '%s' "$END_MARKER" | sed 's/[]\/$*.^[]/\\&/g')/d" "$rc"
    ok "bloc retiré de $rc"
  fi
  echo
  echo "Terminé. Rouvrez un terminal."
}

[ "${1:-}" = "--uninstall" ] && { uninstall; exit 0; }

# --- prérequis --------------------------------------------------------------
say "Prérequis"
python3 - <<'PY' || { echo "Python 3.11+ requis." >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
ok "python $(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

if command -v iperf3 >/dev/null 2>&1; then
  ok "iperf3 $(iperf3 --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  warn "iperf3 absent : indispensable pour mesurer (pacman -S iperf3)"
fi

command -v pipx >/dev/null 2>&1 || {
  echo "pipx est requis (pacman -S python-pipx)." >&2; exit 1; }

# --- installation -----------------------------------------------------------
say "Installation des commandes"
pipx install --force "$REPO" 2>&1 | sed 's/^/  /'

# --- PATH -------------------------------------------------------------------
say "PATH"
rc="$(rc_file)"
need_path=0
case ":$PATH:" in *":$BIN_DIR:"*) ok "$BIN_DIR déjà dans le PATH" ;;
                  *) need_path=1 ;; esac

need_fpath=1
if [ "${SHELL##*/}" != "zsh" ]; then need_fpath=0; fi

if [ "$need_path" = 1 ] || [ "$need_fpath" = 1 ]; then
  if ! grep -qF "$MARKER" "$rc" 2>/dev/null; then
    {
      echo ""
      echo "$MARKER"
      [ "$need_path" = 1 ] && echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
      [ "$need_fpath" = 1 ] && {
        echo "fpath=(\"\$HOME/.local/share/zsh/site-functions\" \$fpath)"
        echo "autoload -Uz compinit && compinit -C"
      }
      echo "$END_MARKER"
    } >> "$rc"
    ok "bloc ajouté à $rc"
  else
    ok "bloc déjà présent dans $rc"
  fi
fi

# --- complétions ------------------------------------------------------------
say "Complétions zsh"
mkdir -p "$COMP_DIR"
install -m 0644 "$REPO/completions/_moonlight-bitrate" "$COMP_DIR/"
install -m 0644 "$REPO/completions/_moonlight-recap" "$COMP_DIR/"
ok "installées dans $COMP_DIR"

# --- vérification -----------------------------------------------------------
say "Vérification"
for cmd in moonlight-bitrate moonlight-recap; do
  if [ -x "$BIN_DIR/$cmd" ]; then
    ok "$cmd $("$BIN_DIR/$cmd" --version | awk '{print $2}')"
  else
    warn "$cmd introuvable dans $BIN_DIR"
  fi
done

echo
echo "Terminé. Ouvrez un nouveau terminal (ou : source $rc), puis :"
echo "    moonlight-recap -b 450"
echo "    moonlight-bitrate -c config.toml -p lan --probe-mtu"
