"""
app.py

Streamlit arayuzu + RAG boru hattinin tamami.

Akis: kullanici soru yazar -> retrieval.py ile en alakali parcalar bulunur ->
bu parcalar "baglam" olarak sistem promptuna eklenir -> Foundry Local'in sohbet
modeli (qwen3-4b) sadece bu baglami kullanarak cevap uretir.

Calistirma: streamlit run app.py
"""

import re
import sqlite3

import streamlit as st

from common import CHAT_MODEL, DB_PATH, EMBED_MODEL, get_client
from lexical_gate import (
    has_lexical_support,
    lexical_support_detail,
    matched_spans,
    missing_from_corpus,
    ungrounded_proper_nouns,
)
from retrieval import get_top_chunks

# qwen3-4b bir "reasoning" modelidir: cevaptan once <think>...</think> icinde
# ic sesle dusunme adimlarini uretir. Kullaniciya sadece nihai cevabi gostermek
# icin bu blogu temizliyoruz.
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Model bazen Turkce cevap icine tek tek CJK karakterler sikistiriyor (kucuk
# coklu-dil modellerinde bilinen bir kusur). Prompt ile cozulemedi, cikti
# uzerinde temizliyoruz.
CJK_PATTERN = re.compile(r"[一-鿿぀-ヿ가-힯]+")


FALLBACK_MESSAGE = (
    "Model bu soru icin cok uzun sure dusundu ve zamaninda bir cevaba ulasamadi. "
    "Lutfen soruyu daha kisa/spesifik sekilde tekrar sorun."
)

NO_INFO_MESSAGE = "Bu bilgi elimdeki dokumanlarda yok."

# --- Savunma katmanlari (ablasyon anahtarlari) ---
# Sistemin dort savunma katmani tek yerde toplandi. Varsayilan olarak hepsi
# acik; ablation.py bunlari tek tek kapatip her katmanin teste ne kattigini
# olcuyor (sonuc: ABLATION_RESULTS.md). Bir tasarim kararinin gercekten
# gerekli olup olmadigi ancak kapatilip olculerek gosterilebilir.
ENABLE_SIMILARITY_GATE = True    # 1. kapi: kosinus esigi (deterministik)
ENABLE_LEXICAL_GATE = True       # 2. kapi: sozcuksel dayanak (deterministik)
ENABLE_RELEVANCE_GRADER = True   # 3. kapi: LLM alaka denetleyicisi (CRAG)
ENABLE_GROUNDEDNESS_CHECK = True # uretim sonrasi: sayi dogrulamasi (deterministik)
ENABLE_PROPER_NOUN_CHECK = True  # uretim sonrasi: ozel isim dayanagi (deterministik)

# Alaka karari uc bolgeli:
#   skor >= HIGH_CONFIDENCE      -> kesin alakali (LLM'e sorulmaz)
#   skor <  SIMILARITY_THRESHOLD -> kesin alakasiz (LLM'e sorulmaz)
#   arada                        -> alaka denetleyicisine sorulur
# Gerekcesi ve olculen skor dagilimlari icin bkz. README.
SIMILARITY_THRESHOLD = 0.30

# DIKKAT: bu esik korpusa bagimlidir. Tek konulu bir dokuman setinde kosinus
# skoru "soruyu cevapliyor mu" degil "bu konu hakkinda mi" olcer; bu yuzden
# 0.50 yetersiz kaldi ve 0.75'e cekildi (ayrinti: README).
HIGH_CONFIDENCE_THRESHOLD = 0.75

# Alaka denetleyicisi (retrieval grading / CRAG deseni).
# Kucuk modeller "cevap yoksa cevaplama" gibi acik uclu talimatta guvenilir
# degil, ama EVET/HAYIR ikili siniflandirmada belirgin sekilde daha basarili.
# "Ayni konu hakkinda olmak yetmez" kurali bilincli olarak eklendi (bkz. README).
RELEVANCE_GRADER_PROMPT = """/no_think
Asagidaki METIN, KULLANICI SORUSUNUN cevabini iceriyor mu?

Sadece tek kelime yaz: EVET veya HAYIR. Baska hicbir sey yazma.

EVET = soruda istenen bilgi (tarih, sayi, isim, tanim, aciklama) metinde acikca yaziyor.
HAYIR = soruda istenen bilgi metinde yok. Metin ayni konu hakkinda olsa bile,
istenen bilginin kendisi metinde gecmiyorsa HAYIR yaz.

METIN:
{context}

KULLANICI SORUSU: {question}"""


def is_chunk_relevant(client, question: str, chunk_content: str) -> bool:
    """Tek bir dokuman parcasinin soruyu cevaplamaya yetip yetmedigini denetler."""
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "user",
                "content": RELEVANCE_GRADER_PROMPT.format(
                    context=chunk_content, question=question
                ),
            }
        ],
        temperature=0.0,
        max_tokens=10,
    )
    verdict = (response.choices[0].message.content or "").upper()
    return "EVET" in verdict


