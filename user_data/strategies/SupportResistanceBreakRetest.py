# pragma pylint: disable=missing-docstring, invalid-name, too-many-locals
"""
SupportResistanceBreakRetest
============================

Destek / direnç kırılımı + retest + "yol açıklığı" stratejisi.

Mantık (SHORT):
    1. Fiyat bir DESTEK seviyesini aşağı kırar (belirli bir marj kadar, hacim onayıyla).
    2. Fiyat kırılan desteğe geri döner (retest) — destek artık direnç görevi görür.
    3. O seviyeden reddedilir (tekrar altında kapatır).
    4. Bir SONRAKİ desteğe olan mesafe yeterince büyükse (% olarak) -> SHORT.

Mantık (LONG): tam tersi.
    1. Fiyat bir DİRENCİ yukarı kırar.
    2. Kırılan dirence geri döner (retest) — direnç artık destek.
    3. O seviyeden desteklenir (tekrar üstünde kapatır).
    4. Bir SONRAKİ dirence olan mesafe yeterince büyükse -> LONG.

Seviyeler, onaylanmış pivot (swing) noktalarının kümelenmesiyle bulunur.
Aynı bölgeye denk gelen pivotlar tek bir seviyede birleşir; bir seviyenin
"dokunuş sayısı" ne kadar fazlaysa o kadar güçlüdür.

Geleceğe bakma (lookahead) yoktur: bir pivot ancak sağındaki `pivot_right`
mum kapandıktan sonra onaylanır ve ancak o bardan itibaren kullanılır.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    stoploss_from_absolute,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Yardımcı fonksiyonlar (strateji sınıfından bağımsız, test edilebilir)
# --------------------------------------------------------------------------- #

def find_confirmed_pivots(
    high: np.ndarray, low: np.ndarray, left: int, right: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    Pivot (swing) tepe ve diplerini bulur ve bunları ONAYLANDIKLARI bara taşır.

    Bir pivot, sağındaki `right` mum kapanmadan bilinemez. Bu yüzden sonuç
    dizileri `right` kadar ileri kaydırılır: conf_ph[t] doluysa, t barında
    (t - right) barındaki tepe pivotu onaylanmış demektir. Böylece t barında
    sadece t'ye kadar bilinen bilgi kullanılır.

    Returns:
        (conf_ph, conf_pl) — onaylanan pivotun fiyatı, yoksa NaN.
    """
    h = pd.Series(high)
    low_s = pd.Series(low)
    window = left + right + 1

    # window uzunluğunda, i+right'ta biten pencere == [i-left, i+right]
    roll_max = h.rolling(window).max().shift(-right)
    roll_min = low_s.rolling(window).min().shift(-right)

    is_ph = h >= roll_max
    is_pl = low_s <= roll_min

    conf_ph = h.where(is_ph).shift(right)
    conf_pl = low_s.where(is_pl).shift(right)

    return conf_ph.to_numpy(dtype=float), conf_pl.to_numpy(dtype=float)


def cluster_levels(prices: np.ndarray, tol_pct: float) -> list[tuple[float, int]]:
    """
    Birbirine yakın pivot fiyatlarını tek bir destek/direnç seviyesinde birleştirir.

    Args:
        prices: pivot fiyatları
        tol_pct: aynı seviye sayılacak maksimum yüzde fark (ör. 0.006 = %0.6)

    Returns:
        [(seviye_fiyatı, dokunuş_sayısı), ...] — fiyata göre artan sırada.
    """
    if prices.size == 0:
        return []

    sp = np.sort(prices)
    out: list[tuple[float, int]] = []
    bucket = [sp[0]]

    for p in sp[1:]:
        if bucket[0] > 0 and (p - bucket[0]) / bucket[0] <= tol_pct:
            bucket.append(p)
        else:
            out.append((float(np.mean(bucket)), len(bucket)))
            bucket = [p]

    out.append((float(np.mean(bucket)), len(bucket)))
    return out


# --------------------------------------------------------------------------- #
#  Strateji
# --------------------------------------------------------------------------- #

