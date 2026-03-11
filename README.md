# Ovalados Bot

Bot de Telegram para cargar resultados de rugby desde fotos de planillas.

## Variables de entorno (cargar en Railway)

| Variable | Valor |
|----------|-------|
| `TELEGRAM_TOKEN` | Token de @BotFather |
| `GEMINI_KEY` | API key de Google AI Studio |
| `GITHUB_TOKEN` | Personal access token de GitHub |
| `GITHUB_REPO` | `ovalados/ovalados-sitio` |
| `ALLOWED_USER` | Tu Telegram user ID (ver abajo) |

## Cómo obtener tu Telegram User ID

1. Buscá @userinfobot en Telegram
2. Mandá /start
3. Te dice tu ID (número)

## Deploy en Railway

1. Subí esta carpeta a un repo GitHub nuevo (ej: `ovalados/ovalados-bot`)
2. Andá a railway.app → New Project → Deploy from GitHub
3. Elegí el repo
4. En Variables, cargá todas las de la tabla de arriba
5. Deploy

## Uso

1. Abrí el bot en Telegram
2. Mandá /start
3. Elegí la división
4. Mandá foto de la planilla
5. Confirmá los resultados
6. ¡Listo! El sitio se actualiza solo
