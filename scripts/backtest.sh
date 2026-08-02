#!/usr/bin/env bash
#
# Gecmis veriyi indirir ve backtest calistirir.
#
# Kullanım:
#   ./scripts/backtest.sh                      # son 1.5 yil
#   ./scripts/backtest.sh 20250101-20260801    # kendi tarih araligin

set -euo pipefail
cd "$(dirname "$0")/.."

RANGE="${1:-20250101-20260801}"
CFG="/freqtrade/user_data/config_backtest.json"

echo
echo "=== Veri indiriliyor: $RANGE ==="
docker compose run --rm freqtrade download-data \
    --config "$CFG" \
    --timeframes 1h \
    --timerange "$RANGE" \
    --trading-mode futures

echo
echo "=== Backtest calisiyor ==="
docker compose run --rm freqtrade backtesting \
    --config "$CFG" \
    --strategy SupportResistanceBreakRetest \
    --timerange "$RANGE" \
    --breakdown month

echo
echo "Sonuclar user_data/backtest_results/ altinda kayitli."
echo "Detayli islem listesi icin:"
echo "  docker compose run --rm freqtrade backtesting-show --config $CFG"
