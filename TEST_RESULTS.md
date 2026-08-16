# Test Sonuclari — 2026-08-16T15:37:08.351445+00:00

| # | Soru | Beklenen | Sonuc | Sure (sn) | Not |
|---|------|----------|-------|-----------|-----|
| 1 | Valorant kac kisiyle oynanir? | cevaplanabilir | GECTI | 2.46 | cevap uretildi + kaynak gosterildi |
| 2 | Duelist rolunun gorevi nedir? | cevaplanabilir | GECTI | 1.90 | cevap uretildi + kaynak gosterildi |
| 3 | Eco turu ne demek? | cevaplanabilir | GECTI | 2.48 | cevap uretildi + kaynak gosterildi |
| 4 | Keskin nisanci tufeklerinin dezavantaji nedir? | cevaplanabilir | GECTI | 1.80 | cevap uretildi + kaynak gosterildi |
| 5 | Orta bolgeyi kontrol etmek neden onemli? | cevaplanabilir | GECTI | 2.06 | cevap uretildi + kaynak gosterildi |
| 6 | Yeni baslayan biri ajan secerken neye dikkat etmeli? | cevaplanabilir | GECTI | 2.02 | cevap uretildi + kaynak gosterildi |
| 7 | Etkisiz hale getirme islemi yarida kesilirse ne olur? | cevaplanabilir | GECTI | 1.61 | cevap uretildi + kaynak gosterildi |
| 8 | Nihai yetenek nasil hazir hale gelir? | cevaplanabilir | GECTI | 2.57 | cevap uretildi + kaynak gosterildi |
| 9 | Olduktan sonra takim arkadaslarina ne bildirilmeli? | cevaplanabilir | GECTI | 1.66 | cevap uretildi + kaynak gosterildi |
| 10 | Durarak ates etmek neden onemli? | cevaplanabilir | GECTI | 2.05 | cevap uretildi + kaynak gosterildi |
| 11 | Valorant hangi tarihte cikti? | cevaplanamaz | GECTI | 0.07 | dogru sekilde 'bilmiyorum' dedi |
| 12 | Valorant turnuvalarinda odul havuzu ne kadar? | cevaplanamaz | GECTI | 0.08 | dogru sekilde 'bilmiyorum' dedi |
| 13 | Bugun hava nasil? | cevaplanamaz | GECTI | 0.07 | dogru sekilde 'bilmiyorum' dedi |
| 14 | Duelist rolundeki ajanlarin isimleri nelerdir? | cevaplanamaz | GECTI | 1.78 | dogru sekilde 'bilmiyorum' dedi |

**Toplam: 14/14 test gecti.**
**Ortalama sure: 1.62 saniye/soru.**

## Uc Durum Testleri

Referans planin Hafta 5 maddesi: *"It handles edge cases (like empty query input, or very general questions)"*. Olcut: uygulama cokmemeli ve makul bir cevap donmeli (belirli bir cevap sart kosulmuyor).

| # | Girdi | Tur | Sonuc | Sure (sn) | Not |
|---|-------|-----|-------|-----------|-----|
| 1 | '' | bos sorgu | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 2 | '   ' | yalnizca bosluk | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 3 | Bana her seyi anlat | cok genel soru | GECTI | 1.31 | cokmedi, 'bilmiyorum' dondu |

**Uc durum: 3/3 gecti.**

Referans dokuman hedefi: kucuk modeller icin ~1-3 saniye/soru. qwen3-4b bir 'reasoning' modeli oldugu icin (cevap oncesi ic dusunme adimi uretir) bu hedefin uzerinde cikabilir; asagida gercek olculen degerler var.