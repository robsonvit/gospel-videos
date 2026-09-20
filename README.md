# 🎬 Jesus Videos Gospel Bot

Bot automático que gera vídeos gospel estilo snowboard para YouTube Shorts, TikTok e Reels.

## Como funciona

1. **Busca música gospel** em alta no YouTube via yt-dlp
2. **Transcreve a letra** com Whisper (faster-whisper) — legendas precisas e sincronizadas
3. **Baixa fundos visuais** do Pexels (montanhas, neve, aurora, natureza)
4. **Monta o vídeo** com FFmpeg: slow motion, xfade, legendas em fonte Cinzel
5. **Envia** ao Telegram e ao YouTube Shorts

## Secrets necessários

| Secret | Descrição |
|---|---|
| `PEXELS_API_KEY` | Chave da API do Pexels |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | ID do chat/canal Telegram |
| `YOUTUBE_CLIENT_ID` | OAuth2 client ID do YouTube |
| `YOUTUBE_CLIENT_SECRET` | OAuth2 client secret do YouTube |
| `YOUTUBE_REFRESH_TOKEN` | Refresh token OAuth2 do YouTube |

## Estilo visual

- **Resolução:** 1080×1920 (9:16 vertical)
- **FPS:** 30
- **Fonte:** Cinzel Regular (serif elegante)
- **Legendas:** UPPERCASE, branca, centralizada, shadow sutil
- **Clips:** Slow motion 0.5x com transições xfade fade
- **Efeitos:** Contraste forte + saturação + glow cinematográfico

## Schedule

Roda automaticamente todo dia às **09:00 Brasília** (12:00 UTC).
Também pode ser disparado manualmente via `workflow_dispatch`.
