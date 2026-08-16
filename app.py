"""
app.py

Streamlit arayuzu + RAG boru hattinin tamami.

Akis: kullanici soru yazar -> retrieval.py ile en alakali parcalar bulunur ->
bu parcalar "baglam" olarak sistem promptuna eklenir -> Foundry Local'in sohbet
modeli (qwen3-4b) sadece bu baglami kullanarak cevap uretir.

Calistirma: streamlit run app.py
"""

import re

import streamlit as st

from common import CHAT_MODEL, get_client
from retrieval import get_top_chunks

# qwen3-4b bir "reasoning" modelidir: cevaptan once <think>...</think> icinde
# ic sesle dusunme adimlarini uretir. Kullaniciya sadece nihai cevabi gostermek
# icin bu blogu temizliyoruz.
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Test sirasinda gozlemlendi: bu kucuk/quantized model, Turkce cevap icinde bazen
# tek tek CJK (Cince/Japonca/Korece) karakterler sikistiriyor (ornegin "bilgi检索
# ederek" gibi) - bu, kucuk coklu-dil modellerinde bilinen bir token kusuru.
# Prompt ile duzeltmeye calismak yerine (denendi, tam cozmedi), cikan cevabi
# basitce temizliyoruz.
CJK_PATTERN = re.compile(r"[一-鿿぀-ヿ가-힯]+")


FALLBACK_MESSAGE = (
    "Model bu soru icin cok uzun sure dusundu ve zamaninda bir cevaba ulasamadi. "
    "Lutfen soruyu daha kisa/spesifik sekilde tekrar sorun."
)

NO_INFO_MESSAGE = "Bu bilgi elimdeki dokumanlarda yok."

# Alaka karari UC BOLGELI bir mantikla veriliyor. Bunun sebebi olculen su iki
# gercek: (1) tek basina bir kosinus esigi yeterli degil, cunku cevaplanabilir ve
# cevaplanamaz sorularin skor dagilimlari kismen cakisiyor; (2) her karari LLM'e
# birakmak da yeterli degil, cunku GPU cikarimi tam deterministik olmadigindan
# ayni soru farkli kosularda farkli sonuclanabiliyor (test sirasinda gozlemlendi).
#
# Cozum: skorun net oldugu durumlarda KOD karar veriyor (deterministik ve hizli),
# sadece belirsiz "gri bolge" LLM denetleyicisine gidiyor.
#
#   skor >= HIGH_CONFIDENCE  -> kesin alakali (LLM'e sorulmaz)
#   skor <  SIMILARITY_THRESHOLD -> kesin alakasiz (LLM'e sorulmaz)
#   arada                    -> alaka denetleyicisine (grader) sorulur
#
# Olculen degerler: cevaplanabilir sorularin en iyi parca skorlari 0.37-0.71,
# cevaplanamaz sorularinki 0.26-0.40 araliginda.
SIMILARITY_THRESHOLD = 0.30
HIGH_CONFIDENCE_THRESHOLD = 0.50

# Alaka denetleyicisi (relevance grader) promptu.
# Neden gerekli: kucuk dil modelleri "baglamda cevap yoksa cevap verme" gibi acik
# uclu bir talimati guvenilir sekilde uygulayamiyor (test edildi, halusinasyon
# yapabiliyor). Ama AYNI model, "bu metin bu soruyu cevapliyor mu? EVET/HAYIR"
# seklindeki IKILI SINIFLANDIRMA gorevinde belirgin sekilde daha basarili.
# Bu yuzden getirilen her parca once ayri ayri denetleniyor, sadece alakali
# bulunanlar cevap uretimine gonderiliyor. (Bu yaklasim literaturde "retrieval
# grading" / CRAG deseni olarak biliniyor.)
RELEVANCE_GRADER_PROMPT = """/no_think
Gorevin: verilen BAGLAM metninin, KULLANICI SORUSUNU cevaplamak icin gerekli bilgiyi icerip icermedigine karar vermek.
Sadece tek kelime yaz: EVET veya HAYIR. Baska hicbir sey yazma.
EVET = baglamda sorunun cevabi var.
HAYIR = baglamda sorunun cevabi yok.

BAGLAM:
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

# NOT (test sirasinda bulunan gercek bir hata): Bu promptun ilk surumu modele
# "hangi kaynak dosyadan yararlandigini belirt" diyordu ve baglam da
# "[Kaynak: dosya]" bloklariyla veriliyordu. Model bunu "bloklari oldugu gibi
# yaz" seklinde yorumlayip baglam metnini kelimesi kelimesine, tekrar tekrar
# kopyaliyor ve token butcesi dolana kadar devam ediyordu (cevap hem yanlis
# hem cok yavas oluyordu). Duzeltme: acik uzunluk siniri + "kopyalama" yasagi
# + kaynak gosterimi icin dar, tek satirlik bir format.
SYSTEM_PROMPT_TEMPLATE = """/no_think
Asagidaki BAGLAM bilgisini kullanarak kullanicinin sorusunu cevapla.

Kurallar:
1. Cevabin EN FAZLA 3 cumle olsun. Kisa ve net yaz.
2. BAGLAM metnini oldugu gibi kopyalama, tekrar etme veya yapistirmaya calisma.
   Sadece sorunun cevabini kendi cumlelerinle yaz.
