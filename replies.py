"""What the bot answers: word cards, lists, help — as Telegram HTML.

Kept apart from the Telegram code so it can be tested without a bot token.
The Neolatino texts reuse the website's wording; a fluent speaker should
still read them (see TEXT below).
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from dictionary import BY_CODE, COMMANDS, EN, LANGS, NEO, Dictionary, Entry, Match
from wiktionary import ImageFinder, split_cell, word_url

CARDS_AT_MOST = 3  # more matches than this → a list with /id_… links
LIST_AT_MOST = 15
CAPTION_LIMIT = 1024  # Telegram's limit for a photo caption

TEXT = {
    "results": lambda n: "1 resultato" if n == 1 else f"{n:,} resultados".replace(",", "."),
    "no_results": "Non se han tropato coincidèntias",
    "try": "Pròva:",
    "conjugation": "Conjugatione",
    "dictionary": "Dictionario Neolatino",
    "search": "Cercare",
    "languages": "Lenguas",
    "updating": "Actualizzando…",
    "updated": lambda n: f"Dictionario actualizzato: {n:,} paraulas.".replace(",", "."),
    "update_failed": "Non se ha potuto carrecare lo dictionario.",
    "not_loaded": "Carrecando lo dictionario…",
    "error": "Errore.",
    "by_id": "una paraula per ID",
    "essential": "ess.",
    "basic": "bàs.",
}


@dataclass
class Reply:
    text: str
    photo: str | None = None  # a picture to send with (or before) the text


def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def attr(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def visible_length(markup: str) -> int:
    """Length of the text Telegram shows (tags removed, entities decoded)."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", markup)))


