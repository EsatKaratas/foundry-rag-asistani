"""
lexical_gate.py

Sozcuksel (lexical) alaka kapisi — kosinus benzerliginin yapisal olarak
goremedigi bir hata turunu deterministik olarak yakalar.

PROBLEM
-------
Kosinus benzerligi anlamsal yakinlik olcer. Tek konulu bir korpusta bu,
"bu parca soruyu cevapliyor mu"yu degil "bu metin ayni konu hakkinda mi"yi
olcmeye baslar. Olculen gercek ornek:

    Soru : "Valorant turnuvalarinda odul havuzu ne kadar?"
    Cevap: (oyun ici ekonomi sistemini anlatiyor)

"turnuva" ve "odul" kelimeleri korpusta HIC gecmiyor. Ama embedding
"turnuva odulu"nu "oyun ici para"ya yakin buluyor, alaka denetleyicisi de
(kucuk bir model) bunu "alakali" sayabiliyor. Sonuc halusinasyon degil —
verilen bilgi dogru — ama sorulan soru bu degil (konu kaymasi).

COZUM
-----
Yogun (dense/embedding) aramaya sozcuksel (sparse/lexical) bir kontrol
ekleniyor; literaturde "hibrit arama" olarak bilinen desen. Fikir basit:
sorunun AYIRT EDICI kelimelerinden en az biri getirilen metinde gecmiyorsa,
o metin bu soruyu cevapliyor olamaz.

"Ayirt edici" tanimi onemli. "Valorant" kelimesi her dokumanda geciyor, yani
hicbir sey ayirt etmiyor — bu yuzden dokuman frekansi (DF) yuksek kelimeler
elenir. Bu, klasik IDF (ters dokuman frekansi) fikrinin sade bir uygulamasi.

Turkce icin iki uyarlama gerekti:
  1. Dokumanlar Turkce karaktersiz yazilmis ama kullanici arayuze "görevi"
     diye yaziyor -> her iki taraf da normalize ediliyor (ö->o, ş->s ...).
  2. Turkce sondan eklemeli bir dil ("turnuva" -> "turnuvalarinda") ->
     tam kelime yerine ilk STEM_LEN karakter (kaba govde) karsilastiriliyor.

Bu kapi bilincli olarak DETERMINISTIK: hicbir LLM cagrisi yapmaz. Projedeki
genel ilkeyle ayni — kesin olarak hesaplanabilen bir sey modele sorulmaz.
Ek fayda: eleme LLM cagrisindan once yapildigi icin cevaplanamaz sorular
daha hizli reddediliyor.
"""

import re
import sqlite3
from collections import Counter
from functools import lru_cache

from common import DB_PATH

# Turkce karakterleri ASCII karsiliklarina indirger. Dokumanlar Turkce
# karaktersiz yazildigi icin karsilastirma ancak boyle guvenilir olur.
TR_MAP = str.maketrans("ıİşŞğĞüÜöÖçÇâîû", "iissgguuooccaiu")

WORD_PATTERN = re.compile(r"[a-z0-9]+")

# Soru kaliplarinda gecen, icerik tasimayan kelimeler. Bunlar korpusta
# gecse de gecmese de alaka hakkinda bilgi vermez.
STOPWORDS = {
    "ne", "nedir", "nasil", "neden", "hangi", "kac", "kadar", "mi", "mu",
    "bir", "bu", "su", "icin", "ile", "ve", "veya", "ama", "de", "da",
    "cok", "daha", "en", "gibi", "olan", "olur", "oluyor", "var", "yok",
    "bana", "beni", "sen", "ben", "her", "seyi", "sey", "anlat", "soyle",
    "yapar", "eder", "etmek", "olmak", "demek", "biri", "neye", "dikkat",
    "etmeli", "gorevi", "bugun",
}

MIN_TERM_LEN = 4    # 3 harfli kelimeler ayirt edici degil
STEM_LEN = 5        # kaba govde uzunlugu (Turkce ek yigilmasini tolere eder)
UBIQUITY_RATIO = 0.6  # dokumanlarin %60+'inda gecen govde "her yerde" sayilir


def _normalize(text: str) -> str:
    return text.translate(TR_MAP).lower()


def _tokens(text: str) -> list[str]:
    return WORD_PATTERN.findall(_normalize(text))


def _stem(word: str) -> str:
    return word[:STEM_LEN]


