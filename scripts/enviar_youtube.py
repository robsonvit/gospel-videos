"""
enviar_youtube.py
Envia videos para o YouTube usando OAuth2 (token de refresh).
"""

import json
import os
import requests
from pathlib import Path

YOUTUBE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL   = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_VIDEOS_URL   = "https://www.googleapis.com/youtube/v3/videos"

CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")


def _obter_access_token() -> str:
    """Obtem um access token via refresh token."""
    resp = requests.post(
        YOUTUBE_TOKEN_URL,
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token", "")
    if not token:
        raise RuntimeError(f"Sem access_token na resposta: {resp.text[:200]}")
    return token


def enviar_video_youtube(
    video_path: str,
    titulo: str,
    descricao: str,
    tags: list = None,
    categoria: str = "22",  # 22 = People & Blogs
) -> str:
    """
    Envia um video para o YouTube como Short (privado -> publico).
    Returns: URL do video publicado
    """
    if not CLIENT_ID or not CLIENT_SECRET or not REFRESH_TOKEN:
        raise RuntimeError(
            "Credentials YouTube nao configuradas "
            "(YOUTUBE_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN)"
        )

    access_token = _obter_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    # Metadata do video
    metadata = {
        "snippet": {
            "title":       titulo[:100],
            "description": descricao[:5000],
            "tags":        (tags or [])[:500],
            "categoryId":  categoria,
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    tamanho = Path(video_path).stat().st_size
    print(f"  Enviando para YouTube ({tamanho / 1024 / 1024:.1f} MB)...")

    # Inicia upload resumable
    init_resp = requests.post(
        YOUTUBE_UPLOAD_URL,
        headers={
            **headers,
            "Content-Type":           "application/json; charset=UTF-8",
            "X-Upload-Content-Type":  "video/mp4",
            "X-Upload-Content-Length": str(tamanho),
        },
        params={"uploadType": "resumable", "part": "snippet,status"},
        json=metadata,
        timeout=60,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers.get("Location", "")
    if not upload_url:
        raise RuntimeError("YouTube nao retornou URL de upload resumable")

    # Envia o arquivo
    with open(video_path, "rb") as f:
        upload_resp = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(tamanho)},
            data=f,
            timeout=600,
        )
    upload_resp.raise_for_status()

    video_id = upload_resp.json().get("id", "")
    if not video_id:
        raise RuntimeError(f"Upload YouTube sem video_id: {upload_resp.text[:300]}")

    url = f"https://youtube.com/shorts/{video_id}"
    print(f"  Video publicado: {url}")
    return url