class Responder:
    def __init__(self, dictionary: Dictionary | None, site: str, images: ImageFinder | None = None):
        self.dictionary = dictionary
        self.site = site if site.endswith("/") else site + "/"
        self.images = images

    # ── links ────────────────────────────────────────────────────
    def word_link(self, entry: Entry) -> str:
        return f"{self.site}#/word/{urllib.parse.quote(entry.id)}"

    def search_link(self, text: str, code: str | None) -> str:
        if code == "neo":
            params = {"q": text, "d": "nl", "l": "eng"}
        else:
            params = {"q": text, "l": BY_CODE[code].site if code else "all"}
        return f"{self.site}#/?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"

    def linked_words(self, value: str, wiki: str | None, proper: bool) -> str:
        parts, sep = split_cell(value)
        out = []
        for part in parts:
            url = word_url(part, wiki, proper)
            out.append(f'<a href="{attr(url)}">{esc(part)}</a>' if url else esc(part))
        return esc(sep).join(out)

    # ── one word ─────────────────────────────────────────────────
    def card(self, entry: Entry, matched_col: int | None = None) -> str:
        badges = [TEXT["essential"]] if entry.ess else ([TEXT["basic"]] if entry.bas else [])
        head = f'<b><a href="{attr(self.word_link(entry))}">{esc(entry.word)}</a></b>'
        meta = " · ".join(filter(None, [f"<i>{esc(entry.cat)}</i>" if entry.cat else "", *badges]))
        lines = [f"{head}  {meta}".strip()]
        if entry.themes:
            lines.append(f"<i>{esc(' › '.join(entry.themes))}</i>")
        lines.append("")
        for i, lang in enumerate(LANGS):
            if i == NEO or not entry.v[i]:
                continue
            words = self.linked_words(entry.v[i], lang.wiki, entry.proper)
            row = f"<code>{lang.code}</code> {words}"
            lines.append(f"<b>{row}</b>" if i == matched_col else row)
        lines.append("")
        footer = [f"/id_{entry.id}"]
        if entry.is_verb:
            verb = urllib.parse.quote(re.sub(r"\s*\([^)]*\)", "", entry.word.split(",")[0]).strip())
            footer.insert(0, f'📝 <a href="{attr(self.site)}#/verb/{verb}">{TEXT["conjugation"]}</a>')
        lines.append("  ·  ".join(footer))
        return "\n".join(lines)

    async def card_reply(self, entry: Entry, matched_col: int | None, sent_photos: set[str]) -> list[Reply]:
        text = self.card(entry, matched_col)
        photo = None
        if self.images and entry.v[EN]:
            words, _ = split_cell(entry.v[EN])
            photo = await self.images.first_image(words[0]) if words else None
        if not photo or photo in sent_photos:  # the same picture once per answer
            return [Reply(text)]
        sent_photos.add(photo)
        if visible_length(text) <= CAPTION_LIMIT:
            return [Reply(text, photo)]
        return [Reply("", photo), Reply(text)]

    # ── many words ───────────────────────────────────────────────
    def word_list(self, matches: list[Match], query: str, code: str | None) -> str:
        lines = [f"<b>{esc(TEXT['results'](len(matches)))}</b>"]
        for m in matches[:LIST_AT_MOST]:
            e = m.entry
            gloss_col = m.col if m.col != NEO else (EN if e.v[EN] else NEO)
            gloss = f" — {esc(e.v[gloss_col])}" if gloss_col != NEO else ""
            lines.append(f'• <a href="{attr(self.word_link(e))}">{esc(e.word)}</a> <i>{esc(e.cat)}</i>{gloss}  /id_{e.id}')
        if len(matches) > LIST_AT_MOST:
            lines.append("…")
        lines.append("")
        lines.append(f'🔎 <a href="{attr(self.search_link(query, code))}">{TEXT["dictionary"]}</a>')
        return "\n".join(lines)

    # ── answers ──────────────────────────────────────────────────
    async def search(self, query: str, code: str | None) -> list[Reply]:
        """/es casa, /neo casa, or plain text (code=None: every language)."""
        query = query.strip()
        if not self.dictionary:
            return [Reply(esc(TEXT["not_loaded"]))]
        if not query:
            example = f"/{code} casa" if code else "/es casa"
            return [Reply(f"{TEXT['try']} <code>{esc(example)}</code>")]
        matches = self.dictionary.search(query, code)
        if not matches:
            matches = self.dictionary.search(query, code, contains=True)
        if not matches:
            return [Reply(self.not_found(query, code))]
        exact = [m for m in matches if m.score == 0]
        show = exact if 0 < len(exact) <= CARDS_AT_MOST else (matches if len(matches) <= CARDS_AT_MOST else [])
        if not show:
            return [Reply(self.word_list(matches, query, code))]
        replies: list[Reply] = []
        photos: set[str] = set()
        for m in show:
            replies += await self.card_reply(m.entry, m.col, photos)
        others = [m for m in matches if m not in show]
        if others:
            replies.append(Reply(self.word_list(others, query, code)))
        return replies

    def not_found(self, query: str, code: str | None) -> str:
        text = f"{TEXT['no_results']}: «{esc(query)}»."
        ideas = self.dictionary.suggest(query, code) if self.dictionary else []
        if ideas:
            command = f"/{code} " if code else ""
            text += f"\n{TEXT['try']} " + ", ".join(f"<code>{esc(command + idea)}</code>" for idea in ideas)
        text += f'\n\n🔎 <a href="{attr(self.search_link(query, code))}">{TEXT["dictionary"]}</a>'
        return text

    async def by_id(self, word_id: str) -> list[Reply]:
        if not self.dictionary:
            return [Reply(esc(TEXT["not_loaded"]))]
        word_id = word_id.strip()
        entry = self.dictionary.by_id.get(word_id)
        if not entry:
            return [Reply(f"{TEXT['no_results']}: <code>/id {esc(word_id) or '…'}</code>")]
        return await self.card_reply(entry, None, set())

    def help(self) -> str:
        langs = " · ".join(f"/{lang.code} {esc(lang.name)}" for lang in LANGS)
        return "\n".join([
            f'<b>{TEXT["dictionary"]}</b> 🤖',
            "",
            f"<b>{TEXT['search']}</b>",
            "<code>/es casa</code> — Castellano → Neolatino",
            "<code>/en house</code> — Anglese → Neolatino",
            "<code>/neo casa</code> — Neolatino",
            f"<code>/id 1900</code> — {TEXT['by_id']}",
            "",
            f"<b>{TEXT['languages']}</b>",
            langs,
            "",
            f'🌐 <a href="{attr(self.site)}">{TEXT["dictionary"]}</a>',
            "",
            "<i>Write a word in a private chat to search every language at once, or use a language "
            "command (in groups too). The words link to Wiktionary in their own language; the picture "
            "comes from English Wiktionary.</i>",
        ])


def parse_command(text: str) -> tuple[str | None, str]:
    """'/es@NeolatinoBot casa' → ('es', 'casa'); '/id_1900' → ('id', '1900'); plain text → (None, text)."""
    text = (text or "").strip()
    match = re.match(r"^/([A-Za-z0-9_]+)(?:@\w+)?(?:\s+(.*))?$", text, re.S)
    if not match:
        return None, text
    command, rest = match.group(1).lower(), (match.group(2) or "").strip()
    id_form = re.match(r"^id_?(\d+)$", command)
    if id_form:
        return "id", id_form.group(1)
    return command, rest


def language_of(command: str | None) -> str | None:
    return COMMANDS.get(command or "")
