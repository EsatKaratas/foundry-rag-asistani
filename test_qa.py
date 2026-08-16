"""
test_qa.py

Fonksiyonel test scripti (referans dokumandaki Hafta 5 - "System Testing & Evaluation"
adimina karsilik gelir).

Amac: sistemin hem cevaplanabilir hem cevaplanamaz sorularda dogru davrandigini
dogrulamak ve soru basina cevap suresini olcmek. Sonuc, TEST_RESULTS.md dosyasina
yazilir.

Calistirma: python test_qa.py
"""

import re
import time
from datetime import datetime, timezone

from app import answer_query, FALLBACK_MESSAGE, NO_INFO_MESSAGE

# (soru, dokumanlarda cevabi var mi, beklenen kaynak dosya ya da None)
#
# Cevaplanamaz sorular bilincli olarak secildi: bazilari oyunla TAMAMEN alakasiz
# (hava durumu), bazilari ise oyunla ilgili ama dokumanlarda YER ALMAYAN konular
# (turnuva odulu, oyunun cikis tarihi). Ikinci grup daha zorlayici bir testtir,
# cunku konu yakinligi nedeniyle retrieval yine de bir seyler getirir ve sistemin
# "yakin ama cevap degil" ayrimini yapabilmesi gerekir.
TEST_CASES = [
    ("Valorant kac kisiyle oynanir?", True, "oyun_temelleri.txt"),
    ("Duelist rolunun gorevi nedir?", True, "ajan_rolleri.txt"),
    ("Eco turu ne demek?", True, "ekonomi_sistemi.txt"),
    ("Keskin nisanci tufeklerinin dezavantaji nedir?", True, "silah_kategorileri.txt"),
    ("Orta bolgeyi kontrol etmek neden onemli?", True, "harita_yapisi.txt"),
    ("Yeni baslayan biri ajan secerken neye dikkat etmeli?", True, "yeni_baslayan_rehberi.txt"),
    ("Valorant hangi tarihte cikti?", False, None),
    ("Valorant turnuvalarinda odul havuzu ne kadar?", False, None),
    ("Bugun hava nasil?", False, None),
]


# Kalite kontrolu sinirlari.
# Bu kontroller sonradan eklendi: ilk surumde test yalnizca "cevap uretildi mi
# yoksa 'bilmiyorum' mu dedi" diye bakiyordu. Bu yuzden testler 9/9 gecerken,
# arayuzde model baglam metnini kelimesi kelimesine kopyalayip tekrarliyordu ve
# test bunu hata olarak gormuyordu. Cevabin ICERIGINI de denetlemek gerekiyor.
MAX_ANSWER_CHARS = 900
VERBATIM_COPY_WINDOW = 120

# Sistem promptunun 5. kuralinin istedigi kaynak satiri: "(Kaynak: dosya.txt)".
# Bosluk ve buyuk/kucuk harf farklarina toleransli.
SOURCE_CITATION_PATTERN = re.compile(r"\(\s*kaynak\s*:", re.IGNORECASE)


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

    # Kaynak gosterimi: referans plan, degerlendirme olcutleri arasinda
    # "Are sources cited?" sorusunu acikca soruyor. Sistem promptunun 5. kuralı
    # cevabin sonuna "(Kaynak: dosya.txt)" satirini eklemeyi sart kosuyor;
    # bu kuralin gercekten uygulanip uygulanmadigi burada dogrulaniyor.
    if not SOURCE_CITATION_PATTERN.search(answer):
        return False, "KALITE: kaynak gosterilmemis"

    return True, "cevap uretildi + kaynak gosterildi"


# Uc durum vakalari (referans plan, Hafta 5: "It handles edge cases (like empty
# query input, or very general questions)").
#
# Bu vakalar bilincli olarak ANA test setinden ayri tutuluyor. Sebep: bu sorular
# icin "dogru cevap" tek bir sey degil - plan yalnizca sistemin bunlari SAGLIKLI
# KARSILAMASINI istiyor, belirli bir cevap sart kosmuyor. Ana sete konsalardi
# ("bilmiyorum demeli" beklentisiyle) "Bana her seyi anlat" gibi genel bir soru
# 0.30-0.75 gri bolgesine dusup alaka denetleyicisine gider ve GPU cikarimi tam
# deterministik olmadigi icin sonuc kosudan kosuya degisebilirdi. Bu da test
# setini kararsiz gosterirdi. Buradaki olcut daha net: COKMEDI + makul cevap.
EDGE_CASES = [
    ("", "bos sorgu"),
    ("   ", "yalnizca bosluk"),
    ("Bana her seyi anlat", "cok genel soru"),
]


def evaluate_edge_case(answer: str) -> tuple[bool, str]:
    """Uc durum olcutu: cokme yok + bos olmayan, makul uzunlukta bir cevap.

    Bos sorgunun neden ayrica onemli oldugu: duzeltmeden once bu girdi
    dogrudan embedding API'sine gidiyor ve Foundry Local HTTP 400 donuyordu
    ("Embedding input at index 0 is null, empty..."), yakalanmayan bir
    exception olarak uygulamayi cokertiyordu.
    """
    if not answer or not answer.strip():
        return False, "BEKLENMEDIK: bos cevap dondu"
    if len(answer) > MAX_ANSWER_CHARS:
        return False, f"KALITE: cevap cok uzun ({len(answer)} karakter)"
    if answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE):
        return True, "cokmedi, 'bilmiyorum' dondu"
    return True, "cokmedi, cevap uretildi"


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

    # --- Uc durum testleri (ayri bolum) ---
    lines.append("## Uc Durum Testleri")
    lines.append("")
    lines.append(
        "Referans planin Hafta 5 maddesi: *\"It handles edge cases (like empty query "
        "input, or very general questions)\"*. Olcut: uygulama cokmemeli ve makul bir "
        "cevap donmeli (belirli bir cevap sart kosulmuyor)."
    )
    lines.append("")
    lines.append("| # | Girdi | Tur | Sonuc | Sure (sn) | Not |")
    lines.append("|---|-------|-----|-------|-----------|-----|")

    edge_passed = 0
    for i, (question, kind) in enumerate(EDGE_CASES, start=1):
        start = time.perf_counter()
        try:
            answer, _chunks = answer_query(question)
            crashed = False
        except Exception as exc:  # noqa: BLE001 - testin amaci tam da bunu yakalamak
            answer = ""
            crashed = True
            crash_note = f"COKTU: {type(exc).__name__}"
        elapsed = time.perf_counter() - start

        if crashed:
            passed, note = False, crash_note
        else:
            passed, note = evaluate_edge_case(answer)
        edge_passed += int(passed)

        shown = repr(question) if not question.strip() else question
        lines.append(
            f"| {i} | {shown} | {kind} | {'GECTI' if passed else 'KALDI'} | "
            f"{elapsed:.2f} | {note} |"
        )

    lines.append("")
    lines.append(f"**Uc durum: {edge_passed}/{len(EDGE_CASES)} gecti.**")
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