3. Sorunun cevabi BAGLAM'da yoksa, baska hicbir sey yazmadan sadece su cumleyi yaz:
   "Bu bilgi elimdeki dokumanlarda yok."
4. Cevabin en sonuna, yeni bir satirda, kullandigin kaynagi tek satirda ekle.
   Ornek bicim: (Kaynak: ornek_dosya.txt)

BAGLAM:
{context}
"""


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


def retrieve_and_gate(question: str, k: int = 3):
    """RAG'in "getir + alaka denetle" asamasi.

    Hem akissiz (answer_query) hem akisli (stream_answer) yol ayni mantigi
    kullansin diye ayri bir fonksiyona alindi.

    Doner: (system_prompt, kullanilan_parcalar, red_mesaji)
    red_mesaji None degilse hicbir uretim yapilmamalidir.
    """
    chunks = get_top_chunks(question, k=k)

    # 1. Kapi (ucuz): en iyi parca bile cok dusuk skorluysa, hicbir LLM cagrisi
    # yapmadan eliyoruz.
    if not chunks or chunks[0]["score"] < SIMILARITY_THRESHOLD:
        return None, chunks, NO_INFO_MESSAGE

    client = get_client()

    # 2. Kapi (asil): her parcayi ayri ayri degerlendir.
    # Skoru yeterince yuksek olanlari dogrudan kabul ediyoruz (LLM'e sormadan);
    # sadece gri bolgedekiler icin alaka denetleyicisini calistiriyoruz.
    relevant_chunks = []
    for chunk in chunks:
        if chunk["score"] >= HIGH_CONFIDENCE_THRESHOLD:
            relevant_chunks.append(chunk)
        elif is_chunk_relevant(client, question, chunk["content"]):
            relevant_chunks.append(chunk)

    if not relevant_chunks:
        return None, chunks, NO_INFO_MESSAGE

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=build_context(relevant_chunks))
    return system_prompt, relevant_chunks, None


def answer_query(question: str, k: int = 3) -> tuple[str, list[dict]]:
    """RAG pipeline'inin tamamini calistirir: getir (retrieve) + uret (generate).

    Akissiz surum - testler bunu kullanir.
    Doner: (model_cevabi, kullanilan_parcalar)
    """
    system_prompt, chunks, refusal = retrieve_and_gate(question, k=k)
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

    return answer, chunks


def stream_generation(system_prompt: str, question: str):
    """Cevabi parca parca (token token) ureten akisli surum - arayuz bunu kullanir.

    Bir generator dondurur; Streamlit'in st.write_stream fonksiyonu bunu okuyup
    ekrana yazarken kullaniciya cevap yaziliyormus gibi gorunur.

    Teknik zorluk: model cevaptan once <think>...</think> blogu uretiyor ve bu
    blok kullaniciya GOSTERILMEMELI. Akissiz surumde tum metin geldikten sonra
    regex ile temizlemek mumkundu; akisli surumde ise metin parca parca geldigi
    icin, </think> etiketi gorulene kadar gelen parcalari biriktirip bastirmiyoruz.

    Not: retrieval ve alaka denetimi burada YAPILMAZ; cagiran taraf bunlari
    onceden yapip hazir system_prompt'u verir. Boylece (maliyetli) alaka
    denetleyicisi soru basina yalnizca bir kez calisir.
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


def render_sources(chunks: list[dict]) -> None:
    """Cevabin dayandigi dokuman parcalarini acilir bir panelde gosterir."""
    if not chunks:
        return
    with st.expander("Kullanılan doküman parçaları (retrieval sonucu)"):
        for i, chunk in enumerate(chunks, start=1):
            st.markdown(
                f"**[{i}] {chunk['source']}** — benzerlik skoru: {chunk['score']:.3f}"
            )
            st.text(chunk["content"])


def main() -> None:
    st.set_page_config(page_title="Yerel RAG Asistani", page_icon="🤖")
    st.title("🤖 Yerel Doküman Asistanı")
    st.caption("Foundry Local + SQLite + RAG — tamamen çevrimdışı çalışır.")

    # Sohbet gecmisi Streamlit'in oturum durumunda (session_state) tutuluyor.
    # Streamlit her etkilesimde tum betigi bastan calistirdigi icin, gecmisi
    # burada saklamazsak her soruda onceki mesajlar kaybolurdu.
    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar:
        st.subheader("Sohbet")
        st.caption(f"Bu oturumda {len(st.session_state.messages) // 2} soru soruldu.")
        if st.button("Sohbeti temizle"):
            st.session_state.messages = []
            st.rerun()

    # Onceki mesajlari yeniden ciz.
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_sources(message.get("chunks", []))

    question = st.chat_input("Sorunuzu yazın...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Retrieval ve alaka denetimi burada, TEK SEFER yapiliyor.
    with st.spinner("Dokümanlar taranıyor..."):
        system_prompt, chunks, refusal = retrieve_and_gate(question)

    with st.chat_message("assistant"):
        if refusal is not None:
            # Dokumanlarda cevap yok: hicbir uretim yapmadan mesaji gosteriyoruz.
            answer = refusal
            st.markdown(answer)
        else:
            # st.write_stream generator'i okurken cevabi ekrana parca parca
            # yazar ve tamamlanmis metni geri dondurur.
            answer = st.write_stream(stream_generation(system_prompt, question))
        render_sources(chunks)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "chunks": chunks}
    )


if __name__ == "__main__":
    main()
