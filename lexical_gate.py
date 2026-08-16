"""
lexical_gate.py

Sozcuksel alaka kapisi: sorunun ayirt edici kelimelerinden en az biri
getirilen metinde gecmiyorsa, o metin bu soruyu cevapliyor olamaz.

Neden gerekli: kosinus benzerligi anlamsal yakinlik olcer ve tek konulu bir
korpusta "bu metin ayni konu hakkinda mi"yi olcmeye baslar. Olculen ornek:
"Valorant turnuvalarinda odul havuzu ne kadar?" sorusuna sistem oyun ici
ekonomiyi anlatiyordu; oysa "turnuva" ve "odul" korpusta hic gecmiyor.
Embedding bunu goremez, kelime karsilastirmasi gorur (hibrit arama deseni).

"Ayirt edici" tanimi kritik: "valorant" her dokumanda gectigi icin hicbir
sey ayirt etmez, bu yuzden dokuman frekansi yuksek kelimeler elenir (IDF).

Turkce icin iki uyarlama: karakter normalizasyonu (dokumanlar Turkce
karaktersiz, kullanici "görevi" yaziyor) ve kaba govde karsilastirmasi
(sondan eklemeli dil: "turnuva" -> "turnuvalarinda").

Tamamen deterministik, hicbir LLM cagrisi yapmaz.
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

# Alan sozlugu: kullanicinin yazmasi muhtemel kelime -> dokumanlarda gecen karsiligi.
#
# Neden gerekli (olculdu): sozcuksel kapi kelime esitligine baktigi icin, ayni seyi
# baska kelimeyle soran gecerli sorulari reddedebiliyordu. 9 esanlamli soruluk bir
# denemede 5'i yanlis reddedildi ("Para biriktirmek ne zaman mantiklidir?",
# "Bomba yerlestirildikten sonra ne olur?" gibi).
#
# Denenen alternatif: ayirt edici kelime bulunamazsa yaygin kelimelere de bakmak.
# Olculdu ve REDDEDILDI - 5 esanlamlidan 3'unu kurtariyor ama cevaplanamaz 4 sorudan
# 3'unu bozuyordu (yaygin "valorant" kelimesi her soruyu geciriyor).
#
# Bu sozluk bilgi tabanina OZGUDUR; dokumanlar degisirse gozden gecirilmelidir.
ALIASES = {
    "para": ["kredi"],
    "butce": ["kredi"],
    "bomba": ["spike"],
    "patlayici": ["spike"],
    "ozel yetenek": ["nihai"],
    "ulti": ["nihai"],
    "ultimate": ["nihai"],
    "sicrama": ["tepme"],
    "geri tepme": ["tepme"],
    "gurultu": ["ses"],
    "adim sesi": ["ayak"],
    "duellocu": ["duelist"],
    "nisanci": ["keskin"],
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


def _alias_stems(question: str) -> list[str]:
    """Sorudaki kelimelerin alan sozlugundeki karsiliklarini govde olarak doner."""
    normalized = _normalize(question)
    stems = []
    for term, karsiliklar in ALIASES.items():
        if term in normalized:
            stems.extend(_stem(k) for k in karsiliklar)
    return stems


def discriminative_stems(question: str) -> list[str]:
    """Sorunun ayirt edici govdeleri: stopword degil, kisa degil, her yerde degil.

    Alan sozlugundeki karsiliklar da eklenir; boylece ayni seyi baska kelimeyle
    soran gecerli sorular kapiya takilmaz (bkz. ALIASES).
    """
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

    for stem in _alias_stems(question):
        if stem not in stems:
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


def matched_spans(question: str, text: str) -> list[tuple[int, int]]:
    """Metinde, sorunun ayirt edici govdeleriyle eslesen kelimelerin araliklari.

    Arayuzdeki kaynak panelinde bu araliklar vurgulaniyor: sozcuksel kapinin
    neye bakarak karar verdigi, karari okumak yerine metinde gorulebiliyor.
    Doner: (baslangic, bitis) indeksleri, metindeki sirayla.
    """
    stems = set(discriminative_stems(question))
    if not stems:
        return []

    spans = []
    for match in WORD_PATTERN.finditer(_normalize(text)):
        if _stem(match.group()) in stems:
            spans.append((match.start(), match.end()))
    return spans


def missing_from_corpus(question: str) -> list[str]:
    """Sorunun, korpusun TAMAMINDA hic gecmeyen ayirt edici kelimelerini doner.

    Govde degil, kullanicinin yazdigi kelimenin kendisi dondurulur - arayuzde
    "turnu..." yerine "turnuvalarinda" gostermek icin.
    """
    frequency, _ = _document_frequency()
    missing = []
    for token in _tokens(question):
        if len(token) < MIN_TERM_LEN or token in STOPWORDS:
            continue
        if _stem(token) not in frequency:
            missing.append(token)
    return missing


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

    Sayi kontrolunun goremedigi halusinasyon turu icin. Olculen ornek:
    "Duelist rolundeki ajanlarin isimleri nelerdir?" sorusuna sistem
    "Jett, Sage, Raze ve Breach" uydurup ustune kaynak gosteriyordu; korpusta
    hicbir ajan ismi gecmiyor. Rakam olmadigi icin sayi kontrolu, "duelist"
    korpusta gectigi icin de sozcuksel kapi bunu yakalayamaz.

    Dayanak: model paraphrase yaparken yeni ozel isim uydurmaz; baglamda
    olmayan bir ozel isim varsa o bilgi baglamdan gelmiyordur.

    Yanlis pozitifi dusuk tutan iki kural: cumle basindaki kelimeler sayilmaz
    (buyuk harf ozel isim demek degildir) ve karsilastirma kaba govde uzerinden
    yapilir ("Duelist'in" ile "Duelist" ayni sayilir).
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
