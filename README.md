# tradedair

Bybit USDT-perpetual üzerinde çalışan, **destek/direnç kırılımı + retest + yol açıklığı**
stratejisini uygulayan kaldıraçlı işlem botu.

Temel: [freqtrade](https://github.com/freqtrade/freqtrade) · Kontrol: Telegram + FreqUI ·
Başlangıç modu: **test (dry-run)** — gerçek fiyat, sahte para.

---

## Strateji

Bot her mumda destek/direnç seviyelerini yeniden hesaplar. Seviyeler, onaylanmış
pivot (swing) noktalarının birbirine yakın olanlarının kümelenmesiyle bulunur;
bir bölgeye ne kadar çok dokunulmuşsa seviye o kadar güçlüdür.

### SHORT girişi

1. **Kırılım** — fiyat bir desteği aşağı kırar (marj + hacim onayı ile).
2. **Retest** — fiyat kırılan desteğe geri döner; destek artık direnç görevi görür.
3. **Ret** — o seviyeden reddedilir, tekrar altında ve düşüş mumu ile kapatır.
4. **Yol açıklığı** — bir sonraki desteğe olan mesafe yeterince büyükse → **SHORT**.

### LONG girişi

Tam tersi: direnç yukarı kırılır → dirence retest → üstünde tutunur →
bir sonraki dirence çok varsa → **LONG**.

### Çıkış — üç kademeli takip eden stop

Stop sabit değil; işlem kâra geçtikçe arkadan sürüklenir, böylece kazanç geri
verilmez. Eşikler **R** cinsinden — 1R = girişten yapısal stop'a olan mesafe,
yani her işlemin kendi riski. Bu sayede her coin'de ve her volatilitede
kendiliğinden ölçeklenir.

| Kademe | Ne zaman | Stop nerede |
|---|---|---|
| **1. Yapısal** | giriş anında | kırılan seviyenin arkasında |
| **2. Başabaş** | lehe 1R hareket | girişte — artık zarar edemez |
| **3. Takip** | lehe 1.5R sonrası | görülen en iyi fiyatın 0.8R arkasında |

Stop asla gevşemez, sadece sıkılaşır.

**Kısmi kâr alma**: hedefe giden yolun yarısı katedilince pozisyonun %50'si
kapatılır — kâr cebe girer. Kalan yarısı takip eden stop ile hedefe kadar
koşmaya devam eder.

**Hedef**: bir sonraki destek/direnç. Yol bittiğinde tez de biter.

**Risk/ödül filtresi**: hedef mesafesi / stop mesafesi oranı eşiğin altındaysa
sinyal alınmaz. Yani "mesafe çok olmalı" kuralı hem mutlak yüzde hem de R/R
olarak uygulanır.

Örnek (testten): giriş 100, yapısal stop 98 (1R = %2). Fiyat 108'e (4R) çıkıp
geri döndüğünde stop 106.27'ye taşınmış oluyor ve orada çıkılıyor —
fiyat bazında **+%6.27**, 3x kaldıraçla hesapta **+%18.8**.

Ayarlanabilir tüm parametreler `user_data/strategies/SupportResistanceBreakRetest.py`
içinde en üstte, isimleriyle birlikte duruyor.

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

Kaldıraç `leverage_num` parametresiyle ayarlanır (varsayılan **3x**).
Freqtrade'de stop değerleri kaldıraçlı hesaba göredir: 3x kaldıraçta
%1'lik fiyat hareketi hesapta %3 eder.

---

## Doğrulama

Strateji kodu ağ erişimi olmadan test edilebilir:

```bash
python scripts/gen_test_data.py        # sentetik OHLCV üretir
python scripts/validate_strategy.py    # giriş mantığı — 3 test
python scripts/validate_exits.py       # çıkış mantığı — takip eden stop + kısmi TP
```

### Giriş testleri (`validate_strategy.py`)

1. **Sinyal üretimi** — kaç sinyal, ortalama yol açıklığı ve R/R.
2. **Kural doğrulaması** — her sinyalin gerçekten kurallara uyduğu:
   yol açıklığı ve R/R eşiklerini geçiyor mu, SHORT'ta stop kırılan desteğin
   üstünde ve hedef altında mı, LONG'da tersi mi.
3. **Geleceğe bakma testi** — en kritik olan. Veri her sinyal barında kesilip
   yeniden hesaplanır; sinyal değişmemelidir. Değişiyorsa strateji geleceği
   görüyordur ve backtest sonuçları yalandır.

Son çalıştırmada üçü de temiz geçti (255 sinyal, 40 barda 0 uyuşmazlık).

### Çıkış testleri (`validate_exits.py`)

Sahte bir işlem hayat döngüsü simüle eder ve doğrular:

- stop hiçbir zaman gevşemiyor, sadece sıkılaşıyor
- 1R'de başabaşa çekiliyor
- 1.5R sonrası kârı kilitleyerek takip ediyor
- fiyat geri çekilince takip eden stop kârda kapatıyor
- kısmi kâr alma tam yolun yarısında, yalnızca bir kez tetikleniyor

Long ve short için ayrı ayrı. Son çalıştırmada ikisi de geçti.

> Bu testler sentetik veriyle çalışır ve **mantığın doğruluğunu** kanıtlar,
> kârlılığı değil. Kârlılık için gerçek Bybit verisiyle backtest gerekir (adım 3).

---

## Önemli ayar: `require_next_level`

Bir kırılım sonrası önde bilinen bir sonraki seviye **yoksa** ne yapılmalı?

| Değer | Davranış |
|---|---|
| `False` (varsayılan) | "Önü açık" kabul edilir, hedef `max_room_pct`'e konur — daha çok sinyal, daha agresif |
| `True` | Sinyal atlanır; sadece iki gerçek seviye arasında işlem açılır — daha az ama daha net sinyal |

Sentetik testte bu ayar sinyal sayısını **255 → 27**'ye düşürdü, çünkü rastgele
yürüyüş verisi sürekli yeni fiyat bölgelerine giriyor. Gerçek piyasada yapı daha
oturmuş olduğu için fark bu kadar büyük olmayacaktır — ama **gerçek veriyle iki
modu da backtest edip karşılaştırmanı öneririm.**

---

## Bilinen sınırlar

- Bu repo'daki testler sentetik veriyle yapıldı; gerçek Bybit verisi bu geliştirme
  ortamından erişilebilir değildi. Gerçek backtest'i kendi sunucunda çalıştır.
- Backtest komisyon ve funding maliyetini içerir ama gerçek slippage'ı tam
  modelleyemez. Dry-run bu farkı görmenin tek yolu.
- Kaldıraçlı işlemde likidasyon riski gerçektir. `liquidation_buffer` 0.05 olarak
  ayarlı ama düşük kaldıraç ve makul pozisyon boyutu asıl korumadır.
