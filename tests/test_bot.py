"""Offline tests: search, word cards, links, pictures, and the Telegram answers.

Run from the bot folder:  python3 -m unittest discover tests -v
Uses tests/sample.csv (118 real rows of the sheet) and canned Wiktionary answers.
"""
import asyncio
import html.parser
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("TELEGRAM_TOKEN", "")

from dictionary import Dictionary, norm, terms  # noqa: E402
from replies import Reply, Responder, parse_command, visible_length  # noqa: E402
from wiktionary import ImageFinder, page_title, split_cell, word_url  # noqa: E402

SITE = "https://gleb.onl/neolatino/"
DICT = Dictionary.from_csv((HERE / "sample.csv").read_text(encoding="utf-8"))


class FakeImages(ImageFinder):
    """en.wiktionary answers for a few pages, as the real API returns them (formatversion=2)."""

    PAGES = {
        "house": ["Wikidata_lexemes_logo_symbol_square.svg", "en-us-house-noun.ogg",
                  "Niigata_NCM_Peasant_Rice_Farmers_House.jpg", "Wikipedia-logo.svg"],
        "dog": ["YellowLabradorLooking.jpg", "En-uk-dog.ogg"],
        "take": ["En-uk-to_take.ogg", "En-us-take.ogg"],
        "here": ["En-uk-here.ogg"],
    }

    def __init__(self):
        super().__init__(session=None)
        self.calls = []

    async def _get(self, params):
        self.calls.append(params)
        if params["action"] == "parse":
            if params["page"] not in self.PAGES:
                raise RuntimeError("missingtitle")
            return {"parse": {"title": params["page"], "images": self.PAGES[params["page"]]}}
        name = params["titles"][5:]
        return {"query": {"pages": [{"title": params["titles"], "imageinfo": [
            {"url": f"https://upload.wikimedia.org/x/{name}", "thumburl": f"https://thumb.wikimedia.org/x/800px-{name}"}]}]}}


def run(coro):
    return asyncio.run(coro)


class TagChecker(html.parser.HTMLParser):
    """Telegram rejects messages with unclosed or unknown tags."""
    ALLOWED = {"b", "i", "a", "code", "pre", "u", "s", "blockquote"}

    def __init__(self):
        super().__init__()
        self.stack, self.bad = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED:
            self.bad.append(tag)
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.bad.append("/" + tag)


def valid_html(text):
    checker = TagChecker()
    checker.feed(text)
    checker.close()
    return not checker.bad and not checker.stack


class DictionaryTest(unittest.TestCase):
    def test_loads_the_sheet(self):
        self.assertEqual(len(DICT), 118, "the row of totals under the header is not a word")
        self.assertEqual(DICT.by_id["1900"].word, "casa")
        self.assertEqual(DICT.by_id["1900"].themes, ["casa", "casa"])

    def test_normalization(self):
        self.assertEqual(norm("Prèndere"), "prendere")
        self.assertEqual(norm("parabla*"), "parabla")
        self.assertEqual(terms("(ac)collí"), ["accolli", "colli"])
        self.assertEqual(terms("colar, pegar"), ["colar", "pegar"])

    def test_search_one_language(self):
        ids = [m.entry.id for m in DICT.search("casa", "es")]
        self.assertEqual(set(ids[:3]), {"1900", "11913", "11912"})
        self.assertEqual(ids[0], "1900", "essential words first")

    def test_search_neolatino(self):
        self.assertEqual([m.entry.id for m in DICT.search("casa", "neo")], ["1900"])
        self.assertEqual([m.entry.id for m in DICT.search("prendere", "neo")], ["8932"], "accents don't matter")
        self.assertIn("2284", [m.entry.id for m in DICT.search("accolli", "neo")])

    def test_search_every_language(self):
        ids = {m.entry.id for m in DICT.search("house") if m.score == 0}
        self.assertEqual(ids, {"1900", "11913", "11912"})

    def test_english_to(self):
        self.assertIn("8932", [m.entry.id for m in DICT.search("to take", "en")])

    def test_starts_with_and_contains(self):
        self.assertIn("8932", [m.entry.id for m in DICT.search("prèn", "neo")])
        self.assertEqual(DICT.search("ndar", "neo"), [])
        self.assertIn("683", [m.entry.id for m in DICT.search("ndar", "neo", contains=True)])

    def test_suggestions(self):
        self.assertIn("casa", DICT.suggest("casaa", "es"))
        self.assertIn("perro", DICT.suggest("pero", "es"))


