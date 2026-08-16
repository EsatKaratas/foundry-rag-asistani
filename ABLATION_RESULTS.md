# Ablasyon Calismasi — 2026-08-16T15:35:50.485294+00:00

Her savunma katmani tek tek kapatilip testin ne kadar bozuldugu olculdu.
Amac, her tasarim kararinin gercekten gerekli oldugunu gostermek: bir
katman kapatildiginda sonuc degismiyorsa o katman gereksizdir.

> **Sure sutunu hakkinda uyari:** Foundry Local arka arkaya cok istek
> alinca GPU bellegi biriktiriyor (olculdu: tek test kosusu 5.6 GB -> 7.8 GB)
> ve uretim sureleri 3-5 kat yavasliyor. Bu calisma tek oturumda alt alta
> kostugu icin ASAGI SATIRLARDAKI sureler sistematik olarak sisiktir;
> yapilandirmalar arasinda sure karsilastirmasi yapmayin. Gecti/kaldi
> sonuclari bundan etkilenmez. Temiz durumda olculen referans deger:
> **1.43 sn/soru** (tam sistem).

| Yapilandirma | Ana test | Uc durum | Ort. sure | Katkisi | Aciklama |
|---|---|---|---|---|---|
| Tam sistem | 14/14 | 3/3 | 1.56 sn | referans | dort savunma katmani da acik |
| Sozcuksel kapi KAPALI | 13/14 | 3/3 | 1.91 sn | **1 vaka** | kosinus + LLM denetleyici + sayi kontrolu var |
| LLM alaka denetleyicisi KAPALI | 14/14 | 3/3 | 1.17 sn | 0 vaka | getirilen her parca kabul ediliyor |
| Sayi dogrulamasi KAPALI | 14/14 | 3/3 | 1.55 sn | 0 vaka | uretim sonrasi sayi dayanagi yok |
| Ozel isim kontrolu KAPALI | 13/14 | 3/3 | 1.55 sn | **1 vaka** | uretim sonrasi ozel isim dayanagi yok |
| Kosinus esigi KAPALI | 14/14 | 3/3 | 1.57 sn | 0 vaka | dusuk skorlu parcalar da elenmiyor |
| Ciplak RAG | 11/14 | 3/3 | 1.16 sn | **3 vaka** | hicbir savunma yok - getir + uret |

## Kapatildiginda kaybedilen vakalar

**Tam sistem:** kaybedilen vaka yok.

**Sozcuksel kapi KAPALI:**

- `Valorant turnuvalarinda odul havuzu ne kadar?` — BEKLENMEDIK: uydurma cevap verdi

**LLM alaka denetleyicisi KAPALI:** kaybedilen vaka yok.

**Sayi dogrulamasi KAPALI:** kaybedilen vaka yok.

**Ozel isim kontrolu KAPALI:**

- `Duelist rolundeki ajanlarin isimleri nelerdir?` — BEKLENMEDIK: uydurma cevap verdi

**Kosinus esigi KAPALI:** kaybedilen vaka yok.

**Ciplak RAG:**

- `Valorant hangi tarihte cikti?` — BEKLENMEDIK: uydurma cevap verdi
- `Bugun hava nasil?` — BEKLENMEDIK: uydurma cevap verdi
- `Duelist rolundeki ajanlarin isimleri nelerdir?` — BEKLENMEDIK: uydurma cevap verdi
