#!/usr/bin/env sh
# Avinstallera Uppa på macOS och Linux:
#   curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.sh | sh
# Från en lokal kopia:  ./uninstall.sh
#
# Tar bort programmet (~/.uppa/uppa.py) och kommandot ~/.local/bin/uppa.
# Behåller Uppas cache och logg (~/.uppa).
# UPPA_PURGE=1 tar bort även ~/.uppa med dina data. UPPA_YES=1 hoppar över frågan.
set -eu
START="$(date +%s)"

DIR="$HOME/.uppa"
SHIM="$HOME/.local/bin/uppa"

say()  { printf '  \033[38;5;49m▲\033[0m %s\n' "$1"; }
die()  { printf '  \033[31m✘\033[0m %s\n' "$1" >&2; exit 1; }

ask() {   # ask "Fråga" -> 0 om ja. Läser från terminalen även när skriptet kommer via curl | sh
  if [ -r /dev/tty ]; then
    printf '  %s [j/N] ' "$1"
    { read -r SVAR < /dev/tty; } 2>/dev/null || SVAR=""
    case "$SVAR" in j|J|ja|Ja|y|Y|yes) return 0 ;; esac
    return 1
  fi
  die "Ingen terminal att fråga i. Kör med UPPA_YES=1 för att avinstallera utan fråga."
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
  say "Uppa är inte installerad här. Inget att ta bort."
  exit 0
fi

printf '\n  Det här tas bort:'
printf "$FOUND\n"
[ "${UPPA_PURGE:-}" = "1" ] || printf '  Behålls: Uppas cache och logg (~/.uppa).\n'
printf '\n'
if [ "${UPPA_YES:-}" != "1" ]; then
  ask "Avinstallera Uppa?" || { say "Avbrutet. Ingenting har tagits bort."; exit 0; }
fi

for t in $TARGETS; do rm -rf "$t"; done
# tom ~/.uppa: städa bort mappen också
rmdir "$DIR" 2>/dev/null || true

SECS=$(( $(date +%s) - START ))
printf '\n  \033[38;5;42m✔\033[0m Uppa är avinstallerad%s (%s s).\n\n' "" "$SECS"
