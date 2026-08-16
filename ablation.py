"""
ablation.py

Ablasyon calismasi: her savunma katmani tek tek kapatilip testin ne kadar
bozuldugu olculur.

NEDEN: Bir sistemde dort ayri savunma katmani varsa, "bunlarin hepsi gerekli"
demek bir iddiadir. Iddia ancak katman kapatilip sonuc olculerek kanitlanir.
Ablasyon calismasi tam olarak bunu yapar - her katmanin teste kac vaka
kazandirdigini ve kac saniyeye mal oldugunu sayisal olarak gosterir.

Bu ayrica ters yonde de bilgi verir: bir katman kapatildiginda sonuc
degismiyorsa, o katman aslinda gereksizdir ve silinmelidir.

Olculen yapilandirmalar:
  - Tam sistem (hepsi acik)                -> referans nokta
  - Her katman TEK BASINA kapali (4 kosu)  -> o katmanin katkisi
  - Ciplak RAG (hicbir savunma yok)        -> referans tutorial'daki hali

Calistirma: python ablation.py
Sonuc: ABLATION_RESULTS.md
"""

import time
from datetime import datetime, timezone

import app
from test_qa import EDGE_CASES, TEST_CASES, evaluate, evaluate_edge_case

# (etiket, aciklama, {anahtar: deger})
# Bos sozluk = varsayilan (hepsi acik).
CONFIGURATIONS = [
    (
        "Tam sistem",
        "bes savunma katmani da acik",
        {},
    ),
    (
        "Sozcuksel kapi KAPALI",
        "kosinus + LLM denetleyici + sayi kontrolu var",
        {"ENABLE_LEXICAL_GATE": False},
    ),
    (
        "LLM alaka denetleyicisi KAPALI",
        "getirilen her parca kabul ediliyor",
        {"ENABLE_RELEVANCE_GRADER": False},
    ),
    (
        "Sayi dogrulamasi KAPALI",
        "uretim sonrasi sayi dayanagi yok",
        {"ENABLE_GROUNDEDNESS_CHECK": False},
    ),
    (
        "Ozel isim kontrolu KAPALI",
        "uretim sonrasi ozel isim dayanagi yok",
        {"ENABLE_PROPER_NOUN_CHECK": False},
    ),
    (
        "Kosinus esigi KAPALI",
        "dusuk skorlu parcalar da elenmiyor",
        {"ENABLE_SIMILARITY_GATE": False},
    ),
    (
        "Ciplak RAG",
        "hicbir savunma yok - getir + uret",
        {
            "ENABLE_SIMILARITY_GATE": False,
            "ENABLE_LEXICAL_GATE": False,
            "ENABLE_RELEVANCE_GRADER": False,
            "ENABLE_GROUNDEDNESS_CHECK": False,
            "ENABLE_PROPER_NOUN_CHECK": False,
        },
    ),
]

SWITCHES = (
    "ENABLE_SIMILARITY_GATE",
    "ENABLE_LEXICAL_GATE",
    "ENABLE_RELEVANCE_GRADER",
    "ENABLE_GROUNDEDNESS_CHECK",
    "ENABLE_PROPER_NOUN_CHECK",
)


def apply_configuration(overrides: dict) -> None:
    """Once hepsini ac, sonra bu yapilandirmanin kapattiklarini kapat."""
    for switch in SWITCHES:
        setattr(app, switch, True)
    for switch, value in overrides.items():
        setattr(app, switch, value)


