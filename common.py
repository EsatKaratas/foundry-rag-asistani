"""
Ortak yardimci fonksiyonlar: Foundry Local servisine baglanma, SQLite yolu, model isimleri.

Bu modul, ingest.py / retrieval.py / app.py tarafindan ortak olarak kullanilir.
Foundry Local, "foundry server start" ile calistirilir ve OpenAI uyumlu bir yerel
HTTP servisi acar. Bu servisin portu her calistirmada degisebildigi icin (varsayilan
ayar rastgele bir porta baglaniyor), portu sabit kodlamak yerine "foundry server status"
komutunun JSON ciktisindan her seferinde okuyoruz.
"""

import json
import subprocess
import time
from pathlib import Path

from openai import OpenAI

DB_PATH = Path(__file__).parent / "rag.db"

CHAT_MODEL = "qwen3-4b"
EMBED_MODEL = "qwen3-embedding-0.6b"


def _run_foundry(args: list[str]) -> str:
    result = subprocess.run(
        ["foundry", *args, "-o", "json"],
        capture_output=True,
        text=True,
        shell=True,
        # foundry CLI ciktisi UTF-8 (renk kodlari, kutu karakterleri iceriyor).
        # Windows'ta varsayilan kod sayfasi (cp1254) bunu cozemeyip
        # UnicodeDecodeError firlatiyor - encoding'i acikca belirtiyoruz.
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "").strip()


def get_foundry_base_url() -> str:
    """Foundry Local servisinin calisan URL'sini doner. Servis kapaliysa baslatir."""
    status_raw = _run_foundry(["server", "status"])
    try:
        status = json.loads(status_raw)
    except json.JSONDecodeError:
        status = {"running": False}

    if not status.get("running"):
        subprocess.run(["foundry", "server", "start"], shell=True, check=True)
        time.sleep(2)
        status_raw = _run_foundry(["server", "status"])
        status = json.loads(status_raw)

    web_urls = status.get("webUrls") or []
    if not web_urls:
        raise RuntimeError(
            "Foundry Local servisi baslatilamadi. 'foundry server status' komutunu "
            "elle calistirip kontrol edin."
        )
    return web_urls[0] + "/v1"


# Modellerin bu surecte yuklenip yuklenmedigini takip eden bayrak. Model yukleme
# islemi idempotent (zaten yukluyse hizlica doner) ama subprocess cagrisi maliyetli
# oldugu icin surec basina bir kez yapiyoruz.
_models_loaded = False


def ensure_models_loaded() -> None:
    """Gerekli modellerin bellege yuklu oldugundan emin olur.

    Neden gerekli: Foundry Local servisi yeniden baslatildiginda (makine yeniden
    baslatilinca, servis cokerse veya elle restart edilirse) daha once yuklenmis
    modeller bellekten dusuyor. Bu durumda API cagrisi
    "Model '...' is not loaded" hatasiyla basarisiz oluyor. Test sirasinda bu hata
    gercekten yasandi; uygulamanin kullaniciya anlamsiz bir hata firlatmasi yerine
    modelleri kendi kendine yuklemesi daha dogru.
    """
    global _models_loaded
    if _models_loaded:
        return

    for model_name in (EMBED_MODEL, CHAT_MODEL):
        subprocess.run(
            ["foundry", "model", "load", model_name],
            capture_output=True,
            text=True,
            shell=True,
            encoding="utf-8",
            errors="replace",
        )
    _models_loaded = True


def get_client() -> OpenAI:
    """Foundry Local'in yerel, OpenAI uyumlu servisine baglanan bir istemci doner."""
    base_url = get_foundry_base_url()
    ensure_models_loaded()
    # Foundry Local yerel oldugu icin gercek bir API anahtari gerekmiyor.
    return OpenAI(base_url=base_url, api_key="foundry-local")
