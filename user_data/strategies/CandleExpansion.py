# pragma pylint: disable=missing-docstring, invalid-name, too-many-locals
"""
CandleExpansion
===============

4 saatlik mum genişlemesi (momentum devamı) stratejisi.

KURAL
-----
1. Bir önceki 4 saatlik mum kapanır. Yönü ve gövde boyu ölçülür.
       onceki_hareket = (onceki_kapanis - onceki_acilis) / onceki_acilis

2. Yeni 4 saatlik mum açılır. Yeni mum, önceki mumla AYNI yönde ve onun
   gövdesinin 1.4 KATI kadar hareket ederse, o anda o yönde işleme girilir.

       tetik_fiyat = yeni_acilis * (1 + 1.4 * onceki_hareket)

   Örnek: önceki 4s mum %1 düştü. Yeni mum kendi açılışından %1.4
   düştüğü anda SHORT açılır. Önceki mum %1 yükseldiyse ve yeni mum
   %1.4 yükselirse LONG açılır.

3. STOP: önceki mumun AÇILIŞ fiyatının %0.5 ötesine konur.
       SHORT -> onceki_acilis * 1.005
       LONG  -> onceki_acilis * 0.995

4. KAR AL: %9  (fiyat hareketi; 8x kaldiracla hesapta ~%72)

5. Kaldıraç: 8x

Her 4 saatlik mumda en fazla BİR giriş yapılır.

NEDEN 15 DAKİKALIK GRAFİK ÜZERİNDE ÇALIŞIR
-------------------------------------------
Analiz 4 saatliktir ama giriş mum İÇİNDE, tetik fiyatına değildiği anda
olmalıdır. Freqtrade 4 saatlik zaman diliminde çalışsaydı yalnızca mum
kapanışlarında karar verir ve girişleri kaçırırdı.

Bu yüzden yürütme 15 dakikalıktır: 4 saatlik mumlar 15 dakikalık veriden
türetilir, tetik her 15 dakikada bir kontrol edilir. Geleceğe bakma yoktur —
her barda yalnızca TAMAMLANMIŞ önceki 4 saatlik mum ve İÇİNDE bulunulan
mumun açılışı kullanılır.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
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


class CandleExpansion(IStrategy):

    INTERFACE_VERSION = 3

    can_short: bool = True

    # Yürütme zaman dilimi (analiz 4 saatlik — yukarıdaki açıklamaya bak)
    timeframe = "15m"
    htf = "4h"

    # Çıkışlar custom_exit (kâr hedefi) ve custom_stoploss (yapısal stop) ile.
    # minimal_roi devre dışı — kâr hedefini biz yönetiyoruz.
    minimal_roi = {"0": 10.0}

    # Son çare emniyet ağı. Gerçek stop custom_stoploss'tan gelir ve
    # her zaman bundan çok daha yakındır.
    stoploss = -0.85

    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True

    # 4 saatlik mumları türetmek için birkaç günlük 15dk verisi yeter
    startup_candle_count: int = 200

    # Stop emirleri borsada durur — sunucu çökse bile koruma devam eder
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_market_ratio": 0.99,
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # ---------------------- Parametreler ---------------------- #

    # Tetik: önceki mum gövdesinin kaç katı
    expansion_mult = DecimalParameter(1.1, 2.5, default=1.4, decimals=2, space="buy")

    # Stop: önceki mumun açılışından ne kadar öte
    stop_beyond_open_pct = DecimalParameter(0.1, 2.0, default=0.5, decimals=2, space="sell")

    # Kâr hedefi — FİYAT hareketi olarak (8x kaldıraçla hesapta 8 katı eder).
    #
    # OLCULEN:
    #   %8 -> kazanma orani %23.3 | basabas gereken %21.3 | beklenen +1.71  KARLI
    #   %4 -> kazanma orani %32.0 | basabas gereken %35.1 | beklenen -1.58  ZARARLI
    #
    # Hedefi yariya indirmek kazanma oranini %23.3'ten sadece %32'ye tasidi;
    # gereken %35.1 idi. Rastgele yuruyus modeli stop/(stop+hedef) ile
    # kiyaslandiginda TP4 modelin ALTINDA, TP8 modelin USTUNDE kaliyor.
    #
    # Anlami: kazananlar hedefe zar zor degip donmuyor, cok daha uzaga
    # gidiyor. Bu stratejinin kenari KALIN SAG KUYRUKTA. Kucuk hedef o
    # kuyrugu kesip kenari yok ediyor — bu yuzden hedefi buyuk tutmak
    # dogru yon.
    take_profit_pct = DecimalParameter(2.0, 20.0, default=9.0, decimals=1, space="sell")

    # Kâr hedefi FİYAT hareketi mi, yoksa kaldıraçlı hesap kârı mı?
    #   False -> %8 FİYAT hareketi  (8x kaldıraçla hesapta ~%64)
    #   True  -> %8 HESAP kârı      (8x kaldıraçla ~%1 fiyat hareketi)
    tp_on_leveraged = BooleanParameter(default=False, space="sell", optimize=False)

    # Çok küçük (doji) önceki mumları ele — tetik gürültü seviyesinde kalmasın
    min_prev_body_pct = DecimalParameter(0.0, 1.0, default=0.15, decimals=2, space="buy")

    # GÜVENLİK SINIRI — stop mesafesi bundan uzaksa işleme girilmez.
    # Stop, önceki mumun açılışına sabit olduğu için önceki mum ne kadar
    # büyükse stop o kadar uzaklaşır. 8x kaldıraçta likidasyon ~%12.5
    # fiyat hareketindedir; bu sınır stop'un likidasyonun ötesine
    # geçmesini engeller.
    max_stop_pct = DecimalParameter(2.0, 12.0, default=10.0, decimals=1, space="buy")

    leverage_num = IntParameter(1, 20, default=8, space="buy", optimize=False)

    # Borsa istenen kaldiraci veremiyorsa isleme GIRME.
    # False yaparsan dusuk kaldiracla acar (pozisyon kucuk olur).
    require_full_leverage = BooleanParameter(default=True, space="buy", optimize=False)

    # leverage() ile confirm_trade_entry arasinda bilgi tasir
    _lev_seen: dict = {}

    # --- Yon acma/kapama ---
    # Ilk gercek backtest'te karin %92.7'si SHORT tarafindan geldi ve o donemde
    # piyasa %40.73 dustu. Long tarafi 360 islemde islem basina sadece
    # +0.29 USDT uretti (short: +3.87). Bu, edge'in gercek mi yoksa ayi
    # piyasasina denk gelmis olmaktan mi ibaret oldugunu test etmek icin.
    allow_long = BooleanParameter(default=True, space="buy", optimize=True)
    allow_short = BooleanParameter(default=True, space="buy", optimize=True)

    # --- Trend filtresi (varsayilan KAPALI) ---
    # Acikken: fiyat EMA ustundeyse sadece long, altindaysa sadece short.
    # Yonu piyasa rejimine baglar; sabit yon tercihinden daha durustur.
    use_trend_filter = BooleanParameter(default=False, space="buy", optimize=True)
    trend_ema = IntParameter(50, 400, default=200, space="buy", optimize=True)

    # ---------------------------------------------------------------- #

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # --- 4 saatlik mumları 15 dakikalık veriden türet --- #
        # floor("4h") UTC'de 00:00/04:00/08:00... sınırlarına oturur,
        # yani borsanın gerçek 4 saatlik mumlarıyla aynı hizada.
        period = df["date"].dt.floor(self.htf)
        g = df.groupby(period, sort=False)

        # İÇİNDE bulunulan 4s mumunun açılışı — periyodun ilk barında bilinir
        cur_open = g["open"].transform("first")

        # ÖNCEKİ (tamamlanmış) 4s mumunun açılış ve kapanışı.
        # shift(1) ile bir önceki periyoda kayar; o periyot kapandığı için
        # bu bilgi geleceğe bakma değildir.
        per_open = g["open"].first()
        per_close = g["close"].last()
        prev_open = period.map(per_open.shift(1))
        prev_close = period.map(per_close.shift(1))

        df["cur_open"] = cur_open
        df["prev_open"] = prev_open
        df["prev_close"] = prev_close

        # Önceki mumun yönü ve gövde boyu (işaretli oran)
        prev_move = (prev_close - prev_open) / prev_open
        df["prev_move"] = prev_move

        # Tetik fiyatı: yeni mum açılışından, önceki gövdenin katı kadar öte
        mult = float(self.expansion_mult.value)
        df["trigger"] = cur_open * (1.0 + mult * prev_move)

        # Stop: önceki mumun açılışının %0.5 ötesi
        sb = float(self.stop_beyond_open_pct.value) / 100.0
        df["stop_short"] = prev_open * (1.0 + sb)
        df["stop_long"] = prev_open * (1.0 - sb)

        # Trend filtresi icin EMA (yalnizca use_trend_filter acikken kullanilir)
        df["trend_ema_val"] = df["close"].ewm(
            span=int(self.trend_ema.value), adjust=False
        ).mean()

        df["period"] = period
        return df

    # ---------------------------------------------------------------- #

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        min_body = float(self.min_prev_body_pct.value) / 100.0
        max_stop = float(self.max_stop_pct.value) / 100.0

        body_ok = df["prev_move"].abs() >= min_body
        valid = df["prev_open"].notna() & df["trigger"].notna() & (df["volume"] > 0)

        use_trend = bool(self.use_trend_filter.value)
        trend_short_ok = (df["close"] < df["trend_ema_val"]) if use_trend else True
        trend_long_ok = (df["close"] > df["trend_ema_val"]) if use_trend else True

        # --- SHORT: önceki mum düşüş, fiyat tetiğe indi --- #
        short_setup = (valid & body_ok & (df["prev_move"] < 0)
                       & bool(self.allow_short.value) & trend_short_ok)
        short_hit = short_setup & (df["low"] <= df["trigger"])
        # Stop girişin ÜSTÜNDE olmalı (yukarı boşlukta bozulabilir)
        short_hit &= df["stop_short"] > df["trigger"]
        # Stop mesafesi likidasyonu geçmesin
        short_hit &= (df["stop_short"] - df["trigger"]) / df["trigger"] <= max_stop

        # --- LONG: önceki mum yükseliş, fiyat tetiğe çıktı --- #
        long_setup = (valid & body_ok & (df["prev_move"] > 0)
                      & bool(self.allow_long.value) & trend_long_ok)
        long_hit = long_setup & (df["high"] >= df["trigger"])
        long_hit &= df["stop_long"] < df["trigger"]
        long_hit &= (df["trigger"] - df["stop_long"]) / df["trigger"] <= max_stop

        # --- Her 4 saatlik mumda yalnızca İLK tetiklenme --- #
        first_short = short_hit & (
            short_hit.groupby(df["period"]).cumsum().eq(1)
        )
        first_long = long_hit & (
            long_hit.groupby(df["period"]).cumsum().eq(1)
        )

        df.loc[first_long, ["enter_long", "enter_tag"]] = (1, "genisleme_long")
        df.loc[first_short, ["enter_short", "enter_tag"]] = (1, "genisleme_short")

        self._notify_signal(df, metadata)
        return df

    # ---------------------------------------------------------------- #

    def _notify_signal(self, df: DataFrame, metadata: dict) -> None:
        """
        Sinyal olustugu anda Telegram'a bildirim gonderir.

        Freqtrade varsayilan olarak yalnizca ISLEM acilinca/kapaninca haber
        verir. Bu, sinyalin kendisini de duyurur — slot dolu oldugu icin
        isleme donusmeyen sinyalleri de gorursun.

        Yalnizca canli/dry-run modda ve yalnizca SON mum icin calisir;
        backtest'te hic devreye girmez.
        """
        dp = getattr(self, "dp", None)
        if dp is None or getattr(dp, "runmode", None) is None:
            return
        if dp.runmode.value not in ("live", "dry_run"):
            return
        if df.empty:
            return

        last = df.iloc[-1]
        is_long = bool(last.get("enter_long") == 1)
        is_short = bool(last.get("enter_short") == 1)
        if not (is_long or is_short):
            return

        pair = metadata.get("pair", "?")
        trigger = float(last["trigger"])
        stop = float(last["stop_long"] if is_long else last["stop_short"])
        prev_move = float(last["prev_move"]) * 100
        tp = float(self.take_profit_pct.value)
        lev = float(self.leverage_num.value)

        target = trigger * (1 + tp / 100) if is_long else trigger * (1 - tp / 100)
        risk = abs(stop - trigger) / trigger * 100

        yon = "LONG" if is_long else "SHORT"
        msg = (
            f"SINYAL - {yon}\n"
            f"{pair}\n\n"
            f"Onceki 4s mum : %{prev_move:+.2f}\n"
            f"Giris (tetik) : {trigger:.6g}\n"
            f"Stop          : {stop:.6g}  (%{risk:.2f} uzakta)\n"
            f"Hedef         : {target:.6g}  (%{tp:.1f})\n"
            f"Risk/Odul     : {tp / risk:.2f}"
        )
        dp.send_msg(msg)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Çıkışlar custom_exit ve custom_stoploss ile yönetiliyor
        return dataframe

    # ---------------------------------------------------------------- #

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        """
        Emir gonderilmeden hemen once son kontrol ve Telegram bildirimi.

        1) KALDIRAC KONTROLU — borsa istenen kaldiraci veremiyorsa islemi
           engeller. Bybit bazi ciftlerde kaldirac kademesi vermiyor; o
           durumda pozisyon sessizce 1x acilir, yani hedeflenenin sekizde
           biri buyuklugunde. Bu, test ettigimiz strateji degildir.
        2) Giris ozetini Telegram'a atar (stop ve hedef dahil).
        """
        want = float(self.leverage_num.value)
        actual, max_lev = self._lev_seen.get(pair, (want, want))

        dp = getattr(self, "dp", None)
        live = (dp is not None and getattr(dp, "runmode", None) is not None
                and dp.runmode.value in ("live", "dry_run"))

        if actual < want - 1e-9 and self.require_full_leverage.value:
            msg = (
                f"KALDIRAC YETERSIZ - ISLEM IPTAL\n"
                f"{pair}\n\n"
                f"Istenen : {want:.0f}x\n"
                f"Borsanin verdigi: {max_lev:.2f}x\n\n"
                f"Bybit bu cift icin kaldirac kademesi vermiyor.\n"
                f"Islem acilsaydi hedeflenenin {want / max(actual, 0.01):.0f} kati "
                f"kucuk olurdu. Bu yuzden girilmedi."
            )
            logger.warning("%s: kaldirac %.2fx < %.0fx — giris iptal", pair, actual, want)
            if live:
                try:
                    dp.send_msg(msg, always_send=True)
                except Exception:
                    pass
            return False

        if not live:
            return True

        try:
            df, _ = dp.get_analyzed_dataframe(pair, self.timeframe)
            if df is None or df.empty:
                return True

            last = df.iloc[-1]
            is_short = side == "short"
            stop = float(last["stop_short"] if is_short else last["stop_long"])
            tp = float(self.take_profit_pct.value)

            target = rate * (1 - tp / 100) if is_short else rate * (1 + tp / 100)
            risk = abs(stop - rate) / rate * 100

            yon = "SHORT" if is_short else "LONG"
            msg = (
                f"ISLEM ACILIYOR - {yon}\n"
                f"{pair}\n\n"
                f"Giris    : {rate:.6g}\n"
                f"Miktar   : {amount:.6g}\n"
                f"Kaldirac : {actual:.0f}x\n"
                f"Nominal  : {amount * rate:.2f} USDT\n\n"
                f"STOP  : {stop:.6g}\n"
                f"        %{risk:.2f} uzakta = hesapta -%{risk * actual:.1f}\n"
                f"HEDEF : {target:.6g}\n"
                f"        %{tp:.1f} = hesapta +%{tp * actual:.0f}\n\n"
                f"Risk/Odul: {tp / risk:.2f}"
            )
            dp.send_msg(msg, always_send=True)
        except Exception as e:
            logger.warning("Giris bildirimi gonderilemedi: %s", e)

        return True

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
        """
        Istenen kaldirac, borsanin o cift icin izin verdiginin ustune cikamaz.

        DIKKAT: Bybit bazi ciftler icin kaldirac kademesi (leverage tier)
        verisi dondurmuyor. O durumda freqtrade max_leverage'i 1.0 kabul
        eder ve pozisyon SESSIZCE 8x yerine 1x acilir — yani hedeflenenin
        sekizde biri buyuklugunde. Bunu yakalayip kaydediyoruz;
        confirm_trade_entry bu bilgiye bakip islemi engelliyor.
        """
        want = float(self.leverage_num.value)
        actual = float(min(want, max_leverage))
        self._lev_seen[pair] = (actual, float(max_leverage))
        if actual < want:
            logger.warning(
                "%s: istenen kaldirac %.0fx ama borsa en fazla %.2fx veriyor",
                pair, want, max_leverage,
            )
        return actual

    # ---------------------------------------------------------------- #

    def _stop_for(self, pair: str, trade: Trade) -> float | None:
        """İşlemin açıldığı andaki yapısal stop fiyatı (önceki mum açılışı ± %0.5)."""
        cached = trade.get_custom_data("stop_price")
        if cached is not None:
            return float(cached)

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None

        rows = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
        if rows.empty:
            return None

        candle = rows.iloc[-1]
        val = candle["stop_short"] if trade.is_short else candle["stop_long"]
        if val is None or np.isnan(val):
            return None

        trade.set_custom_data("stop_price", float(val))
        return float(val)

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
        stop = self._stop_for(pair, trade)
        if stop is None:
            return None

        return stoploss_from_absolute(
            stop,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        tp = float(self.take_profit_pct.value) / 100.0

        if self.tp_on_leveraged.value:
            # current_profit futures'ta zaten kaldıraçlıdır
            if current_profit >= tp:
                return "kar_hedefi"
            return None

        # Fiyat bazında %8
        if trade.is_short:
            if current_rate <= trade.open_rate * (1.0 - tp):
                return "kar_hedefi"
        else:
            if current_rate >= trade.open_rate * (1.0 + tp):
                return "kar_hedefi"
        return None
