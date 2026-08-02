# Lovable ile kendi arayüzünü yapmak

**Kısa cevap: Evet, yapılabilir.** Freqtrade'in tam bir REST API'si var; Lovable'ın
ürettiği React uygulaması bu API'ye bağlanıp botu yönetebilir.

Ama iki teknik engel var ve ikisini de çözmen gerekiyor. Aşağıda ikisinin de
çözümü hazır.

---

## Neden doğrudan olmuyor

**1. HTTPS zorunluluğu.** Lovable uygulaman `https://...lovable.app` üzerinde
çalışır. Tarayıcılar https bir sayfadan http bir adrese istek atmayı engeller
(mixed content). Yani `http://SUNUCU_IP:8080` adresine bağlanamaz.
→ **Çözüm:** Bir alan adı + Caddy reverse proxy (repoda hazır).

**2. CORS.** Freqtrade, tanımadığı bir web adresinden gelen isteği reddeder.
→ **Çözüm:** Lovable uygulamanın adresini `CORS_origins` listesine eklemek.

---

## Kurulum

### 1. Alan adı yönlendir

Bir alan adı al (ya da mevcut birinin alt alan adını kullan) ve **A kaydını**
sunucunun IP adresine yönlendir:

```
bot.senindomainin.com  →  A  →  1.2.3.4
```

### 2. `.env` dosyasına ekle

```bash
API_DOMAIN=bot.senindomainin.com
```

### 3. CORS'a Lovable adresini ekle

`user_data/config.json` içinde:

```json
"CORS_origins": [
    "https://senin-projen.lovable.app",
    "http://localhost:8080"
]
```

> Lovable'da projeni yayınladıktan sonra gerçek adresini buraya yaz.
> Özel alan adı bağladıysan onu da ekle.

### 4. Proxy ile başlat

```bash
docker compose --profile lovable up -d
```

Caddy sertifikayı Let's Encrypt'ten otomatik alır. Birkaç saniye içinde
`https://bot.senindomainin.com/api/v1/ping` çalışıyor olmalı.

---

## Lovable'a verecek prompt

Aşağıdakini Lovable'a olduğu gibi yapıştırabilirsin. `API_URL` kısmını
kendi alan adınla değiştir.

---

