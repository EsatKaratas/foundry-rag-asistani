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
    context = build_context(chunks)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)

    client = get_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0.2,
        # qwen3-4b bir "reasoning" modeli; sistem promptundaki "/no_think"
        # yonergesiyle ic dusunme adimini kapatiyoruz (hem cevap suresini
        # ~10 kata kadar kisaltiyor hem de dusunme donguleri riskini ortadan
        # kaldiriyor - test sirasinda olculdu). max_tokens yine de bir
        # guvenlik sinir olarak kaliyor.
        max_tokens=400,
    )
    raw_answer = response.choices[0].message.content
    answer = strip_reasoning(raw_answer)
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
