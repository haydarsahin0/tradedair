#!/usr/bin/env bash
#
# GUNCELLEME — git pull cakismasi olmadan.
#
#   ./scripts/update.sh
#
# Calisma ayarlarin (.env) hicbir zaman degismez; sadece kod ve
# varsayilan config guncellenir.

set -uo pipefail
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

echo
if ! git diff --quiet 2>/dev/null; then
    warn "Takip edilen dosyalarda yerel degisiklik var:"
    git diff --name-only | sed 's/^/      /'
    echo
    echo "  Bunlar yedeklenip sifirlanacak. Kendi ayarlarin .env'de"
    echo "  tutuldugu icin HICBIR AYARIN KAYBOLMAZ."
    echo
    read -r -p "  Devam? (E/h): " a
    case "${a,,}" in
        h|hayir|n|no) echo "  Iptal."; exit 0 ;;
    esac

    TS="$(date +%Y%m%d-%H%M%S)"
    mkdir -p .backup
    git diff > ".backup/local-changes-${TS}.patch"
    ok "Degisiklikler .backup/local-changes-${TS}.patch dosyasina yedeklendi"

    git checkout -- .
    ok "Takip edilen dosyalar sifirlandi"
fi

echo
echo "  Guncelleniyor..."
if git pull; then
    ok "Kod guncellendi"
else
    warn "git pull basarisiz — yukaridaki hataya bak."
    exit 1
fi

echo
echo "  Calisma ayarlarin (.env):"
for k in DRY_RUN STAKE_AMOUNT MAX_OPEN_TRADES DRY_RUN_WALLET; do
    v="$(grep "^${k}=" .env 2>/dev/null | cut -d= -f2-)"
    printf '     %-18s %s\n' "$k" "${v:-<varsayilan>}"
done
echo
echo "  Botu yeni kodla baslatmak icin:  docker compose up -d --force-recreate"
echo
