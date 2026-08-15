"""
ingest.py

Gorevi:
1) data/ klasorundeki .txt dokumanlarini oku.
2) Her dokumani paragraf bazinda kucuk parcalara (chunk) bol.
3) Her parca icin Foundry Local'in embedding modeliyle (qwen3-embedding-0.6b)
   sayisal bir vektor uret.
4) Parca metnini ve vektorunu SQLite veritabanina (rag.db) yaz.

Calistirma: python ingest.py
Yeniden calistirildiginda tablo sifirdan olusturulur (mevcut veriler silinir).
"""

import json
import sqlite3
from pathlib import Path

from common import DB_PATH, EMBED_MODEL, get_client

DATA_DIR = Path(__file__).parent / "data"


def chunk_text(text: str) -> list[str]:
    """Metni bos satirlara gore paragraflara boler, cok kisa parcalari birlestirir."""
    raw_parts = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    buffer = ""
    for part in raw_parts:
        if len(buffer) + len(part) < 400:
            buffer = f"{buffer}\n\n{part}".strip()
        else:
            if buffer:
                chunks.append(buffer)
            buffer = part
    if buffer:
        chunks.append(buffer)
    return chunks


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS chunks")
    conn.execute(
        """
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL
        )
        """
    )
    conn.commit()


def main() -> None:
    txt_files = sorted(DATA_DIR.glob("*.txt"))
    if not txt_files:
        print(f"UYARI: {DATA_DIR} klasorunde .txt dosyasi bulunamadi.")
        return

    client = get_client()
    conn = sqlite3.connect(DB_PATH)
    create_table(conn)

    total_chunks = 0
    for file_path in txt_files:
        text = file_path.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        print(f"{file_path.name}: {len(chunks)} parca bulundu.")

        for idx, chunk in enumerate(chunks):
            response = client.embeddings.create(model=EMBED_MODEL, input=chunk)
            vector = response.data[0].embedding

            conn.execute(
                "INSERT INTO chunks (source, chunk_index, content, embedding) "
                "VALUES (?, ?, ?, ?)",
                (file_path.name, idx, chunk, json.dumps(vector)),
            )
            total_chunks += 1

    conn.commit()

    # Dogrulama: veritabaninda gercekten satir olustu mu?
    count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    conn.close()

    print()
    print(f"Tamamlandi. {total_chunks} parca islendi, veritabaninda {count} satir var.")
    print(f"Veritabani dosyasi: {DB_PATH}")


if __name__ == "__main__":
    main()
