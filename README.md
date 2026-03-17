# 🐋 WhaleBot — Binance Testnet Balina Kopyacı Bot

Gerçek zamanlı Binance WebSocket verisiyle çalışan, 5 katmanlı anti-manipülasyon filtresi olan, Railway'de tek tıkla deploy edilebilen BTC/USDT balina kopyacı bot.

---

## Sistem Mimarisi

```
Binance WebSocket (aggTrade + depth)
          │
          ▼
   [Whale Detector]          → Büyük işlem, hacim spike, iceberg, imbalance tespiti
          │
          ▼
   [Signal Engine]           → Sinyalleri birleştirir, min 2 aynı yön gerekli
          │
          ▼
   [Anti-Manip Engine]       → 5 filtre: spoof / wash / stop-hunt / news-lock / layering
          │
          ▼
   [Risk Manager]            → Kelly criterion, günlük kayıp kilidi, TP/SL takibi
          │
          ▼
   [FastAPI + Dashboard]     → Tarayıcıdan canlı izleme
```

---

## Dosya Yapısı

```
whale-bot/
├── main.py            ← Railway başlangıç noktası
├── server.py          ← FastAPI server + Dashboard HTML
├── railway.toml       ← Railway deploy konfigürasyonu
├── Procfile           ← Alternatif başlatma komutu
├── requirements.txt   ← Python bağımlılıkları
├── .env.example       ← API key şablonu
└── src/
    ├── __init__.py
    ├── config.py      ← Tüm ayarlar + veri modelleri
    ├── engine.py      ← WebSocket döngüleri + orkestrasyon
    ├── detector.py    ← Balina dedektörü + sinyal motoru
    ├── anti_manip.py  ← Anti-manipülasyon filtreleri
    └── risk.py        ← Risk yönetimi + trade engine
```

---

## Railway'e Deploy (Adım Adım)

### Adım 1 — Testnet API Key al (ücretsiz, 5 dakika)

1. https://testnet.binance.vision adresine git
2. GitHub hesabınla giriş yap
3. **Generate HMAC_SHA256 Key** butonuna tıkla
4. API Key ve Secret Key'i kopyala, kaydet

> ⚠️ Testnet key'leri gerçek para içermez. Tamamen güvenlidir.

### Adım 2 — GitHub'a yükle

```bash
cd whale-bot
git init
git add .
git commit -m "whale bot v1"
# GitHub'da yeni repo oluştur, sonra:
git remote add origin https://github.com/KULLANICI_ADIN/whale-bot.git
git push -u origin main
```

### Adım 3 — Railway'de deploy et

1. https://railway.app → **New Project**
2. **Deploy from GitHub repo** → repoyu seç
3. Railway otomatik `railway.toml`'u okur, build başlar (~1-2 dakika)

### Adım 4 — API Key'leri ekle

Railway panelinde projeyi seç → **Variables** sekmesi → **New Variable**:

```
BINANCE_TESTNET_KEY     =  (Adım 1'de aldığın API Key)
BINANCE_TESTNET_SECRET  =  (Adım 1'de aldığın Secret Key)
```

Değişkenleri ekledikten sonra Railway otomatik restart yapar.

### Adım 5 — Dashboard'u aç

Railway panelinde **Settings → Networking → Public Domain** altında URL'yi bul:
```
https://whale-bot-xxxx.up.railway.app
```
Bu URL'yi tarayıcıda aç — dashboard canlı!

---

## Lokal Çalıştırma (isteğe bağlı)

```bash
# Bağımlılıkları kur
pip install -r requirements.txt

# .env dosyası oluştur
cp .env.example .env
# .env içine gerçek testnet key'lerini yaz

# Botu başlat
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Tarayıcıda aç:
# http://localhost:8000
```

---

## Ayarlar (src/config.py)

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| `SYMBOL` | `BTCUSDT` | İzlenecek parite |
| `WHALE_BTC_THRESHOLD` | `5.0` | Balina sayılacak minimum BTC |
| `MIN_SIGNALS` | `2` | İşlem için minimum sinyal sayısı |
| `STOP_LOSS_PCT` | `0.8` | Stop loss yüzdesi |
| `TAKE_PROFIT_PCT` | `1.6` | Take profit yüzdesi (2:1 RR) |
| `DAILY_LOSS_LIMIT_PCT` | `3.0` | Günlük kayıp kilidi |
| `SPOOF_MIN_LIFETIME_SEC` | `30` | Emir en az bu kadar yaşamalı |
| `NEWS_LOCKOUT_SEC` | `90` | Haber sonrası bekleme süresi |

---

## Anti-Manipülasyon Filtreleri

| Filtre | Ne Tespit Eder | Severity |
|---|---|---|
| **Spoof Detector** | 30 saniyeden kısa yaşayan büyük emir duvarları | HIGH |
| **Wash Trade** | 3 saniye içinde aynı büyüklükte karşılıklı işlemler | MEDIUM |
| **Stop Hunt Radar** | Round number ($95,000, $94,500) yakınındaki fiyat | MEDIUM |
| **News Lockout** | Volatilite spike sonrası 90 saniye kilit | HIGH |
| **Layering Checker** | 5 dakikada 8+ seviye çekilmesi | HIGH |

---

## DEMO Modu

`BINANCE_TESTNET_KEY` ortam değişkeni yoksa veya `DEMO` ise:
- Binance WebSocket'e **bağlanır** (gerçek piyasa verisi akar)
- Tüm sinyalleri ve flagleri **üretir**
- Dashboard **tam çalışır**
- Sadece gerçek işlem **açmaz** (paper trading simülasyonu devam eder)

---

## Güvenlik Notları

- Bu bot **testnet** içindir. Gerçek para kullanmak için ek güvenlik önlemleri gerekir.
- API key'lerini asla koda yazmayın, her zaman environment variable kullanın.
- `.env` dosyasını Git'e commit etmeyin (.gitignore'da zaten var).
- Railway'de Variables paneli şifreli saklanır.

---

## Lisans

MIT — Eğitim ve araştırma amaçlıdır. Gerçek para riski tamamen kullanıcıya aittir.
