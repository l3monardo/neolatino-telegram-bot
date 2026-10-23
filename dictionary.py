"""Dictionario Neolatino — the word list and the search.

Reads the same public Google Sheet as the website (gleb.onl/neolatino) and
searches it the same way: accents and case don't matter, whole words first,
then words that start with what was typed, then words that contain it.
"""
from __future__ import annotations

import csv
import difflib
import io
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Lang:
    code: str  # bot command, e.g. "es"
    col: int  # column in the sheet
    name: str  # Neolatino name
    name_en: str
    site: str  # language code on the website (#/?l=…)
    wiki: str | None  # Wiktionary subdomain, "isv" for the Interslavic dictionary, None = no link
    aliases: tuple[str, ...] = ()


# Columns of the sheet (header row: ID, SEM, cat. gram., 3 topics, ess., bàs., NEO. … INTERSL.)
LANGS: list[Lang] = [
    Lang("neo", 8, "Neolatino", "Neolatino", "lat", None, ("nl", "lat")),
    Lang("iro", 9, "Interromànico", "Inter-Romance", "iro", None, ("inter",)),
    Lang("pt", 10, "Portughese", "Portuguese", "por", "pt", ("por",)),
    Lang("es", 11, "Castellano", "Spanish", "spa", "es", ("cas", "spa")),
    Lang("ca", 12, "Catalano", "Catalan", "cat", "ca", ("cat",)),
    Lang("oc", 13, "Occitano", "Occitan", "oci", "oc", ("occ", "oci")),
    Lang("fr", 14, "Francese", "French", "fra", "fr", ("fra",)),
    Lang("sc", 15, "Sardo", "Sardinian", "srd", "sc", ("sar", "srd")),
    Lang("it", 16, "Italiano", "Italian", "ita", "it", ("ita",)),
    Lang("ro", 17, "Rumeno", "Romanian", "rum", "ro", ("rum",)),
    Lang("en", 18, "Anglese", "English", "eng", "en", ("ang", "eng")),
    Lang("fol", 19, "Folksprak", "Folkspraak", "fol", None, ()),
    Lang("fre", 20, "Frenkisch", "Frenkisch", "fre", None, ()),
    Lang("isv", 21, "Interslavo", "Interslavic", "sla", "isv", ("sla",)),
]
BY_CODE = {lang.code: lang for lang in LANGS}
COMMANDS = {alias: lang.code for lang in LANGS for alias in (lang.code, *lang.aliases)}
NEO = 0  # index of Neolatino in LANGS / Entry.v
EN = next(i for i, lang in enumerate(LANGS) if lang.code == "en")

SOFT_HYPHEN = "­"


def norm(text: str) -> str:
    """Lower case, no accents, no soft hyphens, no editor marks (*)."""
    text = str(text or "").replace(SOFT_HYPHEN, "").replace("*", "")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()


