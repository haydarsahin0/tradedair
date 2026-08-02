#!/usr/bin/env bash
#
# SAGLAMLIK TESTI — "bu edge gercek mi, yoksa ayi piyasasina mi denk geldi?"
#
# Ayni stratejiyi farkli donemlerde ayri ayri calistirir. Bir strateji
# yalnizca tek bir piyasa rejiminde para kazaniyorsa, o rejim bitince
# canlida cokerse sasirmamak gerekir.
#
#   ./scripts/robustness.sh

set -uo pipefail
cd "$(dirname "$0")/.."

CFG="/freqtrade/user_data/config_backtest.json"
OUT="user_data/robustness.txt"
: > "$OUT"

run_period() {
    local label="$1" range="$2"
    echo
    echo "════════════════════════════════════════════════════════"
    echo "  $label   ($range)"
    echo "════════════════════════════════════════════════════════"

    local res
    res="$(docker compose run --rm freqtrade backtesting \
             --config "$CFG" \
             --strategy CandleExpansion \
             --timerange "$range" 2>&1)"

    # Ozet satirlari
    echo "$res" | grep -E "Total/Daily Avg Trades|Absolute profit|Total profit %|Sharpe|Profit factor|Market change|Long / Short profit %|Max % of account underwater" \
        | sed 's/^/  /'

    {
        echo "=== $label ($range) ==="
        echo "$res" | grep -E "Total/Daily Avg Trades|Absolute profit|Total profit %|Sharpe|Profit factor|Market change|Long / Short profit %|Max % of account underwater"
        echo
    } >> "$OUT"
}

echo
echo "Her donem ayri ayri test ediliyor. Bu biraz surer."

run_period "1. YARI  (2025 ilk yari)"   "20250101-20250701"
run_period "2. YARI  (2025 ikinci yari)" "20250701-20260101"
run_period "3. YARI  (2026 ilk yari)"   "20260101-20260701"

echo
echo "════════════════════════════════════════════════════════"
echo "  NASIL OKUNMALI"
echo "════════════════════════════════════════════════════════"
cat <<'TXT'

  Her donemde "Market change" ve "Total profit %" satirlarina bak:

  * Piyasanin DUSTUGU donemlerde kar, YUKSELDIGI donemlerde zarar varsa
    -> bu bir strateji degil, gizli bir short pozisyonudur. Bogaya
       donunce para kaybeder.

  * Her rejimde (yukselen, dusen, yatay) kar varsa -> gercek edge.

  * "Long / Short profit %" satirinda iki taraf da pozitifse saglamdir.
    Tek taraf tasiyorsa, o taraf calismayi birakinca strateji biter.

  Ozet: user_data/robustness.txt
TXT
echo
