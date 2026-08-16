# Test Sonuclari — 2026-08-16T14:52:37.203919+00:00

| # | Soru | Beklenen | Sonuc | Sure (sn) | Not |
|---|------|----------|-------|-----------|-----|
| 1 | Valorant kac kisiyle oynanir? | cevaplanabilir | GECTI | 2.51 | cevap uretildi + kaynak gosterildi |
| 2 | Duelist rolunun gorevi nedir? | cevaplanabilir | GECTI | 1.91 | cevap uretildi + kaynak gosterildi |
| 3 | Eco turu ne demek? | cevaplanabilir | GECTI | 1.80 | cevap uretildi + kaynak gosterildi |
| 4 | Keskin nisanci tufeklerinin dezavantaji nedir? | cevaplanabilir | GECTI | 1.65 | cevap uretildi + kaynak gosterildi |
| 5 | Orta bolgeyi kontrol etmek neden onemli? | cevaplanabilir | GECTI | 1.67 | cevap uretildi + kaynak gosterildi |
| 6 | Yeni baslayan biri ajan secerken neye dikkat etmeli? | cevaplanabilir | GECTI | 2.31 | cevap uretildi + kaynak gosterildi |
| 7 | Valorant hangi tarihte cikti? | cevaplanamaz | GECTI | 0.06 | dogru sekilde 'bilmiyorum' dedi |
| 8 | Valorant turnuvalarinda odul havuzu ne kadar? | cevaplanamaz | GECTI | 0.06 | dogru sekilde 'bilmiyorum' dedi |
| 9 | Bugun hava nasil? | cevaplanamaz | GECTI | 0.06 | dogru sekilde 'bilmiyorum' dedi |
| 10 | Duelist rolundeki ajanlarin isimleri nelerdir? | cevaplanamaz | GECTI | 2.06 | dogru sekilde 'bilmiyorum' dedi |

**Toplam: 10/10 test gecti.**
**Ortalama sure: 1.41 saniye/soru.**

## Uc Durum Testleri

Referans planin Hafta 5 maddesi: *"It handles edge cases (like empty query input, or very general questions)"*. Olcut: uygulama cokmemeli ve makul bir cevap donmeli (belirli bir cevap sart kosulmuyor).

| # | Girdi | Tur | Sonuc | Sure (sn) | Not |
|---|-------|-----|-------|-----------|-----|
| 1 | '' | bos sorgu | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 2 | '   ' | yalnizca bosluk | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 3 | Bana her seyi anlat | cok genel soru | GECTI | 3.85 | cokmedi, cevap uretildi |

**Uc durum: 3/3 gecti.**

Referans dokuman hedefi: kucuk modeller icin ~1-3 saniye/soru. qwen3-4b bir 'reasoning' modeli oldugu icin (cevap oncesi ic dusunme adimi uretir) bu hedefin uzerinde cikabilir; asagida gercek olculen degerler var.