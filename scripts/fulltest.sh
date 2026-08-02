#!/usr/bin/env bash
#
# TAM TEST — cift listesini tazele, veriyi indir, backtest calistir.
#
#   ./scripts/fulltest.sh
#
# Tek komut. Kendini otomatik olarak "screen" icinde baslatir, boylece
# tablet uykuya dalsa ya da baglanti kopsa bile is devam eder.
#
# Ciktinin tamami user_data/logs/fulltest-<tarih>.log dosyasina yazilir.

set -uo pipefail
cd "$(dirname "$0")/.."

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

# --- Kendini screen icinde yeniden baslat --- #
# $STY doluysa zaten screen icindeyiz.
if [ -z "${STY:-}" ] && [ "${1:-}" != "--devam" ]; then
    if command -v screen >/dev/null 2>&1; then
        # Ayni isimde eski bir oturum varsa temizle
        screen -S tradedair-test -X quit >/dev/null 2>&1 || true
        echo
        echo "  Arka planda dayanikli bir oturum baslatiliyor (screen)..."
        echo "  Ayrilmak icin: Ctrl+A sonra D      Geri donmek icin: screen -r tradedair-test"
        echo
        sleep 2
        exec screen -S tradedair-test bash -c \
            "'$SELF' --devam; echo; echo '=== BITTI. Cikmak icin: exit ==='; exec bash"
    fi
    echo "  (screen kurulu degil, dogrudan calisiyor — baglanti kopmasin)"
fi

LOG="user_data/logs/fulltest-$(date +%Y%m%d-%H%M%S).log"
mkdir -p user_data/logs
exec > >(tee -a "$LOG") 2>&1

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

START=$(date +%s)

bold "════ 1/2  CIFT LISTESI TAZELENIYOR ════"
./scripts/pairlist.sh || die "Cift listesi alinamadi."

bold "════ 2/2  VERI INDIRME + BACKTEST ════"
echo "  Bu kisim uzun surer (46 cift icin ~30-40 dakika)."
echo "  Ctrl+A sonra D ile ayrilabilirsin, is devam eder."
echo
./scripts/backtest.sh || die "Backtest basarisiz."

MIN=$(( ($(date +%s) - START) / 60 ))
bold "════ TAMAMLANDI (${MIN} dakika) ════"
echo "  Ciktinin tamami: $LOG"
echo
