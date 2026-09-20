"""
pipeline.py
Orquestrador - Videos JESUS Gospel (Telegram only - modo de teste).

Fluxo:
  1. Busca musica gospel no YouTube (heatmap + IA)
  2. Legendas ja vem do YouTube (segmentos_zona)
  3. Fallback: Whisper se nao houver legendas
  4. Baixa clips Pexels
  5. Monta video 1080x1920 com legendas precisas
  6. Envia SOMENTE ao Telegram (YouTube desativado ate aprovacao)
"""

import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from buscar_musica_gospel import buscar_musica
from transcrever_letra import processar_segmentos_youtube, transcrever_audio
from buscar_videos_pexels import buscar_videos
from montar_video_gospel import montar_video
from enviar_telegram import enviar_video_telegram, enviar_mensagem_telegram

PROJETO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJETO_ROOT / "output"
MAX_DURACAO  = 59.0

# YouTube DESATIVADO ate aprovacao manual
YOUTUBE_ATIVO = False


def executar_pipeline(numero: int = 1) -> bool:
    print(f"\n{'='*60}")
    print(f"  VIDEO JESUS GOSPEL #{numero}")
    print(f"{'='*60}\n")

    work_dir = Path(tempfile.mkdtemp(prefix="jesus_gospel_"))
    print(f"Diretorio de trabalho: {work_dir}")

    try:
        # -- Passo 1: Busca musica + heatmap + IA --
        print("\n[1/4] Buscando musica gospel (heatmap + IA)...")
        musica_dir = str(work_dir / "musica")
        info_musica = buscar_musica(output_dir=musica_dir)

        audio_file       = info_musica["path"]
        titulo_musica    = info_musica["title"]
        artista          = info_musica["artist"]
        duracao_audio    = info_musica["duration"]
        segmentos_yt     = info_musica.get("segmentos_zona", [])

        print(f"\n  Musica: '{titulo_musica}' - {artista}")
        print(f"  Trecho: {info_musica['start']:.1f}s - {info_musica['end']:.1f}s")
        print(f"  Duracao: {duracao_audio:.1f}s")
        print(f"  Segmentos YouTube: {len(segmentos_yt)}")

        if duracao_audio > MAX_DURACAO:
            duracao_audio = MAX_DURACAO

        # -- Passo 2: Legendas --
        print("\n[2/4] Preparando legendas...")
        texto_prompt = ""
        if segmentos_yt:
            print(f"  Letra original do YouTube encontrada ({len(segmentos_yt)} segmentos).")
            # Junta todo o texto para servir de 'cola' para o Whisper (initial_prompt)
            texto_prompt = " ".join([seg["text"] for seg in segmentos_yt]).strip()
        
        print("  Sincronizando tempo exato das palavras (Whisper)...")
        legendas = transcrever_audio(audio_file, modelo="base", prompt_inicial=texto_prompt)

        if not legendas:
            print("  AVISO: Sem legendas disponiveis. Video sem texto.")
            legendas = []
        else:
            print(f"  {len(legendas)} legendas prontas:")
            for leg in legendas[:6]:
                print(f"    [{leg['start']:.1f}s] {leg['text']}")
            if len(legendas) > 6:
                print(f"    ... (+{len(legendas)-6} frases)")

        # -- Passo 3: Clips Pexels --
        print("\n[3/4] Buscando clips Pexels...")
        pexels_dir   = str(work_dir / "pexels_clips")
        pexels_clips = buscar_videos(
            duracao_audio=duracao_audio,
            output_dir=pexels_dir,
        )
        if not pexels_clips:
            raise RuntimeError("Nenhum clip Pexels foi baixado!")
        print(f"  {len(pexels_clips)} clips baixados.")

        # -- Passo 4: Monta o video --
        print("\n[4/4] Montando video final...")
        titulo_seguro = re.sub(r'[<>:"/\\|?*\n\r]', "", titulo_musica)
        titulo_seguro = titulo_seguro.replace(" ", "_")[:50]
        output_file   = str(work_dir / f"JESUS_{titulo_seguro}.mp4")

        montar_video(
            pexels_clips=pexels_clips,
            audio_file=audio_file,
            legendas=legendas,
            output_file=output_file,
            work_dir=str(work_dir / "montagem"),
            duracao_audio=duracao_audio,
        )

        OUTPUT_DIR.mkdir(exist_ok=True)
        output_final = str(OUTPUT_DIR / Path(output_file).name)
        shutil.copy2(output_file, output_final)
        print(f"  Salvo: {output_final}")

        # -- Envia ao Telegram --
        print("\n[+] Enviando ao Telegram...")
        caption = (
            f"<b>{titulo_musica}</b>\n"
            f"{artista}\n\n"
            f"Trecho: {info_musica['start']:.0f}s - {info_musica['end']:.0f}s\n"
            f"Legendas: {len(legendas)} frases\n\n"
            f"#gospel #louvor #jesus #fe"
        )
        enviar_video_telegram(output_final, caption)
        print("  Telegram: OK")

        if YOUTUBE_ATIVO:
            from enviar_youtube import enviar_video_youtube
            print("\n[+] Enviando ao YouTube Shorts...")
            yt_titulo = f"{titulo_musica[:85]} #shorts"
            yt_desc   = f"{titulo_musica}\n{artista}\n\n#gospel #louvor #jesus #fe #shorts"
            yt_tags   = ["gospel", "louvor", "adoracao", "jesus", "fe", "shorts", "cristao"]
            try:
                yt_url = enviar_video_youtube(
                    video_path=output_final,
                    titulo=yt_titulo,
                    descricao=yt_desc,
                    tags=yt_tags,
                )
                print(f"  YouTube: {yt_url}")
                enviar_mensagem_telegram(f"Postado no YouTube!\n{yt_url}")
            except Exception as e:
                print(f"  Erro YouTube: {e}")
                enviar_mensagem_telegram(f"Erro YouTube:\n<code>{str(e)[:300]}</code>")
        else:
            print("\n  [YouTube desativado - modo de teste]")

        print(f"\n{'='*60}")
        print(f"  VIDEO #{numero} CONCLUIDO!")
        print(f"  Musica: {titulo_musica}")
        print(f"  Legendas: {len(legendas)} frases")
        print(f"{'='*60}\n")
        return True

    except Exception as e:
        print(f"\nERRO no pipeline #{numero}:")
        traceback.print_exc()
        try:
            enviar_mensagem_telegram(
                f"JESUS Gospel Bot - Erro #{numero}:\n<code>{str(e)[:300]}</code>"
            )
        except Exception:
            pass
        return False

    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    num_videos = 1
    if len(sys.argv) > 1:
        try:
            num_videos = max(1, min(10, int(sys.argv[1])))
        except ValueError:
            pass

    print(f"\nINICIANDO - {num_videos} video(s) | YouTube: {'ATIVO' if YOUTUBE_ATIVO else 'DESATIVADO (so Telegram)'}")

    sucessos = falhas = 0
    for i in range(1, num_videos + 1):
        if executar_pipeline(numero=i):
            sucessos += 1
        else:
            falhas += 1

    print(f"\nRESUMO: {sucessos} sucesso(s), {falhas} falha(s)")
    if falhas > 0:
        sys.exit(1)
