#!/usr/bin/env bash
#
# Telegram baglantisini teshis eder ve chat ID'yi otomatik bulur.
#
# "Chat not found" hatasi aliyorsan bunu calistir:
#     ./scripts/telegram_fix.sh

set -uo pipefail
cd "$(dirname "$0")/.."

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

[ -f .env ] || { bad ".env dosyasi yok."; exit 1; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a

TOKEN="${TELEGRAM_TOKEN:-}"

# Cevap govdesini ve HTTP kodunu birlikte doner: "<govde>|<kod>"
api() {
    curl -sS --max-time 20 -w '|%{http_code}' \
        "https://api.telegram.org/bot${TOKEN}/$1" 2>&1
}

# api.telegram.org'a hic ulasilabiliyor mu? (token sorunu ile ag sorununu ayirmak icin)
check_net() {
    local code
    code="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' \
            "https://api.telegram.org/bot0:0/getMe" 2>/dev/null || echo "000")"
    # Gecersiz token'a bile 401/404 doner; 000 = hic baglanilamadi
    [ "$code" != "000" ]
}

# .env'e bir anahtari yaz (varsa degistir, yoksa ekle)
set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" .env; then
        python3 - "$key" "$val" <<'PY'
import sys, pathlib
key, val = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
out = []
for line in p.read_text().splitlines():
    out.append(f"{key}={val}" if line.startswith(f"{key}=") else line)
p.write_text("\n".join(out) + "\n")
PY
    else
        printf '%s=%s\n' "$key" "$val" >> .env
    fi
}

echo
bold "1/4  Baglanti ve token kontrolu"

if check_net; then
    ok "api.telegram.org'a ulasilabiliyor"
else
    bad "Sunucudan api.telegram.org'a ULASILAMIYOR."
    echo
    echo "  Bu bir AG sorunu, token sorunu degil. Muhtemel sebepler:"
    echo "    - Sunucunun disari cikisi engelli"
    echo "    - Gecici DNS sorunu"
    echo
    echo "  Kontrol icin:  curl -v https://api.telegram.org/"
    exit 1
fi

if [ -z "$TOKEN" ]; then
    warn ".env icinde TELEGRAM_TOKEN bos."
else
    echo "  .env'deki token: ${TOKEN:0:12}...${TOKEN: -4}"
fi

# Token bos ya da gecersizse sor — dogrulanana kadar tekrar sor.
while :; do
    if [ -n "$TOKEN" ]; then
        RESP="$(api getMe)"
        CODE="${RESP##*|}"
        ME="${RESP%|*}"

        if printf '%s' "$ME" | grep -q '"ok":true'; then
            break
        fi

        echo
        case "$CODE" in
            401)
                bad "Token GECERSIZ (HTTP 401)."
                echo "     En sik sebep: bu token daha once /revoke ile IPTAL EDILMIS."
                echo "     Iptal edilen token bir daha calismaz — YENISINI almalisin."
                ;;
            404)
                bad "Token bicimi hatali (HTTP 404)."
                echo "     Dogru bicim: 1234567890:AAExxxxxxxxxxxxxxxxxxxxxxxx"
                echo "     Rakamlar, iki nokta ve harfler tek parca halinde olmali."
                ;;
            *)
                bad "Beklenmeyen cevap (HTTP ${CODE})."
                printf '     %s\n' "$(printf '%s' "$ME" | head -c 200)"
                ;;
        esac
    fi
    echo
    echo "  YENI TOKEN NASIL ALINIR:"
    echo "    1. Telegram'da @BotFather'i ac"
    echo "    2. /mybots yaz"
    echo "    3. Botunu sec"
    echo "    4. 'API Token' butonuna bas"
    echo "    5. Cikan uzun metni KOPYALA (tamamini, basindan sonuna)"
    echo
    read -r -p "  Token'i yapistir: " TOKEN
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    if [ -z "$TOKEN" ]; then
        bad "Bos birakilamaz."
    fi