def strip_reasoning(raw_answer: str) -> str:
    # Guvenlik durumu: max_tokens sinirina "<think>" blogu KAPANMADAN once
    # takilirsa (test sirasinda gozlemlendi), regex eslesmez ve tum ham
    # dusunme metni kullaniciya sizabilir. Bunu tespit edip acik bir hata
    # mesaji donuyoruz, ham metni asla gostermiyoruz.
    if "<think>" in raw_answer and "</think>" not in raw_answer:
        return FALLBACK_MESSAGE

    without_think = THINK_BLOCK_PATTERN.sub("", raw_answer).strip()
    cleaned = CJK_PATTERN.sub("", without_think).strip()
    return cleaned if cleaned else FALLBACK_MESSAGE

# Uzunluk siniri ve "kopyalama yasagi" kurallari bilincli: ilk surumde model
# baglam metnini oldugu gibi tekrarlayip token butcesini tuketiyordu.
SYSTEM_PROMPT_TEMPLATE = """/no_think
Asagidaki BAGLAM bilgisini kullanarak kullanicinin sorusunu cevapla.

Kurallar:
1. Cevabin EN FAZLA 3 cumle olsun. Kisa ve net yaz.
2. BAGLAM metnini oldugu gibi kopyalama, tekrar etme veya yapistirmaya calisma.
   Sadece sorunun cevabini kendi cumlelerinle yaz.
3. SADECE BAGLAM'daki bilgiyi kullan. Konu hakkinda kendi bildiklerini KULLANMA.
   Bir bilgiyi biliyor olsan bile, BAGLAM'da yazmiyorsa o bilgiyi verme.
4. Sorunun cevabi BAGLAM'da yoksa, baska hicbir sey yazmadan sadece su cumleyi yaz:
   "Bu bilgi elimdeki dokumanlarda yok."
5. Cevabin en sonuna, yeni bir satirda, kullandigin kaynagi tek satirda ekle.
   Ornek bicim: (Kaynak: ornek_dosya.txt)

BAGLAM:
{context}
"""


# Dayanak (groundedness) kontrolu: uretilen cevaptaki bilgi gercekten baglamda
# geciyor mu? Populer bir konuda model, baglamda olmayan bilgiyi kendi egitim
# verisinden verebiliyor; bu kontrol onu yakalamak icin.

NUMBER_PATTERN = re.compile(r"\d+")

# Sistem promptunun 5. kuralinin istedigi kaynak satiri.
SOURCE_CITATION_PATTERN = re.compile(r"\(\s*kaynak\s*:", re.IGNORECASE)


MAX_SENTENCES = 3
MAX_ANSWER_CHARS = 700

# Cevabi anlamli birimlere boler: cumle sonlari VE satir sonlari.
# Satir sonu da sinir sayilmali, cunku model bazen noktalama kullanmayan
# madde listeleri uretiyor - o durumda tum cevap tek bir "cumle" gorunur.
ANSWER_UNIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")


# Yinelenme tespiti. Kucuk modeller bazen ayni ifadeyi onlarca kez tekrarlayan
# bir donguye giriyor (arayuzde gozlemlendi). Bu cikti anlamsizdir ve kirpilarak
# duzeltilemez - kirpilmis hali de anlamsiz kalir.
REPETITION_MIN_WORDS = 30
REPETITION_MIN_UNIQUE_RATIO = 0.35


def is_degenerate_repetition(answer: str) -> bool:
    """Cevap, ayni ifadeyi tekrarlayan bir donguye mi girmis?

    Olcut: benzersiz kelime orani. Saglikli bir cevapta kelimelerin buyuk
    bolumu farklidir (olculen degerler 0.7 uzeri); donguye giren bir ciktida
    ayni birkac kelime yuzlerce kez tekrarlandigi icin bu oran cok dusuk cikar.
    Kisa cevaplar degerlendirilmez - dogal tekrar yaniltici olabilir.
    """
    words = " ".join(answer.split()).lower().split()
    if len(words) < REPETITION_MIN_WORDS:
        return False
    return len(set(words)) / len(words) < REPETITION_MIN_UNIQUE_RATIO


def limit_answer(answer: str) -> str:
    """Cevabi, sistem promptunun soz verdigi sinirlara kodla indirger.

    Promptun "en fazla 3 cumle" kurali bir talep, garanti degil: belirsiz
    sorularda model 1000-1300 karakter uretebiliyordu (olculdu). Iki sinir
    birlikte uygulanir - biri digerinin kacirdigini yakalar: en fazla
    MAX_SENTENCES birim (cumle ya da madde satiri) ve MAX_ANSWER_CHARS karakter.
    """
    if answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE):
        return answer

    units = [u.strip() for u in ANSWER_UNIT_PATTERN.split(answer.strip()) if u.strip()]
    if not units:
        return answer

    kept: list[str] = []
    length = 0
    for unit in units[:MAX_SENTENCES]:
        # Butceyi asacaksa ekleme - ama en az bir birim her zaman kalsin,
        # yoksa cok uzun tek cumlelik cevaplarda bos metin donerdi.
        if kept and length + len(unit) > MAX_ANSWER_CHARS:
            break
        kept.append(unit)
        length += len(unit) + 1

    limited = " ".join(kept).strip()

    # Sert sinir: yukaridaki dongude ILK birim uzunlugu ne olursa olsun
    # korunuyor, yani noktalama kullanmayan tek parca uzun bir cevap hic
    # kirpilmadan geciyordu (arayuzde gozlemlendi). Burada kelime sinirindan
    # kesiliyor.
    if len(limited) > MAX_ANSWER_CHARS:
        cut = limited[:MAX_ANSWER_CHARS]
        space = cut.rfind(" ")
        limited = (cut[:space] if space > 0 else cut).rstrip(" ,;") + "…"

    return limited