class LinkTest(unittest.TestCase):
    def test_split_cells(self):
        self.assertEqual(split_cell("colar, pegar"), (["colar", "pegar"], ", "))
        self.assertEqual(split_cell("melingiana/melinzana"), (["melingiana", "melinzana"], " / "))
        self.assertEqual(split_cell("a/in/dae cuddae"), (["a/in/dae cuddae"], ""))

    def test_page_titles(self):
        self.assertEqual(page_title("Aici", "ro"), "aici", "common words start lower case")
        self.assertEqual(page_title("afganistán", "es", proper=True), "Afganistán", "names are capitalized")
        self.assertEqual(page_title("to strip", "en"), "strip")
        self.assertEqual(page_title("y avoir ", "fr"), "y avoir")

    def test_urls(self):
        self.assertEqual(word_url("casă", "ro"), "https://ro.wiktionary.org/wiki/cas%C4%83")
        self.assertEqual(word_url("cap d'any", "ca"), "https://ca.wiktionary.org/wiki/cap_d'any")
        self.assertEqual(word_url("veliky gråd", "isv"), "https://interslavic.forum/slovnik/?text=veliky%20gr%C3%A5d&lang=isv-en")
        self.assertIsNone(word_url("casa", None))


class ReplyTest(unittest.TestCase):
    def responder(self, images=True):
        return Responder(DICT, SITE, FakeImages() if images else None)

    def test_card(self):
        card = self.responder().card(DICT.by_id["1900"], matched_col=3)
        self.assertTrue(valid_html(card), card)
        self.assertIn('<a href="https://gleb.onl/neolatino/#/word/1900">casa</a>', card)
        self.assertIn('<a href="https://pt.wiktionary.org/wiki/casa">casa</a>', card)
        self.assertIn('<a href="https://ro.wiktionary.org/wiki/cas%C4%83">casă</a>', card)
        self.assertIn('<a href="https://sc.wiktionary.org/wiki/domo">domo</a>', card)
        self.assertIn('<a href="https://interslavic.forum/slovnik/?text=dom&amp;lang=isv-en">dom</a>', card)
        self.assertIn("<code>fol</code> hem", card, "Folkspraak has no Wiktionary: plain text")
        self.assertIn("<b><code>es</code>", card, "the language searched is bold")
        self.assertIn("/id_1900", card)
        self.assertIn("ess.", card)

    def test_card_for_a_verb_and_a_name(self):
        verb = self.responder().card(DICT.by_id["8932"])
        self.assertIn("#/verb/pr%C3%A8ndere", verb)
        name = self.responder().card(DICT.by_id["399"])
        self.assertIn("https://es.wiktionary.org/wiki/Afganist%C3%A1n", name)
        self.assertIn("https://en.wiktionary.org/wiki/Afghanistan", name)
        two = self.responder().card(DICT.by_id["10649"])
        self.assertIn('wiki/strip">to strip</a>, <a href="https://en.wiktionary.org/wiki/undress">undress</a>', two)

    def test_search_with_picture(self):
        replies = run(self.responder().search("cane", "it"))
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].photo, "https://thumb.wikimedia.org/x/800px-YellowLabradorLooking.jpg")
        self.assertIn("cane", replies[0].text)
        self.assertLessEqual(visible_length(replies[0].text), 1024)

    def test_picture_skips_logos_and_sounds(self):
        replies = run(self.responder().search("casa", "neo"))
        self.assertEqual(replies[0].photo, "https://thumb.wikimedia.org/x/800px-Niigata_NCM_Peasant_Rice_Farmers_House.jpg")

    def test_same_picture_once(self):
        replies = run(self.responder().search("casa", "es"))
        photos = [r.photo for r in replies if r.photo]
        self.assertEqual(len(replies), 3)
        self.assertEqual(len(photos), 1, "three 'house' cards, one picture")

    def test_no_picture(self):
        replies = run(self.responder().search("prèndere", "neo"))
        self.assertEqual(len(replies), 1)
        self.assertIsNone(replies[0].photo)

    def test_pictures_are_cached(self):
        responder = self.responder()
        run(responder.search("cane", "it"))
        calls = len(responder.images.calls)
        run(responder.search("cane", "it"))
        self.assertEqual(len(responder.images.calls), calls)

    def test_many_results_become_a_list(self):
        replies = run(self.responder().search("here", "en"))
        self.assertEqual(len(replies), 1)
        text = replies[0].text
        self.assertTrue(valid_html(text), text)
        self.assertIn("6 resultados", text)
        self.assertIn("/id_145", text)
        self.assertIn("#/?q=here&amp;l=eng", text)

    def test_not_found_suggests(self):
        text = run(self.responder().search("casaa", "es"))[0].text
        self.assertTrue(valid_html(text), text)
        self.assertIn("Non se han tropato coincidèntias", text)
        self.assertIn("<code>/es casa</code>", text)

    def test_empty_query(self):
        self.assertIn("/es casa", run(self.responder().search("", "es"))[0].text)

    def test_by_id(self):
        replies = run(self.responder().by_id("1758"))
        self.assertIn("cane", replies[0].text)
        self.assertIn("Non se han", run(self.responder().by_id("999999"))[0].text)

    def test_every_card_is_valid_telegram_html(self):
        responder = self.responder(images=False)
        for entry in DICT.entries:
            card = responder.card(entry, 3)
            self.assertTrue(valid_html(card), card)
            self.assertLess(len(card), 4096)

    def test_help(self):
        text = self.responder().help()
        self.assertTrue(valid_html(text), text)
        self.assertIn("/sc Sardo", text)


class CommandTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_command("/es casa"), ("es", "casa"))
        self.assertEqual(parse_command("/es@NeolatinoBot casa grande"), ("es", "casa grande"))
        self.assertEqual(parse_command("/id_1900"), ("id", "1900"))
        self.assertEqual(parse_command("/id 1900"), ("id", "1900"))
        self.assertEqual(parse_command("/ID_1900@NeolatinoBot"), ("id", "1900"))
        self.assertEqual(parse_command("casa"), (None, "casa"))


class TelegramFlowTest(unittest.TestCase):
    """bot.answer / bot.send with a fake Telegram."""

    def setUp(self):
        import bot
        self.bot = bot
        bot.state.responder = Responder(DICT, SITE, FakeImages())
        self.sent = []

        async def send_message(chat_id, text, **kw):
            self.sent.append(("text", text, kw))

        async def send_photo(chat_id, photo, caption=None, **kw):
            if isinstance(photo, str) and "fail" in photo:
                raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
            self.sent.append(("photo", photo, caption, kw))

        bot.bot.send_message = send_message
        bot.bot.send_photo = send_photo

    def message(self, text, chat="private"):
        return SimpleNamespace(text=text, chat=SimpleNamespace(id=1, type=chat), message_id=7,
                               from_user=SimpleNamespace(id=5), is_topic_message=False, message_thread_id=None)

    def test_private_plain_text_searches_everything(self):
        replies = run(self.bot.answer(self.message("perro")))
        self.assertIn("cane", replies[0].text)

    def test_groups_only_answer_commands(self):
        self.assertEqual(run(self.bot.answer(self.message("perro", "group"))), [])
        self.assertEqual(run(self.bot.answer(self.message("/ban someone", "group"))), [])
        self.assertTrue(run(self.bot.answer(self.message("/es@NeolatinoBot perro", "group"))))

    def test_help_and_id(self):
        self.assertIn("Lenguas", run(self.bot.answer(self.message("/start")))[0].text)
        self.assertIn("cane", run(self.bot.answer(self.message("/id_1758")))[0].text)

    def test_photo_with_caption_and_reply(self):
        run(self.bot.send(self.message("/it cane"), run(self.bot.answer(self.message("/it cane")))))
        kind, photo, caption, kw = self.sent[0]
        self.assertEqual(kind, "photo")
        self.assertIn("cane", caption)
        self.assertEqual(kw["parse_mode"], "HTML")
        self.assertEqual(kw["reply_parameters"].message_id, 7)

    def test_picture_that_telegram_refuses(self):
        async def no_download(url):
            return None
        self.bot.download_picture = no_download
        run(self.bot.send(self.message("x"), [Reply("<b>text</b>", "https://fail.example/x.jpg")]))
        self.assertEqual(self.sent, [("text", "<b>text</b>", self.sent[0][2])])
        self.assertTrue(self.sent[0][2]["link_preview_options"].is_disabled)

    def test_picture_uploaded_when_the_link_fails(self):
        async def download(url):
            return b"\xff\xd8jpeg-bytes"
        self.bot.download_picture = download
        run(self.bot.send(self.message("x"), [Reply("<b>text</b>", "https://fail.example/x.jpg")]))
        self.assertEqual(self.sent[0][0], "photo")
        self.assertEqual(self.sent[0][1], b"\xff\xd8jpeg-bytes")
        self.assertEqual(self.sent[0][2], "<b>text</b>")

    def test_romanian_verb_page(self):
        from wiktionary import page_title
        self.assertEqual(page_title("a lua", "ro"), "lua")


if __name__ == "__main__":
    unittest.main()
