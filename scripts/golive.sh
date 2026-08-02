#!/usr/bin/env bash
#
# CANLI İŞLEME GEÇİŞ — gerçek parayla işlem açmaya başlar.
#
#   ./scripts/golive.sh
#
# Her adımı tek tek doğrular. Bir şey eksikse durur ve ne yapman
# gerektiğini söyler. Onay vermeden hiçbir şey değişmez.

set -uo pipefail
cd "$(dirname "$0")/.."

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -f .env ] || die ".env yok. Once ./scripts/setup.sh calistir."
# shellcheck disable=SC1091
set -a; . ./.env; set +a

echo
printf '\033[1m\033[33m'
cat <<'BANNER'
  ============================================================
    CANLI ISLEME GECIS — GERCEK PARA
  ============================================================
BANNER
printf '\033[0m'

# .env'e bir anahtari yaz (varsa degistir, yoksa ekle)
set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" .env; then
        python3 - "$key" "$val" <<'PY'
import sys, pathlib
key, val = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
out = [f"{key}={val}" if line.startswith(f"{key}=") else line
       for line in p.read_text().splitlines()]
p.write_text("\n".join(out) + "\n")
PY
    else
        printf '%s=%s\n' "$key" "$val" >> .env
    fi
}

# ---------------------------------------------------------------- #
bold "1/6  Bybit API anahtarlari"

SRV_IP="$(curl -sS --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"

if [ -z "${BYBIT_API_KEY:-}" ] || [ -z "${BYBIT_API_SECRET:-}" ]; then
    warn "Anahtarlar henuz girilmemis."
    echo
    echo "  BYBIT'TE ANAHTAR OLUSTURMA:"
    echo "    1. Bybit -> sag ustte profil -> API"
    echo "    2. Create New Key -> System-generated API Key"
    echo "    3. Yetkiler:"
    echo "         Unified Trading -> Trade          (ISARETLE)"
    echo "         Contract -> Orders, Positions     (ISARETLE)"
    echo "         Withdraw                          (ASLA ISARETLEME)"
    if [ -n "$SRV_IP" ]; then
        echo "    4. IP kisitlamasi -> su IP'yi gir:  ${SRV_IP}"
    else
        echo "    4. IP kisitlamasi -> bu sunucunun IP'sini gir"
    fi
    echo
    echo "  Anahtarlari asagiya YAPISTIR (elle yazmana gerek yok):"
    echo
fi

while [ -z "${BYBIT_API_KEY:-}" ]; do
    read -r -p "  API Key    : " BYBIT_API_KEY
    BYBIT_API_KEY="$(printf '%s' "$BYBIT_API_KEY" | tr -d '[:space:]')"
    [ -n "$BYBIT_API_KEY" ] || bad "Bos birakilamaz."
done

while [ -z "${BYBIT_API_SECRET:-}" ]; do
    # -s ile gizli: omuz ustunden okunmasin
    read -r -s -p "  API Secret : " BYBIT_API_SECRET
    echo
    BYBIT_API_SECRET="$(printf '%s' "$BYBIT_API_SECRET" | tr -d '[:space:]')"
    if [ -z "$BYBIT_API_SECRET" ]; then
        bad "Bos birakilamaz."
    else
        echo "               (${#BYBIT_API_SECRET} karakter alindi)"
    fi
done

set_env BYBIT_API_KEY "$BYBIT_API_KEY"
set_env BYBIT_API_SECRET "$BYBIT_API_SECRET"
chmod 600 .env
ok "Anahtarlar .env'e kaydedildi (${BYBIT_API_KEY:0:6}...)"

# --- Anahtarlar GERCEKTEN calisiyor mu? --- #
echo
echo "  Bybit'e baglanip dogrulaniyor..."
BAL="$(docker compose run --rm --entrypoint python freqtrade -c '
import os, sys, ccxt
try:
    ex = ccxt.bybit({
        "apiKey": os.environ["BYBIT_API_KEY"],
        "secret": os.environ["BYBIT_API_SECRET"],
        "options": {"defaultType": "swap"},
    })
    b = ex.fetch_balance()
    usdt = b.get("USDT", {})
    print("OK|%.2f" % float(usdt.get("total") or 0))
except Exception as e:
    print("ERR|%s" % str(e)[:200])
' 2>/dev/null | tail -1)"

case "$BAL" in
    OK\|*)
        BAKIYE="${BAL#OK|}"
        ok "Baglanti basarili — Bybit futures bakiyen: ${BAKIYE} USDT"
        if [ "${BAKIYE%%.*}" -lt 50 ] 2>/dev/null; then
            warn "Bakiye dusuk gorunuyor. Islem acilamayabilir."
        fi
        ;;
    ERR\|*)
        bad "Bybit reddetti: ${BAL#ERR|}"
        echo
        echo "  Sik sebepler:"
        echo "    - Anahtar yanlis kopyalanmis (bas/son karakter eksik)"
        echo "    - IP kisitlamasi bu sunucunun IP'sini icermiyor (${SRV_IP:-?})"
        echo "    - Unified Trading -> Trade yetkisi verilmemis"
        echo
        echo "  Duzelt ve script'i tekrar calistir."
        die "Iptal edildi. dry_run hala acik, hicbir sey degismedi."
        ;;
    *)
        bad "Dogrulama yapilamadi (Docker cikti vermedi)."
        die "Iptal edildi. dry_run hala acik."
        ;;
