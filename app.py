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

SYSTEM_PROMPT_TEMPLATE = """/no_think
Sen, verilen baglam disina cikmayan bir soru-cevap asistanisin.

Kurallar:
- SADECE asagida verilen baglami kullanarak cevap ver.
- KESIN KURAL: Eger sorunun cevabi baglamda YOKSA, baska hicbir sey yazmadan ve
  soruyu tekrar etmeden, SADECE su cumleyi yaz: "Bu bilgi elimdeki dokumanlarda yok."
- Cevap baglamda varsa, hangi kaynak dosya(lar)dan yararlandigini belirt.

Baglam:
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
    parts = []
    for chunk in chunks:
        parts.append(f"[Kaynak: {chunk['source']}]\n{chunk['content']}")
    return "\n\n---\n\n".join(parts)


def answer_query(question: str, k: int = 3) -> tuple[str, list[dict]]:
    """RAG pipeline'inin tamamini calistirir: getir (retrieve) + uret (generate).

    Doner: (model_cevabi, kullanilan_parcalar)
    """
    chunks = get_top_chunks(question, k=k)

    # 1. Kapi (ucuz): en iyi parca bile cok dusuk skorluysa, hicbir LLM cagrisi
    # yapmadan eliyoruz.
    if not chunks or chunks[0]["score"] < SIMILARITY_THRESHOLD:
        return NO_INFO_MESSAGE, chunks

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
        return NO_INFO_MESSAGE, chunks

    chunks = relevant_chunks
    context = build_context(chunks)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)

    answer = _generate_answer(client, system_prompt, question, max_tokens=400)

    # Nadiren, "/no_think" yonergesine ragmen model yine de uzun bir ic dusunme
    # adimina giriyor ve token butcesi dolmadan cevaba ulasamiyor (test sirasinda
    # gozlemlendi: 3 kosudan 1'inde). Bu durumu strip_reasoning tespit edip
    # FALLBACK_MESSAGE donuyor; boyle bir durumda daha genis token butcesiyle
    # bir kez daha deniyoruz ki dusunme adimi tamamlanip cevap uretilebilsin.
    if answer == FALLBACK_MESSAGE:
        answer = _generate_answer(client, system_prompt, question, max_tokens=1200)

    return answer, chunks


def main() -> None:
    st.set_page_config(page_title="Yerel RAG Asistani", page_icon="🤖")
    st.title("🤖 Yerel Doküman Asistanı")
    st.caption("Foundry Local + SQLite + RAG — tamamen çevrimdışı çalışır.")

    question = st.text_input("Sorunuzu yazın:")

    if st.button("Sor") and question.strip():
        with st.spinner("Cevap hazırlanıyor..."):
            answer, chunks = answer_query(question)

        st.markdown("### Cevap")
        st.write(answer)

        with st.expander("Kullanılan doküman parçaları (retrieval sonucu)"):
            for i, chunk in enumerate(chunks, start=1):
                st.markdown(f"**[{i}] {chunk['source']}** — benzerlik skoru: {chunk['score']:.3f}")
                st.text(chunk["content"])


if __name__ == "__main__":
    main()