def ensure_source_citation(answer: str, chunks: list[dict]) -> str:
    """Cevabin sonunda kaynak satiri yoksa, kullanilan parcalardan uretip ekler.

    Promptun 5. kurali bu satiri modelden istiyor ama model bunu cevaplarin
    yaklasik ucte birinde atliyordu (olculdu: 6 soruda 2). Dosya adi retrieval
    asamasindan zaten bilindigi icin modelden istemeye gerek yok. Model dogru
    yazdiginda bu fonksiyon hicbir sey yapmaz.
    """
    if not chunks:
        return answer
    if answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE):
        return answer
    if SOURCE_CITATION_PATTERN.search(answer):
        return answer

    # Ayni dosya birden fazla parcadan gelebilir; sirayi bozmadan tekillestir.
    sources = list(dict.fromkeys(chunk["source"] for chunk in chunks))
    return f"{answer.rstrip()}\n\n(Kaynak: {', '.join(sources)})"


def has_ungrounded_numbers(context: str, answer: str) -> bool:
    """Cevapta, baglamda hic gecmeyen bir sayi var mi?

    Deterministik (modelden bagimsiz) bir kontrol. Gerekcesi: LLM tabanli dayanak
    kontrolu tek basina yetmedi - model kendi halusinasyonunu "dayanakli" diye
    onayladi. Sayilar kodla kesin dogrulanabildigi icin bu kontrol guvenilir.
    """
    context_numbers = set(NUMBER_PATTERN.findall(context))
    answer_numbers = set(NUMBER_PATTERN.findall(answer))
    return bool(answer_numbers - context_numbers)


def is_answer_grounded(client, context: str, answer: str) -> bool:
    """Uretilen cevabin baglamdaki bilgiye dayanip dayanmadigini dogrular.

    Yalnizca deterministik kontroller icerir. LLM'e "bu cevap baglamla uyumlu
    mu" diye sormak uc farkli prompt ile denendi ve ucunde de basarisiz oldu:
    model bir seferinde kendi halusinasyonunu onayladi, digerlerinde gecerli
    cevaplari eledi (testler 8/9 -> 4/9). Ayni modeli kendi ciktisinin hakemi
    yapmak calismiyor; kesin hesaplanabilen olcutler kullaniliyor.
    """
    # Zaten "bilmiyorum" diyorsak dogrulamaya gerek yok.
    if answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE):
        return True

    if ENABLE_GROUNDEDNESS_CHECK and has_ungrounded_numbers(context, answer):
        return False

    # Ozel isim dayanagi: sayi kontrolunun goremedigi halusinasyon turu.
    # Olculen ornek: "Duelist rolundeki ajanlarin isimleri nelerdir?" sorusuna
    # sistem "Jett, Sage, Raze, Breach" uydurup ustune kaynak gosteriyordu;
    # korpusta hicbir ajan ismi gecmiyor. Rakam olmadigi icin sayi kontrolu,
    # "duelist" kelimesi korpusta gectigi icin de sozcuksel kapi yakalayamadi.
    if ENABLE_PROPER_NOUN_CHECK and ungrounded_proper_nouns(context, answer):
        return False

    return True


def _generate_answer(client, system_prompt: str, question: str, max_tokens: int) -> str:
    """Sohbet modelinden cevabi uretir ve ic dusunme adimini temizler."""
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            # "/no_think" hem sistem hem kullanici mesajina ekleniyor; tek yerde
            # verildiginde model bunu bazen goz ardi edebiliyor.
            {"role": "user", "content": f"{question} /no_think"},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return strip_reasoning(response.choices[0].message.content)


def build_context(chunks: list[dict]) -> str:
    """Getirilen parcalari tek bir baglam metnine cevirir.

    Kaynak adi, modelin kopyalamaya tesvik olmamasi icin blok basligi yerine
    sade bir satir olarak veriliyor (bkz. SYSTEM_PROMPT_TEMPLATE'teki not).
    """
    parts = []
    for chunk in chunks:
        parts.append(f"Kaynak dosya: {chunk['source']}\n{chunk['content']}")
    return "\n\n".join(parts)


def _log(trace, gate: str, passed: bool | None, detail: str) -> None:
    """Karar izine bir adim ekler (trace None ise hicbir sey yapmaz)."""
    if trace is None:
        return
    trace.append({"kapi": gate, "gecti": passed, "detay": detail})


