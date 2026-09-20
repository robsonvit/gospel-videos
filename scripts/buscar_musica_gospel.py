"""
buscar_musica_gospel.py
Pipeline inteligente de selecao de trecho musical:

  1. Busca musicas gospel em alta no YouTube (yt-dlp search)
  2. Extrai heatmap (zonas mais reproduzidas) do video
  3. Detecta janela de ~52-58s com maior calor medio
  4. Baixa legendas automaticas do YouTube (VTT)
  5. Usa OpenRouter IA para validar corte musical natural
  6. Baixa somente o trecho validado
"""

import json
import math
import os
import re
import subprocess
import random
import time
import requests
from pathlib import Path

PROJETO_ROOT = Path(__file__).parent.parent
MUSICAS_USADAS_FILE = PROJETO_ROOT / "musicas_usadas.json"
MAX_HISTORICO = 40

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELOS_IA = [
    "openrouter/free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

# Arquivo de cookies do YouTube (export via browser extension)
# No GitHub Actions: decode YOUTUBE_COOKIES_B64 secret para este arquivo
COOKIES_FILE = os.environ.get("YOUTUBE_COOKIES_FILE", "/tmp/youtube_cookies.txt")

QUERIES_GOSPEL = [
    "louvor nacional lancamento 2024",
    "musica gospel brasil 2024",
    "gospel nacional mais tocada",
    "louvor brasileiro atual",
    "gospel hits brasil 2024",
    "louvor pentecostal atual",
    "melhores louvores nacionais 2024",
    "hino gospel nacional 2024",
]

DURACAO_MIN = 48.0
DURACAO_MAX = 58.0
DURACAO_ALVO = 55.0

# User-agent de iPhone para bypass de bot detection em CI
IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

# Cliente poderoso para bypass no YouTube Actions
PLAYER_CLIENTS = ["mweb,android"]

def _ytdlp_bypass(player_client: str = "") -> list:
    """
    Retorna flags de bypass para comandos yt-dlp que baixam conteudo individual.
    Utiliza mweb,android apenas se especificado (ideal para download).
    """
    args = []
    if player_client:
        args.extend(["--extractor-args", f"youtube:player_client={player_client}"])
    
    args.extend([
        "--remote-components", "ejs:github",
        "--add-header", "User-Agent:Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "--add-header", "Accept-Language:pt-BR,pt;q=0.9,en;q=0.8",
        "--no-check-certificates",
        "--sleep-interval", "2",
        "--max-sleep-interval", "5",
    ])
    # Usa cookies se o arquivo existir (prioridade maxima - bypass garantido)
    if os.path.isfile(COOKIES_FILE):
        args += ["--cookies", COOKIES_FILE]
        print(f"  [cookies OK] Usando {COOKIES_FILE}")
    return args


# ── Historico ──────────────────────────────────────────────────────────────────

def carregar_usadas() -> set:
    if MUSICAS_USADAS_FILE.exists():
        try:
            data = json.loads(MUSICAS_USADAS_FILE.read_text(encoding="utf-8"))
            return set(data.get("ids_usados", []))
        except Exception:
            pass
    return set()


def salvar_usada(video_id: str) -> None:
    ids = list(carregar_usadas())
    if video_id not in ids:
        ids.append(video_id)
    if len(ids) > MAX_HISTORICO:
        ids = ids[-MAX_HISTORICO:]
    MUSICAS_USADAS_FILE.write_text(
        json.dumps({"ids_usados": ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Heatmap ────────────────────────────────────────────────────────────────────

def obter_info_video(video_id: str) -> dict:
    """Extrai metadados completos do video incluindo heatmap via yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp", url,
        "--skip-download",
        "--print-json",
        "--no-playlist",
        "--quiet",
    ] + _ytdlp_bypass()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0 or not result.stdout.strip():
        stderr_msg = result.stderr.strip()[:200] if result.stderr.strip() else ""
        raise RuntimeError(f"yt-dlp info falhou para {video_id}: {stderr_msg}")
    return json.loads(result.stdout.strip())


def encontrar_zona_quente(heatmap: list, duracao_video: float) -> tuple:
    """
    Analisa o heatmap e retorna (inicio, fim) da janela de DURACAO_ALVO segundos
    com maior calor medio (zona mais reproduzida).
    """
    if not heatmap:
        inicio = duracao_video * 0.20
        fim = min(inicio + DURACAO_ALVO, duracao_video * 0.80)
        print(f"  Heatmap indisponivel - zona padrao: {inicio:.1f}s-{fim:.1f}s")
        return (round(inicio, 1), round(fim, 1))

    duracao_int = int(math.ceil(duracao_video))
    valores = [0.0] * (duracao_int + 2)

    for segmento in heatmap:
        s = segmento.get("start_time", 0)
        e = segmento.get("end_time", s + 1)
        v = segmento.get("value", 0)
        for t in range(int(s), min(int(e) + 1, len(valores))):
            valores[t] = max(valores[t], v)

    janela = int(DURACAO_ALVO)
    melhor_inicio = int(duracao_video * 0.20)
    melhor_calor = -1.0

    for i in range(len(valores) - janela):
        if i < duracao_video * 0.10 or (i + janela) > duracao_video * 0.90:
            continue
        calor = sum(valores[i : i + janela]) / janela
        if calor > melhor_calor:
            melhor_calor = calor
            melhor_inicio = i

    melhor_fim = melhor_inicio + DURACAO_ALVO
    print(f"  Zona quente: {melhor_inicio}s - {melhor_fim:.0f}s (calor: {melhor_calor:.3f})")
    return (float(melhor_inicio), float(melhor_fim))


# ── Legendas ───────────────────────────────────────────────────────────────────

def baixar_legendas(video_id: str, output_dir: str) -> str | None:
    """Baixa legendas automaticas do YouTube (pt > en > qualquer)."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    for idioma in ["pt", "pt-BR", "en", "pt.*,en"]:
        cmd = [
            "yt-dlp", url,
            "--write-auto-subs",
            "--sub-langs", idioma,
            "--sub-format", "vtt",
            "--skip-download",
            "--output", str(Path(output_dir) / "legenda.%(ext)s"),
            "--quiet", "--no-warnings",
        ] + _ytdlp_bypass()
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        vtts = list(Path(output_dir).glob("*.vtt"))
        if vtts:
            print(f"  Legendas: {vtts[0].name}")
            return str(vtts[0])

    print("  Legendas automaticas indisponiveis.")
    return None


def parsear_vtt(vtt_path: str) -> list:
    """Parseia VTT e retorna lista de { text, start, end } em segundos."""
    content = Path(vtt_path).read_text(encoding="utf-8", errors="ignore")
    content = re.sub(r"WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
    content = re.sub(r"NOTE.*?\n\n", "", content, flags=re.DOTALL)
    content = re.sub(r"STYLE.*?\n\n", "", content, flags=re.DOTALL)

    segmentos = []
    blocos = re.split(r"\n\n+", content.strip())

    for bloco in blocos:
        linhas = bloco.strip().split("\n")
        if len(linhas) < 2:
            continue

        timing_linha = None
        for linha in linhas:
            if "-->" in linha:
                timing_linha = linha
                break
        if not timing_linha:
            continue

        m = re.search(
            r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})",
            timing_linha
        )
        if not m:
            m = re.search(
                r"(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2})[.,](\d{3})",
                timing_linha
            )
            if m:
                start = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000
                end   = int(m.group(4)) * 60 + int(m.group(5)) + int(m.group(6)) / 1000
            else:
                continue
        else:
            start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000
            end   = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000

        texto_linhas = [l for l in linhas if "-->" not in l and not re.match(r"^\d+$", l.strip())]
        texto = " ".join(texto_linhas).strip()
        texto = re.sub(r"<[^>]+>", "", texto).strip()

        if texto:
            segmentos.append({"text": texto, "start": round(start, 3), "end": round(end, 3)})

    limpos = []
    ultimo = ""
    for seg in segmentos:
        if seg["text"] != ultimo:
            limpos.append(seg)
            ultimo = seg["text"]
    return limpos


def extrair_texto_zona(segmentos: list, zona_inicio: float, zona_fim: float) -> list:
    return [s for s in segmentos if s["end"] >= zona_inicio and s["start"] <= zona_fim]


# ── IA: validacao do trecho ────────────────────────────────────────────────────

def validar_trecho_com_ia(segmentos_zona: list, zona_inicio: float, zona_fim: float, titulo: str) -> tuple:
    """Usa OpenRouter IA para ajustar inicio/fim para corte musical natural."""
    if not OPENROUTER_API_KEY:
        print("  OPENROUTER_API_KEY nao configurada - usando zona do heatmap.")
        return (zona_inicio, zona_fim, True)

    if not segmentos_zona:
        print("  Sem texto na zona - usando limites do heatmap.")
        return (zona_inicio, zona_fim, True)

    linhas_texto = [f"[{s['start']:.1f}s] {s['text']}" for s in segmentos_zona]
    texto_zona = "\n".join(linhas_texto)

    prompt = (
        f"Voce e um editor de video de musica gospel.\n"
        f"Musica: \"{titulo}\"\n"
        f"Zona mais reproduzida: {zona_inicio:.1f}s ate {zona_fim:.1f}s\n\n"
        f"Transcricao com timestamps:\n{texto_zona}\n\n"
        f"Encontre o melhor corte (inicio e fim de frase musical completa).\n"
        f"Duracao alvo: entre {DURACAO_MIN:.0f}s e {DURACAO_MAX:.0f}s.\n"
        f"Responda SOMENTE com JSON:\n"
        f"{{\"inicio\": <float>, \"fim\": <float>, \"faz_sentido\": true/false, \"justificativa\": \"<texto breve>\"}}"
    )

    for modelo in MODELOS_IA:
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={"model": modelo, "messages": [{"role": "user", "content": prompt}], "max_tokens": 200, "temperature": 0.2},
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            m = re.search(r"\{.*?\}", content, re.DOTALL)
            if not m:
                continue
            dados = json.loads(m.group())
            inicio = float(dados.get("inicio", zona_inicio))
            fim    = float(dados.get("fim", zona_fim))
            faz    = bool(dados.get("faz_sentido", True))
            just   = dados.get("justificativa", "")
            duracao = fim - inicio
            if duracao < DURACAO_MIN or duracao > DURACAO_MAX + 5:
                fim = inicio + DURACAO_ALVO
            print(f"  IA: {inicio:.1f}s-{fim:.1f}s | {just[:80]}")
            return (round(inicio, 1), round(fim, 1), faz)
        except Exception as e:
            print(f"  Aviso IA ({modelo}): {e}")
            continue

    print("  IA falhou - usando zona do heatmap.")
    return (zona_inicio, zona_fim, True)


# ── Download do trecho ─────────────────────────────────────────────────────────

def _hhmmss(segundos: float) -> str:
    h = int(segundos) // 3600
    m = (int(segundos) % 3600) // 60
    s = int(segundos) % 60
    ms = int((segundos - int(segundos)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def baixar_trecho_audio(video_id: str, inicio: float, fim: float, output_dir: str) -> str:
    """Baixa o audio inteiro e corta com ffmpeg para evitar erros de codec do yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    full_output = str(Path(output_dir) / "full_audio.mp4")
    final_output = str(Path(output_dir) / "musica_gospel.mp3")

    ultimo_erro = ""
    for cliente in PLAYER_CLIENTS:
        cmd = [
            "yt-dlp", url,
            "-f", "best",
            "--output", full_output,
            "--no-playlist",
            "--quiet", "--no-warnings",
        ] + _ytdlp_bypass(player_client="mweb,android")

        print(f"  Baixando audio completo [{cliente}]...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)

        audio_files = list(Path(output_dir).glob("full_audio*"))
        if result.returncode == 0 and audio_files:
            print(f"  Download completo OK. Cortando trecho {_hhmmss(inicio)} - {_hhmmss(fim)}...")
            full_audio = str(audio_files[0])
            
            # Corta e converte com ffmpeg
            cmd_cut = [
                "ffmpeg", "-y", "-i", full_audio,
                "-ss", str(inicio), "-to", str(fim),
                "-b:a", "192k", final_output
            ]
            subprocess.run(cmd_cut, capture_output=True, text=True)
            
            if Path(final_output).exists():
                return final_output
            else:
                ultimo_erro = "Falha no corte com FFmpeg"
                break

        ultimo_erro = result.stderr.strip()[:200] if result.stderr.strip() else "sem output"
        print(f"  Client {cliente} falhou: {ultimo_erro[:100]}")
        time.sleep(3)

    raise RuntimeError(f"Falha em todos os player clients. Ultimo erro: {ultimo_erro}")



def _get_audio_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return DURACAO_ALVO


# ── Pipeline principal ─────────────────────────────────────────────────────────

def buscar_musica(output_dir: str, tentativas: int = 6) -> dict:
    """
    Pipeline: busca → heatmap → legenda → IA → download do trecho.
    Retorna { path, title, artist, video_id, query, duration, start, end, segmentos_zona }
    """
    os.makedirs(output_dir, exist_ok=True)
    ids_usados = carregar_usadas()

    queries = QUERIES_GOSPEL[:]
    random.shuffle(queries)

    for tentativa in range(tentativas):
        query = queries[tentativa % len(queries)]
        print(f"\n[Tentativa {tentativa+1}/{tentativas}] Buscando: '{query}'")
        try:
            resultado = _tentar_pipeline(query, output_dir, ids_usados)
            if resultado:
                return resultado
        except Exception as e:
            print(f"  Erro tentativa {tentativa+1}: {e}")
        time.sleep(2)

    raise RuntimeError(f"Nao foi possivel obter musica gospel apos {tentativas} tentativas.")


def _tentar_pipeline(query: str, output_dir: str, ids_usados: set) -> dict | None:
    # --- 1. Lista candidatos com --flat-playlist ---
    # IMPORTANTE:
    # - NAO usar _ytdlp_bypass() aqui: player_client=ios quebra ytsearch (retorna vazio)
    # - Usar --flat-playlist para nao buscar metadados individuais (evita bot detection)
    # - Filtrar duracao manualmente em Python
    cmd = [
        "yt-dlp", f"ytsearch15:{query}",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(uploader)s\t%(duration)s\t%(view_count)s",
        "--no-warnings",
        "--quiet",
    ]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

    if r.returncode != 0 or not r.stdout.strip():
        stderr_preview = r.stderr.strip()[:300] if r.stderr.strip() else "(sem saida)"
        print(f"  yt-dlp busca falhou (code={r.returncode}): {stderr_preview}")
        return None

    linhas = [l for l in r.stdout.strip().split("\n") if l.strip()]
    print(f"  yt-dlp retornou {len(linhas)} resultados.")

    candidatos = []
    for linha in linhas:
        partes = linha.strip().split("\t")
        if len(partes) < 5:
            # Tenta preencher views se faltar
            while len(partes) < 5:
                partes.append("0")
        vid_id, titulo, uploader, dur_str, views_str = partes[0], partes[1], partes[2], partes[3], partes[4]

        # dur_str pode ser "NA" em modo flat-playlist - aceita sem filtrar nesses casos
        try:
            dur = int(float(dur_str)) if dur_str not in ("NA", "None", "", "0") else 200
        except (ValueError, TypeError):
            dur = 200  # assume duracao razoavel se nao disponivel
            
        try:
            views = int(float(views_str)) if views_str not in ("NA", "None", "") else 0
        except (ValueError, TypeError):
            views = 0

        # Filtra musicas muito curtas ou muito longas
        if dur < 60 or dur > 900:
            continue

        # Evita corais/hinos antigos que confundem o Whisper
        # E evita musicas em ingles (official, lyric, feat, hillsong, etc)
        titulo_low = titulo.lower()
        if any(x in titulo_low for x in ["coral", "harpa", "hino antigo", "coro", "infantil", "official", "lyric", "feat", "ft.", "hillsong", "bethel", "elevation", "maverick", "music video"]):
            continue

        if vid_id not in ids_usados:
            candidatos.append({"id": vid_id, "title": titulo, "artist": uploader, "duration": dur, "views": views})

    if not candidatos:
        print(f"  Nenhum candidato valido (duracao 90-900s, nao usados).")
        return None

    print(f"  {len(candidatos)} candidatos validos. Ordenando por visualizacoes...")
    # Ordena por views decrescente para pegar os maiores hits
    candidatos.sort(key=lambda x: x.get("views", 0), reverse=True)

    for candidato in candidatos[:4]:
        try:
            resultado = _processar_candidato(candidato, query, output_dir)
            if resultado:
                return resultado
        except Exception as e:
            print(f"  Candidato {candidato['id']} falhou: {e}")
        time.sleep(3)  # Evita 429 entre candidatos

    return None


def _processar_candidato(candidato: dict, query: str, output_dir: str) -> dict | None:
    video_id = candidato["id"]
    titulo   = candidato["title"]
    artista  = candidato["artist"]
    dur_total = candidato["duration"]

    print(f"\n  Analisando: '{titulo}' ({artista}) - {dur_total}s [{video_id}]")

    cand_dir = Path(output_dir) / video_id
    cand_dir.mkdir(parents=True, exist_ok=True)

    # --- 2. Heatmap ---
    print("  Extraindo heatmap...")
    try:
        info = obter_info_video(video_id)
        heatmap = info.get("heatmap", [])
        dur_real = float(info.get("duration", dur_total))
    except Exception as e:
        print(f"  Aviso heatmap: {e} - usando duracao estimada.")
        heatmap = []
        dur_real = float(dur_total)

    # --- 3. Zona quente ---
    zona_inicio, zona_fim = encontrar_zona_quente(heatmap, dur_real)
    if (zona_fim - zona_inicio) < DURACAO_MIN:
        zona_fim = zona_inicio + DURACAO_ALVO

    # --- 4. Legendas ---
    print("  Baixando legendas...")
    leg_dir = str(cand_dir / "legendas")
    Path(leg_dir).mkdir(exist_ok=True)
    vtt_path = baixar_legendas(video_id, leg_dir)

    segmentos_todos = []
    segmentos_zona  = []
    if vtt_path:
        segmentos_todos = parsear_vtt(vtt_path)
        segmentos_zona  = extrair_texto_zona(segmentos_todos, zona_inicio, zona_fim)
        print(f"  {len(segmentos_zona)} segmentos na zona quente.")

    # --- 5. IA valida trecho ---
    print("  Validando com IA...")
    start_final, end_final, faz_sentido = validar_trecho_com_ia(
        segmentos_zona, zona_inicio, zona_fim, titulo
    )

    if not faz_sentido:
        print(f"  IA: trecho sem sentido musical - proxima tentativa.")
        return None

    # Ajusta segmentos para timestamps relativos ao trecho
    segmentos_finais = extrair_texto_zona(segmentos_todos, start_final, end_final)
    for seg in segmentos_finais:
        seg["start"] = round(max(0, seg["start"] - start_final), 3)
        seg["end"]   = round(max(0, seg["end"]   - start_final), 3)

    # --- 6. Download do audio ---
    print(f"  Download do trecho: {start_final:.1f}s - {end_final:.1f}s...")
    audio_dir = str(cand_dir / "audio")
    Path(audio_dir).mkdir(exist_ok=True)

    mp3_path = baixar_trecho_audio(video_id, start_final, end_final, audio_dir)
    duracao_real = _get_audio_duration(mp3_path)

    print(f"  Pronto: {duracao_real:.1f}s | {len(segmentos_finais)} legendas")
    salvar_usada(video_id)

    return {
        "path":           mp3_path,
        "title":          titulo,
        "artist":         artista,
        "video_id":       video_id,
        "query":          query,
        "duration":       duracao_real,
        "start":          start_final,
        "end":            end_final,
        "segmentos_zona": segmentos_finais,
    }
