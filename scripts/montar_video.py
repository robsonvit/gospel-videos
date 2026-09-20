"""
montar_video.py — Montagem final do vídeo JESUS usando FFmpeg.

Correções aplicadas:
  [FIX-1] Legendas limpas: pontuação removida, agrupamento em MÁXIMO 2 palavras
  [FIX-2] Frame freeze: fps=30 + setpts=PTS-STARTPTS em todos os clips antes do concat
  [FIX-3] Legenda embolada: escape seguro via re.sub + pausa mínima 0.6s por bloco
  [FIX-4] Voz rápida: tempo mínimo por bloco aumentado para 0.6s
  [FIX-5] Volume voz 110%, música 20%
  [FIX-6] Legendas sem sobreposição: fim de cada bloco limitado ao início do próximo
  [FIX-7] Câmera lenta 0.5x nos clips Pexels (setpts=2.0*PTS)
  [FIX-8] Embaralhamento dinâmico: ordem diferente a cada reciclagem de clips
"""

import json
import os
import re
import random
import subprocess
import sys
import tempfile
from pathlib import Path


# ── Configurações ────────────────────────────────────────────────────────────────
VIDEO_WIDTH  = 1080
VIDEO_HEIGHT = 1920
SHELBY_CLIP_DURATION = 4.0   # Segundos do clip de abertura (CLIPES INICIAIS)
XFADE_DURATION       = 1.0   # Duração da transição suave entre clips (crossfade)
import os
# Caminho da fonte (usado pelo drawtext) - adaptado para rodar local (Windows) e no Github Actions (Linux)
if os.name == 'nt':
    FONT_FILE = r"C\:/Windows/Fonts/impact.ttf"
else:
    FONT_FILE = "/usr/share/fonts/truetype/anton/Anton-Regular.ttf"
FONT_SIZE = 84
VIDEO_FPS = 30               # FPS único para todos os clips → elimina congelamentos
SLOW_MOTION_FACTOR = 2.0    # [FIX-7] Câmera lenta 0.5x: lê 1s de input → produz 2s de output