def retrieve_and_gate(question: str, k: int = 3, trace: list | None = None):
    """RAG'in "getir + alaka denetle" asamasi.

    Hem akissiz (answer_query) hem akisli (stream_answer) yol ayni mantigi
    kullansin diye ayri bir fonksiyona alindi.

    trace: verilirse, her kapinin karari bu listeye yazilir. Arayuz bunu
    "karar izi" panelinde gosteriyor. Isteğe bagli tutuldu ki mevcut
    cagiranlarin (testler dahil) imzasi degismesin.

    Doner: (system_prompt, kullanilan_parcalar, red_mesaji, baglam_metni)
    red_mesaji None degilse hicbir uretim yapilmamalidir.
    """
    # 0. Kapi: bos sorgu. Bu kontrol olmadan sorgu dogrudan embedding API'sine
    # gidiyor ve Foundry Local HTTP 400 donuyordu ("Embedding input at index 0
    # is null, empty..."); yakalanmayan exception uygulamayi cokertiyordu.
    # Kontrol burada, cunku hem akissiz hem akisli yol buradan geciyor.
    if not question or not question.strip():
        _log(trace, "0. Boş sorgu", False, "sorgu boş — hiçbir işlem yapılmadı")
        return None, [], NO_INFO_MESSAGE, ""

    chunks = get_top_chunks(question, k=k)

    # 1. Kapi (ucuz): en iyi parca bile cok dusuk skorluysa, hicbir LLM cagrisi
    # yapmadan eliyoruz.
    if not chunks:
        _log(trace, "Getirme", False, "veritabanında parça yok")
        return None, chunks, NO_INFO_MESSAGE, ""

    _log(
        trace,
        "Getirme",
        True,
        f"{len(chunks)} parça getirildi · en yüksek skor {chunks[0]['score']:.3f}",
    )

    if ENABLE_SIMILARITY_GATE and chunks[0]["score"] < SIMILARITY_THRESHOLD:
        _log(
            trace,
            "1. Kosinüs eşiği",
            False,
            f"{chunks[0]['score']:.3f} < {SIMILARITY_THRESHOLD} — LLM'e hiç gidilmedi",
        )
        return None, chunks, NO_INFO_MESSAGE, ""

    _log(
        trace,
        "1. Kosinüs eşiği",
        True,
        f"{chunks[0]['score']:.3f} ≥ {SIMILARITY_THRESHOLD}",
    )

    # 2. Kapi (sozcuksel): kosinus benzerliginin goremedigi konu kaymasini
    # yakalar. Deterministik ve LLM cagrisindan once calisiyor - hem daha
    # guvenilir hem daha hizli. Ayrinti ve olcum: lexical_gate.py
    if ENABLE_LEXICAL_GATE:
        retrieved_text = "\n".join(chunk["content"] for chunk in chunks)
        supported, stems, matched = lexical_support_detail(question, retrieved_text)
        if not stems:
            _log(trace, "2. Sözcüksel dayanak", None,
                 "sorunun ayırt edici kelimesi yok — karar sonraki kapıya bırakıldı")
        elif not supported:
            _log(trace, "2. Sözcüksel dayanak", False,
                 f"aranan: {', '.join(stems)} — hiçbiri metinde geçmiyor")
            return None, chunks, NO_INFO_MESSAGE, ""
        else:
            _log(trace, "2. Sözcüksel dayanak", True,
                 f"eşleşen: {', '.join(matched)} (aranan: {', '.join(stems)})")

    client = get_client()

    # 3. Kapi (anlamsal): her parcayi ayri ayri degerlendir.
    # Skoru yeterince yuksek olanlari dogrudan kabul ediyoruz (LLM'e sormadan);
    # sadece gri bolgedekiler icin alaka denetleyicisini calistiriyoruz.
    relevant_chunks = []
    auto_accepted = 0
    asked_to_llm = 0
    for chunk in chunks:
        if not ENABLE_RELEVANCE_GRADER:
            relevant_chunks.append(chunk)
        elif chunk["score"] >= HIGH_CONFIDENCE_THRESHOLD:
            auto_accepted += 1
            relevant_chunks.append(chunk)
        else:
            asked_to_llm += 1
            if is_chunk_relevant(client, question, chunk["content"]):
                relevant_chunks.append(chunk)

    if not relevant_chunks:
        _log(trace, "3. Alaka denetleyicisi", False,
             f"{asked_to_llm} parça LLM'e soruldu, hiçbiri kabul edilmedi")
        return None, chunks, NO_INFO_MESSAGE, ""

    _log(
        trace,
        "3. Alaka denetleyicisi",
        True,
        f"{len(relevant_chunks)}/{len(chunks)} parça kabul · "
        f"{auto_accepted} tanesi skoru ≥ {HIGH_CONFIDENCE_THRESHOLD} olduğu için "
        f"LLM'e sorulmadan · {asked_to_llm} tanesi LLM'e soruldu",
    )

    context = build_context(relevant_chunks)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)
    return system_prompt, relevant_chunks, None, context


