# Yerel RAG Doküman Asistanı

Microsoft Foundry Local, SQLite ve RAG (Retrieval-Augmented Generation) deseni kullanan,
tamamen çevrimdışı çalışan bir soru-cevap asistanı. Kullanıcının kendi dokümanlarına
(ders notu, kılavuz, SSS vb.) dayanarak soru cevaplar; internet bağlantısı veya bulut
hesabı gerektirmez.

Bu proje, Microsoft'un yaz stajı/yaz okulu programı kapsamında, "Building Your First
Local RAG Application with Foundry Local" referans dokümanına göre geliştirilmiştir.

## Mimari

```
Kullanıcı (Streamlit arayüzü)
        │
        ▼
  answer_query()  ──────────────►  retrieval.py (get_top_chunks)
   (app.py)                              │
        │                                ▼
        │                        SQLite (rag.db) — dokuman parçaları + embedding vektörleri
        │                                ▲
        ▼                                │
  Foundry Local (qwen3-4b, sohbet)       ingest.py (dokümanları parçalayıp vektörleştirir)
  http://127.0.0.1:<port>/v1             │
        ▲                                ▼
        └──────── Foundry Local (qwen3-embedding-0.6b, embedding) ────────┘
```

- **İstemci katmanı:** Streamlit arayüzü (`app.py`)
- **Pipeline katmanı:** `answer_query()` — retrieval + prompt oluşturma + LLM çağrısı
- **Veri katmanı:** SQLite (`rag.db`), tek tablo: `chunks(id, source, chunk_index, content, embedding)`
- **AI katmanı:** Microsoft Foundry Local, yerel OpenAI-uyumlu bir REST servisi sunar

## Kullanılan Modeller

| Model | Görev | Boyut |
|---|---|---|
| `qwen3-4b` | Sohbet / cevap üretme | 2.6 GB |
| `qwen3-embedding-0.6b` | Embedding (metin → vektör) | 478 MB |

**Not — model seçimi:** Referans doküman `phi-3.5-mini` öneriyordu; test sırasında bu
modelin Türkçe cevaplarda tutarsız/halüsinasyonlu olduğu tespit edildi (İngilizce'de
sorun yoktu). Bu yüzden `qwen3-4b`'ye geçildi.

## Kurulum

```bash
# 1) Foundry Local'i kur (bir kere)
winget install Microsoft.FoundryLocal

# 2) Bağımlılıkları kur
pip install -r requirements.txt

# 3) Foundry Local servisini başlat
foundry server start

# 4) Modelleri indir ve belleğe yükle (bir kere)
foundry model download qwen3-4b
foundry model download qwen3-embedding-0.6b
foundry model load qwen3-4b
foundry model load qwen3-embedding-0.6b
```

## Çalıştırma

```bash
# Dokümanları işle (data/*.txt -> rag.db)
python ingest.py

# Arayüzü başlat
python -m streamlit run app.py
```

Tarayıcıda `http://localhost:8501` açılır. Kendi dokümanlarını eklemek için `data/`
klasörüne `.txt` dosyaları koyup `python ingest.py`'ı tekrar çalıştırmak yeterli
(veritabanı her seferinde sıfırdan oluşturulur).

## Dosya Yapısı

