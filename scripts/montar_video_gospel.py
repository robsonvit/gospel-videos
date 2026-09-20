"""
montar_video_gospel.py
Monta o video gospel estilo snowboard:
- Clips Pexels em slow motion (0.5x) com xfade fade
- Audio: musica gospel (sem narracao)
- Legendas: fonte Cinzel, UPPERCASE, branca, shadow, centralizada
- Efeitos cinematograficos: contraste, saturacao, glow sutil
Output: 1080x1920, 30fps, h264/aac
"""

import os
import random
import subprocess
import sys
from pathlib import Path

VIDEO_W   = 1080
VIDEO_H   = 1920
VIDEO_FPS = 24
XFADE_DUR = 0.8      # segundos de transicao entre clips
SLOW_FACTOR = 0.5    # fator de camera lenta

FONT_FILE = "/usr/share/fonts/truetype/cinzel/Cinzel-Regular.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
FONT_SIZE = 58


def _font_path() -> str:
    """Retorna o caminho da fonte disponivel."""
    for f in [FONT_FILE, FONT_FALLBACK]:
        if os.path.exists(f):
            return f
    # Tenta encontrar qualquer fonte serif
    result = subprocess.run(
        ["fc-match", "serif", "--format=%{file}"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


def run_ffmpeg(args: list, description: str = "") -> None:
    """Executa o FFmpeg e lanca excecao em caso de erro."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    if description:
        print(f"  FFmpeg: {description}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO FFmpeg ({description}):\n{result.stderr[-600:]}")
        raise RuntimeError(f"FFmpeg falhou: {description}")


def get_media_duration(path: str) -> float:
    """Retorna a duracao em segundos de um arquivo de midia."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 5.0


def processar_clip(clip_path: str, output_path: str, duracao_saida: float) -> None:
    """
    Processa um clip Pexels:
    - Redimensiona para 1080x1920 (portrait, crop centralizado)
    - Aplica slow motion 0.5x
    - Espelha horizontalmente (variacao visual)
    """
    dur_input = duracao_saida / SLOW_FACTOR
    hflip = random.choice(["hflip,", ""])  # 50% chance de espelhar

    filtro = (
        f"trim=duration={dur_input:.3f},"
        f"setpts={1.0/SLOW_FACTOR:.1f}*PTS,"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},"
        f"{hflip}"
        f"fps={VIDEO_FPS},"
        f"format=yuv420p"
    )

    run_ffmpeg(
        ["-i", clip_path,
         "-vf", filtro,
         "-an",
         "-c:v", "libx264", "-crf", "28", "-preset", "superfast",
         output_path],
        description=f"Processando {Path(clip_path).name}"
    )


def gerar_filtro_legendas(legendas: list, font_file: str) -> str:
    """
    Gera o filtro drawtext para todas as legendas.
    Cada linha: UPPERCASE, fonte Cinzel, centralizada, shadow.
    """
    if not legendas or not font_file:
        return "copy"

    partes = []
    font_escaped = font_file.replace(":", "\\:").replace("'", "\\'")

    for leg in legendas:
        texto = leg["text"].replace("'", "\\'").replace(":", "\\:")
        start = leg["start"]
        end   = leg["end"]

        # Adiciona 0.05s de fade-in invisivel (alpha)
        parte = (
            f"drawtext="
            f"fontfile='{font_escaped}'"
            f":text='{texto}'"
            f":fontcolor=white@0.95"
            f":fontsize={FONT_SIZE}"
            f":x=(w-text_w)/2"
            f":y=(h-text_h)/2"
            f":shadowcolor=black@0.85"
            f":shadowx=2:shadowy=2"
            f":enable='between(t,{start:.3f},{end:.3f})'"
        )
        partes.append(parte)

    return ",".join(partes)


def montar_video(
    pexels_clips: list,
    audio_file: str,
    legendas: list,
    output_file: str,
    work_dir: str,
    duracao_audio: float,
) -> str:
    """
    Monta o video gospel completo.

    Args:
        pexels_clips: Lista de paths dos clips Pexels
        audio_file:   Path do audio MP3 (musica gospel)
        legendas:     Lista de { text, start, end }
        output_file:  Caminho de saida do video final
        work_dir:     Diretorio de trabalho temporario
        duracao_audio: Duracao do audio em segundos

    Returns:
        Path do video gerado
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    font_file = _font_path()

    if not font_file:
        print("  AVISO: Fonte nao encontrada, legendas desativadas.")
    else:
        print(f"  Fonte: {font_file}")

    # -- 1. Calcula duracao alvo --
    duracao_alvo = min(duracao_audio + 0.5, 59.0)
    print(f"  Duracao alvo: {duracao_alvo:.1f}s")

    # -- 2. Processa clips Pexels --
    print("\n  Processando clips Pexels (slow motion 0.5x)...")
    clips_processados = []
    clip_durations = []
    duracao_acumulada = 0.0

    random.shuffle(pexels_clips)
    pexels_ordem = pexels_clips[:]
    idx = 0
    volta = 0

    while duracao_acumulada < duracao_alvo:
        lista_idx = idx % len(pexels_ordem)
        if lista_idx == 0 and idx > 0:
            volta += 1
            rng = random.Random(volta * 31337)
            rng.shuffle(pexels_ordem)

        clip_orig = pexels_ordem[lista_idx]
        dur_orig  = get_media_duration(clip_orig)

        falta = duracao_alvo - duracao_acumulada
        target = random.uniform(3.5, 7.0)
        add_efetivo = target - XFADE_DUR
        if add_efetivo > falta:
            target = falta + XFADE_DUR

        # Verifica se tem input suficiente para slow motion
        input_necessario = target / SLOW_FACTOR
        if dur_orig < input_necessario:
            target = dur_orig * SLOW_FACTOR

        if target < 1.5:
            idx += 1
            continue

        out_clip = str(work / f"clip_{idx:03d}.mp4")
        processar_clip(clip_orig, out_clip, target)
        clips_processados.append(out_clip)
        clip_durations.append(target)
        duracao_acumulada += (target - XFADE_DUR)
        idx += 1

    print(f"  {len(clips_processados)} clips processados (timeline: {duracao_acumulada:.1f}s)")

    # -- 3. Concatena com xfade --
    print("\n  Concatenando clips com xfade fade...")
    inputs_concat = []
    for c in clips_processados:
        inputs_concat += ["-i", c]

    n = len(clips_processados)
    if n == 1:
        concat_filter = "[0:v]copy[vconcat]"
    else:
        partes_filtro = []
        last_out = "[0:v]"
        offset = clip_durations[0] - XFADE_DUR
        for i in range(1, n):
            label = f"[v{i}]" if i < n - 1 else "[vconcat]"
            partes_filtro.append(
                f"{last_out}[{i}:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset:.3f}{label}"
            )
            last_out = label
            if i < n - 1:
                offset += clip_durations[i] - XFADE_DUR
        concat_filter = ";".join(partes_filtro)

    video_concat = str(work / "video_concat.mp4")
    run_ffmpeg(
        inputs_concat + [
            "-filter_complex", concat_filter,
            "-map", "[vconcat]",
            "-c:v", "libx264", "-crf", "28", "-preset", "superfast",
            "-r", str(VIDEO_FPS),
            video_concat,
        ],
        description="Concatenando clips"
    )

    # -- 4. Monta video final com legendas + efeitos --
    print("\n  Renderizando video final com legendas e efeitos cinematograficos...")

    legenda_filter = gerar_filtro_legendas(legendas, font_file)

    # Efeito cinematografico: contraste forte + saturacao + glow sutil
    efeito = (
        "curves=preset=strong_contrast,"
        "eq=saturation=1.35:contrast=1.10:brightness=-0.15,"
        "split[vmain][vcopy];"
        "[vcopy]gblur=sigma=8[vblur];"
        "[vmain][vblur]blend=all_mode=screen:all_opacity=0.05[vefx]"
    )

    # Junta legendas + efeito
    if legenda_filter != "copy":
        filter_video = f"[0:v]{efeito};[vefx]{legenda_filter}[vout]"
    else:
        filter_video = f"[0:v]{efeito};[vefx]copy[vout]"

    # Audio: musica gospel com fade out nos ultimos 3s
    dur_total = min(duracao_acumulada, duracao_alvo)
    fade_inicio = max(0, dur_total - 3.0)
    audio_filter = (
        f"[1:a]volume=1.0,"
        f"afade=t=out:st={fade_inicio:.1f}:d=3.0[aout]"
    )

    filter_complex = f"{filter_video};{audio_filter}"

    # Escreve filter em arquivo para evitar problemas com aspas
    filter_script = str(work / "filter_final.txt")
    with open(filter_script, "w", encoding="utf-8") as fs:
        fs.write(filter_complex)

    run_ffmpeg(
        ["-i", video_concat,
         "-i", audio_file,
         "-filter_complex_script", filter_script,
         "-map", "[vout]",
         "-map", "[aout]",
         "-c:v", "libx264", "-crf", "28", "-preset", "superfast",
         "-c:a", "aac", "-b:a", "192k",
         "-t", str(dur_total),
         "-r", str(VIDEO_FPS),
         "-movflags", "+faststart",
         "-pix_fmt", "yuv420p",
         output_file],
        description="Video final"
    )

    tamanho = Path(output_file).stat().st_size / (1024 * 1024)
    print(f"\n  Video final: {output_file} ({tamanho:.1f} MB, {dur_total:.1f}s)")
    return output_file