@lru_cache(maxsize=1)
def _document_frequency() -> tuple[Counter, int]:
    """Her govde kac FARKLI dokumanda geciyor? (korpustan bir kez hesaplanir)

    lru_cache: veritabani surec basina bir kez okunur. Korpus degisirse
    (ingest.py yeniden calisirsa) surec yeniden baslatilmali - Streamlit
    zaten her calistirmada yeni surec baslatiyor.
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT source, content FROM chunks").fetchall()
    conn.close()

    stems_per_document: dict[str, set[str]] = {}
    for source, content in rows:
        stems_per_document.setdefault(source, set()).update(
            _stem(token) for token in _tokens(content)
        )

    frequency: Counter = Counter()
    for stems in stems_per_document.values():
        for stem in stems:
            frequency[stem] += 1

    return frequency, len(stems_per_document)


def discriminative_stems(question: str) -> list[str]:
    """Sorunun ayirt edici govdeleri: stopword degil, kisa degil, her yerde degil."""
    frequency, document_count = _document_frequency()
    ubiquity_limit = document_count * UBIQUITY_RATIO

    stems = []
    for token in _tokens(question):
        if len(token) < MIN_TERM_LEN or token in STOPWORDS:
            continue
        stem = _stem(token)
        # "valorant" gibi neredeyse her dokumanda gecen kelimeler hicbir sey
        # ayirt etmez; bunlari saymak kapiyi ise yaramaz hale getirirdi.
        if frequency.get(stem, 0) >= ubiquity_limit:
            continue
        stems.append(stem)
    return stems


def lexical_support_detail(question: str, context: str) -> tuple[bool, list[str], list[str]]:
    """has_lexical_support ile ayni karar, ama gerekcesiyle birlikte.

    Arayuzdeki karar izi panelinde "hangi kelimeler arandi, hangileri bulundu"
    gosterilebilsin diye ayrildi.

    Doner: (destek_var_mi, aranan_govdeler, eslesen_govdeler)
    """
    stems = discriminative_stems(question)
    if not stems:
        return True, [], []

    context_stems = {_stem(token) for token in _tokens(context)}
    matched = [stem for stem in stems if stem in context_stems]
    return bool(matched), stems, matched


def has_lexical_support(question: str, context: str) -> bool:
    """Sorunun ayirt edici kelimelerinden en az biri baglamda geciyor mu?

    Kasitli olarak TOLERANSLI: tek bir eslesme yeterli. Amac gecerli sorulari
    elemek degil, hicbir sozcuksel dayanagi olmayanlari yakalamak.

    Sorunun hic ayirt edici kelimesi yoksa (ornegin "Bana her seyi anlat")
    bu kapi karar veremez ve gecirir; karari sonraki kapilara birakir.
    """
    stems = discriminative_stems(question)
    if not stems:
        return True

    context_stems = {_stem(token) for token in _tokens(context)}
    return any(stem in context_stems for stem in stems)


# --- Cevap tarafi: ozel isim dayanagi ---

# Markdown vurgusu ve noktalama, kelime sinirlarini bozmasin diye temizlenir.
MARKUP_PATTERN = re.compile(r"[*_`#>]+")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?:;\n])\s+")
CAPITALIZED_PATTERN = re.compile(r"\b([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]{2,})\b")


def ungrounded_proper_nouns(context: str, answer: str) -> list[str]:
    """Cevapta gecen ama baglamda hic gecmeyen ozel isimleri doner.

    NEDEN: Sayi kontrolu (has_ungrounded_numbers) yalnizca rakam iceren
    halusinasyonlari yakalar. Olculen gercek acik:

        Soru : "Duelist rolundeki ajanlarin isimleri nelerdir?"
        Cevap: "Jett, Sage, Raze ve Breach'tir. (Kaynak: ajan_rolleri.txt)"

    Korpusta hicbir ajan ismi gecmiyor. Sozcuksel kapi bu soruyu gecirdi
    (cunku "duelist" kelimesi korpusta var), sayi kontrolu goremedi (rakam
    yok), LLM denetleyicisi de yakalayamadi. Sistem uydurdu ve ustune kaynak
    gostererek halusinasyonu yetkili gosterdi.

    Bu fonksiyon ayni deterministik fikri ozel isimlere genisletiyor: model
    paraphrase yaparken yeni ozel isim UYDURMAZ; baglamda gecmeyen bir ozel
    isim gorunuyorsa, o bilgi baglamdan gelmiyor demektir.

    Yanlis pozitifi dusuk tutan iki kural:
      1. Cumle basindaki kelimeler sayilmaz (her cumle buyuk harfle baslar,
         ozel isim olduklarini gostermez).
      2. Karsilastirma normalize edilmis kaba govde uzerinden yapilir; boylece
         "Duelist'in" ile "Duelist" ayni sayilir.
    """
    context_stems = {_stem(token) for token in _tokens(context)}

    clean_answer = MARKUP_PATTERN.sub(" ", answer)
    ungrounded = []

    for sentence in SENTENCE_SPLIT_PATTERN.split(clean_answer):
        words = sentence.split()
        # Cumlenin ilk kelimesi atlanir: buyuk harfli olmasi ozel isim
        # oldugunu gostermez.
        for word in words[1:]:
            for match in CAPITALIZED_PATTERN.findall(word):
                stem = _stem(_normalize(match))
                if stem and stem not in context_stems and match not in ungrounded:
                    ungrounded.append(match)

    return ungrounded


if __name__ == "__main__":
    # Elle hizli kontrol: python lexical_gate.py
    frequency, document_count = _document_frequency()
    print(f"Korpus: {document_count} dokuman, {len(frequency)} farkli govde\n")

    for question in (
        "Duelist rolunun gorevi nedir?",
        "Duelist rolünün görevi nedir?",
        "Valorant turnuvalarinda odul havuzu ne kadar?",
        "Bana her seyi anlat",
    ):
        print(f"{question}\n  ayirt edici govdeler: {discriminative_stems(question)}")
