"""
retrieval.py

Gorevi: Kullanicidan gelen bir soruyu vektorlestirip, SQLite'taki (rag.db) parcalar
arasindan kosinus benzerligiyle en alakali olanlari bulmak.

ingest.py tum vektorleri onceden hesaplayip kaydettigi icin, burada sadece:
1) Soruyu embed et.
2) Veritabanindaki tum parca vektorlerini oku (kucuk veri seti icin bu yeterli;
   buyuk veri setlerinde ozel bir vektor veritabani gerekir).
3) Kosinus benzerligini hesapla, en yuksek skorlu K parcayi don.
"""

import json
import sqlite3

import numpy as np

from common import DB_PATH, EMBED_MODEL, get_client


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def get_top_chunks(query: str, k: int = 3) -> list[dict]:
    """Verilen soruya en alakali k parcayi (source, content, score) olarak dondurur."""
    client = get_client()
    response = client.embeddings.create(model=EMBED_MODEL, input=query)
    query_vector = np.array(response.data[0].embedding)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT source, content, embedding FROM chunks").fetchall()
    conn.close()

    scored = []
    for source, content, embedding_json in rows:
        chunk_vector = np.array(json.loads(embedding_json))
        score = cosine_similarity(query_vector, chunk_vector)
        scored.append({"source": source, "content": content, "score": score})

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:k]


if __name__ == "__main__":
    test_query = "Foundry Local nedir ve neden internete ihtiyac duymaz?"
    print(f"Soru: {test_query}\n")

    results = get_top_chunks(test_query, k=3)
    for i, r in enumerate(results, start=1):
        print(f"[{i}] kaynak={r['source']}  skor={r['score']:.4f}")
        print(r["content"][:150].replace("\n", " ") + "...")
        print()