| Dosya | Görev |
|---|---|
| `common.py` | Foundry Local servisine bağlanma (dinamik port keşfi), model isimleri |
| `ingest.py` | Dokümanları parçalayıp (chunk) vektörleştirip SQLite'a yazar |
| `retrieval.py` | Soruyu vektörleştirip kosinüs benzerliğiyle en alakalı parçaları bulur |
| `app.py` | Streamlit arayüzü + LLM entegrasyonu (RAG'ın "generate" adımı) |
| `test_qa.py` | Fonksiyonel test seti — cevaplanabilir/cevaplanamaz sorularla doğrulama |
| `data/` | Kaynak dokümanlar (.txt) |
| `TEST_RESULTS.md` | Son test koşusunun sonuçları (otomatik üretilir) |

## Test Sonuçları (son ölçüm, gerçek proje dokümanlarıyla)

`data/` klasörü şu an yaz okulu programı hakkında 5 gerçek doküman içeriyor (genel
bilgiler, proje seçenekleri, sertifika süreci, staj belgesi süreci, Foundry Local
teknik detayları). `python test_qa.py` ile 9 soruluk bir test seti (6 cevaplanabilir
+ 3 cevaplanamaz) çalıştırıldı:

- **8 / 9 test geçti**
- **Ortalama süre: ~19 saniye/soru** (çoğu soru 6-10 saniye; bazı sorular modelin
  "düşünme"ye kaçması nedeniyle daha uzun sürdü)

**Bilinen, çözülemeyen 1 sınır durum:** "Python nasıl öğrenilir?" (dokümanlarda
olmayan bir soru) bu koşuda halüsinasyon yaptı. Sebebini ölçtük: bu sorunun
retrieval skoru (0.4386), gerçekten cevaplanabilir bir sorunun skoruyla (0.4414,
"İletişim için hangi kanal kullanılıyor?") neredeyse birebir aynı — aralarında
0.003 fark var. Yani **bu iki soru, embedding modelinin gözünde istatistiksel
olarak ayırt edilemeyecek kadar yakın**; hiçbir sabit eşik ikisini güvenilir
şekilde ayıramaz. Bu, gerçek bir mühendislik sınırı olarak kabul edildi, gizlenmedi.

Güncel sonuçlar için `TEST_RESULTS.md` dosyasına bakın.

## Tasarım Kararları ve Kısıtlar

- **Vektör arama:** SQLite'ın native vektör tipi yok; embedding'ler JSON-serileştirilmiş
  metin olarak saklanıyor, benzerlik hesaplaması (kosinüs) Python/NumPy ile brute-force
  yapılıyor. Küçük veri setleri (birkaç yüz parça) için yeterli; büyük ölçekte özel bir
  vektör indeksi (FAISS, pgvector vb.) gerekir.
- **`/no_think` yönergesi:** `qwen3-4b` bir "reasoning" modeli olduğu için varsayılan
  olarak cevaptan önce uzun bir iç düşünme adımı üretiyor. Bu hem yavaşlığa hem de
  (bazı sorularda) düşünme döngüsüne girip hiç bitirmeme riskine yol açtı. Sistem
  promptuna `/no_think` eklenerek bu adım kapatıldı — süre ortalama ~10 kat kısaldı.
- **`max_tokens` sınırı:** Modelin sınırsız üretim yapmasını önlemek için bir güvenlik
  sınırı olarak tutuluyor.
- **Çıktı temizleme:** Model bazen Türkçe cevap içine tek karakterlik CJK (Çince/Japonca/
  Korece) karakterler sıkıştırıyor (gözlemlenen bir küçük-model kusuru); bu karakterler
  cevap gösterilmeden önce regex ile temizleniyor.
- **Halüsinasyon karşı önlemi (iki katmanlı, ikisi de mükemmel değil):** (1)
  Deterministik katman — retrieval skoru `SIMILARITY_THRESHOLD` (0.40) altındaysa
  LLM'e hiç sorulmadan kod ile "bilmiyorum" dönülüyor; bu, AÇIKÇA alakasız
  soruları güvenilir şekilde yakalıyor. (2) Sistem promptu ayrıca modele "sadece
  bağlamı kullan, yoksa bilmiyorum de" diye talimat veriyor; bu, eşiğin hemen
  üstünde kalan sınır durumlar için ikincil bir savunma ama %100 güvenilir değil
  (bkz. Test Sonuçları). **Eşik neden 0.40 (0.55 değil):** Veri seti 2 dokümandan
  5 dokümana çıkınca skor dağılımı değişti — bazı gerçek cevaplanabilir sorular
  0.44-0.50 aralığına düşebiliyor, bu yüzden eşik düşürüldü ve sınır durumlar
  modelin talimat takibine bırakıldı.
