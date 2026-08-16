# Test Sonuclari — 2026-08-16T18:20:51.554313+00:00

| # | Soru | Beklenen | Sonuc | Sure (sn) | Not |
|---|------|----------|-------|-----------|-----|
| 1 | Valorant kac kisiyle oynanir? | cevaplanabilir | GECTI | 2.37 | cevap uretildi + kaynak gosterildi |
| 2 | Duelist rolunun gorevi nedir? | cevaplanabilir | GECTI | 1.48 | cevap uretildi + kaynak gosterildi |
| 3 | Eco turu ne demek? | cevaplanabilir | GECTI | 4.51 | cevap uretildi + kaynak gosterildi |
| 4 | Keskin nisanci tufeklerinin dezavantaji nedir? | cevaplanabilir | GECTI | 8.84 | cevap uretildi + kaynak gosterildi |
| 5 | Orta bolgeyi kontrol etmek neden onemli? | cevaplanabilir | GECTI | 6.40 | cevap uretildi + kaynak gosterildi |
| 6 | Yeni baslayan biri ajan secerken neye dikkat etmeli? | cevaplanabilir | GECTI | 7.29 | cevap uretildi + kaynak gosterildi |
| 7 | Etkisiz hale getirme islemi yarida kesilirse ne olur? | cevaplanabilir | GECTI | 4.88 | cevap uretildi + kaynak gosterildi |
| 8 | Nihai yetenek nasil hazir hale gelir? | cevaplanabilir | GECTI | 7.95 | cevap uretildi + kaynak gosterildi |
| 9 | Olduktan sonra takim arkadaslarina ne bildirilmeli? | cevaplanabilir | GECTI | 5.01 | cevap uretildi + kaynak gosterildi |
| 10 | Durarak ates etmek neden onemli? | cevaplanabilir | GECTI | 6.54 | cevap uretildi + kaynak gosterildi |
| 11 | Zirh ne ise yarar? | cevaplanabilir | GECTI | 5.53 | cevap uretildi + kaynak gosterildi |
| 12 | Sessiz yurumenin bedeli nedir? | cevaplanabilir | GECTI | 5.77 | cevap uretildi + kaynak gosterildi |
| 13 | Capraz ates nedir? | cevaplanabilir | GECTI | 6.21 | cevap uretildi + kaynak gosterildi |
| 14 | Cok fazla duelist secmek neden sorun olur? | cevaplanabilir | GECTI | 10.19 | cevap uretildi + kaynak gosterildi |
| 15 | Tek basina ilerlemek neden hatali? | cevaplanabilir | GECTI | 6.28 | cevap uretildi + kaynak gosterildi |
| 16 | Valorant hangi tarihte cikti? | cevaplanamaz | GECTI | 0.12 | dogru sekilde 'bilmiyorum' dedi |
| 17 | Valorant turnuvalarinda odul havuzu ne kadar? | cevaplanamaz | GECTI | 0.08 | dogru sekilde 'bilmiyorum' dedi |
| 18 | Bugun hava nasil? | cevaplanamaz | GECTI | 0.08 | dogru sekilde 'bilmiyorum' dedi |
| 19 | Duelist rolundeki ajanlarin isimleri nelerdir? | cevaplanamaz | GECTI | 5.74 | dogru sekilde 'bilmiyorum' dedi |

**Toplam: 19/19 test gecti.**
**Ortalama sure: 5.01 saniye/soru.**

## Uc Durum Testleri

Referans planin Hafta 5 maddesi: *"It handles edge cases (like empty query input, or very general questions)"*. Olcut: uygulama cokmemeli ve makul bir cevap donmeli (belirli bir cevap sart kosulmuyor).

| # | Girdi | Tur | Sonuc | Sure (sn) | Not |
|---|-------|-----|-------|-----------|-----|
| 1 | '' | bos sorgu | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 2 | '   ' | yalnizca bosluk | GECTI | 0.00 | cokmedi, 'bilmiyorum' dondu |
| 3 | Bana her seyi anlat | cok genel soru | GECTI | 3.55 | cokmedi, 'bilmiyorum' dondu |

**Uc durum: 3/3 gecti.**

Referans dokuman hedefi: kucuk modeller icin ~1-3 saniye/soru. qwen3-4b bir 'reasoning' modeli oldugu icin (cevap oncesi ic dusunme adimi uretir) bu hedefin uzerinde cikabilir; asagida gercek olculen degerler var.