def terms(value: str) -> list[str]:
    """The searchable forms of a cell: "(ac)collí" → accolli, colli; "a, b" → a, b."""
    out: list[str] = []
    for part in re.split(r"[,;/]", value or ""):
        part = part.strip()
        if not part:
            continue
        if "(" in part or ")" in part:
            out.append(norm(part.replace("(", "").replace(")", "")))
            out.append(norm(re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", part))))
        else:
            out.append(norm(part))
    seen: set[str] = set()
    return [t for t in out if t and not (t in seen or seen.add(t))]


@dataclass
class Entry:
    id: str
    sem: str
    cat: str
    themes: list[str]
    ess: bool
    bas: bool
    v: list[str]  # one value per LANGS item
    terms: list[list[str]] = field(default_factory=list)

    @property
    def word(self) -> str:
        return self.v[NEO]

    @property
    def proper(self) -> bool:
        """Proper nouns (npr/m, npr/f…) keep their capital letter in links."""
        return self.cat.lower().startswith("npr")

    @property
    def is_verb(self) -> bool:
        return bool(re.match(r"^\s*v\s?\.", self.cat.lower())) or bool(re.search(r"(^|[,;]\s*)v\s?\.", self.cat.lower()))


@dataclass
class Match:
    entry: Entry
    score: int  # 0 whole word, 1 starts with, 2 a word inside starts with, 3 contains
    col: int  # index in LANGS of the language that matched


class Dictionary:
    def __init__(self, entries: list[Entry]):
        self.entries = entries
        self.by_id = {e.id: e for e in entries}
        self._vocab: dict[int, dict[str, str]] = {}

    @classmethod
    def from_csv(cls, text: str) -> "Dictionary":
        if not text.startswith("ID,"):
            raise ValueError("this doesn't look like the Neolatino sheet (first column should be ID)")
        entries: list[Entry] = []
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 22 or not row[0].strip().isdigit() or not row[8].strip():
                continue
            if re.fullmatch(r"[\d.,%\s]+", row[8]):  # the row of totals under the header
                continue
            v = [row[lang.col].replace(SOFT_HYPHEN, "").strip() for lang in LANGS]
            entry = Entry(
                id=row[0].strip(),
                sem=row[1].strip(),
                cat=row[2].strip(),
                themes=[t.strip() for t in row[3:6] if t.strip()],
                ess=row[6].strip() == "e",
                bas=row[7].strip() == "b",
                v=v,
            )
            entry.terms = [terms(value) for value in v]
            entries.append(entry)
        if not entries:
            raise ValueError("the sheet has no words")
        return cls(entries)

    def __len__(self) -> int:
        return len(self.entries)

    # ── search ───────────────────────────────────────────────────
    def _columns(self, code: str | None) -> list[int]:
        if code is None:
            return list(range(len(LANGS)))
        return [next(i for i, lang in enumerate(LANGS) if lang.code == code)]

    @staticmethod
    def _query(text: str, code: str | None) -> str:
        q = norm(text)
        # English verbs are stored bare ("speak"): "to speak" should still match
        if code in (None, "en") and re.match(r"^to\s+\S", q):
            q = re.sub(r"^to\s+", "", q)
        return q

    def search(self, text: str, code: str | None = None, contains: bool = False) -> list[Match]:
        """Whole words first, then "starts with"; with contains=True only the words that contain the text."""
        q = self._query(text, code)
        if not q:
            return []
        cols = self._columns(code)
        found: list[Match] = []
        for entry in self.entries:
            best, best_col = 9, cols[0]
            for col in cols:
                for term in entry.terms[col]:
                    if term == q:
                        score = 0
                    elif contains:
                        score = 3 if q in term else 9
                    elif term.startswith(q):
                        score = 1
                    elif (" " + term).find(" " + q) >= 0 or ("-" + q) in term:
                        score = 2
                    else:
                        score = 9
                    if score < best or (score == best and col == NEO and best_col != NEO):
                        best, best_col = score, col
                if best == 0:
                    break
            if best < 9 and (not contains or best == 3):
                found.append(Match(entry, best, best_col))
        found.sort(key=lambda m: (m.score, not m.entry.ess, not m.entry.bas, len(m.entry.v[m.col]), norm(m.entry.word)))
        return found

    def suggest(self, text: str, code: str | None = None, limit: int = 5) -> list[str]:
        """Close spellings that are in the dictionary ("casaa" → casa)."""
        q = self._query(text, code)
        if not q:
            return []
        vocab: dict[str, str] = {}
        for col in self._columns(code):
            vocab.update(self._vocabulary(col))
        close = difflib.get_close_matches(q, list(vocab), n=limit, cutoff=0.75)
        return [vocab[c] for c in close]

    def _vocabulary(self, col: int) -> dict[str, str]:
        """normalized form → how it is written, for one language."""
        if col not in self._vocab:
            vocab: dict[str, str] = {}
            for entry in self.entries:
                for part in re.split(r"[,;/]", entry.v[col]):
                    part = re.sub(r"\([^)]*\)", "", part).replace("*", "").strip()
                    key = norm(part)
                    if key and key not in vocab:
                        vocab[key] = part
            self._vocab[col] = vocab
        return self._vocab[col]
