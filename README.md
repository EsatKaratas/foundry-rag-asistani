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

## Test Sonuçları

`data/` klasörü şu an yaz okulu programı hakkında 5 gerçek doküman içeriyor (genel
bilgiler, proje seçenekleri, sertifika süreci, staj belgesi süreci, Foundry Local
teknik detayları). `python test_qa.py` ile 9 soruluk bir test seti (6 cevaplanabilir
+ 3 cevaplanamaz) çalıştırıldı:

- **9 / 9 test geçti — art arda 5 bağımsız koşuda da**
- **Ortalama süre: ~6-9 saniye/soru**

### Buraya nasıl gelindi (bulunan ve düzeltilen 4 gerçek hata)

Sistem ilk çalışır hale geldiğinde 6/9 - 8/9 arasında dalgalanıyordu. Kök nedenler
tek tek ölçülerek bulundu:

1. **Chunking hatası — yetim başlık parçaları.** İlk `chunk_text()` sürümü, kısa bir
   başlık satırından sonra uzun bir paragraf gelince başlığı *tek başına* bir parça
   olarak kaydediyordu (ör. sadece `"Yaz Okulu Programi - Genel Bilgiler"`, 35
   karakter). Bu tür kısa parçaların embedding vektörü çok belirsiz oluyor ve
   alakasız sorular dahil **her şeye** orta seviyede benziyor — bu da alakasız
   soruların yanlışlıkla "alakalı" görünmesine yol açıyordu. Düzeltme:
   `MIN_CHUNK_CHARS` altındaki parçalar asla tek başına bırakılmıyor.

2. **Başlık yanlılığı (title bias) — retrieval yanlış parçayı getiriyordu.** Sadece
   her dokümanın ilk parçası başlığı içerdiği için, "Yaz okulu programı kaç hafta
   sürüyor?" sorusunda **beş dokümanın da başlıklı ilk parçası** üst sıraları
   doldurdu ve cevabın gerçekten bulunduğu parça 6. sıraya düştü (yani hiç
   getirilmedi). Düzeltme: doküman başlığı **her parçaya** ekleniyor (contextual
   chunk headers). Aynı soruda doğru parça 6. sıradan 1. sıraya çıktı.

3. **Tek eşiğin yetersizliği.** Başta "retrieval skoru eşiğin altındaysa cevap
   verme" mantığı kuruldu. Ama ölçüldü ki cevaplanabilir (0.37-0.71) ve
   cevaplanamaz (0.26-0.40) soruların skor dağılımları **çakışıyor** — tek bir sabit
   eşik bunları güvenilir ayıramıyor. Düzeltme: üç bölgeli karar mantığı (aşağıda).

4. **Üretim adımında düşünme kaçağı.** `/no_think` yönergesine rağmen model ~3
   koşuda 1 kez uzun iç düşünmeye giriyor, token bütçesi dolmadan cevaba
   ulaşamıyordu. Düzeltme: bu durum tespit edilip daha geniş token bütçesiyle bir
   kez yeniden deneniyor.

5. **Bağlamı kopyalama (testlerin kaçırdığı hata).** Arayüzde manuel deneme
   sırasında görüldü: model soruyu cevaplamak yerine bağlam metnini kelimesi
   kelimesine, üç kez tekrarlayarak yazıyor ve token bütçesi dolana kadar devam
   ediyordu (cevap hem yanlış hem ~100 saniye sürüyordu). Sebep: sistem promptu
   *"hangi kaynak dosyadan yararlandığını belirt"* diyordu ve bağlam
   `[Kaynak: dosya]` blokları halinde veriliyordu — model bunu "blokları olduğu
   gibi yaz" diye yorumluyordu. Düzeltme: açık uzunluk sınırı (en fazla 3 cümle),
   açık "kopyalama" yasağı, kaynak gösterimi için dar tek satırlık format.

   **Bu hata testlerin 9/9 verdiği bir dönemde vardı** — çünkü test yalnızca
   "cevap üretildi mi yoksa 'bilmiyorum' mu dedi" diye bakıyordu, cevabın
   *içeriğine* bakmıyordu. Bu yüzden `test_qa.py`'ye iki kalite kontrolü eklendi:
   (a) cevap uzunluk sınırı, (b) cevabın bağlamdan uzun bir bölümü aynen
   kopyalayıp kopyalamadığının tespiti.

### Ölçüm sırasında öğrenilen bir işletim notu

Art arda çok sayıda test koşusundan sonra GPU belleği dolmaya başlıyor (%94'e kadar
çıktığı gözlemlendi) ve tüm cevap süreleri ~4x yavaşlıyor. Bu bir kod hatası değil;
`foundry server restart` ile servis yeniden başlatılınca süreler normale dönüyor.

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
- **Halüsinasyon karşı önlemi — üç bölgeli alaka kararı:** Getirilen her parça için
  karar şöyle veriliyor:
  - `skor >= 0.50` → kesin alakalı, LLM'e sorulmaz (deterministik + hızlı)
  - `skor < 0.30` → kesin alakasız, LLM'e sorulmaz (deterministik + hızlı)
  - arada (gri bölge) → **alaka denetleyicisine** sorulur

  **Alaka denetleyicisi (relevance grader) neden var:** Küçük dil modelleri
  "bağlamda cevap yoksa cevap verme" gibi *açık uçlu* bir talimatı güvenilir
  uygulayamıyor (test edildi, halüsinasyon yaptı). Ama aynı model, *"bu metin bu
  soruyu cevaplıyor mu? EVET/HAYIR"* şeklindeki **ikili sınıflandırma** görevinde
  belirgin biçimde daha başarılı. Bu yüzden gri bölgedeki her parça ayrı ayrı bu
  soruyla denetleniyor, sadece geçenler cevap üretimine gönderiliyor. (Literatürde
  "retrieval grading" / CRAG deseni olarak biliniyor.)

  **Neden üç bölge, neden hepsini grader'a sormuyoruz:** GPU çıkarımı tam
  deterministik olmadığı için aynı soru farklı koşularda farklı sonuçlanabiliyordu
  (ölçüldü). Skorun net olduğu durumlarda kararı koda bırakmak hem bu kararsızlığı
  ortadan kaldırdı hem de gereksiz LLM çağrılarını eleyerek hızlandırdı.
