"""
Strateji mantığı doğrulama harness'ı (ağ erişimi gerektirmez).

İki şeyi test eder:
  1. Sinyaller üretiliyor mu, ve üretilen sinyaller kuralların gerektirdiği
     özellikleri (yol açıklığı, R/R, stop yönü) taşıyor mu?
  2. GELECEĞE BAKMA VAR MI — en kritik test. Veriyi t barında kesip yeniden
     hesaplarsak, t'deki sinyal aynı çıkıyor mu? Çıkmıyorsa strateji
     geleceği görüyordur ve backtest sonuçları yalandır.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/tradedair/user_data/strategies")

from freqtrade.enums import RunMode  # noqa: E402
from SupportResistanceBreakRetest import SupportResistanceBreakRetest  # noqa: E402

DATA = Path("/home/user/tradedair/user_data/data/bybit/futures")

CONFIG = {
    "stake_currency": "USDT",
    "stake_amount": 100,
    "runmode": RunMode.BACKTEST,
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "timeframe": "1h",
    "exchange": {"name": "bybit"},
}


def load(pair: str) -> pd.DataFrame:
    return pd.read_feather(DATA / f"{pair}-1h-futures.feather")


def analyse(strat, df: pd.DataFrame) -> pd.DataFrame:
    d = strat.populate_indicators(df.copy(), {"pair": "TEST/USDT:USDT"})
    d = strat.populate_entry_trend(d, {"pair": "TEST/USDT:USDT"})
    return d


def main() -> int:
    strat = SupportResistanceBreakRetest(CONFIG)
    pairs = ["BTC_USDT_USDT", "ETH_USDT_USDT", "SOL_USDT_USDT",
             "BNB_USDT_USDT", "XRP_USDT_USDT"]

    print("=" * 68)
    print("1) SİNYAL ÜRETİMİ")
    print("=" * 68)

    total_l = total_s = 0
    all_rooms, all_rrs = [], []
    frames = {}

    for p in pairs:
        df = load(p)
        d = analyse(strat, df)
        frames[p] = d

        longs = int(d["enter_long"].fillna(0).sum()) if "enter_long" in d else 0
        shorts = int(d["enter_short"].fillna(0).sum()) if "enter_short" in d else 0
        total_l += longs
        total_s += shorts

        sig = d[d["sig_long"] | d["sig_short"]]
        rooms = sig["sr_room"].dropna()
        rrs = sig["sr_rr"].dropna()
        all_rooms.extend(rooms.tolist())
        all_rrs.extend(rrs.tolist())

        print(f"  {p:16s} long={longs:4d}  short={shorts:4d}  "
              f"ort.yol={rooms.mean():5.2f}%  ort.R/R={rrs.mean():4.2f}"
              if len(rooms) else
              f"  {p:16s} long={longs:4d}  short={shorts:4d}  (sinyal yok)")

    print(f"\n  TOPLAM: {total_l} long, {total_s} short  "
          f"({total_l + total_s} sinyal / {len(pairs) * 14592} mum)")
    if all_rooms:
        print(f"  Yol açıklığı: min={min(all_rooms):.2f}%  "
              f"medyan={np.median(all_rooms):.2f}%  max={max(all_rooms):.2f}%")
        print(f"  Risk/Ödül   : min={min(all_rrs):.2f}  "
              f"medyan={np.median(all_rrs):.2f}  max={max(all_rrs):.2f}")

    # ---------------- Kural doğrulaması ---------------- #
    print("\n" + "=" * 68)
    print("2) KURAL DOĞRULAMASI")
    print("=" * 68)

    min_room = float(strat.min_room_pct.value)
    min_rr = float(strat.min_rr.value)
    ok = True

    for p, d in frames.items():
        sig = d[d["sig_long"] | d["sig_short"]]
        if sig.empty:
            continue

        if (sig["sr_room"] < min_room - 1e-9).any():
            print(f"  ✗ {p}: min yol açıklığı ihlali")
            ok = False
        if (sig["sr_rr"] < min_rr - 1e-9).any():
            print(f"  ✗ {p}: min R/R ihlali")
            ok = False

        s = sig[sig["sig_short"]]
        if not s.empty:
            if not (s["sr_stop"] > s["close"]).all():
                print(f"  ✗ {p}: SHORT stop'u fiyatın altında kalmış")
                ok = False
            if not (s["sr_target"] < s["close"]).all():
                print(f"  ✗ {p}: SHORT hedefi fiyatın üstünde")
                ok = False
            if not (s["close"] < s["sr_broken"]).all():
                print(f"  ✗ {p}: SHORT girişi kırılan desteğin üstünde kapatmış")
                ok = False

        lg = sig[sig["sig_long"]]
        if not lg.empty:
            if not (lg["sr_stop"] < lg["close"]).all():
                print(f"  ✗ {p}: LONG stop'u fiyatın üstünde kalmış")
                ok = False
            if not (lg["sr_target"] > lg["close"]).all():
                print(f"  ✗ {p}: LONG hedefi fiyatın altında")
                ok = False
            if not (lg["close"] > lg["sr_broken"]).all():
                print(f"  ✗ {p}: LONG girişi kırılan direncin altında kapatmış")
                ok = False

    if ok:
        print("  ✓ Tüm sinyaller kurallara uyuyor:")
        print(f"    - yol açıklığı >= %{min_room}")
        print(f"    - risk/ödül >= {min_rr}")
        print("    - SHORT: stop kırılan desteğin üstünde, hedef altında")
        print("    - LONG : stop kırılan direncin altında, hedef üstünde")

    # ---------------- Geleceğe bakma testi ---------------- #
    print("\n" + "=" * 68)
    print("3) GELECEĞE BAKMA (LOOKAHEAD) TESTİ")
    print("=" * 68)
    print("  Veri t barında kesilip yeniden hesaplanıyor; sinyal değişmemeli.")

    df = load("BTC_USDT_USDT")
    full = frames["BTC_USDT_USDT"]
    sig_idx = full.index[(full["sig_long"] | full["sig_short"])].tolist()

    rng = np.random.default_rng(42)
    if len(sig_idx) > 25:
        sample = sorted(rng.choice(sig_idx, 25, replace=False).tolist())
    else:
        sample = sig_idx

    # Sinyalsiz barlardan da örnek al (yanlış pozitif üretmemeli)
    nosig = [i for i in range(2000, len(full)) if i not in set(sig_idx)]
    sample += sorted(rng.choice(nosig, 15, replace=False).tolist())

    mismatches = 0
    checked = 0
    for t in sample:
        truncated = df.iloc[: t + 1].copy().reset_index(drop=True)
        d2 = analyse(strat, truncated)
        last = d2.iloc[-1]
        exp = full.iloc[t]

        same_long = bool(last["sig_long"]) == bool(exp["sig_long"])
        same_short = bool(last["sig_short"]) == bool(exp["sig_short"])
        checked += 1
        if not (same_long and same_short):
            mismatches += 1
            if mismatches <= 5:
                print(f"    ✗ bar {t} ({exp['date']}): "
                      f"tam veri L={bool(exp['sig_long'])}/S={bool(exp['sig_short'])} "
                      f"vs kesik L={bool(last['sig_long'])}/S={bool(last['sig_short'])}")

    print(f"\n  {checked} bar kontrol edildi, {mismatches} uyuşmazlık.")
    if mismatches == 0:
        print("  ✓ GELECEĞE BAKMA YOK — strateji sadece geçmiş veriyi kullanıyor.")
    else:
        print("  ✗ GELECEĞE BAKMA TESPİT EDİLDİ — backtest sonuçlarına güvenilmez!")
        ok = False

    print()
    return 0 if (ok and mismatches == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
