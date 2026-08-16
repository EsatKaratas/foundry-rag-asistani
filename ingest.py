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


# Chunk boyut sinirlari. MIN_CHUNK_CHARS onemli: bu sinirin altindaki parcalar
# TEK BASINA birakilmaz. Ilk surumde dokuman basligi ("Valorant Ekonomi Sistemi"
# gibi kisa bir satir) tek basina parca oluyordu; bu tur kisa parcalarin embedding
# vektoru belirsiz cikiyor ve alakasiz sorular dahil her seye orta seviyede
# benziyordu, bu da retrieval skorlarini bozuyordu.
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 500


def chunk_text(text: str) -> list[str]:
    """Metni paragraflara boler; cok kisa parcalari bir sonrakiyle birlestirir.

    Her parcanin basina dokumanin baslik satiri eklenir (contextual chunk header).
    Neden: baslik yalnizca ilk parcada olunca, konu kelimeleri iceren sorularda
    tum dokumanlarin baslikli ilk parcalari ust siralari dolduruyor ve cevabin
    gercekten bulundugu parca asagi dusuyordu (olculdu: dogru parca 6. siraya
    dustu). Baslik her parcaya eklenince bu yanlilik ortadan kalkar.
    """
    raw_parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not raw_parts:
        return []

    # Ilk satir dokuman basligi olarak kabul edilir.
    title = raw_parts[0].splitlines()[0].strip()

    chunks: list[str] = []
    buffer = ""

    for part in raw_parts:
        candidate = f"{buffer}\n\n{part}".strip() if buffer else part

        # Buffer'i kapatip yeni parcaya gecmek icin iki kosul da saglanmali:
        # (1) mevcut buffer anlamli buyuklukte olmali, (2) eklemek onu cok
        # buyutuyor olmali. Aksi halde birlestirmeye devam ediyoruz.
        if len(buffer) >= MIN_CHUNK_CHARS and len(candidate) > MAX_CHUNK_CHARS:
            chunks.append(buffer)
            buffer = part
        else:
            buffer = candidate

    if buffer:
        # Son parca cok kucukse tek basina birakmayip oncekine ekliyoruz.
        if chunks and len(buffer) < MIN_CHUNK_CHARS:
            chunks[-1] = f"{chunks[-1]}\n\n{buffer}"
        else:
            chunks.append(buffer)

    # Basligi zaten icermeyen parcalarin basina ekle.
    return [c if c.startswith(title) else f"{title}\n\n{c}" for c in chunks]


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
