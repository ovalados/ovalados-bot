#!/usr/bin/env python3
"""
Ovalados Bot — Lee fotos de planillas y actualiza resultados en GitHub
"""
import os, json, base64, logging, re, requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config desde variables de entorno ─────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
GITHUB_REPO    = os.environ.get("GITHUB_REPO", "ovalados/ovalados-sitio")
ALLOWED_USER   = int(os.environ.get("ALLOWED_USER", "0"))

# ── Divisiones disponibles ────────────────────────────────
DIVISIONES = {
    "intermedia":      "intermedia",
    "preintermedia_a": "preintermedia-a",
    "preintermedia_b": "preintermedia-b",
    "preintermedia_c": "preintermedia-c",
    "preintermedia_d": "preintermedia-d",
}

DIVISION_LABELS = {
    "intermedia":      "Intermedia",
    "preintermedia_a": "Pre-Intermedia A",
    "preintermedia_b": "Pre-Intermedia B",
    "preintermedia_c": "Pre-Intermedia C",
    "preintermedia_d": "Pre-Intermedia D",
}

user_state = {}

# ── GitHub API ────────────────────────────────────────────
def github_get_file(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]
    return None, None

def github_update_file(path, content, sha, message):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    encoded = base64.b64encode(json.dumps(content, ensure_ascii=False, indent=2).encode()).decode()
    payload = {"message": message, "content": encoded, "sha": sha}
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in [200, 201]

# ── Gemini Vision ─────────────────────────────────────────
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

def analizar_foto(image_bytes, division_label):
    prompt = f"""Analizá esta imagen con resultados de rugby de la división {division_label}.
Puede ser captura de pantalla, foto de planilla, pizarra, o cualquier formato.
Extraé todos los partidos con score final.

Respondé SOLO con un JSON array válido. Sin texto, sin markdown, sin bloques de código.
Formato:
[{{"home": "Club Local", "hs": 24, "away": "Club Visitante", "as": 18}}]

Si no hay resultados claros respondé: []"""

    img_b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
        ]}],
        "generationConfig": {"temperature": 0.1}
    }

    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        try:
            r = requests.post(url, json=payload, timeout=30)
            logger.info(f"Gemini {model}: status {r.status_code}")
            if r.status_code == 404:
                continue
            if r.status_code != 200:
                logger.error(f"Gemini {model} error: {r.text[:200]}")
                continue

            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"Gemini response: {text[:200]}")

            # Limpiar markdown si viene
            text = re.sub(r'```(?:json)?\s*|\s*```', '', text).strip()
            # Extraer solo el array JSON si hay texto extra
            m = re.search(r'\[[\s\S]*\]', text)
            if m:
                text = m.group(0)

            return json.loads(text)
        except Exception as e:
            logger.error(f"Gemini {model} exception: {e}")
            continue

    return []

# ── Handlers ──────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER and update.effective_user.id != ALLOWED_USER:
        await update.message.reply_text("⛔ No autorizado.")
        return
    await update.message.reply_text(
        "🏉 *Ovalados Bot*\n\nMandame una foto y te ayudo a cargar los resultados.\n\nPrimero elegí la división:",
        parse_mode="Markdown",
        reply_markup=division_keyboard()
    )

def division_keyboard():
    buttons = [[InlineKeyboardButton(label, callback_data=f"div_{key}")]
               for key, label in DIVISION_LABELS.items()]
    return InlineKeyboardMarkup(buttons)

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data.startswith("div_"):
        div = query.data[4:]
        user_state[uid] = {"division": div, "step": "waiting_photo"}
        await query.edit_message_text(
            f"✓ División: *{DIVISION_LABELS[div]}*\n\nAhora mandame la foto.",
            parse_mode="Markdown"
        )

    elif query.data == "confirmar":
        state = user_state.get(uid, {})
        if not state.get("resultados"):
            await query.edit_message_text("❌ No hay resultados para guardar.")
            return

        div = state["division"]
        resultados = state["resultados"]
        json_key = DIVISIONES[div]
        path = f"data/{json_key}.json"

        await query.edit_message_text("⏳ Guardando en GitHub...")

        data, sha = github_get_file(path)
        if data is None:
            data = {"teams": [], "matches": {}, "lastUpdate": ""}

        from datetime import datetime, timezone
        updated = 0
        for r in resultados:
            for rnd, rd in data.get("matches", {}).items():
                ms = rd.get("ms") or rd.get("matches") or []
                for m in ms:
                    if (m.get("home","").lower() == r["home"].lower() and
                        m.get("away","").lower() == r["away"].lower() and
                        not m.get("played")):
                        m["hs"] = r["hs"]
                        m["as"] = r["as"]
                        m["played"] = True
                        updated += 1
                        break

        data["lastUpdate"] = datetime.now(timezone.utc).isoformat()

        if updated == 0:
            if "results" not in data:
                data["results"] = []
            data["results"].extend(resultados)
            updated = len(resultados)

        ok = github_update_file(path, data, sha, f"🏉 {DIVISION_LABELS[div]}: {updated} resultado(s)")

        if ok:
            await query.edit_message_text(
                f"✅ *{updated} resultado(s) guardado(s)* en {DIVISION_LABELS[div]}!\n\nEl sitio se actualiza en ~1 minuto.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Error al guardar en GitHub. Intentá de nuevo.")

        user_state.pop(uid, None)

    elif query.data == "cancelar":
        user_state.pop(uid, None)
        await query.edit_message_text("❌ Cancelado.")

    elif query.data == "reintentar":
        state = user_state.get(uid, {})
        state["step"] = "waiting_photo"
        await query.edit_message_text(
            f"División: *{DIVISION_LABELS.get(state.get('division',''), '?')}*\n\nMandame la foto de nuevo.",
            parse_mode="Markdown"
        )

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER and update.effective_user.id != ALLOWED_USER:
        return

    uid = update.effective_user.id
    state = user_state.get(uid, {})

    if state.get("step") != "waiting_photo":
        await update.message.reply_text("Primero elegí la división con /start", reply_markup=division_keyboard())
        return

    msg = await update.message.reply_text("🔍 Analizando...")

    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    img_bytes = bytes(await file.download_as_bytearray())

    div = state["division"]
    resultados = analizar_foto(img_bytes, DIVISION_LABELS[div])

    if not resultados:
        await msg.edit_text(
            "❌ No pude leer resultados. ¿Intentamos de nuevo?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📷 Reintentar", callback_data="reintentar"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
            ]])
        )
        return

    user_state[uid]["resultados"] = resultados
    user_state[uid]["step"] = "confirming"

    lines = [f"*{DIVISION_LABELS[div]}* — Resultados:\n"]
    for r in resultados:
        lines.append(f"• {r['home']} *{r['hs']}* — *{r['as']}* {r['away']}")
    lines.append("\n¿Son correctos?")

    await msg.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar", callback_data="confirmar"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ]])
    )

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER and update.effective_user.id != ALLOWED_USER:
        return
    await update.message.reply_text("Mandame una foto, o usá /start para elegir la división.", reply_markup=division_keyboard())

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