esac

# ---------------------------------------------------------------- #
bold "2/6  Islem buyuklugu"

CFG=user_data/config.json
KASA="${BAKIYE%%.*}"
[ -n "$KASA" ] && [ "$KASA" -gt 0 ] 2>/dev/null || KASA=500

echo
echo "  Bybit bakiyene gore ($KASA USDT) secenekler — 3 slot ile:"
echo
python3 - "$KASA" <<'PY'
import sys
k = int(sys.argv[1])
stop_lev = 12.2   # medyan stop, hesap yuzdesi olarak
print("   %-8s %-14s %-16s %s" % ("islem", "kullanim", "islem basi kayip", "beklenen dusus"))
for pay, dd in ((0.30, "~%32"), (0.45, "~%42"), (0.60, "~%54")):
    s = max(int(k * pay / 3), 1)
    print("   %-8s %-14s %-16s %s"
          % (f"{s} USDT", f"%{pay*100:.0f}", f"%{s*stop_lev/100/k*100:.2f}", dd))
PY
echo
echo "  Dusuk kullanim = daha az getiri AMA daha az dusus."
echo "  Birim risk basina verim hepsinde ayni."
echo
CUR="$(python3 -c "import json;print(json.load(open('$CFG'))['stake_amount'])")"
read -r -p "  Islem basina kac USDT? (bos = mevcut $CUR): " STK
if [ -n "$STK" ]; then
    python3 - "$CFG" "$STK" "$KASA" <<'PY'
import json, sys
p, stk, kasa = sys.argv[1], int(float(sys.argv[2])), int(sys.argv[3])
c = json.load(open(p))
c["stake_amount"] = stk
c["dry_run_wallet"] = kasa
json.dump(c, open(p, "w"), indent=4, ensure_ascii=False)
open(p, "a").write("\n")
PY
    ok "Islem basina $STK USDT olarak ayarlandi"
fi

echo
python3 - "$CFG" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
dep = c['stake_amount'] * c['max_open_trades']
print(f"  Ayni anda islem  : {c['max_open_trades']}")
print(f"  Islem basina     : {c['stake_amount']} USDT")
print(f"  Sermaye kullanimi: {dep} USDT")
PY
echo "  Kaldirac         : 8x"
echo "  Kar hedefi       : %9 fiyat (hesapta ~%72)"

# ---------------------------------------------------------------- #
bold "3/6  Bilmen gerekenler"
cat <<'TXT'
  Backtest sonucu (2025-01 -> 2026-08, gecmis veri):
    Getiri        : +%216
    MAKS DUSUS    : %54   <-- 500 USDT hesap 230 USDT'ye indi
    Dusus suresi  : 53 gun
    Ust uste kayip: 23 islem
    En kotu islem : -%70 (hesapta)
    Kazanma orani : %21.6  (5 islemden 4'u zarar eder, bu NORMAL)

  Gecmis performans gelecegi garanti etmez. Istatistiksel anlamlilik
  testi (p-value 0.2666) bu sonucun sans olma ihtimalini disliyamiyor.

  Bu bot dry-run'da hic calistirilmadi; gercek slippage olculmedi.
TXT

# ---------------------------------------------------------------- #
bold "4/6  Onay"
echo
read -r -p "  Yukaridakileri okudum, gercek parayla baslat (EVET yaz): " a
[ "$a" = "EVET" ] || die "Iptal edildi. Hicbir sey degismedi."

# ---------------------------------------------------------------- #
bold "5/6  dry_run kapatiliyor"
python3 - "$CFG" <<'PY'
import json, sys
p = sys.argv[1]
c = json.load(open(p))
c["dry_run"] = False
json.dump(c, open(p, "w"), indent=4, ensure_ascii=False)
open(p, "a").write("\n")
PY
ok "dry_run = false  (artik gercek emir gonderilecek)"

# ---------------------------------------------------------------- #
bold "6/6  Bot yeniden baslatiliyor"
docker compose up -d --force-recreate
sleep 15
docker compose logs --tail 25

echo
bold "Baslatildi."
cat <<'TXT'

  Telegram'a bakmayi unutma — su anlarda mesaj gelecek:
    * Sinyal olustugunda (islem acilmasa bile)
    * Emir gonderildiginde ve dolduğunda
    * Cikis olduğunda (kar hedefi / stop / likidasyon)
    * Uyari ve hata durumlarinda

  ACIL DURDURMA:  Telegram'dan  /stop
  POZISYON KAPAT: Telegram'dan  /fx

  Ilk gunlerde /status ve /profit ile sik sik kontrol et.
TXT
echo
