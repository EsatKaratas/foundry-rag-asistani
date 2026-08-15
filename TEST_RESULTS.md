# Test Sonuclari — 2026-08-15T22:10:23.996769+00:00

| # | Soru | Beklenen | Sonuc | Sure (sn) | Not |
|---|------|----------|-------|-----------|-----|
| 1 | Foundry Local nedir? | cevaplanabilir | GECTI | 3.73 | cevap uretildi |
| 2 | Foundry Local internet baglantisina ihtiyac duyar mi? | cevaplanabilir | GECTI | 1.95 | cevap uretildi |
| 3 | RAG nedir, adimlarini kisaca acikla. | cevaplanabilir | GECTI | 66.44 | cevap uretildi |
| 4 | RAG kullanmanin en buyuk faydasi nedir? | cevaplanabilir | GECTI | 21.72 | cevap uretildi |
| 5 | Python nasil ogrenilir? | cevaplanamaz | GECTI | 1.16 | dogru sekilde 'bilmiyorum' dedi |
| 6 | SQLite nedir? | cevaplanamaz | KALDI | 5.40 | BEKLENMEDIK: uydurma cevap verdi |
| 7 | Bugun hava nasil? | cevaplanamaz | GECTI | 1.17 | dogru sekilde 'bilmiyorum' dedi |

**Toplam: 6/7 test gecti.**
**Ortalama sure: 14.51 saniye/soru.**

Referans dokuman hedefi: kucuk modeller icin ~1-3 saniye/soru. qwen3-4b bir 'reasoning' modeli oldugu icin (cevap oncesi ic dusunme adimi uretir) bu hedefin uzerinde cikabilir; asagida gercek olculen degerler var.