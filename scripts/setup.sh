#!/usr/bin/env bash
#
# tradedair — tek seferlik kurulum.
#
# Kullanım:  ./scripts/setup.sh
#
# Docker'ı kurar (yoksa), gizli anahtarları üretir, .env dosyasını hazırlar
# ve botu test modunda başlatır. Sana sadece iki şey sorar:
# Telegram token'ı ve chat ID.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }

echo
bold "tradedair kurulumu"
echo "Dizin: $ROOT"
echo

# ---------------------------------------------------------------- #
bold "1/5  Docker kontrolu"

if command -v docker >/dev/null 2>&1; then
    ok "Docker zaten kurulu ($(docker --version | cut -d, -f1))"
else
    warn "Docker bulunamadi, kuruluyor..."
    if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        die "Docker kurulumu icin root veya sudo yetkisi gerekli."
    fi
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
    ok "Docker kuruldu"
fi

if ! docker compose version >/dev/null 2>&1; then
    die "docker compose eklentisi bulunamadi. Docker'i guncelleyip tekrar dene."
fi
ok "docker compose calisiyor"

# ---------------------------------------------------------------- #
echo
bold "2/5  Telegram bilgileri"

if [ -f .env ]; then
    warn ".env dosyasi zaten var."
    read -r -p "  Ustune yazilsin mi? (e/H): " ow
    case "${ow,,}" in
        e|evet|y|yes) ;;
        *) echo "  Mevcut .env korunuyor, 3. adima geciliyor."; SKIP_ENV=1 ;;
    esac
fi

if [ -z "${SKIP_ENV:-}" ]; then
    echo
    echo "  Telegram'da @BotFather'a yaz -> /newbot -> sana bir token verir."
    echo "  Sonra @userinfobot'a bir mesaj at -> sana chat ID'ni soyler."
    echo
    read -r -p "  Telegram TOKEN : " TG_TOKEN
    read -r -p "  Telegram CHAT ID: " TG_CHAT

    [ -n "$TG_TOKEN" ] || die "Token bos birakilamaz."
    [ -n "$TG_CHAT" ]  || die "Chat ID bos birakilamaz."

    # FreqUI sifresi
    echo
    read -r -p "  FreqUI icin sifre (bos birak = otomatik uret): " UI_PASS
    if [ -z "$UI_PASS" ]; then
        UI_PASS="$(openssl rand -base64 18)"
        AUTO_PASS=1
    fi

    JWT="$(openssl rand -hex 32)"
    WST="$(openssl rand -hex 32)"

    cat > .env <<EOF
# tradedair — otomatik olusturuldu $(date -u '+%Y-%m-%d %H:%M UTC')

TELEGRAM_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}

FREQUI_USERNAME=tradedair
FREQUI_PASSWORD=${UI_PASS}
FREQUI_JWT_SECRET=${JWT}
FREQUI_WS_TOKEN=${WST}

# Lovable arayuzu kullanacaksan doldur (docs/LOVABLE.md)
API_DOMAIN=

# CANLIYA GECERKEN doldurulur. Test modunda bos kalir.
# Anahtari olustururken "Withdraw" yetkisini ASLA verme.
BYBIT_API_KEY=
BYBIT_API_SECRET=
EOF

    chmod 600 .env
    ok ".env olusturuldu (izinler 600)"
    if [ -n "${AUTO_PASS:-}" ]; then
        echo
        bold "  FreqUI giris bilgilerin:"
        echo "    kullanici: tradedair"
        echo "    sifre    : ${UI_PASS}"
        warn "Bu sifreyi simdi bir yere kaydet!"
    fi
fi

# ---------------------------------------------------------------- #
echo
bold "3/5  Dizinler ve takas alani"
mkdir -p user_data/logs user_data/data
ok "user_data/logs ve user_data/data hazir"

# Kucuk sunucularda (1 GB RAM) backtest bellek sikistirir.
# Takas alani yoksa ve RAM 2 GB'in altindaysa 2 GB swap ekle.
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 9999)
SWAP_MB=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)

if [ "$RAM_MB" -lt 2048 ] && [ "$SWAP_MB" -lt 512 ]; then
    warn "RAM ${RAM_MB} MB ve takas alani yok — 2 GB swap olusturuluyor..."
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile 2>/dev/null || true
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "2 GB takas alani aktif (yeniden baslatmada da kalici)"
else
    ok "Bellek yeterli (RAM ${RAM_MB} MB, swap ${SWAP_MB} MB)"
fi

# ---------------------------------------------------------------- #
echo
bold "4/5  Freqtrade imaji"
docker compose pull freqtrade
ok "Imaj indirildi"

# ---------------------------------------------------------------- #
echo
bold "5/5  Backtest"
echo
read -r -p "  Gecmis veriyi indirip backtest calistirilsin mi? (E/h): " bt
case "${bt,,}" in
    h|hayir|n|no)
        warn "Backtest atlandi. Sonra calistirmak icin: ./scripts/backtest.sh"
        ;;
    *)
        echo
        echo "  Veri indiriliyor (birkac dakika surebilir)..."
        ./scripts/backtest.sh || warn "Backtest basarisiz oldu, kuruluma devam ediliyor."
        ;;
esac

# ---------------------------------------------------------------- #
echo
bold "Kurulum tamam."
echo
echo "  Botu TEST MODUNDA baslatmak icin:"
echo "      docker compose up -d"
echo
echo "  Sonra Telegram'a 'bot basladi' mesaji gelecek."
echo "  Oradan /status ve /profit komutlarini kullanabilirsin."
echo
echo "  FreqUI:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo
