"""
test_deterministic.py

Modelden BAGIMSIZ katmanlarin birim testleri.

Neden ayri bir dosya: test_qa.py uctan uca calisir ve Foundry Local + GPU +
yuklu modeller gerektirir; GitHub Actions'ta kosturulamaz. Oysa sistemin
savunma katmanlarinin cogu tamamen deterministik - hicbir LLM cagrisi
yapmazlar ve saf fonksiyon olarak test edilebilirler.

Bu dosya yalnizca o katmanlari test eder, dolayisiyla her ortamda kosar.
Kapsam sinirlidir ve bilincli olarak boyledir: gecmesi "sistem calisiyor"
demek degil, "deterministik kurallar bozulmamis" demektir.

Calistirma: python test_deterministic.py
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

# lexical_gate korpusu veritabanindan okur; testler icin gecici, kucuk bir
# veritabani olusturup DB_PATH'i ona yonlendiriyoruz. Boylece test gercek
# rag.db'ye (ve dolayisiyla makinedeki veriye) bagimli olmuyor.
import common

_TMP = Path(tempfile.gettempdir()) / "rag_test_korpus.db"
BELGELER = {
    "ekonomi.txt": (
        "Valorant Ekonomi Sistemi. Her turun basinda oyuncular kredi harcayarak "
        "silah ve zirh satin alir. Tasarruf turunda az harcama yapilir."
    ),
    "roller.txt": (
        "Valorant Ajan Rolleri. Duelist ajanlar catismayi baslatan karakterlerdir. "
        "Sentinel bolge tutar ve arkayi korur."
    ),
    "spike.txt": (
        "Valorant Spike ve Tur Akisi. Saldiran takim spike yerlestirir. "
        "Savunan takim spike'i etkisiz hale getirebilir."
    ),
}


def korpusu_hazirla() -> None:
    conn = sqlite3.connect(_TMP)
    conn.execute("DROP TABLE IF EXISTS chunks")
    conn.execute(
        "CREATE TABLE chunks (id INTEGER PRIMARY KEY, source TEXT, "
        "chunk_index INTEGER, content TEXT, embedding TEXT)"
    )
    for i, (kaynak, metin) in enumerate(BELGELER.items()):
        conn.execute(
            "INSERT INTO chunks (source, chunk_index, content, embedding) "
            "VALUES (?, ?, ?, ?)",
            (kaynak, i, metin, "[]"),
        )
    conn.commit()
    conn.close()


korpusu_hazirla()
common.DB_PATH = _TMP

import lexical_gate  # noqa: E402  (DB_PATH ayarlandiktan sonra import edilmeli)

lexical_gate.DB_PATH = _TMP
lexical_gate._document_frequency.cache_clear()

from app import (  # noqa: E402
    NO_INFO_MESSAGE,
    ensure_source_citation,
    has_ungrounded_numbers,
    is_degenerate_repetition,
    limit_answer,
)
from lexical_gate import (  # noqa: E402
    has_lexical_support,
    missing_from_corpus,
    ungrounded_proper_nouns,
)
from test_qa import copied_ratio, looks_like_verbatim_copy  # noqa: E402

BAGLAM = " ".join(BELGELER.values())
PARCALAR = [{"source": k, "content": v} for k, v in BELGELER.items()]

sonuclar: list[tuple[bool, str]] = []


def dogrula(kosul: bool, aciklama: str) -> None:
    sonuclar.append((bool(kosul), aciklama))


# --- Sozcuksel kapi ---
dogrula(
    has_lexical_support("Tasarruf turu ne demek?", BAGLAM),
    "sozcuksel kapi: dokumanda gecen kelimeli soruyu gecirir",
)
dogrula(
    not has_lexical_support("Turnuva odul havuzu ne kadar?", BAGLAM),
    "sozcuksel kapi: korpusta hic gecmeyen kelimeli soruyu reddeder",
)
dogrula(
    has_lexical_support("Bana her seyi anlat", BAGLAM),
    "sozcuksel kapi: ayirt edici kelimesi olmayan soruda karar vermez, gecirir",
)
dogrula(
    has_lexical_support("Bomba nasil yerlestirilir?", BAGLAM),
    "alan sozlugu: 'bomba' -> 'spike' esanlamlisi eslesir",
)
dogrula(
    has_lexical_support("Duelist rolünün görevi nedir?", BAGLAM),
    "Turkce karakterli soru normalize edilerek eslesir",
)
dogrula(
    missing_from_corpus("Turnuva odulu ne kadar?") != [],
    "eksik kelime listesi: korpusta olmayan kelimeleri bildirir",
)

# --- Ozel isim dayanagi ---
dogrula(
    ungrounded_proper_nouns(BAGLAM, "Bu rolde Jett ve Phoenix bulunur.") != [],
    "ozel isim: baglamda gecmeyen isimleri yakalar",
)
dogrula(
    ungrounded_proper_nouns(BAGLAM, "Duelist ajanlar catismayi baslatir.") == [],
    "ozel isim: gecerli cevapta yanlis pozitif uretmez",
)
dogrula(
    ungrounded_proper_nouns(BAGLAM, "Sentinel bolge tutar.") == [],
    "ozel isim: cumle basindaki buyuk harfli kelimeyi isim saymaz",
)

# --- Sayi dayanagi ---
dogrula(
    has_ungrounded_numbers(BAGLAM, "Oyun 2020 yilinda cikti."),
    "sayi kontrolu: baglamda gecmeyen sayiyi yakalar",
)
dogrula(
    not has_ungrounded_numbers(BAGLAM, "Tasarruf turunda az harcama yapilir."),
    "sayi kontrolu: sayisiz cevapta yanlis pozitif uretmez",
)

# --- Yinelenme dongusu ---
dogrula(
    is_degenerate_repetition("ayni ifade tekrar ediyor " * 25),
    "yinelenme: dongu metnini yakalar",
)
dogrula(
    not is_degenerate_repetition(
        "Duelist ajanlar catismayi baslatan, ilk giren ve rakiple dogrudan "
        "carpismayi hedefleyen karakterlerdir. Yetenekleri hareket kabiliyetini "
        "artirmaya yoneliktir."
    ),
    "yinelenme: saglikli cevapta yanlis pozitif uretmez",
)

# --- Cevap uzunlugu ---
dogrula(
    len(limit_answer("Cok uzun bir cevap. " * 200)) <= 720,
    "uzunluk siniri: cok uzun cevabi kirpar",
)
dogrula(
    len(limit_answer("Tek bir uzun birim " * 100)) <= 720,
    "uzunluk siniri: noktalamasiz tek birimi de kirpar",
)
dogrula(
    limit_answer(NO_INFO_MESSAGE) == NO_INFO_MESSAGE,
    "uzunluk siniri: 'bilmiyorum' mesajina dokunmaz",
)

# --- Kaynak satiri ---
dogrula(
    "(Kaynak:" in ensure_source_citation("Bir cevap.", PARCALAR),
    "kaynak satiri: eksikse kodla eklenir",
)
dogrula(
    ensure_source_citation("Bir cevap. (Kaynak: roller.txt)", PARCALAR).count("Kaynak")
    == 1,
    "kaynak satiri: zaten varsa ikinci kez eklenmez",
)
dogrula(
    ensure_source_citation(NO_INFO_MESSAGE, PARCALAR) == NO_INFO_MESSAGE,
    "kaynak satiri: 'bilmiyorum' mesajina eklenmez",
)

# --- Kopyalama olcutu ---
dogrula(
    looks_like_verbatim_copy(BAGLAM, PARCALAR),
    "kopyalama: baglamin oldugu gibi yapistirilmasini yakalar",
)
dogrula(
    looks_like_verbatim_copy(BAGLAM + " " + BAGLAM + " " + BAGLAM, PARCALAR),
    "kopyalama: baglamin tekrarlanmasini da yakalar",
)
dogrula(
    copied_ratio(
        "Oyuncular her tur basinda ellerindeki krediyle ekipman tercihi yapar ve "
        "bu tercih takimin o turdaki gucunu belirler.",
        PARCALAR,
    )
    < 0.6,
    "kopyalama: kendi cumleleriyle yazilmis cevabi kopya saymaz",
)


def main() -> int:
    gecen = sum(1 for ok, _ in sonuclar if ok)
    for ok, aciklama in sonuclar:
        print(f"[{'GECTI' if ok else 'KALDI'}] {aciklama}")
    print()
    print(f"Toplam: {gecen}/{len(sonuclar)} deterministik test gecti.")
    return 0 if gecen == len(sonuclar) else 1


if __name__ == "__main__":
    sys.exit(main())
