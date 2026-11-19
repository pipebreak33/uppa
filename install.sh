#!/usr/bin/env sh
# uppa för macOS och Linux:
#   curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/install.sh | sh
# Från en lokal kopia:  ./install.sh
# Styr källan med UPPA_REPO=ägare/repo och UPPA_BRANCH=gren (eller en release-tagg).
set -eu
# Language: TRUPPA_LANG, else ~/.truppa/config.json (shared by the whole troupe), else English
TL="${TRUPPA_LANG:-}"
if [ -z "$TL" ] && [ -f "$HOME/.truppa/config.json" ]; then
  TL="$(sed -n 's/.*"lang"[^"]*"\([a-z]*\)".*/\1/p' "$HOME/.truppa/config.json" 2>/dev/null | head -n 1)"
fi
t() { case "$TL" in sv*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }
START="$(date +%s)"

REPO="${UPPA_REPO:-pipebreak33/uppa}"
BRANCH="${UPPA_BRANCH:-main}"
DIR="$HOME/.uppa"
BIN="$HOME/.local/bin"

say() { printf '  \033[38;5;49m▲\033[0m %s\n' "$1"; }
die() { printf '  \033[31m✘\033[0m %s\n' "$1" >&2; exit 1; }

# 1. Python 3.8+ (uppa är ett enda Python-skript utan beroenden)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  case "$(uname -s)" in
    Darwin) die "$(t "Python 3.8+ is missing. Run: xcode-select --install   (or: brew install python)" "Python 3.8+ saknas. Kör: xcode-select --install   (eller: brew install python)")";;
    *)      die "$(t "Python 3.8+ is missing. Run: sudo apt install python3   (or the dnf/pacman equivalent)" "Python 3.8+ saknas. Kör: sudo apt install python3   (eller dnf/pacman motsvarande)")";;
  esac
fi

# 2. Hämta uppa.py (lokal kopia bredvid skriptet om den finns, annars från GitHub)
mkdir -p "$DIR" "$BIN"
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/uppa.py" ] && [ "${UPPA_FROM_WEB:-}" != "1" ]; then
  say "$(t "Installing from $HERE" "Installerar från $HERE")"
  cp "$HERE/uppa.py" "$DIR/uppa.py"
else
  say "$(t "Fetching uppa from github.com/$REPO ($BRANCH)" "Hämtar uppa från github.com/$REPO ($BRANCH)")"
  curl -fsSL "https://raw.githubusercontent.com/$REPO/$BRANCH/uppa.py" -o "$DIR/uppa.py.new" \
    || die "$(t "the download failed: check the network or UPPA_REPO/UPPA_BRANCH" "nedladdningen misslyckades – kolla nätet eller UPPA_REPO/UPPA_BRANCH")"
  "$PY" -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$DIR/uppa.py.new" \
    || die "$(t "the downloaded script is broken" "det nedladdade skriptet är trasigt")"
  mv "$DIR/uppa.py.new" "$DIR/uppa.py"
fi

# 3. Startkommando i ~/.local/bin (ta bort först: är det en symlänk ska vi inte skriva genom den)
rm -f "$BIN/uppa"
cat > "$BIN/uppa" <<SHIM
#!/usr/bin/env sh
exec "$PY" "$DIR/uppa.py" "\$@"
SHIM
chmod +x "$BIN/uppa"

# 4. ~/.local/bin i PATH
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    case "${SHELL:-}" in
      */zsh)  RC="$HOME/.zshrc" ;;
      */bash) RC="$HOME/.bashrc"; [ "$(uname -s)" = Darwin ] && RC="$HOME/.bash_profile" ;;
      *)      RC="$HOME/.profile" ;;
    esac
    grep -qs '.local/bin' "$RC" 2>/dev/null || printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
    say "$(t "Added ~/.local/bin to PATH ($RC). Open a new terminal." "La till ~/.local/bin i PATH ($RC). Öppna en ny terminal.")"
    ;;
esac

VER="$("$PY" "$DIR/uppa.py" --version 2>/dev/null || echo uppa)"
SECS=$(( $(date +%s) - START )); if [ "$SECS" -ge 60 ]; then TOOK="$((SECS / 60)) min $((SECS % 60)) s"; else TOOK="$SECS s"; fi
printf "$(t '\n  \033[38;5;42m✔\033[0m %s installed in %s. Run: \033[1muppa\033[0m   (the base package: uppa install bas)\n' '\n  \033[38;5;42m✔\033[0m %s installerad på %s. Kör: \033[1muppa\033[0m   (grundpaketet: uppa install bas)\n')" "$VER" "$TOOK"
printf "$(t '  \033[2mUninstall: curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.sh | sh\033[0m\n\n' '  \033[2mAvinstallera: curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.sh | sh\033[0m\n\n')"