class SupportResistanceBreakRetest(IStrategy):

    INTERFACE_VERSION = 3

    # Kaldıraçlı futures — her iki yön de açık
    can_short: bool = True

    timeframe = "1h"

    # Çıkışı custom_exit (hedef seviye) ve custom_stoploss (yapısal stop) yönetir.
    # Buradakiler sadece emniyet ağı.
    minimal_roi = {"0": 0.50}
    stoploss = -0.15

    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    trailing_stop = False
    process_only_new_candles = True

    # lookback + pivot penceresi kadar ısınma gerekiyor
    startup_candle_count: int = 400

    # stoploss_on_exchange: stop emri doğrudan Bybit'e gönderilir ve orada durur.
    # Sunucu çökse, internet gitse, bot kapansa bile stop borsada aktif kalır.
    # Kaldıraçlı işlemde bu bir lüks değil, zorunluluk.
    #
    # Takip eden stop ile uyumlu: stop seviyesi değiştikçe freqtrade borsadaki
    # emri iptal edip yenisini kurar (stoploss_on_exchange_interval saniyede bir).
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_market_ratio": 0.99,
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # ---------------------- Hiperparametreler ---------------------- #

    # Pivot tespiti
    pivot_left = IntParameter(2, 6, default=3, space="buy", optimize=True)
    pivot_right = IntParameter(2, 6, default=3, space="buy", optimize=True)

    # Seviye oluşturma
    lookback = IntParameter(150, 500, default=300, space="buy", optimize=False)
    cluster_tol_pct = DecimalParameter(0.2, 1.5, default=0.6, decimals=2, space="buy")
    min_touches = IntParameter(2, 5, default=3, space="buy", optimize=True)

    # Kırılım
    break_margin_pct = DecimalParameter(0.1, 1.0, default=0.25, decimals=2, space="buy")
    vol_mult = DecimalParameter(1.0, 2.5, default=1.2, decimals=1, space="buy")

    # Retest
    retest_max_bars = IntParameter(5, 40, default=20, space="buy", optimize=True)
    retest_tol_pct = DecimalParameter(0.1, 1.0, default=0.35, decimals=2, space="buy")

    # Yol açıklığı ve risk
    min_room_pct = DecimalParameter(1.0, 6.0, default=2.5, decimals=1, space="buy")
    max_room_pct = DecimalParameter(8.0, 25.0, default=15.0, decimals=1, space="buy")
    min_rr = DecimalParameter(1.0, 4.0, default=2.0, decimals=1, space="buy")
    # Stop tamponu: kirilan seviyenin ne kadar otesine konacagi.
    # Ikisinin BUYUGU kullanilir — ATR oynakligi yakalar, yuzde taban gorevi gorur.
    #
    # Ilk backtest'te sabit %0.5 tampon %22.5 kazanma orani verdi: stop
    # gurultu seviyesindeydi ve normal fitiller supuruyordu. ATR'ye baglamak
    # stop'u piyasanin o anki oynakligina gore olceklendirir.
    stop_buffer_pct = DecimalParameter(0.2, 2.5, default=1.0, decimals=2, space="buy")
    stop_buffer_atr = DecimalParameter(0.3, 3.0, default=1.2, decimals=1, space="buy")

    # Önde bilinen bir sonraki seviye YOKSA ne yapmalı?
    #   False -> "önü açık" kabul edilir, hedef max_room_pct'e konur (agresif)
    #   True  -> sinyal atlanır; sadece gerçek iki seviye arasında işlem açılır
    # Kendi kuralın "bir sonraki desteğe çok varsa" dediği için varsayılan
    # False; ama True daha muhafazakâr ve hedefi gerçek yapıya bağlar.
    require_next_level = BooleanParameter(default=False, space="buy", optimize=True)

    # Kaldıraç
    leverage_num = IntParameter(1, 10, default=3, space="buy", optimize=False)

    # Hedefe yaklaşınca çık (hedefin tam üstünde likidite biter)
    target_approach_pct = DecimalParameter(0.0, 1.0, default=0.2, decimals=2, space="sell")

    # --- Takip eden stop (kâr arttıkça stop'u arkadan taşı) ---
    # Eşikler "R" cinsinden: 1R = girişten yapısal stop'a olan mesafe.
    # Böylece her işlemde ve her coin'de kendi riskine göre ölçeklenir.
    #
    #   move >= be_trigger_r    -> stop başabaşa çekilir (artık zarar edemez)
    #   move >= trail_trigger_r -> stop en iyi fiyatın trail_dist_r kadar arkasına
    breakeven_trigger_r = DecimalParameter(0.8, 3.0, default=1.8, decimals=1, space="sell")
    breakeven_offset_pct = DecimalParameter(0.0, 0.5, default=0.1, decimals=2, space="sell")
    trail_trigger_r = DecimalParameter(1.2, 4.0, default=2.5, decimals=1, space="sell")
    trail_dist_r = DecimalParameter(0.5, 2.0, default=1.0, decimals=1, space="sell")

    # --- Kısmi kâr alma ---
    # Hedefe giden yolun bir kısmı katedilince pozisyonun bir bölümünü kapat,
    # kalanı takip eden stop ile koştur.
    partial_tp_enable = BooleanParameter(default=True, space="sell", optimize=True)
    partial_tp_at = DecimalParameter(0.3, 0.8, default=0.5, decimals=2, space="sell")
    partial_tp_share = DecimalParameter(0.2, 0.7, default=0.5, decimals=2, space="sell")

    # Kısmi çıkış için gerekli
    position_adjustment_enable = True

    # ---------------------------------------------------------------- #

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["vol_ma"] = dataframe["volume"].rolling(20).mean()

        signals = self._compute_sr_signals(dataframe)
        for col, values in signals.items():
            dataframe[col] = values

        return dataframe

    # ---------------------------------------------------------------- #

    def _compute_sr_signals(self, df: DataFrame) -> dict[str, np.ndarray]:
        """
        Destek/direnç seviyelerini kurar, kırılım-retest durum makinesini
        yürütür ve giriş sinyallerini üretir.

        Bar bazında ilerler; her barda o ana kadar ONAYLANMIŞ pivotları
        kullanır, dolayısıyla geleceğe bakmaz.
        """
        n = len(df)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        open_ = df["open"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        vol_ma = df["vol_ma"].to_numpy(dtype=float)
        atr = df["atr"].to_numpy(dtype=float)

        left = int(self.pivot_left.value)
        right = int(self.pivot_right.value)
        lookback = int(self.lookback.value)
        tol = float(self.cluster_tol_pct.value) / 100.0
        min_touch = int(self.min_touches.value)
        margin = float(self.break_margin_pct.value) / 100.0
        vmult = float(self.vol_mult.value)
        max_retest = int(self.retest_max_bars.value)
        rt_tol = float(self.retest_tol_pct.value) / 100.0
        min_room = float(self.min_room_pct.value)
        max_room = float(self.max_room_pct.value)
        min_rr = float(self.min_rr.value)
        stop_buf = float(self.stop_buffer_pct.value) / 100.0
        stop_atr = float(self.stop_buffer_atr.value)
        need_level = bool(self.require_next_level.value)

        conf_ph, conf_pl = find_confirmed_pivots(high, low, left, right)

        sig_long = np.zeros(n, dtype=bool)
        sig_short = np.zeros(n, dtype=bool)
        sr_stop = np.full(n, np.nan)
        sr_target = np.full(n, np.nan)
        sr_room = np.full(n, np.nan)
        sr_rr = np.full(n, np.nan)
        sr_broken = np.full(n, np.nan)
        sr_real_level = np.full(n, np.nan)

        # Kayan pencere içindeki onaylanmış pivotlar
        piv_idx: list[int] = []
        piv_price: list[float] = []

        # Kırılım durumu
        brk_dir = 0            # -1 destek kırıldı, +1 direnç kırıldı, 0 yok
        brk_level = np.nan
        brk_bar = -1

        warmup = max(lookback // 3, left + right + 20)

        for t in range(n):
            # Bu barda onaylanan pivotları ekle
            if not np.isnan(conf_ph[t]):
                piv_idx.append(t)
                piv_price.append(float(conf_ph[t]))
            if not np.isnan(conf_pl[t]):
                piv_idx.append(t)
                piv_price.append(float(conf_pl[t]))

            # Pencereden çıkanları at
            cutoff = t - lookback
            while piv_idx and piv_idx[0] < cutoff:
                piv_idx.pop(0)
                piv_price.pop(0)

            if t < warmup or t < 1 or len(piv_price) < 4:
                continue
            if np.isnan(vol_ma[t]) or vol_ma[t] <= 0:
                continue

            clusters = cluster_levels(np.asarray(piv_price), tol)
            lv = np.array(
                [price for price, touches in clusters if touches >= min_touch],
                dtype=float,
            )
            if lv.size == 0:
                continue

            c = close[t]
            c_prev = close[t - 1]
            vol_ok = volume[t] > vol_ma[t] * vmult

            # ---------------- 1) KIRILIM TESPİTİ ---------------- #
            below_prev = lv[lv < c_prev]
            above_prev = lv[lv > c_prev]
            sup_prev = below_prev.max() if below_prev.size else np.nan
            res_prev = above_prev.min() if above_prev.size else np.nan

            if not np.isnan(sup_prev) and c < sup_prev * (1 - margin) and vol_ok:
                brk_dir, brk_level, brk_bar = -1, float(sup_prev), t
            elif not np.isnan(res_prev) and c > res_prev * (1 + margin) and vol_ok:
                brk_dir, brk_level, brk_bar = 1, float(res_prev), t

            # ---------------- 2) RETEST + GİRİŞ ---------------- #
            bars_since = t - brk_bar

            if brk_dir == -1 and 0 < bars_since <= max_retest:
                # Kırılan desteğe geri geldi mi, ve altında mı kapattı?
                touched = high[t] >= brk_level * (1 - rt_tol)
                rejected = c < brk_level
                bearish = c < open_[t]

                if touched and rejected and bearish:
                    below = lv[lv < c * 0.999]
                    real_level = below.size > 0
                    if real_level:
                        target = float(below.max())
                    elif need_level:
                        target = np.nan  # bilinen seviye yok -> sinyali atla
                    else:
                        # Altta bilinen seviye yok -> önü açık kabul et
                        target = c * (1 - max_room / 100.0)

                    room = (c - target) / c * 100.0
                    room = min(room, max_room)
                    # Stop tamponu: yuzde ve ATR'nin BUYUGU.
                    # Boylece oynak piyasada genisler, sakin piyasada
                    # yuzde tabani devreye girer.
                    buf = max(brk_level * stop_buf, stop_atr * atr[t])
                    stop = brk_level + buf
                    risk = (stop - c) / c * 100.0

                    if risk > 0 and not np.isnan(room):
                        rr = room / risk
                        if room >= min_room and rr >= min_rr:
                            sig_short[t] = True
                            sr_stop[t] = stop
                            sr_target[t] = c - (room / 100.0) * c
                            sr_room[t] = room
                            sr_rr[t] = rr
                            sr_broken[t] = brk_level
                            sr_real_level[t] = 1.0 if real_level else 0.0
                            brk_dir = 0  # sinyal tüketildi

            elif brk_dir == 1 and 0 < bars_since <= max_retest:
                touched = low[t] <= brk_level * (1 + rt_tol)
                supported = c > brk_level
                bullish = c > open_[t]

                if touched and supported and bullish:
                    above = lv[lv > c * 1.001]
                    real_level = above.size > 0
                    if real_level:
                        target = float(above.min())
                    elif need_level:
                        target = np.nan
                    else:
                        target = c * (1 + max_room / 100.0)

                    room = (target - c) / c * 100.0
                    room = min(room, max_room)
                    buf = max(brk_level * stop_buf, stop_atr * atr[t])
                    stop = brk_level - buf
                    risk = (c - stop) / c * 100.0

                    if risk > 0 and not np.isnan(room):
                        rr = room / risk
                        if room >= min_room and rr >= min_rr:
                            sig_long[t] = True
                            sr_stop[t] = stop
                            sr_target[t] = c + (room / 100.0) * c
                            sr_room[t] = room
                            sr_rr[t] = rr
                            sr_broken[t] = brk_level
                            sr_real_level[t] = 1.0 if real_level else 0.0
                            brk_dir = 0

            # ---------------- 3) DURUMU GEÇERSİZ KIL ---------------- #
            if brk_dir != 0:
                expired = (t - brk_bar) > max_retest
                # Kırılan seviyeyi geri aldıysa tez çürümüştür
                reclaimed = (
                    (brk_dir == -1 and c > brk_level * (1 + margin))
                    or (brk_dir == 1 and c < brk_level * (1 - margin))
                )
                if expired or reclaimed:
                    brk_dir = 0

        return {
            "sig_long": sig_long,
            "sig_short": sig_short,
            "sr_stop": sr_stop,
            "sr_target": sr_target,
            "sr_room": sr_room,
            "sr_rr": sr_rr,
            "sr_broken": sr_broken,
            "sr_real_level": sr_real_level,
        }

    # ---------------------------------------------------------------- #

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["sig_long"]) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "res_break_retest")

        dataframe.loc[
            (dataframe["sig_short"]) & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "sup_break_retest")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Çıkışlar custom_exit ve custom_stoploss ile yönetiliyor.
        return dataframe

    # ---------------------------------------------------------------- #

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return float(min(self.leverage_num.value, max_leverage))

    # ---------------------------------------------------------------- #

    def _entry_levels(self, pair: str, trade: Trade) -> tuple[float | None, float | None]:
        """
        İşlemin açıldığı mumdaki yapısal stop ve hedef seviyesini döndürür.
        İlk çağrıda hesaplanır ve işleme kaydedilir (yeniden başlatmaya dayanıklı).
        """
        stop = trade.get_custom_data("sr_stop")
        target = trade.get_custom_data("sr_target")
        if stop is not None and target is not None:
            return float(stop), float(target)

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None, None

        entry_rows = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
        if entry_rows.empty:
            return None, None

        candle = entry_rows.iloc[-1]
        stop_val = candle.get("sr_stop")
        target_val = candle.get("sr_target")

        if stop_val is None or target_val is None:
            return None, None
        if np.isnan(stop_val) or np.isnan(target_val):
            return None, None

        trade.set_custom_data("sr_stop", float(stop_val))
        trade.set_custom_data("sr_target", float(target_val))
        return float(stop_val), float(target_val)

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        """
        Üç kademeli stop:

          1. Başlangıç — kırılan seviyenin arkasında (yapısal stop).
             Fiyat o seviyeyi geri alırsa kırılım başarısız demektir.
          2. Başabaş  — lehimize 1R hareket olunca stop girişe çekilir.
             Bu noktadan sonra işlem zarar edemez.
          3. Takip    — 1.5R'den sonra stop, görülen en iyi fiyatın
             0.8R arkasından sürüklenir; kâr arttıkça stop da yükselir.

        Stop asla geriye gitmez — freqtrade zaten gevşemeyi kabul etmez,
        ayrıca aşağıdaki min/max mantığı da sadece sıkılaştırır.
        """
        struct_stop, _ = self._entry_levels(pair, trade)
        if struct_stop is None:
            return None

        entry = trade.open_rate
        if not entry or entry <= 0:
            return None

        # 1R = girişten yapısal stop'a olan mesafe (oran olarak)
        risk = abs(entry - struct_stop) / entry
        if risk <= 0:
            return None

        is_short = trade.is_short

        # İşlem boyunca görülen en iyi fiyat
        if is_short:
            best = trade.min_rate if trade.min_rate else current_rate
            move = (entry - best) / entry
        else:
            best = trade.max_rate if trade.max_rate else current_rate
            move = (best - entry) / entry

        move_r = move / risk
        new_stop = struct_stop

        be_offset = float(self.breakeven_offset_pct.value) / 100.0

        # Kademe 2 — başabaş
        if move_r >= float(self.breakeven_trigger_r.value):
            if is_short:
                new_stop = min(new_stop, entry * (1 - be_offset))
            else:
                new_stop = max(new_stop, entry * (1 + be_offset))

        # Kademe 3 — takip eden stop
        if move_r >= float(self.trail_trigger_r.value):
            trail_gap = float(self.trail_dist_r.value) * risk
            if is_short:
                new_stop = min(new_stop, best * (1 + trail_gap))
            else:
                new_stop = max(new_stop, best * (1 - trail_gap))

        return stoploss_from_absolute(
            new_stop,
            current_rate,
            is_short=is_short,
            leverage=trade.leverage,
        )

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> float | None:
        """
        Hedefe giden yolun `partial_tp_at` kadarı katedilince pozisyonun
        `partial_tp_share` kadarını kapatır — kâr cebe girer, kalan pozisyon
        takip eden stop ile hedefe kadar koşmaya devam eder.

        Bir işlemde yalnızca bir kez çalışır.
        """
        if not self.partial_tp_enable.value:
            return None
        if trade.get_custom_data("partial_done"):
            return None

        _, target = self._entry_levels(trade.pair, trade)
        if target is None:
            return None

        entry = trade.open_rate
        if not entry or entry <= 0:
            return None

        total = abs(target - entry)
        if total <= 0:
            return None

        # Hedefe ne kadar yaklaştık?
        if trade.is_short:
            progress = (entry - current_rate) / total
        else:
            progress = (current_rate - entry) / total

        if progress < float(self.partial_tp_at.value):
            return None

        share = float(self.partial_tp_share.value)
        amount = trade.stake_amount * share

        if min_stake is not None:
            # Kalan pozisyon min_stake'in altına düşecekse kısmi çıkış yapma
            if amount < min_stake or (trade.stake_amount - amount) < min_stake:
                return None

        trade.set_custom_data("partial_done", True)
        logger.info(
            "%s: kismi kar alma — yolun %.0f%%'i katedildi, pozisyonun %.0f%%'i kapatiliyor",
            trade.pair, progress * 100, share * 100,
        )
        return -amount

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """
        Bir sonraki destek/dirence ulaşınca çık — sinyalin dayandığı "yol"
        bittiği için tez de biter.
        """
        _, target = self._entry_levels(pair, trade)
        if target is None:
            return None

        approach = float(self.target_approach_pct.value) / 100.0

        if trade.is_short:
            if current_rate <= target * (1 + approach):
                return "hedef_destek"
        else:
            if current_rate >= target * (1 - approach):
                return "hedef_direnc"

        return None
