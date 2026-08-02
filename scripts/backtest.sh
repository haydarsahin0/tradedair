#!/usr/bin/env bash
#
# Gecmis veriyi indirir ve backtest calistirir.
#
# Kullanım:
#   ./scripts/backtest.sh                      # son 1.5 yil
#   ./scripts/backtest.sh 20250101-20260801    # kendi tarih araligin

set -uo pipefail
cd "$(dirname "$0")/.."

RANGE="${1:-20250101-20260801}"
CFG="/freqtrade/user_data/config_backtest.json"

die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

echo
echo "=== Veri indiriliyor: $RANGE ==="
if ! docker compose run --rm freqtrade download-data \
        --config "$CFG" \
        --timeframes 15m \
        --timerange "$RANGE" \
        --trading-mode futures; then
    die "Veri indirilemedi. Yukaridaki hata mesajina bak."
fi

# Veri gercekten indi mi? (freqtrade bazen hata verip 0 donebiliyor)
if ! ls user_data/data/bybit/futures/*-1h-futures.feather >/dev/null 2>&1; then
    die "Veri dosyalari olusmadi. Borsa baglantisini ve tarih araligini kontrol et."
fi
echo "  -> $(ls user_data/data/bybit/futures/*-1h-futures.feather | wc -l) cift icin veri hazir"

echo
echo "=== Backtest calisiyor ==="
if ! docker compose run --rm freqtrade backtesting \
        --config "$CFG" \
        --strategy CandleExpansion \
        --timerange "$RANGE" \
        --breakdown month; then
    die "Backtest basarisiz. Yukaridaki hata mesajina bak."
fi

# Sonucu Telegram'a gonder (token yoksa sessizce atlar)
python3 scripts/notify_backtest.py || true

echo
echo "Sonuclar user_data/backtest_results/ altinda kayitli."
echo "Detayli islem listesi icin:"
echo "  docker compose run --rm freqtrade backtesting-show --config $CFG"
