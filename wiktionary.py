"""Links to Wiktionary and the picture of a word.

Every word of a natural language links to the Wiktionary in that language
(pt.wiktionary.org for Portuguese, es.wiktionary.org for Spanish …).
Interslavic words open in the Interslavic dictionary. The picture is the first
photo of the English word's page on en.wiktionary.org, as in the Interslavic bot.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse

log = logging.getLogger(__name__)

USER_AGENT = "NeolatinoBot/1.0 (https://gleb.onl/neolatino; Telegram dictionary bot)"
ISV_DICTIONARY = "https://interslavic.forum/slovnik/?text={word}&lang=isv-en"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")
SKIP_IMAGE = re.compile(r"logo|icon|symbol|wiki|commons|disambig|question|loudspeaker|speaker|lock-|nuvola", re.I)


def split_cell(value: str) -> tuple[list[str], str]:
    """The words of a cell and the separator to show between them.

    "colar, pegar" → [colar, pegar]; Sardinian "melingiana/melinzana" → two words,
    but "a/in/dae cuddae" (alternatives inside a phrase) stays one.
    """
    value = (value or "").strip()
    if ";" in value:
        return [p.strip() for p in value.split(";") if p.strip()], "; "
    if "," in value:
        return [p.strip() for p in value.split(",") if p.strip()], ", "
    if "/" in value and " " not in value:
        return [p.strip() for p in value.split("/") if p.strip()], " / "
    return ([value] if value else []), ""


def page_title(word: str, lang: str, proper: bool = False) -> str:
    """The Wiktionary page of a word as the dictionary writes it."""
    title = word.replace("*", "")
    title = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", title) if not title.startswith("(") else title.replace("(", "").replace(")", "")
    title = re.sub(r"\s+", " ", title).strip(" .;:")
    if lang == "en":
        title = re.sub(r"^to\s+", "", title)  # "to take" → take
    if lang == "ro":
        title = re.sub(r"^a\s+(?=\S)", "", title)  # "a lua" → lua
    if not title:
        return ""
    # page names are case-sensitive: common words lower case, names capitalized
    first = title[0].upper() if proper else title[0].lower()
    return first + title[1:]


def word_url(word: str, wiki: str | None, proper: bool = False) -> str | None:
    if not wiki:
        return None
    if wiki == "isv":
        clean = re.sub(r"\s*\([^)]*\)", "", word.replace("*", "")).strip()
        return ISV_DICTIONARY.format(word=urllib.parse.quote(clean)) if clean else None
    title = page_title(word, wiki, proper)
    if not title:
        return None
    return f"https://{wiki}.wiktionary.org/wiki/{urllib.parse.quote(title.replace(' ', '_'), safe=chr(39))}"


class ImageFinder:
    """First photo on an English Wiktionary page (cached, so a word is looked up once a day)."""

    def __init__(self, session, ttl: float = 24 * 3600, timeout: float = 8):
        self.session = session  # aiohttp.ClientSession
        self.ttl = ttl
        self.timeout = timeout
        self.cache: dict[str, tuple[float, str | None]] = {}

    async def _get(self, params: dict) -> dict:
        import aiohttp

        params = {"format": "json", "formatversion": "2", **params}
        async with self.session.get(
            "https://en.wiktionary.org/w/api.php",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def first_image(self, word: str) -> str | None:
        title = page_title(word, "en")
        if not title:
            return None
        cached = self.cache.get(title)
        if cached and time.time() - cached[0] < self.ttl:
            return cached[1]
        url = None
        try:
            url = await self._lookup(title)
        except (asyncio.TimeoutError, Exception) as error:  # a missing picture is never an error for the user
            log.info("no picture for %r: %s", title, error)
        self.cache[title] = (time.time(), url)
        return url

    async def _lookup(self, title: str) -> str | None:
        data = await self._get({"action": "parse", "page": title, "prop": "images", "redirects": "1"})
        files = data.get("parse", {}).get("images", []) or []
        photos = [f for f in files if f.lower().endswith(IMAGE_EXT) and not SKIP_IMAGE.search(f)]
        if not photos:
            return None
        info = await self._get({
            "action": "query",
            "titles": f"File:{photos[0]}",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "800",  # a smaller copy: Telegram refuses photos above 5 MB by link
        })
        pages = info.get("query", {}).get("pages", []) or []
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            for image in page.get("imageinfo", []) or []:
                return image.get("thumburl") or image.get("url")
        return None
