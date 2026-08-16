# Yerel RAG Doküman Asistanı — Valorant Bilgi Asistanı

Microsoft Foundry Local, SQLite ve RAG (Retrieval-Augmented Generation) deseni kullanan,
tamamen çevrimdışı çalışan bir soru-cevap asistanı. Kullanıcının kendi dokümanlarına
dayanarak soru cevaplar; internet bağlantısı veya bulut hesabı gerektirmez.

Bu projede bilgi tabanı olarak **Valorant** oyunu hakkında hazırlanmış dokümanlar
kullanılıyor (oyun temelleri, ajan rolleri, ekonomi sistemi, silah kategorileri,
harita yapısı, yeni başlayan rehberi). Bilgi tabanını değiştirmek için `data/`
klasöründeki `.txt` dosyalarını değiştirip `python ingest.py` çalıştırmak yeterli.

**Arayüz özellikleri:** sohbet geçmişi (oturum boyunca önceki sorular korunur) ve
cevabın token token akması (streaming).

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
| `lexical_gate.py` | Sözcüksel alaka kapısı — konu kaymasını deterministik olarak yakalar |
| `app.py` | Streamlit arayüzü + LLM entegrasyonu (RAG'ın "generate" adımı) |
| `test_qa.py` | Fonksiyonel test seti — cevaplanabilir/cevaplanamaz sorularla doğrulama |
| `data/` | Kaynak dokümanlar (.txt) |
| `TEST_RESULTS.md` | Son test koşusunun sonuçları (otomatik üretilir) |

## En değerli bulgu: popüler bir konuya geçince ne değişti

Bilgi tabanı yaz okulu dokümanlarından **Valorant**'a çevrildiğinde, daha önce
9/9 geçen sistem 7/9'a düştü. Sebep tek bir hata değil, RAG'in temel bir
zorluğuydu:

**1. Kosinüs eşiği korpusa bağımlıymış.** Karışık konulu bir doküman setinde
(her dosya farklı konu) 0.50 eşiği çalışıyordu. Ama tüm dokümanlar tek bir konu
hakkında olduğunda, kosinüs skoru artık "bu parça soruyu cevaplıyor mu"yu değil
sadece "bu metin Valorant hakkında mı"yı ölçüyor. Dokümanlarda cevabı olmayan
sorular bile 0.53-0.60 skorluyordu.

**2. Model konuyu zaten biliyordu.** Yaz okulu dokümanlarında bu sorun yoktu
çünkü model o programı hiç bilmiyordu. Valorant popüler bir oyun olduğu için
model, bağlamda olmayan bilgiyi kendi eğitim verisinden verebiliyordu
("Valorant 2020'de çıktı" — doğru bilgi, ama bizim dokümanlarımızda yok).

**3. Modelin kendi halüsinasyonunu kendisine denetletmek işe yaramadı.** Üretim
sonrası bir "dayanak kontrolü" (groundedness check) eklendi: *"cevaptaki bilgi
bağlamda geçiyor mu?"* Sonuç: model kendi ürettiği yanlış cevabı **"evet,
dayanaklı"** diye onayladı. Sebebi açık — o bilgiyi bağımsız olarak "bildiği"
için kontrol katmanı da aynı yanılgıya düşüyor.

**Çözüm — modelden bağımsız, deterministik doğrulama:** Sayılar (tarih, fiyat,
adet) halüsinasyonun en sık görüldüğü bilgi tipidir ve modele hiç sormadan,
kodla kesin olarak kontrol edilebilir. Cevapta bağlamda hiç geçmeyen bir sayı
varsa cevap reddediliyor. Bu, "2020" hatasını kesin olarak çözdü.

**Alınan ders:** LLM tabanlı kontroller olasılıksaldır ve aynı modelin kendi
hatasını yakalaması beklenemez. Kesin olarak doğrulanabilen şeyler (sayılar,
tarihler, isimler) kodla kontrol edilmelidir.

## Test Sonuçları

`data/` klasörü Valorant hakkında 6 doküman içeriyor. `python test_qa.py` ile
9 soruluk bir ana test seti (6 cevaplanabilir + 3 cevaplanamaz) ve ayrıca 3 uç
durum vakası çalıştırıldı:

- **9 / 9 ana test geçti** — 3 ardışık koşuda kararlı
- **3 / 3 uç durum testi geçti** (boş sorgu, yalnızca boşluk, çok genel soru)
- **Ortalama süre: 1.36 - 1.52 saniye/soru** — referans dokümanın hedeflediği
  1-3 saniye aralığının içinde. Cevaplanamaz sorular **0.06 saniyede** reddediliyor,
  çünkü sözcüksel kapı hiçbir LLM çağrısı yapmadan karar veriyor.

**Uç durumlar neden ayrı bölümde:** bu girdiler için "doğru cevap" tek bir şey
değil; referans plan yalnızca sistemin bunları sağlıklı karşılamasını istiyor,
belirli bir cevap şart koşmuyor. Ölçüt: **çökmedi + makul cevap döndü**. Ana sete
"bilmiyorum demeli" beklentisiyle konsalardı, "Bana her şeyi anlat" gibi genel bir
soru 0.30-0.75 gri bölgesine düşüp alaka denetleyicisine gider ve GPU çıkarımı tam
deterministik olmadığı için sonuç koşudan koşuya değişebilirdi.

**Uzun süre çözülemeyen sınır durum ve nasıl çözüldüğü:** "Valorant turnuvalarında
ödül havuzu ne kadar?" sorusuna sistem uzunca bir süre "bilmiyorum" demek yerine
oyun içi ekonomi sistemini anlatıyordu. Bu bir **halüsinasyon değildi** — verilen
bilgi doğruydu ve dokümanlarda gerçekten vardı. Sorun, sorulan sorunun değil
semantik olarak yakın başka bir sorunun cevaplanmasıydı (**konu kayması**).

Bu hata ne eşik ayarıyla ne de alaka denetleyicisiyle çözülebiliyordu, çünkü ikisi
de aynı şeye bakıyor: anlamsal yakınlık. Çözüm bu yüzden farklı bir sinyalden geldi
— aşağıdaki **sözcüksel kapı** bölümüne bakın. Ölçüm: "turnuva" ve "ödül"
kelimeleri korpusta **hiç geçmiyor**, dolayısıyla getirilen metin bu soruyu
cevaplıyor olamaz. Bu kapı eklendikten sonra test 9/9'a çıktı.

Güncel sonuçlar için `TEST_RESULTS.md` dosyasına bakın.

## Tasarım Kararları ve Kısıtlar

- **Vektör arama:** SQLite'ın native vektör tipi yok; embedding'ler JSON-serileştirilmiş
  metin olarak saklanıyor, benzerlik hesaplaması (kosinüs) Python/NumPy ile brute-force
  yapılıyor. Küçük veri setleri (birkaç yüz parça) için yeterli; büyük ölçekte özel bir
  vektör indeksi (FAISS, pgvector vb.) gerekir.
- **Neden `foundry-local-sdk` yerine `openai` istemcisi:** `foundry-local-sdk` kendini
  *"control-plane SDK"* olarak tanımlıyor ve `FoundryLocalManager` sınıfı yalnızca
  model/servis yönetimi metotları içeriyor (`discover_eps`,
  `download_and_register_eps`, `start_web_service`, `stop_web_service`); **çıkarım
  (inference) için hiçbir metodu yok** ve paketin kendi bağımlılıkları arasında zaten
  `openai` var. Foundry Local servisi OpenAI-uyumlu bir yerel REST ucu açtığı için
  (`http://127.0.0.1:<port>/v1`), çıkarım doğrudan `openai` istemcisiyle bu uca
  yapılıyor — yani SDK atlanmış değil, SDK'nın da kullandığı çıkarım yolu doğrudan
  kullanılıyor. Servis yönetimi (port keşfi, model yükleme) ise `foundry` CLI
  üzerinden yapılıyor: servisin portu her başlatmada değişebiliyor, bu yüzden
  `foundry server status -o json` çıktısındaki `webUrls` alanı okunuyor.

- **`/no_think` yönergesi:** `qwen3-4b` bir "reasoning" modeli olduğu için varsayılan
  olarak cevaptan önce uzun bir iç düşünme adımı üretiyor. Bu hem yavaşlığa hem de
  (bazı sorularda) düşünme döngüsüne girip hiç bitirmeme riskine yol açtı. Sistem
  promptuna `/no_think` eklenerek bu adım kapatıldı — süre ortalama ~10 kat kısaldı.
- **`max_tokens` sınırı:** Modelin sınırsız üretim yapmasını önlemek için bir güvenlik
  sınırı olarak tutuluyor.
- **Çıktı temizleme:** Model bazen Türkçe cevap içine tek karakterlik CJK (Çince/Japonca/
  Korece) karakterler sıkıştırıyor (gözlemlenen bir küçük-model kusuru); bu karakterler
  cevap gösterilmeden önce regex ile temizleniyor.
- **Sözcüksel kapı (hibrit arama) — konu kaymasının deterministik çözümü:**
  Kosinüs benzerliği anlamsal yakınlık ölçer. Tek konulu bir korpusta bu, *"bu parça
  soruyu cevaplıyor mu"*yu değil *"bu metin aynı konu hakkında mı"*yı ölçmeye başlar.
  Eşik ayarı bu sorunu çözmez, çünkü eşik de aynı sinyale bakar.

  Çözüm, **farklı bir sinyal** eklemekten geldi: sorunun ayırt edici kelimelerinden
  en az biri getirilen metinde geçmiyorsa, o metin bu soruyu cevaplıyor olamaz.
  Ölçülen örnek: `turnuva` ve `ödül` kelimeleri korpusta **hiç geçmiyor** — yani
  sistemin bu soruyu cevaplayabilmesi mümkün değil, ne kadar "yakın" görünürse
  görünsün. (Literatürde **hibrit arama**: yoğun/embedding + seyrek/sözcüksel.)

  *"Ayırt edici"* tanımı kritik: `valorant` kelimesi her dokümanda geçtiği için
  hiçbir şey ayırt etmiyor, bu yüzden doküman frekansı yüksek kelimeler eleniyor
  (klasik **IDF** fikrinin sade bir uygulaması). Türkçe için iki uyarlama gerekti:
  (1) dokümanlar Türkçe karaktersiz yazılmış ama kullanıcı arayüze `görevi` diye
  yazıyor → iki taraf da normalize ediliyor; (2) Türkçe sondan eklemeli
  (`turnuva` → `turnuvalarında`) → tam kelime yerine ilk 5 karakterlik kaba gövde
  karşılaştırılıyor.

  Kapı **tolerelı** tasarlandı: tek eşleşme yeterli. Amaç geçerli soruları elemek
  değil, hiçbir sözcüksel dayanağı olmayanları yakalamak. Sorunun hiç ayırt edici
  kelimesi yoksa ("Bana her şeyi anlat") kapı karar veremez ve geçirir.
  Entegrasyondan önce 6 cevaplanabilir + 3 cevaplanamaz soruya karşı ayrı ayrı
  ölçüldü: **0 yanlış eleme**, 3 cevaplanamaz sorunun 3'ü de elendi.

  İki kazanç: test 8/9 → **9/9**, ve kapı LLM çağrısından önce çalıştığı için
  cevaplanamaz sorular **2.1 saniye yerine 0.06 saniyede** reddediliyor.

- **Halüsinasyon karşı önlemi — üç bölgeli alaka kararı:** Sözcüksel kapıyı geçen
  parçalar için karar şöyle veriliyor:
  - `skor >= 0.75` → kesin alakalı, LLM'e sorulmaz (deterministik + hızlı)
  - `skor < 0.30` → kesin alakasız, LLM'e sorulmaz (deterministik + hızlı)
  - arada (gri bölge) → **alaka denetleyicisine** sorulur

  **Alaka denetleyicisi (relevance grader) neden var:** Küçük dil modelleri
  "bağlamda cevap yoksa cevap verme" gibi *açık uçlu* bir talimatı güvenilir
  uygulayamıyor (test edildi, halüsinasyon yaptı). Ama aynı model, *"bu metin bu
  soruyu cevaplıyor mu? EVET/HAYIR"* şeklindeki **ikili sınıflandırma** görevinde
  belirgin biçimde daha başarılı. Bu yüzden gri bölgedeki her parça ayrı ayrı bu
  soruyla denetleniyor, sadece geçenler cevap üretimine gönderiliyor. (Literatürde
  "retrieval grading" / CRAG deseni olarak biliniyor.)

  **Neden üç bölge:** GPU çıkarımı tam deterministik olmadığı için aynı soru farklı
  koşularda farklı sonuçlanabiliyor. Skorun net olduğu durumlarda kararı koda bırakmak
  hem bu kararsızlığı azaltıyor hem de gereksiz LLM çağrılarını eleyerek hızlandırıyor.
  Üst eşik başta 0.50'ydi; tek konulu (Valorant) bir korpusta bunun yetersiz kaldığı
  ölçülüp 0.75'e çıkarıldı (bkz. "En değerli bulgu" bölümü).

- **Dayanak kontrolü (son savunma katmanı):** Üretilen cevapta, bağlamda hiç geçmeyen
  bir sayı varsa cevap reddedilip "bilmiyorum" dönülüyor. Bu kontrol bilinçli olarak
  **deterministiktir** — LLM'e sorulan bir dayanak kontrolü denendi ve model kendi
  halüsinasyonunu onayladığı için başarısız oldu.

- **Kaynak gösterimi de deterministik:** Sistem promptunun 5. kuralı modelden cevabın
  sonuna `(Kaynak: dosya.txt)` satırını eklemesini istiyor. Teste bu kural için bir
  doğrulama eklendiğinde ölçüldü ki **model bunu cevapların yaklaşık üçte birinde
  atlıyor** (6 cevaplanabilir sorudan 2'sinde). Kaynak dosya adı retrieval aşamasından
  zaten elimizde olduğu için, satır eksikse kodla ekleniyor
  (`ensure_source_citation`). Prompt kuralı yine duruyor; model kendiliğinden doğru
  yazdığında bu fonksiyon hiçbir şey yapmıyor. Aynı ilke: kesin bilinen bir bilgi
  modelden istenmez, kodla yazılır.

- **Uç durumlar:** Boş sorgu, yalnızca boşluk içeren sorgu ve çok genel sorular
  `test_qa.py` içinde ayrı bir bölümde test ediliyor (3/3 geçti).

- **Boş sorgu koruması:** Boş veya yalnızca boşluk içeren bir sorgu doğrudan embedding
  API'sine gittiğinde Foundry Local HTTP 400 dönüyor
  (`Embedding input at index 0 is null, empty...`) ve bu yakalanmayan bir exception
  olarak uygulamayı çökertiyordu. Arayüzden tetiklenmiyordu (`st.chat_input` boş girdi
  göndermiyor), ancak fonksiyon doğrudan çağrıldığında çöküyordu. Kontrol
  `retrieve_and_gate()` başına konuldu — hem akışsız (test) hem akışlı (arayüz) yol
  buradan geçiyor.

## Kaynaklar

Bu proje, Microsoft yaz okulu programının referans planına ("One-Month Project Plan:
Local RAG AI Assistant with Microsoft Foundry Local") göre geliştirildi. Planın
işaret ettiği kaynaklar:

**Ana referans (topluluk içeriği):**
- [Building Your First Local RAG Application with Foundry Local](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/building-your-first-local-rag-application-with-foundry-local/4501968)
  — Microsoft Tech Community

**Resmi Microsoft Learn dokümantasyonu:**
- [What is Foundry Local?](https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local)
- [Foundry Local dokümantasyonu](https://learn.microsoft.com/en-us/azure/foundry-local/)
  — kurulum ve "Get started" adımları
- [Tutorial: Build a RAG application](https://learn.microsoft.com/en-us/azure/foundry-local/tutorials/tutorial-build-rag-app)
  — özellikle "Generate document embeddings" ve "Search for relevant documents"
  bölümleri; bu projedeki `get_top_chunks()`, tutorial'daki `find_relevant()`
  fonksiyonunun SQLite'a taşınmış hâli
- [Prompt engineering techniques](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/prompt-engineering)
  — sistem mesajı tasarımı ve prompt kurgusunun temelleri
- [Tutorial: Use a SQLite database in a Windows app](https://learn.microsoft.com/en-us/windows/apps/develop/data-access/sqlite-data-access)
  — SQLite'ın yerel depolama için avantajları

**Diğer:**
- [SQLite resmi dokümantasyonu](https://www.sqlite.org/) — veritabanı motoru
