"""
transcrever_letra.py
Processa os segmentos de legenda ja baixados do YouTube.

Prioridade:
  1. Usa os segmentos do YouTube (baixados pelo buscar_musica_gospel)
  2. Fallback: Whisper no audio local se nao houver legendas

Os segmentos ja chegam com timestamps relativos ao inicio do trecho.
Agrupamos em frases de ate 4 palavras e convertemos para UPPERCASE.
"""

import re


def processar_segmentos_youtube(segmentos: list) -> list:
    """
    Recebe segmentos do YouTube { text, start, end }
    e retorna legendas prontas para o FFmpeg drawtext.
    
    - Converte para UPPERCASE
    - Remove pontuacao desnecessaria
    - Garante que nao ha sobreposicao de timestamps
    """
    if not segmentos:
        return []
    
    legendas = []
    for seg in segmentos:
        texto = _limpar_texto(seg["text"])
        if not texto:
            continue
        # Quebra em frases de ate 5 palavras para o estilo visual
        frases = _quebrar_em_frases(texto, seg["start"], seg["end"], max_palavras=5)
        legendas.extend(frases)
    
    # Remove duplicatas e sobreposicoes
    legendas = _deduplicar(legendas)
    return legendas


def _quebrar_em_frases(texto: str, start: float, end: float, max_palavras: int = 5) -> list:
    """
    Divide um texto longo em frases menores distribuindo o tempo proporcionalmente.
    """
    palavras = texto.split()
    if len(palavras) <= max_palavras:
        return [{"text": texto, "start": start, "end": end}]
    
    duracao = end - start
    grupos = []
    i = 0
    while i < len(palavras):
        grupo = palavras[i : i + max_palavras]
        fracao = len(grupo) / len(palavras)
        t_inicio = start + (i / len(palavras)) * duracao
        t_fim    = start + ((i + len(grupo)) / len(palavras)) * duracao
        grupos.append({
            "text":  " ".join(grupo),
            "start": round(t_inicio, 3),
            "end":   round(t_fim, 3),
        })
        i += max_palavras
    return grupos


def _limpar_texto(texto: str) -> str:
    """Remove pontuacao excessiva, tags e converte para UPPERCASE."""
    texto = re.sub(r"<[^>]+>", "", texto)          # remove tags HTML/VTT
    texto = re.sub(r"\[.*?\]", "", texto)           # remove [musica], [aplausos] etc.
    texto = re.sub(r"\(.*?\)", "", texto)           # remove (instrumental)
    texto = re.sub(r"[^\w\s]", " ", texto, flags=re.UNICODE)
    texto = " ".join(texto.split())
    return texto.upper()


def _deduplicar(legendas: list) -> list:
    """Remove entradas duplicadas consecutivas."""
    if not legendas:
        return []
    resultado = [legendas[0]]
    for leg in legendas[1:]:
        if leg["text"] != resultado[-1]["text"]:
            resultado.append(leg)
    return resultado


def transcrever_audio(audio_path: str, modelo: str = "base", prompt_inicial: str = "") -> list:
    """
    Usa Whisper para transcrever e obter word-level timestamps.
    Se um prompt inicial for fornecido, a IA sera forgada a tentar usar essas exatas palavras.
    Retorna lista de { text, start, end }.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  AVISO: faster-whisper nao instalado. Sem legendas.")
        return []
    
    print(f"  [Fallback] Whisper '{modelo}' transcrevendo: {audio_path}")
    model = WhisperModel(modelo, device="cpu", compute_type="int8")
    
    kwargs = {
        "language": "pt",
        "beam_size": 5,
        "word_timestamps": True,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.8,
        "log_prob_threshold": -1.5,
    }
    if prompt_inicial:
        kwargs["initial_prompt"] = prompt_inicial
        
    segments, info = model.transcribe(audio_path, **kwargs)
    print(f"  Idioma detectado: {info.language} ({info.language_probability:.2f})")
    
    palavras = []
    for segment in segments:
        if hasattr(segment, "words") and segment.words:
            for word in segment.words:
                t = word.word.strip()
                if t:
                    palavras.append({"text": t, "start": word.start, "end": word.end})
    
    if not palavras:
        return []
    
    return _agrupar_palavras(palavras, max_palavras=3)


def _agrupar_palavras(palavras: list, max_palavras: int = 3) -> list:
    """Agrupa palavras em frases curtas com pausa natural."""
    if not palavras:
        return []
    
    legendas = []
    grupo = []
    inicio = palavras[0]["start"]
    PAUSA = 0.5
    
    for i, p in enumerate(palavras):
        grupo.append(p)
        proxima = palavras[i + 1] if i + 1 < len(palavras) else None
        
        deve_fechar = (
            len(grupo) >= max_palavras
            or (proxima and (proxima["start"] - p["end"]) > PAUSA)
            or proxima is None
        )
        
        if deve_fechar:
            texto = " ".join(x["text"] for x in grupo)
            texto = _limpar_texto(texto)
            if texto:
                legendas.append({
                    "text":  texto,
                    "start": round(inicio, 3),
                    "end":   round(grupo[-1]["end"], 3),
                })
            grupo = []
            if proxima:
                inicio = proxima["start"]
    
    return legendas