def answer_query(question: str, k: int = 3) -> tuple[str, list[dict]]:
    """RAG pipeline'inin tamamini calistirir: getir (retrieve) + uret (generate).

    Akissiz surum - testler bunu kullanir.
    Doner: (model_cevabi, kullanilan_parcalar)
    """
    system_prompt, chunks, refusal, context = retrieve_and_gate(question, k=k)
    if refusal is not None:
        return refusal, chunks

    client = get_client()
    answer = _generate_answer(client, system_prompt, question, max_tokens=400)

    # Nadiren, "/no_think" yonergesine ragmen model yine de uzun bir ic dusunme
    # adimina giriyor ve token butcesi dolmadan cevaba ulasamiyor (test sirasinda
    # gozlemlendi: 3 kosudan 1'inde). Bu durumu strip_reasoning tespit edip
    # FALLBACK_MESSAGE donuyor; boyle bir durumda daha genis token butcesiyle
    # bir kez daha deniyoruz ki dusunme adimi tamamlanip cevap uretilebilsin.
    if answer == FALLBACK_MESSAGE:
        answer = _generate_answer(client, system_prompt, question, max_tokens=1200)

    # Yinelenme dongusu: kirpmak ise yaramaz, bir kez daha uretmeyi deniyoruz.
    # Ikinci deneme de donguye girerse cevabi hic gostermiyoruz.
    if is_degenerate_repetition(answer):
        answer = _generate_answer(client, system_prompt, question, max_tokens=400)
        if is_degenerate_repetition(answer):
            return FALLBACK_MESSAGE, chunks

    # Son savunma: cevaptaki bilgi gercekten baglamda geciyor mu?
    if not is_answer_grounded(client, context, answer):
        return NO_INFO_MESSAGE, chunks

    return ensure_source_citation(limit_answer(answer), chunks), chunks


def stream_generation(system_prompt: str, question: str):
    """Cevabi token token ureten akisli surum - arayuz bunu kullanir.

    Teknik zorluk: model cevaptan once <think> blogu uretiyor ve bu blok
    kullaniciya gosterilmemeli. Metin parca parca geldigi icin, </think>
    etiketi gorulene kadar gelen parcalar biriktirilip bastirilmiyor.

    Retrieval ve alaka denetimi burada yapilmaz; cagiran taraf hazir
    system_prompt'u verir, boylece maliyetli denetleyici soru basina bir kez
    calisir.
    """
    client = get_client()
    stream = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{question} /no_think"},
        ],
        temperature=0.2,
        max_tokens=400,
        stream=True,
    )

    buffer = ""
    thinking_handled = False
    # Dusunme blogu kapandiktan sonra model genelde once bos satirlar gonderiyor;
    # cevap bos satirla baslamasin diye ilk gercek metne kadar bunlari kirpiyoruz.
    content_started = False

    def emit(text: str) -> str:
        nonlocal content_started
        cleaned = CJK_PATTERN.sub("", text)
        if not content_started:
            cleaned = cleaned.lstrip()
            if cleaned:
                content_started = True
        return cleaned

    for part in stream:
        if not part.choices:
            continue
        delta = part.choices[0].delta.content or ""
        if not delta:
            continue

        if thinking_handled:
            piece = emit(delta)
            if piece:
                yield piece
            continue

        # Henuz dusunme blogunun bitip bitmedigini bilmiyoruz: biriktir.
        buffer += delta

        if "</think>" in buffer:
            # Dusunme blogu bitti; sonrasindaki metni yayinlamaya basla.
            thinking_handled = True
            remainder = buffer.split("</think>", 1)[1]
            buffer = ""
            piece = emit(remainder)
            if piece:
                yield piece
        elif "<think>" not in buffer and len(buffer) > 12:
            # Yeterince metin geldi ve icinde <think> yok: bu model dusunme
            # adimi uretmiyor demektir, biriktirmeyi birakip dogrudan yayinla.
            thinking_handled = True
            piece = emit(buffer)
            buffer = ""
            if piece:
                yield piece

    # Akis bitti ama hicbir sey yayinlanmadiysa (ornegin dusunme blogu
    # kapanmadan token butcesi doldu), kullaniciya ham dusunme metni yerine
    # anlasilir bir mesaj gosteriyoruz.
    if not thinking_handled:
        yield FALLBACK_MESSAGE


def rejection_hint(question: str, trace: list[dict]) -> str:
    """Reddedilen bir soru icin kullaniciya somut ipucu uretir.

    "Bilmiyorum" tek basina cikmaz sokaktir: kullanici sorusunun mu yanlis
    anlasildigini yoksa bilginin gercekten olmadigini mi bilemez. Bu ipucu
    farki soyluyor - hangi kelimenin bilgi tabaninda hic gecmedigini gosterir.

    Yalnizca sozcuksel kapinin reddettigi durumlarda uretilir; diger kapilarin
    reddi farkli bir sebebe dayanir ve eksik kelime listesi orada yaniltici
    olurdu. Cevabin kendisi degismez, bu yalnizca altina eklenen bir not.
    """
    rejected_by_lexical = any(
        step["kapi"].startswith("2.") and step["gecti"] is False for step in trace
    )
    if not rejected_by_lexical:
        return ""

    missing = missing_from_corpus(question)
    if not missing:
        return ""
    return (
        "Şu kelimeler dokümanlarda hiç geçmiyor: "
        + ", ".join(f"“{word}”" for word in missing)
        + " — bu konu bilgi tabanında yok."
    )


