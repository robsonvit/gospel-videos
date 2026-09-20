"""
enviar_telegram.py
Envia videos e mensagens para o Telegram via Bot API.
"""

import os
import requests
from pathlib import Path

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
API_BASE  = f"https://api.telegram.org/bot{BOT_TOKEN}"


def enviar_video_telegram(video_path: str, caption: str = "") -> None:
    """Envia um video MP4 para o Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        print("  AVISO: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nao configurados.")
        return

    tamanho_mb = Path(video_path).stat().st_size / (1024 * 1024)
    print(f"  Enviando video ao Telegram ({tamanho_mb:.1f} MB)...")

    with open(video_path, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/sendVideo",
            data={
                "chat_id": CHAT_ID,
                "caption": caption[:1024],
                "parse_mode": "HTML",
                "supports_streaming": "true",
            },
            files={"video": f},
            timeout=300,
        )

    resp.raise_for_status()
    print("  Video enviado ao Telegram com sucesso!")


def enviar_mensagem_telegram(mensagem: str) -> None:
    """Envia uma mensagem de texto para o Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": mensagem[:4096],
                "parse_mode": "HTML",
            },
            timeout=30,
        )
    except Exception as e:
        print(f"  Aviso: Erro ao enviar mensagem Telegram: {e}")
