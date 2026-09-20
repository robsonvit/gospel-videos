"""
buscar_videos_pexels.py
Busca e baixa clips de video do Pexels para o fundo do video gospel.
Usa queries esteticas fixas (montanhas, neve, aurora, natureza).
"""

import json
import os
import random
import subprocess
import time
from pathlib import Path

import requests

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/videos/search"

PROJETO_ROOT = Path(__file__).parent.parent
PEXELS_USADOS_FILE = PROJETO_ROOT / "pexels_usados.json"
MAX_PEXELS_HISTORICO = 200

# Queries esteticas para o estilo snowboard gospel
QUERIES_PEXELS = [
    "mountain snow",
    "snowboarder",
    "aurora borealis night",
    "winter landscape",
    "misty forest",
    "aerial mountain",
    "snowy valley",
    "winter nature",
    "mountain fog",
    "cold lake mountain",
    "winter sky",
    "snow peak",
]

VIDEO_WIDTH  = 1080
VIDEO_HEIGHT = 1920
MIN_DURACAO  = 4    # segundos minimos por clip
MAX_DURACAO  = 20   # segundos maximos por clip


def carregar_usados() -> set:
    if PEXELS_USADOS_FILE.exists():
        try:
            data = json.loads(PEXELS_USADOS_FILE.read_text(encoding="utf-8"))
            return set(str(v) for v in data.get("ids_usados", []))
        except Exception:
            pass
    return set()


def salvar_usados(ids: set) -> None:
    ids_lista = list(ids)
    if len(ids_lista) > MAX_PEXELS_HISTORICO:
        ids_lista = ids_lista[-MAX_PEXELS_HISTORICO:]
    PEXELS_USADOS_FILE.write_text(
        json.dumps({"ids_usados": ids_lista}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _melhor_arquivo(video_files: list) -> dict | None:
    """Escolhe o arquivo de video de melhor qualidade HD disponivel."""
    # Prefere HD (1920x1080 ou 1280x720) para depois rotacionar
    ordens = ["hd", "sd", "hls"]
    for qualidade in ordens:
        for f in video_files:
            if f.get("quality") == qualidade:
                return f
    return video_files[0] if video_files else None


def buscar_videos(duracao_audio: float, output_dir: str) -> list:
    """
    Busca e baixa clips do Pexels para cobrir a duracao_audio.
    Baixa clips suficientes com margem de seguranca.

    Returns:
        Lista de paths dos videos baixados.
    """
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY nao configurada!")

    os.makedirs(output_dir, exist_ok=True)
    ids_usados = carregar_usados()

    # Calcula quantos clips precisamos (cada um dura 3-10s, com margem 2x)
    duracao_alvo = duracao_audio * 2.0
    clips_necessarios = max(8, int(duracao_alvo / 5))

    print(f"  Buscando {clips_necessarios} clips Pexels para {duracao_audio:.1f}s de audio...")

    queries = QUERIES_PEXELS[:]
    random.shuffle(queries)

    videos_baixados = []
    ids_novos = set()
    query_idx = 0

    headers = {"Authorization": PEXELS_API_KEY}

    while len(videos_baixados) < clips_necessarios and query_idx < len(queries) * 3:
        query = queries[query_idx % len(queries)]
        query_idx += 1
        page = random.randint(1, 5)

        try:
            resp = requests.get(
                PEXELS_API_URL,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 15,
                    "page": page,
                    "orientation": "portrait",
                    "size": "medium",
                },
                timeout=30,
            )
            resp.raise_for_status()
            dados = resp.json()
        except Exception as e:
            print(f"  Erro Pexels API '{query}': {e}")
            time.sleep(2)
            continue

        videos = dados.get("videos", [])
        if not videos:
            continue

        random.shuffle(videos)

        for v in videos:
            vid_id = str(v.get("id", ""))
            if vid_id in ids_usados or vid_id in ids_novos:
                continue

            duracao = v.get("duration", 0)
            if not (MIN_DURACAO <= duracao <= MAX_DURACAO):
                continue

            arquivo = _melhor_arquivo(v.get("video_files", []))
            if not arquivo or not arquivo.get("link"):
                continue

            url = arquivo["link"]
            nome_saida = Path(output_dir) / f"pexels_{vid_id}.mp4"

            try:
                r = requests.get(url, timeout=60, stream=True)
                r.raise_for_status()
                with open(nome_saida, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                videos_baixados.append(str(nome_saida))
                ids_novos.add(vid_id)
                print(f"  Baixado: pexels_{vid_id}.mp4 ({duracao}s) - '{query}'")

                if len(videos_baixados) >= clips_necessarios:
                    break
            except Exception as e:
                print(f"  Falha ao baixar {vid_id}: {e}")

        time.sleep(0.5)

    # Salva historico
    salvar_usados(ids_usados | ids_novos)
    print(f"  Total clips Pexels baixados: {len(videos_baixados)}")
    return videos_baixados