def run_suite() -> dict:
    """Ana test setini ve uc durumlari kosar, ozet doner."""
    passed = 0
    total_time = 0.0
    failures = []

    for question, expect_answerable, _source in TEST_CASES:
        start = time.perf_counter()
        try:
            answer, chunks = app.answer_query(question)
            crashed = False
        except Exception as exc:  # noqa: BLE001
            answer, chunks, crashed = "", [], True
            crash_name = type(exc).__name__
        total_time += time.perf_counter() - start

        if crashed:
            ok, note = False, f"COKTU ({crash_name})"
        else:
            ok, note = evaluate(question, expect_answerable, answer, chunks)

        passed += int(ok)
        if not ok:
            failures.append((question, note))

    edge_passed = 0
    edge_failures = []
    for question, kind in EDGE_CASES:
        try:
            answer, _chunks = app.answer_query(question)
            ok, note = evaluate_edge_case(answer)
        except Exception as exc:  # noqa: BLE001
            ok, note = False, f"COKTU ({type(exc).__name__})"
        edge_passed += int(ok)
        if not ok:
            edge_failures.append((f"[uc durum: {kind}] {question!r}", note))

    return {
        "passed": passed,
        "edge_passed": edge_passed,
        "avg_time": total_time / len(TEST_CASES),
        "failures": failures + edge_failures,
    }


def main() -> None:
    print("Ablasyon calismasi basliyor: "
          f"{len(CONFIGURATIONS)} yapilandirma x {len(TEST_CASES)} soru\n")

    results = []
    for label, description, overrides in CONFIGURATIONS:
        print(f"-> {label} ...", end="", flush=True)
        apply_configuration(overrides)
        summary = run_suite()
        results.append((label, description, summary))
        print(f" {summary['passed']}/{len(TEST_CASES)} "
              f"({summary['avg_time']:.2f} sn/soru)")

    # Ayarlari varsayilana dondur (bu modul baska yerden import edilirse diye).
    apply_configuration({})

    baseline = results[0][2]["passed"]

    lines = [
        f"# Ablasyon Calismasi — {datetime.now(timezone.utc).isoformat()}",
        "",
        "Her savunma katmani tek tek kapatilip testin ne kadar bozuldugu olculdu.",
        "Amac, her tasarim kararinin gercekten gerekli oldugunu gostermek: bir",
        "katman kapatildiginda sonuc degismiyorsa o katman gereksizdir.",
        "",
        "> **Sure sutunu hakkinda uyari:** Foundry Local arka arkaya cok istek",
        "> alinca GPU bellegi biriktiriyor (olculdu: tek test kosusu 5.6 GB -> 7.8 GB)",
        "> ve uretim sureleri 3-5 kat yavasliyor. Bu calisma tek oturumda alt alta",
        "> kostugu icin ASAGI SATIRLARDAKI sureler sistematik olarak sisiktir;",
        "> yapilandirmalar arasinda sure karsilastirmasi yapmayin. Gecti/kaldi",
        "> sonuclari bundan etkilenmez. Temiz durumda olculen referans deger:",
        "> **1.43 sn/soru** (tam sistem).",
        "",
        "| Yapilandirma | Ana test | Uc durum | Ort. sure | Katkisi | Aciklama |",
        "|---|---|---|---|---|---|",
    ]

    for label, description, summary in results:
        delta = summary["passed"] - baseline
        if label == "Tam sistem":
            contribution = "referans"
        elif delta == 0:
            contribution = "0 vaka"
        else:
            contribution = f"**{abs(delta)} vaka**"

        lines.append(
            f"| {label} | {summary['passed']}/{len(TEST_CASES)} | "
            f"{summary['edge_passed']}/{len(EDGE_CASES)} | "
            f"{summary['avg_time']:.2f} sn | {contribution} | {description} |"
        )

    lines.append("")
    lines.append("## Kapatildiginda kaybedilen vakalar")
    lines.append("")

    for label, _description, summary in results:
        if not summary["failures"]:
            lines.append(f"**{label}:** kaybedilen vaka yok.")
            lines.append("")
            continue
        lines.append(f"**{label}:**")
        lines.append("")
        for question, note in summary["failures"]:
            lines.append(f"- `{question}` — {note}")
        lines.append("")

    report = "\n".join(lines)
    with open("ABLATION_RESULTS.md", "w", encoding="utf-8") as handle:
        handle.write(report)

    print()
    print(report)


if __name__ == "__main__":
    main()