def render_trace(trace: list[dict]) -> None:
    """Boru hattinin karar izini gosterir.

    NEDEN: RAG boru hatti kullanici icin tamamen gorunmez - ekranda yalnizca
    cevap (ya da "bilmiyorum") beliriyor, o karari HANGI katmanin verdigi
    gorunmuyor. Bu panel her kapinin kararini ve gerekcesini aciyor; sistemin
    "bilmiyorum" demesi de artik bir kara kutu degil, izlenebilir bir karar.
    """
    if not trace:
        return

    icons = {True: "✅", False: "⛔", None: "➖"}
    with st.expander(f"🔍 Karar izi ({len(trace)} adım)"):
        for step in trace:
            icon = icons.get(step["gecti"], "➖")
            st.markdown(
                f"{icon} **{step['kapi']}** — "
                f"<span style='opacity:0.75'>{step['detay']}</span>",
                unsafe_allow_html=True,
            )


def highlight_matches(text: str, question: str) -> str:
    """Sorunun ayirt edici kelimeleriyle eslesen yerleri isaretler.

    Sozcuksel kapinin neye bakarak karar verdigi, karari okumak yerine
    metinde dogrudan gorulebilir hale gelir.
    """
    spans = matched_spans(question, text)
    if not spans:
        return text

    parts = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        parts.append(
            f"<mark style='background:rgba(15,182,168,0.35);"
            f"color:inherit;padding:0 2px;border-radius:2px'>{text[start:end]}</mark>"
        )
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def render_sources(chunks: list[dict], question: str = "") -> None:
    """Cevabin dayandigi dokuman parcalarini acilir bir panelde gosterir."""
    if not chunks:
        return
    with st.expander(f"📄 Kaynaklar ({len(chunks)} parça)"):
        for i, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{i}. {chunk['source']}**")
            # Skoru hem sayi hem gorsel cubuk olarak gosteriyoruz; kosinus
            # benzerligi 0-1 arasinda oldugu icin dogrudan progress'e verilebilir.
            st.progress(
                min(max(chunk["score"], 0.0), 1.0),
                text=f"benzerlik: {chunk['score']:.3f}",
            )
            st.markdown(
                "<div style='font-size:0.82rem;opacity:0.85;white-space:pre-wrap'>"
                f"{highlight_matches(chunk['content'], question)}</div>",
                unsafe_allow_html=True,
            )
            if i < len(chunks):
                st.divider()


SAMPLE_QUESTIONS = [
    "Valorant kaç kişiyle oynanır?",
    "Duelist rolünün görevi nedir?",
    "Eco turu ne demek?",
    "Tepme kontrolü nedir?",
]

USER_AVATAR = "🧑"
BOT_AVATAR = "🤖"

# Valorant'in gorsel kimligine yakin bir gorunum icin ozel CSS.
# Temel renkler .streamlit/config.toml'da tanimli; burasi sadece bicimsel
# ince ayar (koseli kenarlar, kirmizi vurgu cizgileri, buyuk harf basliklar).
VALORANT_RED = "#FF4655"
VALORANT_TEAL = "#0FB6A8"

CUSTOM_CSS = f"""
<style>
/* Baslik: Valorant'in koseli, buyuk harfli, sikistirilmis tipografisine yakin */
h1 {{
    text-transform: uppercase;
    letter-spacing: 3px;
    font-weight: 800 !important;
    border-left: 6px solid {VALORANT_RED};
    padding-left: 16px;
    margin-bottom: 4px !important;
}}

/* Sohbet balonlari: sol kenarda ince vurgu cizgisi, koseli kutular.
   Varsayilan (kullanici) kirmizi; asistan mesajlari asagida yesile cevriliyor. */
[data-testid="stChatMessage"] {{
    background-color: rgba(255, 70, 85, 0.06);
    border-left: 3px solid {VALORANT_RED};
    border-radius: 2px;
    padding: 14px 16px;
    margin-bottom: 10px;
}}

/* Asistan (robot) mesajlari yesil. Streamlit rol icin ayri bir secici vermiyor,
   bu yuzden mesaji sardigimiz isaretleyici sinifa gore ayiriyoruz. */
[data-testid="stChatMessage"]:has(.bot-msg) {{
    background-color: rgba(15, 182, 168, 0.07);
    border-left-color: {VALORANT_TEAL};
}}

/* Dugmeler: koseli, kirmizi cerceveli, buyuk harf */
.stButton > button {{
    border-radius: 2px;
    border: 1px solid rgba(255, 70, 85, 0.45);
    background-color: rgba(255, 70, 85, 0.06);
    color: #ECE8E1;
    font-weight: 600;
    letter-spacing: 0.4px;
    transition: all 0.15s ease-in-out;
}}
.stButton > button:hover {{
    border-color: {VALORANT_RED};
    background-color: rgba(255, 70, 85, 0.18);
    transform: translateX(2px);
}}

/* Kenar cubugu basliklari */
[data-testid="stSidebar"] h3 {{
    text-transform: uppercase;
    letter-spacing: 2px;
    font-size: 0.85rem !important;
    color: {VALORANT_RED};
    border-bottom: 1px solid rgba(255, 70, 85, 0.25);
    padding-bottom: 6px;
}}

/* Istatistik kutulari */
[data-testid="stMetricValue"] {{
    color: {VALORANT_RED};
    font-weight: 800;
}}

/* Kaynak paneli */
[data-testid="stExpander"] {{
    border: 1px solid rgba(255, 70, 85, 0.25);
    border-radius: 2px;
}}

/* Sohbet giris kutusu */
[data-testid="stChatInput"] {{
    border: 1px solid rgba(255, 70, 85, 0.35);
    border-radius: 2px;
}}
</style>
"""


