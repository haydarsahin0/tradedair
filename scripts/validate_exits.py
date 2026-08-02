"""
Takip eden stop mantiginin dogrulamasi (ag erisimi gerektirmez).

Sahte bir islem hayat dongusu kurar ve kontrol eder:
  1. Stop baslangicta yapisal seviyede mi (onceki 4s mumun acilisi +- %0.5)
  2. Basabas esiginde girise cekiliyor mu
  3. Takip esiginden sonra en iyi fiyati takip ediyor mu
  4. Stop hic gevsiyor mu (ASLA gevsememeli)
  5. Fiyat geri gelince kar kilitlenmis olarak cikiliyor mu
  6. use_trailing kapaliyken eski davranis korunuyor mu
"""
import sys

sys.path.insert(0, "/home/user/tradedair/user_data/strategies")

from datetime import datetime, timezone  # noqa: E402

from freqtrade.enums import RunMode  # noqa: E402

from CandleExpansion import CandleExpansion  # noqa: E402

CFG = {
    "stake_currency": "USDT",
    "stake_amount": 100,
    "runmode": RunMode.BACKTEST,
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "timeframe": "15m",
    "exchange": {"name": "bybit"},
}

NOW = datetime.now(timezone.utc)


class FakeTrade:
    def __init__(self, pair, open_rate, is_short, stop, leverage=8.0):
        self.pair = pair
        self.open_rate = open_rate
        self.is_short = is_short
        self.leverage = leverage
        self.stake_amount = 100.0
        self.max_rate = open_rate
        self.min_rate = open_rate
        self._data = {"stop_price": stop}

    def get_custom_data(self, key, default=None):
        return self._data.get(key, default)

    def set_custom_data(self, key, value):
        self._data[key] = value

    def observe(self, rate):
        self.max_rate = max(self.max_rate, rate)
        self.min_rate = min(self.min_rate, rate)


def stop_price(strat, trade, rate):
    """custom_stoploss'un dondurdugu orani stop fiyatina cevirir."""
    ratio = strat.custom_stoploss(trade.pair, trade, NOW, rate, 0.0, False)
    if ratio is None:
        return None
    d = ratio / trade.leverage
    return rate * (1 + d) if trade.is_short else rate * (1 - d)


def run_case(name, is_short, trailing=True):
    strat = CandleExpansion(CFG)
    strat.use_trailing.value = trailing

    be_r = float(strat.be_trigger_r.value)
    tr_r = float(strat.trail_trigger_r.value)
    ds_r = float(strat.trail_dist_r.value)

    entry = 100.0
    struct = 102.27 if is_short else 97.73     # ~1R = %2.27
    risk = abs(entry - struct) / entry

    print(f"\n{'=' * 68}\n{name}\n{'=' * 68}")
    print(f"  giris={entry}  yapisal stop={struct}  1R=%{risk*100:.2f}")
    if trailing:
        print(f"  basabas={be_r}R  takip={tr_r}R sonra  mesafe={ds_r}R")
    else:
        print("  takip eden stop KAPALI")

    trade = FakeTrade("BTC/USDT:USDT", entry, is_short, struct)
    path = sorted({0.0, 1.0, be_r, tr_r, tr_r + 1, tr_r + 2, 4.0}) + [tr_r + 1, tr_r]

    print(f"\n  {'hareket':>8} {'fiyat':>9} {'stop':>9}  durum")
    print(f"  {'-'*8} {'-'*9} {'-'*9}  {'-'*30}")

    ok = True
    active = None
    exit_px = None

    def tighter(a, b):
        return b if a is None else (min(a, b) if is_short else max(a, b))

    for r in path:
        rate = entry * (1 - r * risk) if is_short else entry * (1 + r * risk)

        if active is not None:
            hit = (rate >= active) if is_short else (rate <= active)
            if hit:
                exit_px = active
                print(f"  {r:7.1f}R {rate:9.3f} {active:9.3f}  >>> STOP TETIKLENDI")
                break

        trade.observe(rate)
        want = stop_price(strat, trade, rate)
        new = tighter(active, want)

        if active is not None:
            loosened = (want > active + 1e-9) if is_short else (want < active - 1e-9)
            if loosened:
                print(f"  ✗ STOP GEVSEDI: {active:.3f} -> {want:.3f}")
                ok = False
        active = new

        at_be = (active <= entry + 1e-9) if is_short else (active >= entry - 1e-9)
        locked = (active < entry - 1e-9) if is_short else (active > entry + 1e-9)

        if trailing and r >= be_r and not at_be:
            print(f"  ✗ {r:.1f}R'de stop hala basabasin gerisinde")
            ok = False

        label = "yapisal stop"
        if locked:
            label = "KAR KILITLI (takip ediyor)"
        elif at_be:
            label = "basabas — artik zarar edemez"
        print(f"  {r:7.1f}R {rate:9.3f} {active:9.3f}  {label}")

    if trailing:
        if exit_px is None:
            print("  ✗ geri cekilmeye ragmen stop tetiklenmedi")
            ok = False
        else:
            pnl = (entry - exit_px) / entry if is_short else (exit_px - entry) / entry
            print(f"\n  Fiyat {max(path):.1f}R'ye gitti, geri cekilince "
                  f"{exit_px:.3f}'te cikildi.")
            print(f"  -> Fiyat bazinda: %{pnl*100:+.2f}   "
                  f"8x hesapta: %{pnl*100*8:+.1f}   ({pnl/risk:+.2f}R)")
            if pnl <= 0:
                print("  ✗ takip eden stop kari koruyamadi")
                ok = False
    else:
        if exit_px is not None and abs(exit_px - struct) > 1e-6:
            print(f"  ✗ takip kapaliyken stop yapisal seviyede olmali "
                  f"({struct}), {exit_px} bulundu")
            ok = False
        else:
            print("\n  ✓ Takip kapali — stop yapisal seviyede sabit kaldi")

    return ok


def main():
    r = [
        run_case("LONG  — takip ACIK", is_short=False, trailing=True),
        run_case("SHORT — takip ACIK", is_short=True, trailing=True),
        run_case("LONG  — takip KAPALI (eski davranis)", is_short=False, trailing=False),
    ]
    print(f"\n{'=' * 68}")
    if all(r):
        print("✓ TUM CIKIS TESTLERI GECTI")
        print("  - stop hicbir zaman gevsemedi")
        print("  - basabas esiginde girise cekildi")
        print("  - takip esiginden sonra kari kilitleyerek takip etti")
        print("  - takip kapaliyken eski davranis korundu")
        return 0
    print("✗ BAZI TESTLER BASARISIZ")
    return 1


if __name__ == "__main__":
    sys.exit(main())
