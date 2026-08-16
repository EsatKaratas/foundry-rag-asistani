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
GROUNDEDNESS_PROMPT = """/no_think
Asagida bir METIN ve bu metne dayanarak verildigi iddia edilen bir CEVAP var.

CEVAP'ta gecen bilgilerin tamami METIN'de yaziyor mu?

Sadece tek kelime yaz: EVET veya HAYIR. Baska hicbir sey yazma.

EVET = cevaptaki tum bilgiler metinde bulunuyor.
HAYIR = cevapta, metinde bulunmayan en az bir bilgi var.

METIN:
{context}

CEVAP: {answer}"""


NUMBER_PATTERN = re.compile(r"\d+")


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
    """Uretilen cevabin baglamdaki bilgiye dayanip dayanmadigini dogrular."""
    # Zaten "bilmiyorum" diyorsak dogrulamaya gerek yok.
    if answer.strip() in (NO_INFO_MESSAGE, FALLBACK_MESSAGE):
        return True

    # 1. Deterministik kontrol (modelden bagimsiz, bu yuzden once bu calisiyor).
    if has_ungrounded_numbers(context, answer):
        return False

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "user",
                "content": GROUNDEDNESS_PROMPT.format(context=context, answer=answer),
            }
        ],
        temperature=0.0,
        max_tokens=10,
    )
    verdict = (response.choices[0].message.content or "").upper()
    return "EVET" in verdict


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

    Doner: (system_prompt, kullanilan_parcalar, red_mesaji, baglam_metni)
    red_mesaji None degilse hicbir uretim yapilmamalidir.
    """
    chunks = get_top_chunks(question, k=k)

    # 1. Kapi (ucuz): en iyi parca bile cok dusuk skorluysa, hicbir LLM cagrisi
    # yapmadan eliyoruz.
    if not chunks or chunks[0]["score"] < SIMILARITY_THRESHOLD:
        return None, chunks, NO_INFO_MESSAGE, ""

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
        return None, chunks, NO_INFO_MESSAGE, ""

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

    # Son savunma: cevaptaki bilgi gercekten baglamda geciyor mu?
    if not is_answer_grounded(client, context, answer):
        return NO_INFO_MESSAGE, chunks

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
    with st.expander(f"📄 Kaynaklar ({len(chunks)} parça)"):
        for i, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{i}. {chunk['source']}**")
            # Skoru hem sayi hem gorsel cubuk olarak gosteriyoruz; kosinus
            # benzerligi 0-1 arasinda oldugu icin dogrudan progress'e verilebilir.
            st.progress(
                min(max(chunk["score"], 0.0), 1.0),
                text=f"benzerlik: {chunk['score']:.3f}",
            )
            st.caption(chunk["content"])
            if i < len(chunks):
                st.divider()


SAMPLE_QUESTIONS = [
    "Valorant kaç kişiyle oynanır?",
    "Duelist rolünün görevi nedir?",
    "Eco turu ne demek?",
    "Tepme kontrolü nedir?",
]

USER_AVATAR = "🎮"
BOT_AVATAR = "🎯"

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

/* Sohbet balonlari: sol kenarda ince vurgu cizgisi, koseli kutular */
[data-testid="stChatMessage"] {{
    background-color: rgba(31, 39, 49, 0.55);
    border-left: 3px solid {VALORANT_RED};
    border-radius: 2px;
    padding: 14px 16px;
    margin-bottom: 10px;
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


def render_sidebar() -> None:
    """Kenar cubugu: bilgi tabani istatistikleri, model bilgisi, ornek sorular."""
    with st.sidebar:
        st.markdown("### ⚙️ Sistem")

        # Bilgi tabani istatistikleri dogrudan veritabanindan okunuyor.
        try:
            conn = sqlite3.connect(DB_PATH)
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            doc_count = conn.execute(
                "SELECT COUNT(DISTINCT source) FROM chunks"
            ).fetchone()[0]
            conn.close()
        except sqlite3.Error:
            chunk_count = doc_count = 0

        col1, col2 = st.columns(2)
        col1.metric("Doküman", doc_count)
        col2.metric("Parça", chunk_count)

        st.caption(f"💬 Sohbet: `{CHAT_MODEL}`")
        st.caption(f"🔎 Embedding: `{EMBED_MODEL}`")
        st.caption("🔌 Çevrimdışı — hiçbir veri dışarı çıkmaz")

        st.divider()
        st.markdown("### 💡 Örnek sorular")
        # Dugmeye basildiginda Streamlit zaten betigi bastan calistiriyor; soruyu
        # oturum durumuna yaziyoruz, main() asagida onu okuyup isliyor.
        for sample in SAMPLE_QUESTIONS:
            if st.button(sample, use_container_width=True, key=f"ornek_{sample}"):
                st.session_state.pending_question = sample

        st.divider()
        soru_sayisi = sum(1 for m in st.session_state.messages if m["role"] == "user")
        st.caption(f"Bu oturumda {soru_sayisi} soru soruldu.")
        if st.button("🗑️ Sohbeti temizle", use_container_width=True):
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
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_sources(message.get("chunks", []))

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
    with st.spinner("Dokümanlar taranıyor..."):
        system_prompt, chunks, refusal, context = retrieve_and_gate(question)

    with st.chat_message("assistant", avatar=BOT_AVATAR):
        if refusal is not None:
            # Dokumanlarda cevap yok: hicbir uretim yapmadan mesaji gosteriyoruz.
            answer = refusal
            st.markdown(answer)
        else:
            # Cevabi degistirilebilir bir alana yaziyoruz: akis bittikten sonra
            # dayanak kontrolu basarisiz olursa yazilani silip yerine
            # "bilmiyorum" mesajini koyabilmemiz gerekiyor.
            slot = st.empty()
            with slot.container():
                answer = st.write_stream(stream_generation(system_prompt, question))

            if not is_answer_grounded(get_client(), context, answer):
                answer = NO_INFO_MESSAGE
                slot.empty()
                slot.markdown(answer)

        render_sources(chunks)

    # Cevap tamamlandi: soru ve cevabi birlikte gecmise yaziyoruz.
    st.session_state.messages.append(
        {"role": "user", "content": question, "avatar": USER_AVATAR}
    )
    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "chunks": chunks, "avatar": BOT_AVATAR}
    )


if __name__ == "__main__":
    main()
