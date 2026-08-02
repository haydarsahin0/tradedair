"""
Sentetik OHLCV üretici — sadece strateji mantığını doğrulamak için.
Gerçek piyasa verisi DEĞİL, performans rakamı olarak yorumlanamaz.

Rejim değiştiren (yatay <-> trend) bir süreç üretir, böylece doğal olarak
destek/direnç bölgeleri, kırılımlar ve retestler oluşur.
"""
import numpy as np
import pandas as pd
from pathlib import Path

OUT = Path("/home/user/tradedair/user_data/data/bybit/futures")
OUT.mkdir(parents=True, exist_ok=True)

PAIRS = {
    "BTC_USDT_USDT": 95000.0,
    "ETH_USDT_USDT": 3300.0,
    "SOL_USDT_USDT": 190.0,
    "BNB_USDT_USDT": 650.0,
    "XRP_USDT_USDT": 2.3,
}

START = pd.Timestamp("2025-06-01", tz="UTC")
END = pd.Timestamp("2026-08-01", tz="UTC")
idx = pd.date_range(START, END, freq="15min", inclusive="left")
N = len(idx)


def make_series(seed: int, start_price: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Rejim: 0 = yatay (mean reverting), 1 = trend
    regime = np.zeros(N, dtype=int)
    drift = np.zeros(N)
    t = 0
    while t < N:
        length = int(rng.integers(480, 2400))
        is_trend = rng.random() < 0.40
        d = rng.normal(0, 0.0005) if is_trend else 0.0
        regime[t:t + length] = 1 if is_trend else 0
        drift[t:t + length] = d
        t += length

    vol = 0.0022
    logp = np.zeros(N)
    logp[0] = np.log(start_price)
    anchor = logp[0]

    for i in range(1, N):
        shock = rng.normal(0, vol)
        if regime[i] == 0:
            # yatay: çapaya geri çekilir -> net destek/direnç oluşur
            pull = -0.01 * (logp[i - 1] - anchor)
            logp[i] = logp[i - 1] + pull + shock
        else:
            logp[i] = logp[i - 1] + drift[i] + shock
            anchor = logp[i]

    close = np.exp(logp)
    open_ = np.concatenate([[close[0]], close[:-1]])

    wick = np.abs(rng.normal(0, vol * 0.7, N))
    high = np.maximum(open_, close) * (1 + wick)
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.7, N)))

    base_vol = rng.lognormal(6, 0.4, N)
    move = np.abs(close / open_ - 1)
    volume = base_vol * (1 + 30 * move)

    return pd.DataFrame(
        {
            "date": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


for seed, (pair, price) in enumerate(PAIRS.items()):
    df = make_series(seed + 7, price)
    df.to_feather(OUT / f"{pair}-15m-futures.feather", compression="lz4")

    # Funding rate (8 saatlik)
    f_idx = pd.date_range(START, END, freq="8h", inclusive="left")
    rng = np.random.default_rng(1000 + seed)
    rate = rng.normal(0.0001, 0.00008, len(f_idx))
    fdf = pd.DataFrame(
        {
            "date": f_idx,
            "open": rate, "high": rate, "low": rate, "close": rate,
            "volume": np.zeros(len(f_idx)),
        }
    )
    fdf.to_feather(OUT / f"{pair}-8h-funding_rate.feather", compression="lz4")

    # Mark price (8 saatlik) — close'dan örneklenir
    mark = df.set_index("date")["close"].reindex(f_idx, method="ffill").to_numpy()
    mdf = pd.DataFrame(
        {
            "date": f_idx,
            "open": mark, "high": mark, "low": mark, "close": mark,
            "volume": np.zeros(len(f_idx)),
        }
    )
    mdf.to_feather(OUT / f"{pair}-8h-mark.feather", compression="lz4")

    print(f"{pair}: {len(df)} mum, {df['close'].iloc[0]:.2f} -> {df['close'].iloc[-1]:.2f}")

print("\nYazildi:", OUT)