done

BOT_NAME="$(printf '%s' "$ME" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["username"])')"
ok "Token gecerli — bot: @${BOT_NAME}"

if [ "$TOKEN" != "${TELEGRAM_TOKEN:-}" ]; then
    set_env TELEGRAM_TOKEN "$TOKEN"
    ok ".env icindeki token guncellendi"
fi

# Bot calisiyorsa gelen mesajlari o yutar, getUpdates bos doner.
echo
bold "2/4  Bot gecici olarak durduruluyor"
if docker compose ps --status running 2>/dev/null | grep -q tradedair; then
    docker compose stop >/dev/null 2>&1
    ok "Durduruldu (sonunda tekrar baslatilacak)"
    RESTART=1
else
    ok "Zaten calismiyor"
fi

echo
bold "3/4  Chat ID araniyor"
echo
echo "  ==> SIMDI TELEGRAM'I AC:"
echo "      1. @${BOT_NAME} botunu ara"
echo "      2. Sohbeti ac ve START butonuna bas"
echo "      3. Bota herhangi bir mesaj yaz (ornegin: merhaba)"
echo
read -r -p "  Bunu yaptiktan sonra ENTER'a bas..." _

UPD_RAW="$(api getUpdates)"
UPD="${UPD_RAW%|*}"
IDS="$(printf '%s' "$UPD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
seen = []
for u in d.get("result", []):
    for k in ("message", "edited_message", "channel_post", "my_chat_member"):
        c = u.get(k, {}).get("chat")
        if c and c.get("id") not in [s[0] for s in seen]:
            seen.append((c["id"], c.get("first_name") or c.get("title") or ""))
for i, n in seen:
    print(f"{i}\t{n}")
')"

if [ -z "$IDS" ]; then
    bad "Hic mesaj bulunamadi."
    echo
    echo "  Muhtemel sebepler:"
    echo "    - Bota henuz mesaj yazmadin"
    echo "    - Yanlis botu araddin (dogrusu: @${BOT_NAME})"
    echo
    echo "  Bota mesaj yazip bu script'i tekrar calistir."
    [ -n "${RESTART:-}" ] && docker compose start >/dev/null 2>&1
    exit 1
fi

echo
ok "Bulunan sohbet(ler):"
printf '%s\n' "$IDS" | while IFS=$'\t' read -r id name; do
    echo "      $id   $name"
done

NEW_ID="$(printf '%s' "$IDS" | head -1 | cut -f1)"
CUR_ID="${TELEGRAM_CHAT_ID:-}"

echo
if [ "$NEW_ID" = "$CUR_ID" ]; then
    ok "Chat ID zaten dogru ($NEW_ID) — sorun baska yerde."
else
    warn ".env icindeki ID yanlis:"
    echo "      mevcut: ${CUR_ID:-<bos>}"
    echo "      dogru : ${NEW_ID}"
    set_env TELEGRAM_CHAT_ID "$NEW_ID"
    ok ".env guncellendi"
fi

echo
bold "4/4  Test mesaji"
SEND="$(curl -sS --max-time 15 \
    --data-urlencode "chat_id=${NEW_ID}" \
    --data-urlencode "text=tradedair baglantisi calisiyor. Bot birazdan baslayacak." \
    "https://api.telegram.org/bot${TOKEN}/sendMessage")"

if printf '%s' "$SEND" | grep -q '"ok":true'; then
    ok "Test mesaji gonderildi — Telegram'i kontrol et!"
else
    bad "Mesaj gonderilemedi: $SEND"
fi

echo
bold "Bot yeniden baslatiliyor"
docker compose up -d --force-recreate >/dev/null 2>&1
ok "Basladi"
echo
echo "  Birkac saniye icinde Telegram'a 'bot basladi' mesaji gelmeli."
echo "  Gelmezse:  docker compose logs --tail 30 | grep -i telegram"
echo
