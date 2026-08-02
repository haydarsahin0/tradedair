#!/usr/bin/env bash
#
# Parametre optimizasyonu (hyperopt).
#
# Stratejideki tum parametreleri veriye gore optimize eder.
#
# Kullanim:
#   ./scripts/hyperopt.sh              # 300 deneme, varsayilan araliklar
#   ./scripts/hyperopt.sh 600          # 600 deneme (daha uzun, daha iyi)
#
# ONEMLI: Optimizasyon EGITIM doneminde yapilir, sonra AYRI bir donemde
# dogrulanir. Ayni veride optimize edip ayni veride test etmek kendini
# kandirmaktir (overfit) — gercek piyasada calismaz.

set -uo pipefail
cd "$(dirname "$0")/.."

EPOCHS="${1:-300}"
CFG="/freqtrade/user_data/config_backtest.json"

# Egitim: ilk ~14 ay | Dogrulama: son ~5 ay (hic gorulmemis veri)
TRAIN="20250101-20260301"
TEST="20260301-20260801"

die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

echo
echo "=== 1/2  EGITIM donemi optimizasyonu: $TRAIN ($EPOCHS deneme) ==="
echo "    Bu uzun surer — kucuk sunucuda 1-3 saat."
echo

if ! docker compose run --rm freqtrade hyperopt \
        --config "$CFG" \
        --strategy SupportResistanceBreakRetest \
        --hyperopt-loss SharpeHyperOptLoss \
        --spaces buy sell \
        --timerange "$TRAIN" \
        --epochs "$EPOCHS" \
        --job-workers 1 \
        --print-all=false; then
    die "Hyperopt basarisiz."
fi

echo
echo "=== 2/2  DOGRULAMA — hic optimize edilmemis donem: $TEST ==="
echo "    Buradaki sonuc gercege daha yakindir."
echo

docker compose run --rm freqtrade backtesting \
    --config "$CFG" \
    --strategy SupportResistanceBreakRetest \
    --timerange "$TEST" \
    --breakdown month

python3 scripts/notify_backtest.py || true

echo
echo "En iyi parametreler user_data/strategies/SupportResistanceBreakRetest.json"
echo "dosyasina yazildi ve bundan sonra otomatik kullanilir."
echo
echo "Egitim ve dogrulama sonuclari BIRBIRINE YAKINSA strateji saglamdir."
echo "Egitimde harika, dogrulamada kotuyse overfit olmustur — guvenme."