@st.cache_data(show_spinner=False)
def knowledge_base_summary() -> list[tuple[str, int]]:
    """Bilgi tabanindaki her dokumanin adi ve parca sayisi."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source"
    ).fetchall()
    conn.close()
    return rows


def render_knowledge_base() -> None:
    """Kenar cubugunda bilgi tabaninin icerigini gosterir.

    Asistan yalnizca bu dokumanlara dayanarak cevap verdigi icin, neyin
    sorulabilecegini bilmek kullanicinin isini kolaylastiriyor; aksi halde
    "bilmiyorum" cevaplari keyfi gorunuyor.
    """
    try:
        documents = knowledge_base_summary()
    except sqlite3.Error:
        return
    if not documents:
        return

    total = sum(count for _name, count in documents)
    st.markdown(f"### Bilgi tabanı ({len(documents)} doküman)")
    with st.expander(f"{total} parça · listeyi gör"):
        for name, count in documents:
            baslik = name.replace(".txt", "").replace("_", " ")
            st.markdown(
                f"<div style='font-size:0.8rem;opacity:0.8'>{baslik}"
                f"<span style='opacity:0.5'> · {count} parça</span></div>",
                unsafe_allow_html=True,
            )


def render_sidebar() -> None:
    """Kenar cubugu: model rozeti, ornek sorular, sohbet kontrolu."""
    with st.sidebar:
        # Model rozeti: teknik ayrintilari yigmak yerine tek satirlik sade bir
        # gosterim. Modelin yerel calistigini belirten kucuk bir durum isigi var.
        st.markdown(
            f"""
            <div style="
                border: 1px solid rgba(255,70,85,0.35);
                border-left: 3px solid {VALORANT_RED};
                border-radius: 2px;
                padding: 12px 14px;
                margin-bottom: 22px;">
                <div style="
                    font-size: 0.68rem;
                    letter-spacing: 2px;
                    opacity: 0.55;
                    text-transform: uppercase;">Model</div>
                <div style="
                    font-size: 1.15rem;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                    margin-top: 2px;">{CHAT_MODEL}</div>
                <div style="font-size: 0.72rem; opacity: 0.6; margin-top: 6px;">
                    <span style="
                        display:inline-block;
                        width:7px; height:7px;
                        border-radius:50%;
                        background:{VALORANT_TEAL};
                        margin-right:6px;"></span>yerel · çevrimdışı
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        render_knowledge_base()

        st.markdown("### Örnek sorular")
        # Dugmeye basildiginda Streamlit zaten betigi bastan calistiriyor; soruyu
        # oturum durumuna yaziyoruz, main() asagida onu okuyup isliyor.
        for sample in SAMPLE_QUESTIONS:
            if st.button(sample, use_container_width=True, key=f"ornek_{sample}"):
                st.session_state.pending_question = sample

        st.divider()
        if st.button("Sohbeti temizle", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Valorant Bilgi Asistanı",
        page_icon="🎯",
        initial_sidebar_state="expanded",
    )

    # Sohbet gecmisi Streamlit'in oturum durumunda (session_state) tutuluyor.
    # Streamlit her etkilesimde tum betigi bastan calistirdigi icin, gecmisi
    # burada saklamazsak her soruda onceki mesajlar kaybolurdu.
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    st.title("Valorant Bilgi Asistanı")
    st.caption(
        "Foundry Local + SQLite + RAG · tamamen çevrimdışı · veri cihazdan çıkmaz"
    )

    render_sidebar()

    # Sohbet bostayken kisa bir yonlendirme gosteriyoruz.
    if not st.session_state.messages:
        st.markdown(
            f"""
            <div style="
                border-left: 3px solid {VALORANT_TEAL};
                background: rgba(15, 182, 168, 0.07);
                padding: 14px 18px;
                margin: 8px 0 18px 0;
                border-radius: 2px;">
                <strong style="letter-spacing:1px;">BRIEFING</strong><br>
                Bu asistan yalnızca <code>data/</code> klasöründeki dokümanlara dayanarak
                cevap verir. Dokümanlarda olmayan bir soru sorarsan bilmediğini söyler —
                soldaki örnek sorulardan biriyle başlayabilirsin.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Onceki mesajlari yeniden ciz.
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=message.get("avatar")):
            if message["role"] == "assistant":
                # CSS'in asistan mesajini yesile boyayabilmesi icin gorunmez
                # bir isaretleyici (bkz. CUSTOM_CSS icindeki .bot-msg kurali).
                st.markdown("<span class='bot-msg'></span>", unsafe_allow_html=True)
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_trace(message.get("trace", []))
                render_sources(message.get("chunks", []), message.get("question", ""))

    # Soru ya sohbet kutusundan ya da kenar cubugundaki ornek dugmesinden gelir.
    question = st.chat_input("Sorunuzu yazın...")
    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None

    if not question:
        return

    # Soruyu once SADECE ekranda gosteriyoruz, gecmise henuz yazmiyoruz.
    # Sebep: cevap uretilirken kullanici baska bir dugmeye basarsa Streamlit
    # betigi bastan calistirir ve uretim yarida kesilir. Soruyu gecmise hemen
    # yazsaydik, cevabi olmayan "oksuz" bir soru mesaji kalirdi (gozlemlendi).
    # Ikisini de en sonda, cevap hazir olunca birlikte yaziyoruz.
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(question)

    # Retrieval ve alaka denetimi burada, TEK SEFER yapiliyor.
    # trace: her kapinin karari buraya yaziliyor, asagida panelde gosteriliyor.
    trace: list[dict] = []
    with st.spinner("Dokümanlar taranıyor..."):
        system_prompt, chunks, refusal, context = retrieve_and_gate(
            question, trace=trace
        )

    with st.chat_message("assistant", avatar=BOT_AVATAR):
        st.markdown("<span class='bot-msg'></span>", unsafe_allow_html=True)
        if refusal is not None:
            # Dokumanlarda cevap yok: hicbir uretim yapmadan mesaji gosteriyoruz.
            answer = refusal
            st.markdown(answer)
            hint = rejection_hint(question, trace)
            if hint:
                st.caption(hint)
        else:
            # Cevabi degistirilebilir bir alana yaziyoruz: akis bittikten sonra
            # dayanak kontrolu basarisiz olursa yazilani silip yerine
            # "bilmiyorum" mesajini koyabilmemiz gerekiyor.
            slot = st.empty()
            with slot.container():
                answer = st.write_stream(stream_generation(system_prompt, question))

            # Yinelenme dongusu akis sirasinda durdurulamaz (metin zaten
            # ekrana yazildi), ama akis bitince tespit edilip yerine saglikli
            # bir cevap konabilir. Bir kez daha uretiyoruz; o da donguye
            # girerse cevabi hic gostermiyoruz.
            if is_degenerate_repetition(answer):
                _log(trace, "Yinelenme kontrolü", False,
                     "model aynı ifadeyi tekrarladı — cevap yeniden üretildi")
                answer = _generate_answer(
                    get_client(), system_prompt, question, max_tokens=400
                )
                if is_degenerate_repetition(answer):
                    answer = FALLBACK_MESSAGE
                slot.empty()
                slot.markdown(answer)

            # Uretim sonrasi deterministik kontroller - hepsi ize yaziliyor.
            bad_numbers = ENABLE_GROUNDEDNESS_CHECK and has_ungrounded_numbers(
                context, answer
            )
            bad_names = ENABLE_PROPER_NOUN_CHECK and ungrounded_proper_nouns(
                context, answer
            )

            if bad_numbers or bad_names:
                reason = (
                    "bağlamda geçmeyen sayı var"
                    if bad_numbers
                    else f"bağlamda geçmeyen özel isim: {', '.join(bad_names)}"
                )
                _log(trace, "4. Dayanak kontrolü", False,
                     f"{reason} — cevap reddedildi")
                answer = NO_INFO_MESSAGE
                slot.empty()
                slot.markdown(answer)
            else:
                _log(trace, "4. Dayanak kontrolü", True,
                     "cevaptaki sayı ve özel isimler bağlamda geçiyor")

                shortened = limit_answer(answer)
                if shortened != answer:
                    _log(trace, "5. Uzunluk sınırı", None,
                         f"{len(answer)} → {len(shortened)} karakter (en fazla "
                         f"{MAX_SENTENCES} birim / {MAX_ANSWER_CHARS} karakter)")

                finalized = ensure_source_citation(shortened, chunks)
                if finalized != shortened:
                    _log(trace, "6. Kaynak satırı", None,
                         "model kaynağı yazmamıştı — kodla eklendi")

                if finalized != answer:
                    answer = finalized
                    slot.empty()
                    slot.markdown(answer)

        render_trace(trace)
        render_sources(chunks, question)

    # Cevap tamamlandi: soru ve cevabi birlikte gecmise yaziyoruz.
    st.session_state.messages.append(
        {"role": "user", "content": question, "avatar": USER_AVATAR}
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "chunks": chunks,
            "trace": trace,
            # Soru saklaniyor ki gecmisteki mesajlarda da kaynak panelindeki
            # eslesen kelimeler vurgulanabilsin.
            "question": question,
            "avatar": BOT_AVATAR,
        }
    )


if __name__ == "__main__":
    main()
