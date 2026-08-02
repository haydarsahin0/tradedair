# tradedair

Bybit USDT-perpetual üzerinde çalışan, **4 saatlik mum genişlemesi**
stratejisini uygulayan kaldıraçlı işlem botu.

Temel: [freqtrade](https://github.com/freqtrade/freqtrade) · Kontrol: Telegram + FreqUI ·
Başlangıç modu: **test (dry-run)** — gerçek fiyat, sahte para.

---

## Strateji — CandleExpansion

Bir 4 saatlik mum kapanır, yönü ve gövde boyu ölçülür. Yeni mum **aynı yönde**
ve o gövdenin **1.4 katı** kadar hareket ederse, tam o anda o yönde işleme girilir.

```
tetik_fiyat = yeni_acilis * (1 + 1.4 * onceki_hareket)
```

**Örnek:** önceki 4s mum %1 düştü → yeni mum kendi açılışından %1.4 düştüğü an
**SHORT**. Önceki mum %1 yükseldiyse ve yeni mum %1.4 yükselirse **LONG**.

| | |
|---|---|
| Analiz | 4 saatlik mumlar |
| Yürütme | 15 dakikalık (aşağıda neden) |
| Tetik | önceki gövdenin 1.4 katı |
| Stop | önceki mumun **açılışının** %0.5 ötesi |
| Kâr al | %4 fiyat hareketi (hesapta ~%32) |
| Kaldıraç | 8x |
| Kasa | 500 USDT |
| Aynı anda işlem | 3 |
| İşlem başına | 100 USDT (sermayenin %60'ı kullanımda) |
| Giriş sıklığı | her 4s mumda en fazla bir kez |

### Neden 15 dakikalık grafikte çalışıyor

Analiz 4 saatliktir ama giriş mumun **içinde**, fiyat tetiğe değdiği anda olmalı.
Freqtrade 4 saatlik zaman diliminde çalışsaydı sadece mum kapanışlarında karar
verir ve girişleri kaçırırdı. Bu yüzden 4 saatlik mumlar 15 dakikalık veriden
türetiliyor ve tetik her 15 dakikada kontrol ediliyor.

Geleceğe bakma yok: her barda yalnızca **tamamlanmış** önceki 4 saatlik mum ve
**içinde bulunulan** mumun açılışı kullanılıyor.

### Risk (8x kaldıraçla)

Stop, önceki mumun açılışına sabitlendiği için **stop mesafesi önceki mumun
boyuna göre değişir** — büyük mum, uzak stop.

Sentetik veride ölçülen: stop mesafesi medyan **%1.5 fiyat** (hesapta **%12**),
en kötü durumda %7.2 fiyat (hesapta %58). Kâr hedefi %4 fiyat = hesapta %32.
Risk/ödül medyan **5.2**, yani başabaş için **%16 kazanma oranı** yeterli.

`max_stop_pct` parametresi stop'un likidasyonun ötesine geçmesini engeller
(8x'te likidasyon ~%12.5 fiyat hareketinde).

---

## Kurulum (tek seferlik)

Bunu bir kere yapman yeterli. Sonrasında her şey telefondan yönetilir.

Bot 7/24 açık bir makinede çalışmalı — bir VPS (Hetzner ~5€/ay) ya da evde
sürekli açık bir bilgisayar/Raspberry Pi.

### 1. Telegram botunu oluştur (telefondan)

- Telegram'da **@BotFather**'a yaz → `/newbot` → isim ver → sana bir **token** verir.
- **@userinfobot**'a bir mesaj at → sana **chat ID**'ni söyler.

Bu ikisini not al.

### 2. Sunucuda kurulum

```bash
git clone -b claude/vibe-trading-bot-strategy-ex4d14 \
  https://github.com/haydarsahin0/tradedair.git
cd tradedair
./scripts/setup.sh
```

Script Docker'ı kurar, gizli anahtarları üretir, `.env` dosyasını hazırlar ve
istersen backtest'i çalıştırır. Sana sadece Telegram token'ını ve chat ID'ni sorar.

### 3. Botu başlat (test modunda)

```bash
docker compose up -d
```

Telegram'a "bot başladı" mesajı gelecek. Artık bilgisayara gerek yok.

Backtest'i sonra tekrar çalıştırmak istersen:

```bash
./scripts/backtest.sh                    # varsayılan aralık
./scripts/backtest.sh 20240101-20260801  # kendi aralığın
```

---

## Telefondan kullanım

### Telegram komutları

| Komut | Ne yapar |
|---|---|
| `/start` `/stop` | işlemi başlat / durdur |
| `/pause` | yeni giriş yapma, açık işlemleri yönetmeye devam et |
| `/status` | açık pozisyonlar |
| `/status table` | hepsi tek tabloda |
| `/profit` | toplam kâr-zarar |
| `/daily` `/weekly` `/monthly` | dönemsel rapor |
| `/balance` | bakiye |
| `/forcelong BTC/USDT:USDT` | elle long aç |
| `/forceshort BTC/USDT:USDT` | elle short aç |
| `/fx` | pozisyonu anında kapat |
| `/whitelist` | işlem yapılan çiftler |
| `/reload_config` | ayarları yeniden yükle (bot durmadan) |

Komutları yazmana gerek yok — Telegram'da buton klavyesi çıkıyor.
Her giriş/çıkış/stop olayında bildirim gelir.

### FreqUI (tablet için)

Tarayıcıdan `http://SUNUCU_IP:8080` — `.env`'deki kullanıcı adı/şifre ile giriş.
Grafikler, işlem geçmişi ve seviyeler burada görünür.

> Sunucuyu internete açıyorsan mutlaka güçlü bir şifre kullan, tercihen bir
> reverse proxy arkasına HTTPS ile koy.

### Lovable ile kendi arayüzün

Freqtrade'in tam bir REST API'si var, yani Lovable'da kendi panelini yapıp
bota bağlayabilirsin. Alan adı + HTTPS + CORS ayarı gerekiyor; hepsinin
kurulumu ve Lovable'a yapıştıracağın hazır prompt **[docs/LOVABLE.md](docs/LOVABLE.md)**
dosyasında.

```bash
docker compose --profile lovable up -d   # HTTPS proxy ile başlat
```

---

## Test modundan canlıya geçiş

**Acele etme.** Önce dry-run'da en az birkaç hafta izle, `/profit` ve `/daily`
rakamlarının backtest ile tutarlı olduğunu gör.

Canlıya geçerken:

1. Bybit'te API anahtarı oluştur — **"Withdraw" (para çekme) yetkisini ASLA verme**.
2. `.env` içine `BYBIT_API_KEY` ve `BYBIT_API_SECRET` gir.
3. `user_data/config.json` içinde `"dry_run": false` yap.
4. `stake_amount` ve `max_open_trades` değerlerini kaldırabileceğin kayba göre ayarla.
5. `docker compose up -d --force-recreate`

Kaldıraç `leverage_num` parametresiyle ayarlanır (varsayılan **8x**).
Freqtrade'de stop değerleri kaldıraçlı hesaba göredir: 8x kaldıraçta
%1'lik fiyat hareketi hesapta %8 eder. Tipik bir stop %1.5 fiyat =
**hesapta %12 kayıp**; büyük mumlardan sonra bu %50'yi aşabilir.

---

## Doğrulama

Strateji kodu ağ erişimi olmadan test edilebilir:

```bash
python scripts/gen_test_data.py        # sentetik OHLCV üretir
python scripts/validate_strategy.py    # 5 test
```

Testler:

1. **Sinyal üretimi** — kaç giriş, hangi yönde
2. **4 saatlik mum türetimi** — bağımsız bir resample ile birebir karşılaştırılır
3. **Kural doğrulaması** — tetik formülü, yön, girişin gerçekten tetiğe
   değdiğinde olması, stop'un doğru yerde ve doğru tarafta olması,
   her mumda tek giriş
4. **Risk profili** — stop mesafesi, hesaptaki kayıp, risk/ödül, başabaş oranı
5. **Geleceğe bakma testi** — veri kesilip yeniden hesaplanır, sinyal değişmemeli

Son çalıştırmada beşi de temiz geçti (3213 sinyal, 35 barda 0 uyuşmazlık).

> Bu testler sentetik veriyle çalışır ve **mantığın doğruluğunu** kanıtlar,
> kârlılığı değil. Kârlılık için gerçek Bybit verisiyle backtest gerekir (adım 3).

---

## Bilinen sınırlar

- Bu repo'daki testler sentetik veriyle yapıldı; gerçek Bybit verisi bu geliştirme
  ortamından erişilebilir değildi. Gerçek backtest'i kendi sunucunda çalıştır.
- Backtest komisyon ve funding maliyetini içerir ama gerçek slippage'ı tam
  modelleyemez. Dry-run bu farkı görmenin tek yolu.
- Kaldıraçlı işlemde likidasyon riski gerçektir. `liquidation_buffer` 0.05 olarak
  ayarlı ama düşük kaldıraç ve makul pozisyon boyutu asıl korumadır.
