#!/usr/bin/env sh
# uppa för macOS och Linux:
#   curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/install.sh | sh
# Från en lokal kopia:  ./install.sh
# Styr källan med UPPA_REPO=ägare/repo och UPPA_BRANCH=gren (eller en release-tagg).
set -eu

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
    Darwin) die "Python 3.8+ saknas. Kör: xcode-select --install   (eller: brew install python)";;
    *)      die "Python 3.8+ saknas. Kör: sudo apt install python3   (eller dnf/pacman motsvarande)";;
  esac
fi

# 2. Hämta uppa.py (lokal kopia bredvid skriptet om den finns, annars från GitHub)
mkdir -p "$DIR" "$BIN"
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/uppa.py" ] && [ "${UPPA_FROM_WEB:-}" != "1" ]; then
  say "Installerar från $HERE"
  cp "$HERE/uppa.py" "$DIR/uppa.py"
else
  say "Hämtar uppa från github.com/$REPO ($BRANCH)"
  curl -fsSL "https://raw.githubusercontent.com/$REPO/$BRANCH/uppa.py" -o "$DIR/uppa.py.new" \
    || die "nedladdningen misslyckades – kolla nätet eller UPPA_REPO/UPPA_BRANCH"
  "$PY" -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$DIR/uppa.py.new" \
    || die "det nedladdade skriptet är trasigt"
  mv "$DIR/uppa.py.new" "$DIR/uppa.py"
fi

# 3. Startkommando i ~/.local/bin
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
    say "La till ~/.local/bin i PATH ($RC). Öppna en ny terminal."
    ;;
esac

VER="$("$PY" "$DIR/uppa.py" --version 2>/dev/null || echo uppa)"
printf '\n  \033[38;5;42m✔\033[0m %s installerad. Kör: \033[1muppa\033[0m   (grundpaketet: uppa install bas)\n\n' "$VER"
