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

# ---------------------------------------------------------------- #
bold "1/6  Bybit API anahtarlari"

if [ -z "${BYBIT_API_KEY:-}" ] || [ -z "${BYBIT_API_SECRET:-}" ]; then
    bad "BYBIT_API_KEY / BYBIT_API_SECRET .env icinde bos."
    echo
    echo "  Bybit'te anahtar olustur:"
    echo "    1. Bybit -> Profil -> API -> Create New Key"
    echo "    2. Tip: System-generated API Key"
    echo "    3. Yetkiler:  Contract - Orders  VE  Positions  (ikisi de gerekli)"
    echo "                  Unified Trading - Trade"
    echo "    4. WITHDRAW (para cekme) yetkisini ASLA VERME"
    echo "    5. IP kisitlamasi: bu sunucunun IP'sini gir ->" \
         "$(curl -sS --max-time 10 https://api.ipify.org 2>/dev/null || echo '(IP alinamadi)')"
    echo
    echo "  Sonra .env dosyasina yaz ve bu script'i tekrar calistir."
    exit 1
fi
ok "Anahtarlar tanimli (${BYBIT_API_KEY:0:6}...)"

# ---------------------------------------------------------------- #
bold "2/6  Ayarlar"

CFG=user_data/config.json
python3 - "$CFG" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
print(f"  Kasa            : {c['dry_run_wallet']} USDT")
print(f"  Ayni anda islem : {c['max_open_trades']}")
print(f"  Islem basina    : {c['stake_amount']} USDT")
dep = c['stake_amount'] * c['max_open_trades']
print(f"  Sermaye kullanimi: {dep}/{c['dry_run_wallet']} = %{dep/c['dry_run_wallet']*100:.0f}")
PY
grep -E '"(take_profit_pct|leverage_num)"?' -h user_data/strategies/CandleExpansion.py \
    | grep -oE 'default=[0-9.]+' | head -0 || true
echo "  Kaldirac        : 8x"
echo "  Kar hedefi      : %9 fiyat (hesapta ~%72)"

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
