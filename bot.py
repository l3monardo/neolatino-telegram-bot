"""Dictionario Neolatino — Telegram bot.

Like the Interslavic Slovnik-bot: "/es casa" answers with the word's table from
the dictionary, every word linked to the Wiktionary of its language, and the
picture of the word when English Wiktionary has one.

Run:  python3 bot.py   (settings in .env — see .env.example)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from telebot import types
from telebot.async_telebot import AsyncTeleBot

from dictionary import LANGS, Dictionary
from replies import TEXT, Reply, Responder, esc, language_of, parse_command
from wiktionary import USER_AGENT, ImageFinder

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("neolatino-bot")

SHEET_CSV = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vSGCRUv8z5VSCk7lBy_4gtH2PkFvMH5ny65qauUmYzqWinGEw23IAQT_1seyBGfqw"
             "/pub?gid=1315031947&single=true&output=csv")
TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
SITE_URL = os.getenv("SITE_URL", "https://gleb.onl/neolatino/").strip()
SHEET_URL = os.getenv("SHEET_CSV_URL", SHEET_CSV).strip()
REFRESH_HOURS = float(os.getenv("REFRESH_HOURS", "12"))
CACHE_FILE = Path(os.getenv("CACHE_FILE", Path(__file__).with_name("dictionario.csv")))
# who may run /actualizzare (Telegram user ids, comma-separated); empty = everyone, at most once in 5 minutes
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}

HELP_COMMANDS = {"start", "help", "auxilio", "adjuto"}
UPDATE_COMMANDS = {"actualizzare", "update", "obnovi"}


class State:
    responder: Responder
    session: aiohttp.ClientSession | None = None
    last_update = 0.0


state = State()
state.responder = Responder(None, SITE_URL)


# ── the dictionary ───────────────────────────────────────────────
async def download_sheet(session: aiohttp.ClientSession) -> str:
    async with session.get(SHEET_URL, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=60)) as response:
        response.raise_for_status()
        return await response.text(encoding="utf-8")


async def load_dictionary(download: bool = True) -> Dictionary:
    """The sheet from Google (saved to CACHE_FILE); the saved copy when Google can't be reached."""
    if download and state.session:
        try:
            text = await download_sheet(state.session)
            dictionary = Dictionary.from_csv(text)
            CACHE_FILE.write_text(text, encoding="utf-8")
            log.info("dictionary downloaded: %d words", len(dictionary))
            return dictionary
        except Exception as error:
            log.warning("couldn't download the sheet (%s), using the saved copy", error)
    if not CACHE_FILE.exists():
        raise RuntimeError(f"couldn't download the sheet from {SHEET_URL} and there is no saved copy yet")
    dictionary = Dictionary.from_csv(CACHE_FILE.read_text(encoding="utf-8"))
    log.info("dictionary from %s: %d words", CACHE_FILE, len(dictionary))
    return dictionary


async def refresh_forever() -> None:
    while True:
        await asyncio.sleep(REFRESH_HOURS * 3600)
        try:
            state.responder.dictionary = await load_dictionary()
        except Exception as error:
            log.error("refresh failed: %s", error)


# ── Telegram ─────────────────────────────────────────────────────
bot = AsyncTeleBot(TOKEN or "0:not-set")


async def send(message: types.Message, replies: list[Reply]) -> None:
    reply_to = types.ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True)
    thread = message.message_thread_id if getattr(message, "is_topic_message", False) else None
    for item in replies:
        if item.photo and await send_picture(message, item, reply_to, thread):
            continue
        if not item.text:  # the picture didn't go out and there is nothing else to say
            continue
        await bot.send_message(message.chat.id, item.text, parse_mode="HTML",
                               link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                               reply_parameters=reply_to, message_thread_id=thread)


async def send_picture(message: types.Message, item: Reply, reply_to, thread) -> bool:
    """The picture with the word card as its caption. By link first; when Telegram can't fetch
    the link itself, the bot downloads the picture and uploads it. False → send the text alone."""
    for attempt in ("link", "upload"):
        photo = item.photo if attempt == "link" else await download_picture(item.photo)
        if photo is None:
            return False
        try:
            await bot.send_photo(message.chat.id, photo, caption=item.text or None, parse_mode="HTML",
                                 reply_parameters=reply_to, message_thread_id=thread)
            return True
        except Exception as error:
            log.info("picture not sent by %s (%s): %s", attempt, item.photo, error)
    return False


async def download_picture(url: str) -> bytes | None:
    if not state.session:
        return None
    try:
        async with state.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            data = await response.content.read(10 * 1024 * 1024 + 1)
            return data if 0 < len(data) <= 10 * 1024 * 1024 else None
    except Exception as error:
        log.info("picture download failed (%s): %s", url, error)
        return None


async def update_command(message: types.Message) -> list[Reply]:
    user = message.from_user.id if message.from_user else 0
    if ADMIN_IDS and user not in ADMIN_IDS:
        return []
    if not ADMIN_IDS and time.time() - state.last_update < 300:
        return [Reply(esc(TEXT["updated"](len(state.responder.dictionary or []))))]
    state.last_update = time.time()
    await send(message, [Reply(esc(TEXT["updating"]))])
    try:
        state.responder.dictionary = await load_dictionary()
        return [Reply(esc(TEXT["updated"](len(state.responder.dictionary))))]
    except Exception as error:
        log.error("update failed: %s", error)
        return [Reply(esc(TEXT["update_failed"]))]


async def answer(message: types.Message) -> list[Reply]:
    """Every text message: language commands, /id, /help, and plain words in private chats."""
    command, rest = parse_command(message.text or "")
    private = message.chat.type == "private"
    responder = state.responder
    if command is None:
        return await responder.search(rest, None) if private and rest else []
    if command in HELP_COMMANDS:
        return [Reply(responder.help())]
    if command == "id":
        return await responder.by_id(rest)
    if command in UPDATE_COMMANDS:
        return await update_command(message)
    code = language_of(command)
    if code:
        return await responder.search(rest, code)
    return [Reply(responder.help())] if private else []  # in groups, other bots' commands are not ours


@bot.message_handler(content_types=["text"])
async def on_text(message: types.Message) -> None:
    try:
        command, rest = parse_command(message.text or "")
        if command is not None or message.chat.type == "private":
            await bot.send_chat_action(message.chat.id, "typing")
        await send(message, await answer(message))
    except Exception:
        log.exception("failed to answer %r", message.text)
        try:
            await send(message, [Reply(esc(TEXT["error"]))])
        except Exception:
            pass


async def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_TOKEN is missing: copy .env.example to .env and put the token from @BotFather there.")
    state.session = aiohttp.ClientSession()
    state.responder = Responder(None, SITE_URL, ImageFinder(state.session))
    state.responder.dictionary = await load_dictionary()
    commands = [types.BotCommand("help", "Dictionario Neolatino — help")]
    commands += [types.BotCommand(lang.code, f"{lang.name} → Neolatino" if lang.code != "neo" else "Neolatino") for lang in LANGS]
    commands.append(types.BotCommand("id", "Paraula per ID"))
    try:
        await bot.set_my_commands(commands)
    except Exception as error:
        log.warning("couldn't set the command menu: %s", error)
    asyncio.create_task(refresh_forever())
    log.info("bot is running (%s)", SITE_URL)
    try:
        await bot.delete_webhook()
        await bot.infinity_polling(timeout=30, skip_pending=True)
    finally:
        await state.session.close()


if __name__ == "__main__":
    asyncio.run(main())
