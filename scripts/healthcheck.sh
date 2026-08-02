#!/usr/bin/env bash
#
# 7/24 calisma kontrolu.
#
# Botun sen bakmadigin zamanlarda da ayakta kalmasi icin gereken her seyi
# tek tek dogrular ve eksik varsa duzeltmeyi soyler.
#
#   ./scripts/healthcheck.sh

set -uo pipefail
cd "$(dirname "$0")/.."

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; PROBLEMS=$((PROBLEMS+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

PROBLEMS=0

bold "1. Docker sunucu acilisinda kendiliginden basliyor mu?"
if systemctl is-enabled docker >/dev/null 2>&1; then
    ok "Docker acilista otomatik basliyor"
else
    bad "Docker acilista baslamiyor — sunucu yeniden baslarsa bot kalkmaz"
    echo "      Duzelt:  systemctl enable docker"
fi

bold "2. Bot calisiyor mu?"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx tradedair; then
    UP="$(docker inspect -f '{{.State.StartedAt}}' tradedair 2>/dev/null | cut -dT -f1,2 | tr T ' ' | cut -d. -f1)"
    ok "Calisiyor (baslangic: ${UP} UTC)"
else
    bad "Bot CALISMIYOR"
    echo "      Duzelt:  docker compose up -d"
fi

bold "3. Cokerse / sunucu yeniden baslarsa kendini toparlar mi?"
POL="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' tradedair 2>/dev/null || echo yok)"
if [ "$POL" = "unless-stopped" ] || [ "$POL" = "always" ]; then
    ok "Yeniden baslatma politikasi: $POL"
else
    bad "Yeniden baslatma politikasi yok ($POL)"
    echo "      Duzelt:  docker compose up -d --force-recreate"
fi

RESTARTS="$(docker inspect -f '{{.RestartCount}}' tradedair 2>/dev/null || echo 0)"
if [ "${RESTARTS:-0}" -gt 5 ]; then
    warn "Bot ${RESTARTS} kez yeniden baslamis — surekli cokuyor olabilir"
    echo "      Bak:  docker compose logs --tail 50"
else
    ok "Yeniden baslatma sayisi normal (${RESTARTS})"
fi

bold "4. Disk"
USE="$(df -P / | awk 'NR==2 {print $5}' | tr -d '%')"
AVAIL="$(df -Ph / | awk 'NR==2 {print $4}')"
if [ "${USE:-0}" -lt 85 ]; then
    ok "Disk %${USE} dolu, ${AVAIL} bos"
else
    bad "Disk %${USE} dolu — dolarsa bot durur"
    echo "      Duzelt:  docker system prune -af"
fi

bold "5. Bellek"
SWAP="$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)"
RAM="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
if [ "${SWAP:-0}" -ge 512 ] || [ "${RAM:-0}" -ge 2048 ]; then
    ok "RAM ${RAM} MB + takas ${SWAP} MB"
else
    bad "RAM ${RAM} MB, takas alani yok — bellek dolarsa bot oldurulur"
    echo "      Duzelt:  ./scripts/setup.sh (takas alanini kendisi kurar)"
fi

bold "6. Borsa baglantisi"
if docker compose logs --tail 300 2>/dev/null | grep -qi "Bybit"; then
    ok "Loglarda Bybit baglantisi goruluyor"
else
    warn "Son loglarda borsa aktivitesi yok"
fi

bold "7. Telegram"
if docker compose logs --tail 300 2>/dev/null | grep -qi "chat not found\|telegram.*error"; then
    bad "Telegram hatasi var — bildirim alamiyorsun"
    echo "      Duzelt:  ./scripts/telegram_fix.sh"
else
    ok "Telegram hatasi yok"
fi

bold "8. Stop emirleri borsada mi?"
if grep -q '"stoploss_on_exchange": True' user_data/strategies/*.py 2>/dev/null; then
    ok "Stop emirleri Bybit'te duruyor — sunucu cokse bile korumadasin"
else
    warn "Stop emirleri sadece botta tutuluyor"
fi

echo
if [ "$PROBLEMS" -eq 0 ]; then
    printf '\033[32m\033[1m  SISTEM 7/24 CALISMAYA HAZIR.\033[0m\n'
    echo "  Tabletini kapatabilirsin, bot calismaya devam eder."
else
    printf '\033[31m\033[1m  %d SORUN VAR — yukaridaki duzeltmeleri uygula.\033[0m\n' "$PROBLEMS"
fi
echo