> Bir kripto işlem botu kontrol paneli yap. Backend olarak freqtrade REST API
> kullanılacak: `https://bot.senindomainin.com/api/v1`
>
> **Kimlik doğrulama:**
> `POST /token/login` — HTTP Basic Auth (kullanıcı adı + şifre) ile çağrılır,
> `{ access_token, refresh_token }` döner. Sonraki tüm isteklerde
> `Authorization: Bearer {access_token}` header'ı gönderilir.
> Access token 15 dakikada bir dolar; `POST /token/refresh` ile
> (refresh token'ı Bearer olarak göndererek) yenilenir. Otomatik yenileme yap.
>
> **Ekranlar:**
>
> 1. **Giriş** — kullanıcı adı/şifre formu, token'ları güvenli sakla.
>
> 2. **Panel (ana ekran)**
>    - `GET /status` → açık pozisyonlar. Her kart için: çift, yön (long/short),
>      giriş fiyatı, güncel fiyat, kâr/zarar (yüzde ve tutar), açık kalma süresi,
>      stop seviyesi. Kâr yeşil, zarar kırmızı.
>    - `GET /profit` → toplam kâr/zarar, kazanan/kaybeden işlem sayısı,
>      en iyi ve en kötü işlem. Üstte özet kartları olarak.
>    - `GET /balance` → bakiye.
>    - `GET /count` → açık işlem sayısı / maksimum.
>    - 5 saniyede bir otomatik yenile.
>
> 3. **Geçmiş**
>    - `GET /trades?limit=50` → kapanmış işlemler tablosu. Sütunlar: çift, yön,
>      giriş/çıkış fiyatı, kâr %, çıkış sebebi (exit_reason), süre.
>    - `GET /daily?timescale=30` → günlük kâr/zarar grafiği (çubuk grafik).
>
> 4. **Kontrol**
>    - `POST /start` ve `POST /stop` → botu başlat/durdur (büyük butonlar).
>    - `POST /pause` → yeni giriş yapma.
>    - `POST /forceexit` body `{ "tradeid": "123" }` → pozisyonu kapat.
>      Her açık pozisyon kartında "Kapat" butonu, onay diyaloğu ile.
>    - `POST /forceenter` body `{ "pair": "BTC/USDT:USDT", "side": "long" }`
>      → elle pozisyon aç. `GET /whitelist`'ten gelen çiftlerle dropdown.
>    - `GET /logs` → son log kayıtları, katlanabilir bir panelde.
>
> **Tasarım:** Mobil öncelikli, tek elle kullanılabilir. Koyu tema.
> Alt kısımda sabit navigasyon çubuğu (Panel / Geçmiş / Kontrol).
> Butonlar parmak için yeterince büyük. Sayılar okunaklı ve büyük punto.
> Bot durumu (çalışıyor/durdu) her ekranın üstünde sabit görünsün.
>
> **Önemli:** Para kaybettirebilecek her işlem (pozisyon kapatma, pozisyon açma,
> botu durdurma) için onay diyaloğu koy.

---

## Tam API referansı

| Ne | Metod | Yol |
|---|---|---|
| Sağlık kontrolü (auth gerekmez) | GET | `/api/v1/ping` |
| Giriş | POST | `/api/v1/token/login` |
| Token yenile | POST | `/api/v1/token/refresh` |
| Açık pozisyonlar | GET | `/api/v1/status` |
| İşlem geçmişi | GET | `/api/v1/trades` |
| Tek işlem | GET | `/api/v1/trade/{id}` |
| Kâr/zarar özeti | GET | `/api/v1/profit` |
| Bakiye | GET | `/api/v1/balance` |
| Günlük rapor | GET | `/api/v1/daily?timescale=7` |
| İstatistikler | GET | `/api/v1/stats` |
| Açık/maks işlem | GET | `/api/v1/count` |
| Botu başlat | POST | `/api/v1/start` |
| Botu durdur | POST | `/api/v1/stop` |
| Duraklat | POST | `/api/v1/pause` |
| Elle giriş | POST | `/api/v1/forceenter` |
| Elle çıkış | POST | `/api/v1/forceexit` |
| İşlem çiftleri | GET | `/api/v1/whitelist` |
| Kara liste | GET/POST/DELETE | `/api/v1/blacklist` |
| Ayarları yeniden yükle | POST | `/api/v1/reload_config` |
| Loglar | GET | `/api/v1/logs` |
| Sürüm | GET | `/api/v1/version` |

**Canlı akış (WebSocket):**
`wss://bot.senindomainin.com/api/v1/message/ws?token={WS_TOKEN}`

Abone olmak için:
```json
{ "type": "subscribe", "data": ["whitelist", "analyzed_df"] }
```

`enable_openapi: true` ayarlı olduğu için tam şemayı
`https://bot.senindomainin.com/docs` adresinden de görebilirsin —
Lovable'a bu adresi vermek de işe yarar.

---

## Güvenlik — bunu atlama

Bu API'yi internete açmak, **paranı yönetebilen bir arayüzü internete açmak**
demektir. Minimum önlemler:

1. **Güçlü şifre.** `.env` içindeki `FREQUI_PASSWORD` uzun ve rastgele olsun:
   ```bash
   openssl rand -base64 24
   ```
2. **Bybit API anahtarında para çekme yetkisi olmasın.** Anahtar sızsa bile
   paran çekilemez.
3. **`jwt_secret_key` ve `ws_token` rastgele olsun** — `openssl rand -hex 32`.
4. **Sunucu güvenlik duvarı**: 8080 portunu dışarıya kapat, sadece 80/443 açık
   kalsın. Caddy zaten içeriden freqtrade'e bağlanıyor.
   ```bash
   ufw allow 80
   ufw allow 443
   ufw deny 8080
   ```
5. **Telegram'ı da açık tut.** Arayüzde bir sorun olursa `/stop` ve `/fx`
   komutları yedeğin olur.

---

## Alternatif: Lovable'a hiç gerek yok

Bunu söylemek dürüstlük olur — **FreqUI zaten var ve çalışıyor.** Alan adı,
sertifika, CORS, güvenlik duvarı derdi olmadan `http://SUNUCU_IP:8080`
adresinden tablette açılıyor, Telegram'dan da tam kontrol var.

Lovable'ı şunun için tercih et: arayüzün tam olarak senin istediğin gibi
olmasını istiyorsan, kendi eklemek istediğin görselleştirmeler varsa, ya da
sadece kendi yaptığın bir şeyi kullanmak istiyorsan. Bunlar geçerli sebepler —
ama teknik bir zorunluluk değil.
