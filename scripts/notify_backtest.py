#!/usr/bin/env python3
"""
En son backtest sonucunu Telegram'a gonderir.

Kullanim:
    python3 scripts/notify_backtest.py

.env icindeki TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID kullanilir.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "user_data" / "backtest_results"


def load_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # Ortam degiskeni dosyayi ezer
    for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def latest_result() -> dict | None:
    """En son backtest ciktisini okur (.zip ya da .json)."""
    if not RESULTS.exists():
        return None

    cands = sorted(
        [p for p in RESULTS.iterdir()
         if p.suffix in (".zip", ".json") and "config" not in p.name
         and p.name != ".last_result.json"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for p in cands:
        try:
            if p.suffix == ".zip":
                with zipfile.ZipFile(p) as z:
                    name = next((n for n in z.namelist()
                                 if n.endswith(".json") and "config" not in n), None)
                    if not name:
                        continue
                    data = json.loads(z.read(name))
            else:
                data = json.loads(p.read_text())

            if "strategy" in data:
                return data
        except Exception:
            continue
    return None


def fmt(data: dict) -> str:
    name, res = next(iter(data["strategy"].items()))

    def g(*keys, default=0):
        for k in keys:
            if k in res:
                return res[k]
        return default

    trades = g("total_trades")
    wins = g("wins")
    losses = g("losses")
    profit_abs = g("profit_total_abs")
    profit_pct = g("profit_total") * 100
    dd = g("max_drawdown_account", "max_drawdown") * 100
    sharpe = g("sharpe")
    win_rate = (wins / trades * 100) if trades else 0
    duration = g("holding_avg", default="")

    verdict = "KARLI" if profit_abs > 0 else "ZARARDA"
    icon = "\U0001F7E2" if profit_abs > 0 else "\U0001F534"

    lines = [
        f"{icon} <b>Backtest sonucu — {verdict}</b>",
        "",
        f"<b>Strateji:</b> {name}",
        f"<b>Donem:</b> {g('backtest_start', default='?')} → {g('backtest_end', default='?')}",
        "",
        f"<b>Islem:</b> {trades}",
        f"<b>Kazanma orani:</b> %{win_rate:.1f}  ({wins}K / {losses}Z)",
        f"<b>Toplam:</b> {profit_abs:+.2f} USDT  (%{profit_pct:+.2f})",
        f"<b>Maks. dusus:</b> %{dd:.2f}",
        f"<b>Sharpe:</b> {sharpe:.2f}",
    ]
    if duration:
        lines.append(f"<b>Ort. sure:</b> {duration}")

    # Basabas icin gereken ortalama kazanc
    if 0 < win_rate < 100:
        need = (100 - win_rate) / win_rate
        lines += ["", f"<i>Bu kazanma oraninda basabas icin ortalama "
                      f"{need:.2f}R kazanc gerekir.</i>"]

    return "\n".join(lines)


def send(token: str, chat_id: str, text: str) -> bool:
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=body, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"  Telegram'a gonderilemedi: {e}", file=sys.stderr)
        return False


def main() -> int:
    env = load_env()
    token = env.get("TELEGRAM_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat:
        print("  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID yok — rapor gonderilmedi.")
        return 0  # backtest'i basarisiz saymayalim

    data = latest_result()
    if data is None:
        print("  Backtest sonucu bulunamadi.", file=sys.stderr)
        return 1

    text = fmt(data)
    print()
    print(text.replace("<b>", "").replace("</b>", "")
              .replace("<i>", "").replace("</i>", ""))
    print()

    if send(token, chat, text):
        print("  Rapor Telegram'a gonderildi.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
