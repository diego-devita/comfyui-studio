#!/usr/bin/env python3
"""ComfyUI Studio — Telegram Bot

Polling bot that lets you run presets from Telegram.
Runs as a background process inside the pod alongside uvicorn.

Flow:
  /start    → list presets (inline buttons)
  Pick preset → show preset details + ask for image
  Send photo  → confirm launch
  Confirm     → execute job, poll progress every 10s, send result

Environment:
  TELEGRAM_BOT_TOKEN  — from @BotFather (if empty, bot doesn't start)
  API_KEY             — same as Studio backend
  STUDIO_PORT         — backend port (default 8000)
"""

import asyncio
import io
import json
import logging
import os
import time

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("studio-bot")

# ── Config ──

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
STUDIO_URL = "http://127.0.0.1:" + os.environ.get("STUDIO_PORT", "8000")
API_KEY = os.environ.get("API_KEY", "changeme")

HEADERS = {"X-API-Key": API_KEY}


# ── Studio API helpers ──

async def studio_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{STUDIO_URL}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def studio_post(path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{STUDIO_URL}{path}", headers=HEADERS, **kwargs)
        r.raise_for_status()
        return r.json()


async def studio_get_bytes(path: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{STUDIO_URL}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.content


# ── Handlers ──

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available presets."""
    presets = await studio_get("/api/admin/presets")
    if not presets:
        await update.message.reply_text("No presets available. Create one from the Studio web UI.")
        return

    buttons = []
    for p in presets:
        label = p.get("name", p["id"])
        buttons.append([InlineKeyboardButton(label, callback_data=f"preset:{p['id']}")])

    await update.message.reply_text(
        "🎨 *Choose a preset:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_preset_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle preset selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("preset:"):
        preset_id = data.split(":", 1)[1]
        preset = await studio_get(f"/api/admin/presets/{preset_id}")

        context.user_data["preset"] = preset
        context.user_data["placeholder_answers"] = {}

        # Check for placeholders
        placeholders = await studio_get(f"/api/admin/presets/{preset_id}/placeholders")
        context.user_data["placeholders"] = placeholders

        wf_name = preset.get("workflow", {}).get("workflow_name", "?")
        desc = preset.get("description", "")
        text = f"✅ *{preset.get('name', preset_id)}*\n"
        if desc:
            text += f"_{desc}_\n"
        text += f"\nWorkflow: `{wf_name}`\n"

        if placeholders:
            context.user_data["state"] = "answering_placeholders"
            context.user_data["current_placeholder"] = 0
            await query.edit_message_text(text, parse_mode="Markdown")
            await _ask_next_placeholder(update, context)
        else:
            context.user_data["state"] = "waiting_image"
            text += "\n📷 Now send me a photo to use as input."
            await query.edit_message_text(text, parse_mode="Markdown")

    elif data.startswith("ph_answer:"):
        # Handle choice placeholder answer
        parts = data.split(":", 2)
        ph_idx = int(parts[1])
        answer = parts[2]
        context.user_data["placeholder_answers"][str(ph_idx)] = answer
        context.user_data["current_placeholder"] = ph_idx + 1
        await query.answer()
        await _ask_next_placeholder(update, context)

    elif data.startswith("confirm:"):
        await _launch_job(update, context)

    elif data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled.")


async def _ask_next_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the next placeholder question, or move to image if done."""
    placeholders = context.user_data.get("placeholders", [])
    current = context.user_data.get("current_placeholder", 0)

    if current >= len(placeholders):
        # All answered — ask for image
        context.user_data["state"] = "waiting_image"
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, "📷 Now send me a photo to use as input.")
        return

    ph = placeholders[current]
    scene_label = f"Scena {ph['scene']}: " if ph.get("scene") else ""
    question = f"{scene_label}{ph['question']}"

    chat_id = update.effective_chat.id

    if ph["options"]:
        # Choice — inline buttons
        buttons = []
        for opt in ph["options"]:
            buttons.append([InlineKeyboardButton(opt, callback_data=f"ph_answer:{ph['index']}:{opt}")])
        await context.bot.send_message(
            chat_id, question,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        # Free text
        context.user_data["state"] = "answering_text"
        context.user_data["text_ph_index"] = ph["index"]
        await context.bot.send_message(chat_id, f"{question}\n_(scrivi la risposta)_", parse_mode="Markdown")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text — either placeholder answer or show presets."""
    state = context.user_data.get("state")

    if state == "answering_text":
        # Free text placeholder answer
        ph_idx = context.user_data.get("text_ph_index")
        context.user_data["placeholder_answers"][str(ph_idx)] = update.message.text.strip()
        context.user_data["current_placeholder"] = ph_idx + 1
        context.user_data["state"] = "answering_placeholders"
        await _ask_next_placeholder(update, context)
        return

    await cmd_start(update, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive photo for the preset."""
    state = context.user_data.get("state")
    if state != "waiting_image":
        await cmd_start(update, context)
        return

    # Download the photo (highest resolution)
    photo = update.message.photo[-1]
    file = await photo.get_file()
    bio = io.BytesIO()
    await file.download_to_memory(bio)
    bio.seek(0)

    context.user_data["image_bytes"] = bio.getvalue()
    context.user_data["image_name"] = f"telegram_{photo.file_unique_id}.jpg"
    context.user_data["state"] = "confirm"

    preset = context.user_data.get("preset", {})
    buttons = [
        [
            InlineKeyboardButton("🚀 Launch", callback_data="confirm:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
        ]
    ]
    await update.message.reply_text(
        f"📷 Image received.\n\n"
        f"Ready to run *{preset.get('name', '?')}*?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _launch_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the preset job and track progress."""
    query = update.callback_query
    preset = context.user_data.get("preset", {})
    image_bytes = context.user_data.get("image_bytes")
    image_name = context.user_data.get("image_name", "input.jpg")
    answers = context.user_data.get("placeholder_answers", {})
    preset_id = preset.get("id", "")

    status_msg = await query.edit_message_text("⏳ Uploading and queuing job...")

    try:
        # Execute via preset run endpoint
        files = {"input_image": (image_name, image_bytes, "image/jpeg")}
        form_data = {"seed": "-1"}
        if answers:
            form_data["answers"] = json.dumps(answers)

        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{STUDIO_URL}/api/admin/presets/{preset_id}/run",
                headers=HEADERS,
                files=files,
                data=form_data,
            )
            r.raise_for_status()
            result = r.json()

        prompt_id = result["prompt_id"]
        seeds = result.get("seeds", {})
        seed_info = ", ".join(f"{k}={v}" for k, v in seeds.items()) if seeds else "random"

        await status_msg.edit_text(
            f"🚀 *Job queued*\n"
            f"ID: `{prompt_id[:12]}...`\n"
            f"Seed: {seed_info}\n\n"
            f"⏳ Waiting for completion...",
            parse_mode="Markdown",
        )

        # Poll progress
        last_percent = -1
        for i in range(180):  # max 30 min (180 × 10s)
            await asyncio.sleep(10)

            try:
                status = await studio_get(f"/api/run/status/{prompt_id}")
            except Exception:
                continue

            st = status.get("status", "pending")
            percent = status.get("percent", 0)
            node = status.get("node_title", "")
            eta = status.get("eta_seconds")

            # Queued — waiting for execution slot
            if st in ("queued", "pending"):
                if last_percent != -2:
                    last_percent = -2
                    try:
                        await status_msg.edit_text("⏳ *In coda* — waiting for execution slot...", parse_mode="Markdown")
                    except Exception:
                        pass
                continue

            if st == "completed":
                # Get result
                outputs = status.get("outputs", {})
                out = outputs.get("video") or outputs.get("image")

                if out:
                    url = (
                        f"/api/comfyui/view?filename={out['filename']}"
                        f"&type={out.get('type', 'output')}"
                        f"&subfolder={out.get('subfolder', '')}"
                    )
                    file_bytes = await studio_get_bytes(url)

                    await status_msg.edit_text("✅ *Done!* Sending result...", parse_mode="Markdown")

                    if out["filename"].endswith((".mp4", ".webm")):
                        await status_msg.reply_video(
                            video=io.BytesIO(file_bytes),
                            filename=out["filename"],
                            caption=f"Preset: {preset.get('name', '?')}\nSeed: {seed_info}",
                        )
                    else:
                        await status_msg.reply_photo(
                            photo=io.BytesIO(file_bytes),
                            filename=out["filename"],
                            caption=f"Preset: {preset.get('name', '?')}\nSeed: {seed_info}",
                        )
                else:
                    await status_msg.edit_text("✅ *Completed* but no output found.", parse_mode="Markdown")

                context.user_data.clear()
                return

            if st in ("failed", "stalled", "error"):
                await status_msg.edit_text(
                    f"❌ *Job {st}*\n{status.get('error', 'Unknown error')}",
                    parse_mode="Markdown",
                )
                context.user_data.clear()
                return

            # Update progress (only if changed)
            if percent != last_percent:
                last_percent = percent
                if percent == 0 and not node:
                    text = "⏳ *Loading models...*"
                else:
                    eta_str = f"{eta}s" if eta else "?"
                    text = (
                        f"⏳ *Running* — {percent}%\n"
                        f"Node: {node}\n"
                        f"ETA: {eta_str}"
                    )
                try:
                    await status_msg.edit_text(text, parse_mode="Markdown")
                except Exception:
                    pass  # "message is not modified" error

        await status_msg.edit_text("⚠️ *Timeout* — job took too long.", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Job failed: {e}")
        try:
            await status_msg.edit_text(f"❌ *Error:* {str(e)[:200]}", parse_mode="Markdown")
        except Exception:
            pass

    context.user_data.clear()


# ── Bot lifecycle ──

_bot_app = None
_bot_thread = None
_bot_started_at = None

def bot_running() -> bool:
    return _bot_thread is not None and _bot_thread.is_alive()

def bot_status() -> dict:
    return {
        "running": bot_running(),
        "name": os.environ.get("TELEGRAM_BOT_NAME", ""),
        "started_at": _bot_started_at,
    }

def start_bot() -> str:
    global _bot_app, _bot_thread, _bot_started_at, BOT_TOKEN

    if bot_running():
        return "already running"

    resolved_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not resolved_token:
        return "no token configured"

    BOT_TOKEN = resolved_token

    import threading

    def _run():
        global _bot_app, _bot_started_at
        from datetime import datetime, timezone, timedelta
        _bot_started_at = datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            _bot_app = Application.builder().token(BOT_TOKEN).build()
            _bot_app.add_handler(CommandHandler("start", cmd_start))
            _bot_app.add_handler(CommandHandler("presets", cmd_start))
            _bot_app.add_handler(CallbackQueryHandler(cb_preset_selected))
            _bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
            _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
            logger.info(f"Bot starting — Studio: {STUDIO_URL}")

            # Manual polling — run_polling() requires main thread
            async def _poll():
                await _bot_app.initialize()
                await _bot_app.start()
                await _bot_app.updater.start_polling()
                # Keep running until stopped
                while _bot_app and _bot_started_at:
                    await asyncio.sleep(1)
                await _bot_app.updater.stop()
                await _bot_app.stop()
                await _bot_app.shutdown()

            loop.run_until_complete(_poll())
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
        finally:
            _bot_app = None
            _bot_started_at = None

    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()
    return "started"

def stop_bot() -> str:
    global _bot_app, _bot_thread, _bot_started_at
    if not bot_running():
        return "not running"
    try:
        if _bot_app:
            _bot_app.stop_running()
    except Exception as e:
        logger.error(f"Error stopping bot: {e}")
    _bot_started_at = None
    return "stopped"


# ── Auto-start on import ──

def auto_start():
    """Start bot if TELEGRAM_BOT_TOKEN env var is set. Called from backend startup."""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        start_bot()


# ── Standalone mode ──

if __name__ == "__main__":
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("Set TELEGRAM_BOT_TOKEN env var or configure from Settings UI.")
    else:
        BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CallbackQueryHandler(cb_preset_selected))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        logger.info(f"Bot starting — Studio: {STUDIO_URL}")
        app.run_polling()
