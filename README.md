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

## Test Sonuçları (son ölçüm)

`python test_qa.py` ile 7 soruluk bir test seti (4 cevaplanabilir + 3 cevaplanamaz)
çalıştırıldı, art arda 2 kez tekrarlandı:

- **7 / 7 test geçti (iki koşuda da)**
- **Ortalama süre: ~2.5-3.9 saniye/soru** — referans dokümanın hedeflediği 1-3
  saniye aralığına yakın/içinde.

**Geçmişte bulunan ve düzeltilen bir hata:** İlk sürümde, dokümanlarda olmayan bir
konu sorulduğunda (ör. "SQLite nedir?") model bazen doğru şekilde "bilmiyorum"
diyordu, bazen halüsinasyon yapıp uydurma cevap veriyordu (6/7 test, ortalama
~14.5s/soru). Kök neden: bu davranış tamamen modelin talimatı doğru uygulamasına
bağlıydı, ki bu %100 güvenilir değildi. **Çözüm:** Retrieval aşamasında en iyi
(top-1) benzerlik skorunun bir eşiğin (0.55) altında kalıp kalmadığına bakılıyor —
test verisinde cevaplanabilir sorular 0.68-0.78, cevaplanamaz sorular 0.31-0.46
skorluyordu, aralarında net bir boşluk var. Eşiğin altındaki sorular için LLM'e
hiç sorulmadan, doğrudan kod ile "bilmiyorum" mesajı dönülüyor — bu hem
halüsinasyon riskini ortadan kaldırdı hem de bu tür sorularda cevabı neredeyse
anlık hale getirdi (0.05sn).

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
- **Halüsinasyon karşı önlemi (iki katmanlı):** (1) Deterministik katman — retrieval
  skoru `SIMILARITY_THRESHOLD` (0.55) altındaysa LLM'e hiç sorulmadan kod ile
  "bilmiyorum" dönülüyor (birincil, güvenilir savunma). (2) Sistem promptu ayrıca
  modele "sadece bağlamı kullan, yoksa bilmiyorum de" diye talimat veriyor (ikincil,
  eşiğin üstünde kalıp yine de bağlamla alakasız bir soru gelirse yedek savunma).
