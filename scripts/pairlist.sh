#!/usr/bin/env bash
#
# CIFT LISTESI GENISLETME
#
# Canli config'te VolumePairList var — Bybit'teki tum USDT perp'leri
# hacme gore siralayip ilk N tanesini secer, kalite filtrelerinden gecirir.
#
# Ama VolumePairList BACKTEST'te calismaz: gecmise donuk "o gun hangi
# coinler en yuksek hacimliydi" bilgisi yok. Freqtrade'in cozumu:
# listeyi CANLI borsadan bir kez cek, sabit liste olarak backtest'e yaz.
#
# Bu script tam olarak onu yapar.
#
#   ./scripts/pairlist.sh          # canli config'teki sayi kadar (50)
#   ./scripts/pairlist.sh 25       # 25 cift
#
# DIKKAT: cift sayisi backtest'in bellek ve sure ihtiyacini dogrudan
# belirler. 1 GB RAM'li sunucuda 50 rahat, 100 sikisik, 200+ calismaz.

set -uo pipefail
cd "$(dirname "$0")/.."

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

N="${1:-}"
LIVE=user_data/config.json
BT=user_data/config_backtest.json

if [ -n "$N" ]; then
    python3 - "$LIVE" "$N" <<'PY'
import json, sys
p, n = sys.argv[1], int(sys.argv[2])
c = json.load(open(p))
for pl in c["pairlists"]:
    if pl["method"] == "VolumePairList":
        pl["number_assets"] = n
json.dump(c, open(p, "w"), indent=4, ensure_ascii=False)
open(p, "a").write("\n")
PY
    ok "Canli config'te cift sayisi $N olarak ayarlandi"
fi

CNT="$(python3 -c "
import json
c=json.load(open('$LIVE'))
print(next(p['number_assets'] for p in c['pairlists'] if p['method']=='VolumePairList'))")"

bold "1/2  Bybit'ten guncel cift listesi cekiliyor (hedef: $CNT cift)"
echo "  Hacme gore siralanip yas/fiyat/makas/oynaklik filtrelerinden geciriliyor..."
echo

OUT="$(docker compose run --rm freqtrade test-pairlist \
        --config /freqtrade/user_data/config.json \
        --print-json 2>&1)"

PAIRS="$(printf '%s' "$OUT" | grep -oE '^\[.*\]$' | tail -1)"

if [ -z "$PAIRS" ]; then
    printf '%s\n' "$OUT" | tail -25
    die "Cift listesi alinamadi. Yukaridaki hataya bak."
fi

python3 - "$BT" "$PAIRS" <<'PY'
import json, sys
bt, pairs = sys.argv[1], json.loads(sys.argv[2])
c = json.load(open(bt))
c["exchange"]["pair_whitelist"] = pairs
c["pairlists"] = [{"method": "StaticPairList"}]
json.dump(c, open(bt, "w"), indent=4, ensure_ascii=False)
open(bt, "a").write("\n")
print(f"  -> {len(pairs)} cift backtest config'ine yazildi\n")
for i in range(0, len(pairs), 4):
    print("     " + "  ".join(p.replace('/USDT:USDT', '').ljust(8) for p in pairs[i:i+4]))
PY

bold "2/2  Hazir"
cat <<TXT

  Canli config  : VolumePairList — liste her 30 dakikada kendini yeniler,
                  yeni yukselen coinler otomatik girer, dusenler cikar.
  Backtest config: yukaridaki liste SABIT olarak yazildi (bugunun anlik
                  goruntusu).

  ONEMLI — HAYATTA KALMA YANLILIGI (survivorship bias):
  Bu liste BUGUN hacimli olan coinlerden olusuyor. Gecmise donuk test
  ederken, o donemde daha kucuk ya da hic olmayan coinleri "bugun basarili
  olduklarini bilerek" test etmis oluyorsun. Bu, backtest sonucunu GERCEKTEN
  DAHA IYI gosterir. Sonucu bu payi dusunerek oku.

  Simdi backtest:
      ./scripts/backtest.sh

  Veri indirme $CNT cift icin uzun surer. Kopmaya karsi:
      screen -S bt
      ./scripts/backtest.sh
      (Ctrl+A sonra D ile ayril, "screen -r bt" ile geri don)
TXT
echo