# ── Utilidades FFmpeg ─────────────────────────────────────────────────────────
def get_media_duration(filepath: str) -> float:
    """Retorna duração de um arquivo de mídia via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", filepath,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    return 0.0


def run_ffmpeg(args: list, description: str = "") -> None:
    """Executa um comando FFmpeg."""
    if description:
        print(f"  [FFmpeg] {description}...")
    cmd = ["ffmpeg", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        stderr_text = result.stderr[-3000:] if result.stderr else "Sem output de erro."
        print(f"  ERRO FFmpeg:\n{stderr_text}")
        raise RuntimeError(f"FFmpeg falhou: {description}")


# ── [FIX-1] Limpeza e escape de texto para drawtext ──────────────────────────
def _limpar_palavra(palavra: str) -> str:
    """
    Remove TODA a pontuação de uma palavra.
    Mantém apenas letras (incluindo acentuadas), números e hífen.
    """
    # Mantém letras Unicode (incluindo á é ã ç ñ etc) e números
    limpa = re.sub(r"[^\w\-]", "", palavra, flags=re.UNICODE)
    # Remove também underscores e números que possam vir do whisper
    limpa = re.sub(r"[_\d]", "", limpa)
    return limpa.strip().upper()


def _escape_drawtext(texto: str) -> str:
    """
    Escapa caracteres para o filtro drawtext do FFmpeg.
    Regra dentro de single-quotes: apenas \\ e \\: precisam de escape.
    Apostrofos são simplesmente removidos na limpeza anterior.
    """
    texto = texto.replace("\\", "\\\\")
    texto = texto.replace("'",  "")       # Removido na limpeza, mas garantia extra
    texto = texto.replace(":",  "\\:")
    texto = texto.replace("%",  "\\%")
    texto = texto.replace("[",  "")
    texto = texto.replace("]",  "")
    texto = texto.replace("{",  "")
    texto = texto.replace("}",  "")
    return texto


def gerar_filtro_legendas(word_timings: list, font_file: str) -> str:
    """
    Gera cadeia de filtros drawtext para legendas palavra a palavra.

    [FIX-1] Máximo 2 palavras por bloco (era 3 — muito para velocidade da voz)
    [FIX-3] Pausa mínima de 0.6s por bloco (era 0.35 — muito rápido)
    [FIX-1] Texto limpo sem pontuação para não quebrar sintaxe FFmpeg

    Args:
        word_timings: [{word, start, duration}] do Groq Whisper
        font_file: Caminho absoluto da fonte TrueType

    Returns:
        String de filtros FFmpeg prontos para uso no filter_complex
    """
    if not word_timings:
        return "null"

    # ── Agrupa em blocos de MÁXIMO 2 palavras ────────────────────────────────
    grupos = []
    grupo_atual = []

    for i, timing in enumerate(word_timings):
        grupo_atual.append(timing)
        prox_inicio = word_timings[i + 1]["start"] if i < len(word_timings) - 1 else float("inf")
        fim_atual   = timing["start"] + timing["duration"]
        pausa       = prox_inicio - fim_atual

        # [FIX-1] Máximo 2 palavras OU pausa natural de 0.4s
        if len(grupo_atual) >= 2 or pausa > 0.40:
            grupos.append(grupo_atual)
            grupo_atual = []

    if grupo_atual:
        grupos.append(grupo_atual)

    # ── Gera um filtro drawtext por bloco ────────────────────────────────────
    # [FIX-6] Calcula o inicio do proximo bloco para limitar o fim do atual
    blocos_raw = []
    for grupo in grupos:
        inicio = grupo[0]["start"]
        fim    = grupo[-1]["start"] + grupo[-1]["duration"]
        if fim - inicio < 0.60:
            fim = inicio + 0.60
        blocos_raw.append((inicio, fim, grupo))

    filtros = []
    for i, (inicio, fim, grupo) in enumerate(blocos_raw):
        # [FIX-6] Garante que fim não ultrapassa o início do próximo bloco
        if i + 1 < len(blocos_raw):
            proximo_inicio = blocos_raw[i + 1][0]
            fim = min(fim, proximo_inicio - 0.01)  # 10ms de margem

        if fim <= inicio:
            fim = inicio + 0.40  # fallback mínimo

        # [FIX-1] Limpa pontuação de cada palavra antes de exibir
        palavras_limpas = [_limpar_palavra(w["word"]) for w in grupo]
        palavras_limpas = [p for p in palavras_limpas if p]  # Remove vazias
        if not palavras_limpas:
            continue

        texto          = " ".join(palavras_limpas)
        texto_escapado = _escape_drawtext(texto)
        if not texto_escapado.strip():
            continue

        f = (
            f"drawtext="
            f"fontfile={font_file}:"
            f"text='{texto_escapado}':"
            f"fontsize={FONT_SIZE}:"
            f"fontcolor=#FFD700:"        # Amarelo dourado
            f"borderw=5:"               # Outline preto espesso
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"          # Centralizado horizontalmente
            f"y=(h-text_h)/2:"          # Centralizado verticalmente
            f"enable='between(t,{inicio:.3f},{fim:.3f})'"
        )
        filtros.append(f)

    if not filtros:
        return "null"

    return ",".join(filtros)


# ── [FIX-2] Processamento de clips com FPS uniforme ──────────────────────
def processar_clip_vertical(
    input_path: str,
    output_path: str,
    duracao: float,
    aplicar_hflip: bool = False,
    slow_motion: bool = False,
) -> None:
    """
    Converte clipe para formato vertical 1080x1920.

    [FIX-2] fps=30 ANTES de qualquer outro filtro → elimina congelamentos
    [FIX-2] setpts=PTS-STARTPTS → reseta timestamps para evitar descontinuidades
    [FIX-7] slow_motion=True: lê (duracao/SLOW_MOTION_FACTOR) segundos do input
             e aplica setpts=SLOW_MOTION_FACTOR*PTS para obter câmera lenta real.
             Resultado: 1s de input → 2s de output (0.5x velocidade).
    """
    hflip_str = "hflip," if aplicar_hflip else ""

    if slow_motion:
        # Lê menos segundos do input; setpts estica o tempo no output
        duracao_input = duracao / SLOW_MOTION_FACTOR
        setpts_str = f"setpts={SLOW_MOTION_FACTOR:.1f}*PTS-STARTPTS"
        desc_extra = f" [SLOW {SLOW_MOTION_FACTOR:.1f}x]"
    else:
        duracao_input = duracao
        setpts_str = "setpts=PTS-STARTPTS"
        desc_extra = ""

    vf = (
        f"fps={VIDEO_FPS},"               # [FIX-2] Normaliza FPS PRIMEIRO
        f"{hflip_str}"
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        f"setsar=1,"
        f"{setpts_str}"                   # [FIX-2/FIX-7] Timestamps
    )
    run_ffmpeg([
        "-t", str(duracao_input),          # [FIX-7] Limit input reading
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-r", str(VIDEO_FPS),            # [FIX-2] Força FPS também no codec
        "-an",
        output_path,
    ], description=f"Convertendo {Path(input_path).name} ({duracao:.1f}s @ {VIDEO_FPS}fps{desc_extra})")


# ── Função principal de montagem ──────────────────────────────────────────────
def montar_video(
    shelby_clips: list,
    pexels_clips: list,
    audio_file: str,
    word_timings: list,
    output_file: str,
    work_dir: str,
    musicas_dir: str = "",
) -> str:
    """
    Monta o vídeo final completo com todos os fixes aplicados.
    
    musicas_dir: pasta com os arquivos .mp3 de fundo (opcional). Se vazio, sem música.
    """
    work = Path(work_dir)

    # ── 1. Duração do áudio ───────────────────────────────────────────────────
    # [FIX-8] Usa ffprobe diretamente no arquivo MP3 — mais preciso que os timings
    # do Whisper, que frequentemente subestima a última palavra/sílaba.
    duracao_audio = get_media_duration(audio_file)
    # Adiciona margem de 2s para garantir que o vídeo nunca corte antes do áudio
    MARGEM_FINAL = 2.0
    duracao_audio_com_margem = duracao_audio + MARGEM_FINAL
    print(f"\nDuracao do audio: {duracao_audio:.1f}s (+{MARGEM_FINAL}s margem = {duracao_audio_com_margem:.1f}s total)")

    # Na montagem com xfade, cada transição subtrai XFADE_DURATION do total.
    # Vamos calcular isso dinamicamente no loop.
    duracao_alvo = duracao_audio_com_margem
    print(f"Duracao alvo do video: {duracao_alvo:.1f}s")

    # ── 2. Clip Shelby ────────────────────────────────────────────────────────
    print("\nProcessando clip Shelby...")
    shelby_escolhido = random.choice(shelby_clips)
    shelby_dur_orig  = get_media_duration(shelby_escolhido)
    shelby_dur       = min(SHELBY_CLIP_DURATION, shelby_dur_orig)
    shelby_out       = str(work / "shelby_proc.mp4")
    processar_clip_vertical(shelby_escolhido, shelby_out, shelby_dur, aplicar_hflip=False)

    # ── 3. Clips Pexels (espelhados + câmera lenta 0.5x) ────────────────────
    print("\nProcessando clips Pexels (hflip + slow motion 0.5x)...")
    pexels_processados = []
    
    # Duração total atual (Shelby já ocupa shelby_dur)
    duracao_total_atual = shelby_dur
    clip_durations = [shelby_dur]

    idx = 0
    volta = 0  # Conta quantas vezes reciclamos a lista inteira

    # Lista de trabalho: será embaralhada de forma diferente a cada reciclagem
    pexels_ordem = pexels_clips[:]
    random.shuffle(pexels_ordem)

    while duracao_total_atual < duracao_alvo:
        # Ao completar uma volta na lista, embaralha com seed diferente
        lista_idx = idx % len(pexels_ordem)
        if lista_idx == 0 and idx > 0:
            volta += 1
            rng_recicla = random.Random(volta * 31337)
            rng_recicla.shuffle(pexels_ordem)
            print(f"  ♻️  Reciclando clips (volta #{volta}) com nova ordem...")

        clip_orig = pexels_ordem[lista_idx]
        dur_orig  = get_media_duration(clip_orig)

        # Com slow_motion=True, o input real consumido = dur_clip/SLOW_MOTION_FACTOR
        # Mas a duração de OUTPUT (o que entra no concat) = dur_clip
        # Duração alvo do clip: aleatório entre 3 e 6 segundos (para dar dinâmica)
        # Se for o último clip, ajusta para bater exatamente a duração alvo
        falta = duracao_alvo - duracao_total_atual
        target_clip = random.uniform(3.0, 6.0)
        
        # Como o xfade vai sobrepor XFADE_DURATION, este clip vai adicionar de fato (target_clip - XFADE_DURATION)
        # Se (target_clip - XFADE_DURATION) for maior que o que falta, cortamos.
        add_efetivo = target_clip - XFADE_DURATION
        if add_efetivo > falta:
            target_clip = falta + XFADE_DURATION
        
        dur_clip = target_clip

        # Garante que temos input suficiente para a câmera lenta
        dur_input_necessario = dur_clip / SLOW_MOTION_FACTOR
        if dur_orig < dur_input_necessario:
            # Clip muito curto: usa o máximo possível em slow motion
            dur_clip = dur_orig * SLOW_MOTION_FACTOR

        if dur_clip < 0.5 + XFADE_DURATION:  # Tem que ser maior que o fade
            idx += 1
            continue

        out_clip = str(work / f"pexels_{idx:02d}.mp4")
        processar_clip_vertical(
            clip_orig, out_clip, dur_clip,
            aplicar_hflip=True,   # [FIX] Sempre espelhado horizontalmente
            slow_motion=True,     # [FIX-7] Câmera lenta 0.5x
        )
        pexels_processados.append(out_clip)
        clip_durations.append(dur_clip)
        
        # Atualiza a duração total da timeline
        duracao_total_atual += (dur_clip - XFADE_DURATION)
        idx += 1

    duracao_total = duracao_total_atual
    print(f"  {len(pexels_processados)} clips Pexels (Timeline total atingiu {duracao_total:.1f}s)")

    # ── 4. Concatena usando concat FILTER (mais robusto que demuxer) ──────────
    print("\nConcatenando clips com concat filter...")
    todos = [shelby_out] + pexels_processados

    # Monta inputs e xfade filter dinamicamente
    inputs = []
    for c in todos:
        inputs += ["-i", c]

    n = len(todos)
    if n == 1:
        concat_filter = "[0:v]copy[vconcat]"
    else:
        filter_parts = []
        last_out = "[0:v]"
        current_offset = clip_durations[0] - XFADE_DURATION
        for i in range(1, n):
            out_label = f"[v{i}]" if i < n - 1 else "[vconcat]"
            filter_parts.append(
                f"{last_out}[{i}:v]xfade=transition=fade:duration={XFADE_DURATION}:offset={current_offset:.2f}{out_label}"
            )
            last_out = out_label
            if i < n - 1:
                current_offset += clip_durations[i] - XFADE_DURATION
        
        concat_filter = ";".join(filter_parts)

    video_concat = str(work / "video_concat.mp4")
    run_ffmpeg(
        inputs + [
            "-filter_complex", concat_filter,
            "-map", "[vconcat]",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-r", str(VIDEO_FPS),
            video_concat,
        ],
        description="Concatenando todos os clips (filter)"
    )

    # ── 5. Música de fundo (opcional) ────────────────────────────────────────
    musica_escolhida = ""
    if musicas_dir:
        musicas_disponiveis = sorted(Path(musicas_dir).glob("*.mp3"))
        if musicas_disponiveis:
            musica_escolhida = str(random.choice(musicas_disponiveis))
            print(f"\n[Musica] Escolhida: {Path(musica_escolhida).name}")
        else:
            print(f"\n[Musica] Nenhum .mp3 encontrado em {musicas_dir} — sem fundo.")

    # ── 6. Monta vídeo final com legendas + efeitos ───────────────────────────
    print("\nGerando filtro de legendas (drawtext)...")
    legenda_filter = gerar_filtro_legendas(
        word_timings=word_timings,
        font_file=FONT_FILE,
    )

    # Filter complex: legendas → HDR → glow
    filter_complex = (
        f"[0:v]{legenda_filter},"
        f"curves=preset=strong_contrast,"
        f"eq=saturation=1.40:contrast=1.12:brightness=0.02,"
        f"split[vmain][vcopy];"
        f"[vcopy]gblur=sigma=7[vblur];"
        f"[vmain][vblur]blend=all_mode=screen:all_opacity=0.12[vout]"
    )

    # ── Monta áudio: narração pura OU narração + fundo 20% ────────────────────
    # [FIX-5] Voz em 110% (Fish Audio é baixinho), música em 20%
    if musica_escolhida:
        print("Mixando narracao + musica de fundo (voz 110%, fundo 20%)...")
        ffmpeg_inputs = [
            "-i", video_concat,
            "-i", audio_file,
            "-i", musica_escolhida,
        ]
        # amix: voz em 110%, música em 20%. duration=first → corta na narração
        audio_filter = (
            "[1:a]volume=1.10[voz];"
            "[2:a]volume=0.20,atrim=duration=" + str(duracao_total) + "[bgm];"
            "[voz][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        filter_final = filter_complex + f";{audio_filter}"
        audio_map = ["-map", "[aout]"]
    else:
        # Sem música: ainda aplica 110% de volume na voz
        ffmpeg_inputs = [
            "-i", video_concat,
            "-i", audio_file,
        ]
        filter_final = filter_complex + ";[1:a]volume=1.10[aout]"
        audio_map = ["-map", "[aout]"]

    filter_script = str(work / "filter_complex.txt")
    with open(filter_script, "w", encoding="utf-8") as fs:
        fs.write(filter_final)

    print("Renderizando video final com audio + legendas + efeitos...")
    run_ffmpeg(
        ffmpeg_inputs + [
            "-filter_complex_script", filter_script,
            "-map", "[vout]",
        ] + audio_map + [
            "-c:v", "libx264", "-crf", "22", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duracao_total),
            "-r", str(VIDEO_FPS),
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_file,
        ], description="Video final")

    tamanho = Path(output_file).stat().st_size / (1024 * 1024)
    print(f"\nVideo final: {output_file} ({tamanho:.1f} MB)")
    return output_file


# ── Teste standalone ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        test_file = sys.argv[2] if len(sys.argv) > 2 else ""
        if test_file and Path(test_file).exists():
            dur = get_media_duration(test_file)
            print(f"Duracao de '{test_file}': {dur:.2f}s")
        else:
            print("Use: python montar_video.py --test arquivo.mp4")
