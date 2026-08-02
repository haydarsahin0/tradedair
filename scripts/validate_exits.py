"""
Takip eden stop ve kısmi kâr alma mantığının doğrulaması.

Sahte bir işlem hayat döngüsü kurar ve şunları kontrol eder:
  1. Stop başlangıçta yapısal seviyede mi (kırılan seviyenin arkasında)
  2. 1R lehimize hareket olunca başabaşa çekiliyor mu
  3. 1.5R sonrası en iyi fiyatı takip ediyor mu
  4. Stop hiç gevşiyor mu (ASLA gevşememeli)
  5. Fiyat geri gelince stop yerinde kalıyor mu
  6. Kısmi kâr alma doğru noktada ve yalnızca bir kez tetikleniyor mu

Ağ erişimi gerektirmez.
"""
import sys

sys.path.insert(0, "/home/user/tradedair/user_data/strategies")

from datetime import datetime, timezone  # noqa: E402

from freqtrade.enums import RunMode  # noqa: E402
from freqtrade.strategy import stoploss_from_absolute  # noqa: E402

from SupportResistanceBreakRetest import SupportResistanceBreakRetest  # noqa: E402

CFG = {
    "stake_currency": "USDT",
    "stake_amount": 100,
    "runmode": RunMode.BACKTEST,
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "timeframe": "1h",
    "exchange": {"name": "bybit"},
}

NOW = datetime.now(timezone.utc)


class FakeTrade:
    """custom_stoploss / adjust_trade_position için minimum Trade taklidi."""

    def __init__(self, pair, open_rate, is_short, stop, target, leverage=3.0):
        self.pair = pair
        self.open_rate = open_rate
        self.is_short = is_short
        self.leverage = leverage
        self.stake_amount = 100.0
        self.max_rate = open_rate
        self.min_rate = open_rate
        self._data = {"sr_stop": stop, "sr_target": target}

    def get_custom_data(self, key, default=None):
        return self._data.get(key, default)

    def set_custom_data(self, key, value):
        self._data[key] = value

    def observe(self, rate):
        self.max_rate = max(self.max_rate, rate)
        self.min_rate = min(self.min_rate, rate)


def stop_price(strat, trade, rate):
    """
    custom_stoploss'un döndürdüğü oranı tekrar stop fiyatına çevirir.

    stoploss_from_absolute:  ratio = (1 - stop/current) * leverage   (long)
                             ratio = (stop/current - 1) * leverage   (short)
    Dolayısıyla tersi:       stop  = current * (1 -+ ratio/leverage)
    """
    ratio = strat.custom_stoploss(trade.pair, trade, NOW, rate, 0.0, False)
    if ratio is None:
        return None
    d = ratio / trade.leverage
    return rate * (1 + d) if trade.is_short else rate * (1 - d)


