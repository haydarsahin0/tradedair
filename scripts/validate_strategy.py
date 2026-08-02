"""
CandleExpansion stratejisinin doğrulaması (ağ erişimi gerektirmez).

Kontrol edilenler:
  1. 4 saatlik mumlar 15 dakikalık veriden DOĞRU türetiliyor mu
     (bağımsız bir resample ile karşılaştırılır)
  2. Tetik fiyatı kurala uyuyor mu:  tetik = yeni_acilis * (1 + 1.4 * onceki_hareket)
  3. Girişler gerçekten fiyat tetiğe değdiğinde mi oluyor
  4. Yön doğru mu (önceki mum düşüşse SHORT, yükselişse LONG)
  5. Stop doğru yerde mi (önceki mumun açılışının %0.5 ötesi, doğru tarafta)
  6. Her 4 saatlik mumda en fazla BİR giriş var mı
  7. GELECEĞE BAKMA var mı — veri kesilip yeniden hesaplandığında
     sinyal değişiyor mu
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/tradedair/user_data/strategies")

from freqtrade.enums import RunMode  # noqa: E402

from CandleExpansion import CandleExpansion  # noqa: E402

DATA = Path("/home/user/tradedair/user_data/data/bybit/futures")

CFG = {
    "stake_currency": "USDT",
    "stake_amount": 100,
    "runmode": RunMode.BACKTEST,
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "timeframe": "15m",
    "exchange": {"name": "bybit"},
}


def load(pair: str) -> pd.DataFrame:
    return pd.read_feather(DATA / f"{pair}-15m-futures.feather")


def analyse(strat, df):
    d = strat.populate_indicators(df.copy(), {"pair": "TEST/USDT:USDT"})
    return strat.populate_entry_trend(d, {"pair": "TEST/USDT:USDT"})


def col(d, name):
    return d[name].fillna(0) if name in d else pd.Series(0, index=d.index)


def sig(row, name) -> float:
    """
    Tek bir satirdaki sinyal degeri.

    DIKKAT: sinyalsiz barlarda deger NaN'dir ve NaN == NaN her zaman False'tur.
    Ayrica `nan or 0` ifadesi 0 degil NaN dondurur (NaN "truthy"dir). Bu yuzden
    karsilastirmadan once NaN'i acikca 0'a cevirmek gerekir.
    """
    v = row.get(name)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if np.isnan(v) else v


def main() -> int:
    strat = CandleExpansion(CFG)
    mult = float(strat.expansion_mult.value)
    sb = float(strat.stop_beyond_open_pct.value) / 100.0
    tp = float(strat.take_profit_pct.value)
    lev = float(strat.leverage_num.value)

    pairs = ["BTC_USDT_USDT", "ETH_USDT_USDT", "SOL_USDT_USDT", "BNB_USDT_USDT"]
    ok = True
    frames = {}

    print("=" * 70)
    print("1) SINYAL URETIMI")
    print(f"   tetik={mult}x   stop=onceki acilis +-%{sb*100:.2f}   "
          f"TP=%{tp}   kaldirac={lev:.0f}x")
    print("=" * 70)

    tot_l = tot_s = 0
    for p in pairs:
        d = analyse(strat, load(p))
        frames[p] = d
        nl = int(col(d, "enter_long").sum())
        ns = int(col(d, "enter_short").sum())
        tot_l += nl
        tot_s += ns
        np_ = d["period"].nunique()
        print(f"  {p:16s} long={nl:4d}  short={ns:4d}   "
              f"({np_} adet 4s mumu, giris orani %{(nl+ns)/np_*100:.1f})")
    print(f"\n  TOPLAM: {tot_l} long, {tot_s} short")

    # ---------------- 4 saatlik mum türetimi ---------------- #
    print("\n" + "=" * 70)
    print("2) 4 SAATLIK MUM TURETIMI DOGRU MU")
    print("=" * 70)

    raw = load("BTC_USDT_USDT").set_index("date")
    ref = raw.resample("4h").agg({"open": "first", "close": "last"}).dropna()
    d = frames["BTC_USDT_USDT"]

    chk = d.dropna(subset=["prev_open", "prev_close"]).copy()
    exp_open = chk["period"].map(ref["open"].shift(1))
    exp_close = chk["period"].map(ref["close"].shift(1))
    do = (chk["prev_open"] - exp_open).abs().max()
    dc = (chk["prev_close"] - exp_close).abs().max()

    if do < 1e-6 and dc < 1e-6:
        print("  ✓ Onceki 4s mumunun acilis/kapanisi bagimsiz resample ile birebir ayni")
        print(f"    ({len(ref)} adet 4s mumu karsilastirildi)")
    else:
        print(f"  ✗ Uyusmazlik: acilis {do:.8f}, kapanis {dc:.8f}")
        ok = False

    # ---------------- Kural doğrulaması ---------------- #
    print("\n" + "=" * 70)
    print("3) KURAL DOGRULAMASI")
    print("=" * 70)

    for p, d in frames.items():
        e = d[(col(d, "enter_long") == 1) | (col(d, "enter_short") == 1)]
        if e.empty:
            continue

        want = e["cur_open"] * (1 + mult * e["prev_move"])
        if (want - e["trigger"]).abs().max() > 1e-6:
            print(f"  ✗ {p}: tetik fiyati formule uymuyor")
            ok = False

        s = e[col(e, "enter_short") == 1]
        if not s.empty:
            if not (s["prev_move"] < 0).all():
                print(f"  ✗ {p}: SHORT girisi yukselen onceki mumda acilmis")
                ok = False
            if not (s["low"] <= s["trigger"] + 1e-9).all():
                print(f"  ✗ {p}: SHORT fiyat tetige degmeden acilmis")
                ok = False
            if not (s["stop_short"] > s["trigger"]).all():
                print(f"  ✗ {p}: SHORT stop'u girisin altinda kalmis")
                ok = False
            if (s["stop_short"] - s["prev_open"] * (1 + sb)).abs().max() > 1e-6:
                print(f"  ✗ {p}: SHORT stop'u onceki acilisin %{sb*100} otesinde degil")
                ok = False

        lg = e[col(e, "enter_long") == 1]
        if not lg.empty:
            if not (lg["prev_move"] > 0).all():
                print(f"  ✗ {p}: LONG girisi dusen onceki mumda acilmis")
                ok = False
            if not (lg["high"] >= lg["trigger"] - 1e-9).all():
                print(f"  ✗ {p}: LONG fiyat tetige degmeden acilmis")
                ok = False
            if not (lg["stop_long"] < lg["trigger"]).all():
                print(f"  ✗ {p}: LONG stop'u girisin ustunde kalmis")
                ok = False
            if (lg["stop_long"] - lg["prev_open"] * (1 - sb)).abs().max() > 1e-6:
                print(f"  ✗ {p}: LONG stop'u onceki acilisin %{sb*100} otesinde degil")
                ok = False

        per_counts = e.groupby("period").size()
        if (per_counts > 1).any():
            print(f"  ✗ {p}: {int((per_counts>1).sum())} mumda birden fazla giris")
            ok = False

    if ok:
        print("  ✓ Tetik fiyati formule birebir uyuyor")
        print("  ✓ Yon dogru: dusen onceki mumda SHORT, yukselende LONG")
        print("  ✓ Girisler fiyat tetige gercekten degdiginde olmus")
        print(f"  ✓ Stop tam olarak onceki mumun acilisinin %{sb*100} otesinde")
        print("  ✓ Stop dogru tarafta (SHORT'ta ustte, LONG'da altta)")
        print("  ✓ Her 4 saatlik mumda en fazla bir giris")

    # ---------------- Risk profili ---------------- #
    print("\n" + "=" * 70)
    print(f"4) RISK PROFILI ({lev:.0f}x kaldiracla)")
    print("=" * 70)

    dists = []
    for p, d in frames.items():
        e = d[(col(d, "enter_long") == 1) | (col(d, "enter_short") == 1)]
        for _, r in e.iterrows():
            if r.get("enter_short", 0) == 1:
                dists.append((r["stop_short"] - r["trigger"]) / r["trigger"] * 100)
            else:
                dists.append((r["trigger"] - r["stop_long"]) / r["trigger"] * 100)

    if dists:
        a = np.array(dists)
        med = float(np.median(a))
        print(f"  Stop mesafesi (fiyat) : medyan %{med:.2f}   "
              f"min %{a.min():.2f}   max %{a.max():.2f}")
        print(f"  Hesaptaki kayip       : medyan %{med*lev:.1f}   max %{a.max()*lev:.1f}")
        print(f"  Kar hedefi            : %{tp} fiyat  =  hesapta %{tp*lev:.0f}")
        print(f"  Risk/Odul (medyan)    : {tp/med:.2f}")
        print(f"  Basabas icin gereken kazanma orani: %{100/(1+tp/med):.1f}")

    # ---------------- Geleceğe bakma ---------------- #
    print("\n" + "=" * 70)
    print("5) GELECEGE BAKMA (LOOKAHEAD) TESTI")
    print("=" * 70)

    df = load("BTC_USDT_USDT")
    full = frames["BTC_USDT_USDT"]
    sig_idx = full.index[(col(full, "enter_long") == 1)
                         | (col(full, "enter_short") == 1)].tolist()

    rng = np.random.default_rng(42)
    sample = sorted(rng.choice(sig_idx, min(20, len(sig_idx)), replace=False).tolist())
    nosig = [i for i in range(500, len(full)) if i not in set(sig_idx)]
    sample += sorted(rng.choice(nosig, 15, replace=False).tolist())

    mism = 0
    for t in sample:
        d2 = analyse(strat, df.iloc[: t + 1].copy().reset_index(drop=True))
        last = d2.iloc[-1]
        exp = full.iloc[t]
        same_l = sig(last, "enter_long") == sig(exp, "enter_long")
        same_s = sig(last, "enter_short") == sig(exp, "enter_short")
        if not (same_l and same_s):
            mism += 1
            if mism <= 5:
                print(f"    ✗ bar {t} ({exp['date']}) uyusmadi")

    print(f"\n  {len(sample)} bar kontrol edildi, {mism} uyusmazlik.")
    if mism == 0:
        print("  ✓ GELECEGE BAKMA YOK — strateji sadece gecmis veriyi kullaniyor")
    else:
        print("  ✗ GELECEGE BAKMA TESPIT EDILDI")
        ok = False

    print()
    return 0 if (ok and mism == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
