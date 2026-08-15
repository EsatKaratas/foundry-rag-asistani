"""
test_qa.py

Fonksiyonel test scripti (referans dokumandaki Hafta 5 - "System Testing & Evaluation"
adimina karsilik gelir).

Amac: sistemin hem cevaplanabilir hem cevaplanamaz sorularda dogru davrandigini
dogrulamak ve soru basina cevap suresini olcmek. Sonuc, TEST_RESULTS.md dosyasina
yazilir.

Calistirma: python test_qa.py
"""

import time
from datetime import datetime, timezone

from app import answer_query, FALLBACK_MESSAGE, NO_INFO_MESSAGE

# (soru, dokumanlarda cevabi var mi, beklenen kaynak dosya ya da None)
TEST_CASES = [
    ("Yaz okulu programi kac hafta suruyor?", True, "genel_bilgiler.txt"),
    ("Iletisim icin hangi kanal kullaniliyor?", True, "genel_bilgiler.txt"),
    ("Hangi proje secenekleri var?", True, "proje_secenekleri.txt"),
    ("Sertifika almak icin ne yapmam lazim?", True, "sertifika_ve_teslim.txt"),
    ("Zorunlu stajda sigorta girisini kim yapiyor?", True, "staj_belgesi_sureci.txt"),
    ("RAG mimarisinin adimlari nelerdir?", True, "foundry_local_teknik_detaylar.txt"),
    ("Python nasil ogrenilir?", False, None),
    ("Bugun hava nasil?", False, None),
    ("En sevdigin renk nedir?", False, None),
]


def evaluate(question: str, expect_answerable: bool, answer: str) -> tuple[bool, str]:
    is_fallback = answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE)

    if expect_answerable:
        passed = not is_fallback and len(answer.strip()) > 0
        note = "cevap uretildi" if passed else "BEKLENMEDIK: cevap veremedi / bos dondu"
    else:
        passed = is_fallback
        note = "dogru sekilde 'bilmiyorum' dedi" if passed else "BEKLENMEDIK: uydurma cevap verdi"

    return passed, note


def main() -> None:
    lines = []
    lines.append(f"# Test Sonuclari — {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("| # | Soru | Beklenen | Sonuc | Sure (sn) | Not |")
    lines.append("|---|------|----------|-------|-----------|-----|")

    total_passed = 0
    total_time = 0.0

    for i, (question, expect_answerable, _expected_source) in enumerate(TEST_CASES, start=1):
        start = time.perf_counter()
        answer, chunks = answer_query(question)
        elapsed = time.perf_counter() - start
        total_time += elapsed

        passed, note = evaluate(question, expect_answerable, answer)
        total_passed += int(passed)

        expected_label = "cevaplanabilir" if expect_answerable else "cevaplanamaz"
        result_label = "GECTI" if passed else "KALDI"

        lines.append(
            f"| {i} | {question} | {expected_label} | {result_label} | "
            f"{elapsed:.2f} | {note} |"
        )

    lines.append("")
    lines.append(f"**Toplam: {total_passed}/{len(TEST_CASES)} test gecti.**")
    lines.append(f"**Ortalama sure: {total_time / len(TEST_CASES):.2f} saniye/soru.**")
    lines.append("")
    lines.append(
        "Referans dokuman hedefi: kucuk modeller icin ~1-3 saniye/soru. "
        "qwen3-4b bir 'reasoning' modeli oldugu icin (cevap oncesi ic dusunme adimi "
        "uretir) bu hedefin uzerinde cikabilir; asagida gercek olculen degerler var."
    )

    report = "\n".join(lines)
    with open("TEST_RESULTS.md", "w", encoding="utf-8") as f:
        f.write(report)

    print(report)


if __name__ == "__main__":
    main()