def run_case(name, is_short):
    print(f"\n{'=' * 66}\n{name}\n{'=' * 66}")
    strat = SupportResistanceBreakRetest(CFG)

    entry = 100.0
    if is_short:
        struct_stop = 102.0      # kırılan desteğin üstünde
        target = 90.0
    else:
        struct_stop = 98.0       # kırılan direncin altında
        target = 110.0

    risk = abs(entry - struct_stop) / entry          # 1R = %2
    trade = FakeTrade("BTC/USDT:USDT", entry, is_short, struct_stop, target)

    # Fiyatın lehimize kademeli ilerlemesi (R cinsinden), sonra geri çekilme
    path_r = [0.0, 0.5, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 3.0, 2.0]

    print(f"  giris={entry}  yapisal stop={struct_stop}  hedef={target}  1R=%{risk*100:.1f}")
    print(f"\n  {'hareket':>8} {'fiyat':>9} {'stop':>9}  durum")
    print(f"  {'-'*8} {'-'*9} {'-'*9}  {'-'*28}")

    ok = True
    be_seen = False
    trail_seen = False
    active_stop = None      # freqtrade gibi: her zaman en sıkı stop tutulur
    exit_price = None

    def tighter(a, b):
        if a is None:
            return b
        return min(a, b) if is_short else max(a, b)

    for r in path_r:
        rate = entry * (1 - r * risk) if is_short else entry * (1 + r * risk)

        # Önce: mevcut stop bu fiyatta tetiklendi mi?
        if active_stop is not None:
            breached = (rate >= active_stop) if is_short else (rate <= active_stop)
            if breached:
                exit_price = active_stop
                print(f"  {r:7.1f}R {rate:9.3f} {active_stop:9.3f}  >>> STOP TETIKLENDI")
                break

        trade.observe(rate)
        desired = stop_price(strat, trade, rate)

        new_active = tighter(active_stop, desired)
        # Sıkılaştırma dışında hareket olmamalı
        if active_stop is not None and abs(new_active - desired) > 1e-6:
            loosened = (desired > active_stop) if is_short else (desired < active_stop)
            if loosened:
                print(f"  ✗ STOP GEVSEDI: {active_stop:.3f} -> {desired:.3f}")
                ok = False
        active_stop = new_active

        if is_short:
            at_be = active_stop <= entry + 1e-6
            locked = active_stop < entry - 1e-6
        else:
            at_be = active_stop >= entry - 1e-6
            locked = active_stop > entry + 1e-6

        if r >= 1.0 and not at_be:
            print(f"  ✗ {r:.1f}R'de stop hala basabasin gerisinde")
            ok = False
        if r >= 1.0:
            be_seen = True
        if r >= 1.5 and locked:
            trail_seen = True

        label = "yapisal stop"
        if locked:
            label = "KAR KILITLI (takip ediyor)"
        elif at_be:
            label = "basabas — artik zarar edemez"

        print(f"  {r:7.1f}R {rate:9.3f} {active_stop:9.3f}  {label}")

    if not be_seen:
        print("  ✗ basabas kademesi hic tetiklenmedi")
        ok = False
    if not trail_seen:
        print("  ✗ takip kademesi hic kar kilitlemedi")
        ok = False

    if exit_price is None:
        print("  ✗ fiyat geri cekilmesine ragmen stop tetiklenmedi")
        ok = False
    else:
        pnl = (entry - exit_price) / entry if is_short else (exit_price - entry) / entry
        print(f"\n  Fiyat 4R'ye kadar gitti, geri cekilince {exit_price:.3f}'te cikildi.")
        print(f"  -> Fiyat bazinda kar: %{pnl*100:.2f}"
              f"   |  3x kaldiracla hesapta: %{pnl*100*3:.2f}")
        if pnl <= 0:
            print("  ✗ takip eden stop kari koruyamadi")
            ok = False

    # ---- Kısmi kâr alma ----
    print("\n  Kismi kar alma:")
    t2 = FakeTrade("BTC/USDT:USDT", entry, is_short, struct_stop, target)
    fired = []
    for frac in [0.2, 0.4, 0.49, 0.5, 0.6, 0.8]:
        rate = (entry - frac * abs(target - entry)) if is_short \
            else (entry + frac * abs(target - entry))
        t2.observe(rate)
        res = strat.adjust_trade_position(
            t2, NOW, rate, 0.0, 10.0, 1000.0, rate, rate, 0.0, 0.0
        )
        if res is not None:
            fired.append((frac, res))

    if len(fired) == 1 and abs(fired[0][0] - 0.5) < 1e-9:
        print(f"    ✓ yolun %50'sinde bir kez tetiklendi, {-fired[0][1]:.0f} USDT kapatildi")
    elif len(fired) == 0:
        print("    ✗ hic tetiklenmedi")
        ok = False
    else:
        print(f"    ✗ beklenmeyen tetikleme: {fired}")
        ok = False

    return ok


def main():
    a = run_case("LONG  — direnc kirilimi sonrasi", is_short=False)
    b = run_case("SHORT — destek kirilimi sonrasi", is_short=True)

    print(f"\n{'=' * 66}")
    if a and b:
        print("✓ TUM CIKIS TESTLERI GECTI")
        print("  - stop hicbir zaman gevsemedi")
        print("  - 1R'de basabasa cekildi")
        print("  - 1.5R sonrasi kari kilitleyerek takip etti")
        print("  - kismi kar alma tam yolun yarisinda, tek sefer calisti")
        return 0
    print("✗ BAZI TESTLER BASARISIZ")
    return 1


if __name__ == "__main__":
    sys.exit(main())
