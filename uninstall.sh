#!/usr/bin/env sh
# Avinstallera Uppa på macOS och Linux:
#   curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.sh | sh
# Från en lokal kopia:  ./uninstall.sh
#
# Tar bort programmet (~/.uppa/uppa.py) och kommandot ~/.local/bin/uppa.
# Behåller Uppas cache och logg (~/.uppa).
# UPPA_PURGE=1 tar bort även ~/.uppa med dina data. UPPA_YES=1 hoppar över frågan.
set -eu
# Language: TRUPPA_LANG, else ~/.truppa/config.json (shared by the whole troupe), else English
TL="${TRUPPA_LANG:-}"
if [ -z "$TL" ] && [ -f "$HOME/.truppa/config.json" ]; then
  TL="$(sed -n 's/.*"lang"[^"]*"\([a-z]*\)".*/\1/p' "$HOME/.truppa/config.json" 2>/dev/null | head -n 1)"
fi
t() { case "$TL" in sv*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }
START="$(date +%s)"

DIR="$HOME/.uppa"
SHIM="$HOME/.local/bin/uppa"

say()  { printf '  \033[38;5;49m▲\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✘\033[0m %s\n' "$1" >&2; exit 1; }

ask() {   # ask "Fråga" -> 0 om ja. Läser från terminalen även när skriptet kommer via curl | sh
  if [ -r /dev/tty ]; then
    printf "$(t '  %s [y/N] ' '  %s [j/N] ')" "$1"
    { read -r SVAR < /dev/tty; } 2>/dev/null || SVAR=""
    case "$SVAR" in j|J|ja|Ja|y|Y|yes|Yes) return 0 ;; esac
    return 1
  fi
  die "$(t "No terminal to ask in. Run with UPPA_YES=1 to uninstall without asking." "Ingen terminal att fråga i. Kör med UPPA_YES=1 för att avinstallera utan fråga.")"
}

FOUND=""
TARGETS=""
if [ "${UPPA_PURGE:-}" = "1" ]; then
  [ -e "$DIR" ] && { FOUND="$FOUND\n    $DIR (med dina data)"; TARGETS="$TARGETS $DIR"; }
else
  for p in uppa.py; do
    [ -e "$DIR/$p" ] && { FOUND="$FOUND\n    $DIR/$p"; TARGETS="$TARGETS $DIR/$p"; }
  done
fi
# startkommandot: bara om det är vårt (pekar på ~/.uppa)
if [ -e "$SHIM" ] && grep -qsF "/.uppa/" "$SHIM"; then FOUND="$FOUND\n    $SHIM"; TARGETS="$TARGETS $SHIM"; fi
if [ -z "$FOUND" ]; then
  say "$(t "Uppa is not installed here. Nothing to remove." "Uppa är inte installerad här. Inget att ta bort.")"
  exit 0
fi

printf "$(t '\n  This is removed:' '\n  Det här tas bort:')"
printf "$FOUND\n"
[ "${UPPA_PURGE:-}" = "1" ] || printf "$(t '  Kept: the Uppa cache and log (~/.uppa).\n' '  Behålls: Uppas cache och logg (~/.uppa).\n')"
printf '\n'
if [ "${UPPA_YES:-}" != "1" ]; then
  ask "$(t "Uninstall Uppa?" "Avinstallera Uppa?")" || { say "$(t "Cancelled. Nothing has been removed." "Avbrutet. Ingenting har tagits bort.")"; exit 0; }
fi

for t in $TARGETS; do rm -rf "$t"; done
# tom ~/.uppa: städa bort mappen också
rmdir "$DIR" 2>/dev/null || true

SECS=$(( $(date +%s) - START ))
printf "$(t '\n  \033[38;5;42m✔\033[0m Uppa is uninstalled%s (%s s).\n\n' '\n  \033[38;5;42m✔\033[0m Uppa är avinstallerad%s (%s s).\n\n')" "" "$SECS"
