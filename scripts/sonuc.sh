#!/usr/bin/env bash
#
# SON BACKTEST SONUCU
#
#   ./scripts/sonuc.sh          # ozet
#   ./scripts/sonuc.sh tam      # ciktinin tamami
#
# Test hala calisiyorsa onu da soyler.

set -uo pipefail
cd "$(dirname "$0")/.."

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

# --- 1. Test hala suruyor mu? --- #
if screen -ls 2>/dev/null | grep -q "tradedair-test"; then
    bold "TEST HALA CALISIYOR"
    echo "  Canli izlemek icin:   screen -r tradedair-test"
    echo "  Ayrilmak icin:        Ctrl+A sonra D"
    echo
    LOG="$(ls -t user_data/logs/fulltest-*.log 2>/dev/null | head -1)"
    if [ -n "$LOG" ]; then
        echo "  Su ana kadarki son satirlar:"
        tail -8 "$LOG" | sed 's/^/     /'
    fi
    echo
    exit 0
fi

# --- 2. Son log --- #
LOG="$(ls -t user_data/logs/fulltest-*.log 2>/dev/null | head -1)"

if [ -z "$LOG" ]; then
    warn "Hic fulltest logu bulunamadi."
    echo "  Testi baslatmak icin:  ./scripts/fulltest.sh"
    echo
    echo "  Freqtrade'in kendi kayitlarindan okumayi denemek icin:"
    echo "    docker compose run --rm -e FREQTRADE__DRY_RUN=true freqtrade \\"
    echo "      backtesting-show --config /freqtrade/user_data/config_backtest.json"
    exit 1
fi

bold "SON TEST: $(basename "$LOG")"
echo "  Tarih: $(stat -c %y "$LOG" 2>/dev/null | cut -d. -f1)"
echo "  Boyut: $(du -h "$LOG" | cut -f1)"

if [ "${1:-}" = "tam" ]; then
    bold "CIKTININ TAMAMI"
    cat "$LOG"
    exit 0
fi

# --- 3. Hata var mi? --- #
if grep -qE "Backtest basarisiz|ERROR - |Traceback" "$LOG"; then
    bold "HATA BULUNDU"
    grep -E "ERROR - |Backtest basarisiz|impossible to backtest" "$LOG" \
        | tail -5 | sed 's/^/  /'
    echo
    echo "  Tamamini gormek icin:  ./scripts/sonuc.sh tam"
    echo
fi

# --- 4. Kac cift test edildi --- #
CIFT="$(grep -oE "[0-9]+ cift icin veri hazir" "$LOG" | tail -1)"
[ -n "$CIFT" ] && ok "$CIFT"

# --- 5. Ozet tablolar --- #
if grep -q "SUMMARY METRICS" "$LOG"; then
    bold "OZET"
    sed -n '/SUMMARY METRICS/,/^$/p' "$LOG" \
        | grep -E "Total/Daily|Starting balance|Final balance|Absolute profit|Total profit|CAGR|Sharpe|Sortino|Calmar|Profit factor|p-value|Market change|Long / Short profit %|Max % of account underwater|Trades per day|Best Pair|Worst Pair|Worst trade|Max Consecutive|Rejected" \
        | sed 's/^/  /'
fi

if grep -q "STRATEGY SUMMARY" "$LOG"; then
    bold "STRATEJI OZETI"
    sed -n '/STRATEGY SUMMARY/,$p' "$LOG" | head -12 | sed 's/^/  /'
fi

echo
echo "  Tamamini gormek icin:  ./scripts/sonuc.sh tam"
echo "  Log dosyasi         :  $LOG"
echo
