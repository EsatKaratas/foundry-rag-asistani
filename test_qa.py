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


# Kalite kontrolu sinirlari.
# Bu kontroller sonradan eklendi: ilk surumde test yalnizca "cevap uretildi mi
# yoksa 'bilmiyorum' mu dedi" diye bakiyordu. Bu yuzden testler 9/9 gecerken,
# arayuzde model baglam metnini kelimesi kelimesine kopyalayip tekrarliyordu ve
# test bunu hata olarak gormuyordu. Cevabin ICERIGINI de denetlemek gerekiyor.
MAX_ANSWER_CHARS = 900
VERBATIM_COPY_WINDOW = 120


def looks_like_verbatim_copy(answer: str, chunks: list[dict]) -> bool:
    """Cevabin, baglamdan uzun bir bolumu oldugu gibi kopyalayip kopyalamadigini kontrol eder.

    Yontem: cevabin icinde VERBATIM_COPY_WINDOW karakterlik herhangi bir pencere,
    getirilen parcalarin metninde aynen geciyorsa bu bir kopyalama sayilir.
    """
    normalized_answer = " ".join(answer.split())
    if len(normalized_answer) < VERBATIM_COPY_WINDOW:
        return False

    normalized_context = " ".join(" ".join(c["content"] for c in chunks).split())

    for start in range(0, len(normalized_answer) - VERBATIM_COPY_WINDOW + 1, 20):
        window = normalized_answer[start : start + VERBATIM_COPY_WINDOW]
        if window in normalized_context:
            return True
    return False


def evaluate(
    question: str, expect_answerable: bool, answer: str, chunks: list[dict]
) -> tuple[bool, str]:
    is_fallback = answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE)

    if not expect_answerable:
        passed = is_fallback
        note = "dogru sekilde 'bilmiyorum' dedi" if passed else "BEKLENMEDIK: uydurma cevap verdi"
        return passed, note

    # Cevaplanabilir sorular icin: once cevap uretilmis mi, sonra KALITESI nasil.
    if is_fallback or not answer.strip():
        return False, "BEKLENMEDIK: cevap veremedi / bos dondu"

    if len(answer) > MAX_ANSWER_CHARS:
        return False, f"KALITE: cevap cok uzun ({len(answer)} karakter)"

    if looks_like_verbatim_copy(answer, chunks):
        return False, "KALITE: baglam metni oldugu gibi kopyalanmis"

    return True, "cevap uretildi"


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

        passed, note = evaluate(question, expect_answerable, answer, chunks)
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
