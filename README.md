# Dictionario Neolatino — Telegram bot

The Neolatino counterpart of the Interslavic [Slovnik-bot](https://github.com/l3monardo/Slovnik-bot):
ask for a word and it answers with the word's table from the dictionary.

- Every word of a natural language links to **Wiktionary in that language** — Portuguese to
  pt.wiktionary.org, Spanish to es.wiktionary.org, and so on for Catalan, Occitan, French, Sardinian,
  Italian, Romanian and English.
- When the word's English Wiktionary page has a **picture**, the bot sends it, with the table as
  its caption.
- The Neolatino word opens on the website (gleb.onl/neolatino), and verbs get a link to their
  conjugation there. Interslavic words open in the Interslavic dictionary. Inter-Romance, Folkspraak
  and Frenkisch have no Wiktionary, so they're plain text.

It reads the same Google Sheet as the website and reloads it every 12 hours.

## Commands

| Command | |
|---|---|
| `/es casa` | Spanish → Neolatino (also `/pt /ca /oc /fr /sc /it /ro /en /iro /fol /fre /isv`) |
| `/neo casa` | Neolatino word |
| `/id 1900` or `/id_1900` | one word by its ID (the lists show tappable `/id_…`) |
| `/help`, `/start` | help |
| `/actualizzare` | reload the sheet now |

In a private chat you can just write a word: it is looked up in every language. In groups the bot
answers only its commands (`/es@YourBot casa` works too). Up to three matches come as full tables;
more come as a list with `/id_…` links; a word that isn't found gets spelling suggestions
(`/es casaa` → `/es casa`).

## Setting it up

1. **Create the bot**: in Telegram, @BotFather → `/newbot` → a name (*Dictionario Neolatino*) and
   a username (e.g. `NeolatinoDictionarioBot`). Copy the token.
2. **Install** (Python 3.10 or newer), in this folder:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env      # then put the token in .env
   ```
3. **Run**: `./run.sh`. The first start downloads the sheet (about 2 MB) and saves a copy in
   `dictionario.csv`, used when Google can't be reached.
4. **Keep it running** on the same machine as the Interslavic bot: `neolatino-bot.service` is a
   ready systemd service (change the user and the paths in it; the commands are at the top of the
   file). Shared web hosting like Hostinger's can't keep a bot running, because it needs a process
   that's always on.

Optional, in @BotFather: `/setuserpic` (the red "N" from the website), `/setdescription`, and
`/setjoingroups` to allow groups. Leave group privacy on: the bot only needs its commands.

## Settings (`.env`)

| | |
|---|---|
| `TELEGRAM_TOKEN` | from @BotFather (required) |
| `SITE_URL` | the website the links open, default `https://gleb.onl/neolatino/` |
| `REFRESH_HOURS` | how often the sheet is reloaded, default 12 |
| `ADMIN_IDS` | Telegram user ids allowed to run `/actualizzare`; empty = anyone, once per 5 minutes |
| `SHEET_CSV_URL` | the published sheet; only change it if the sheet moves |

## Files

```
bot.py            Telegram: commands, sending the answers (picture + caption, or text)
replies.py        the answers: word table, lists, "not found", help (all texts are here)
dictionary.py     the sheet: reading it, the languages, search, spelling suggestions
wiktionary.py     Wiktionary links and the picture lookup (en.wiktionary.org API)
tests/            offline tests with 118 real rows of the sheet: python3 -m unittest discover tests
```

## How the links and pictures work

- **Links**: a cell like `colar, pegar` gives two links. Sardinian `melingiana/melinzana` gives two
  as well, but `a/in/dae cuddae` stays one. Page names follow Wiktionary: common words in lower case
  (`Aici` → aici), names capitalized (`afganistán` → Afganistán), English verbs without "to", and
  Romanian verbs without "a" (`a lua` → lua).
- **Picture**: the first photo on the English Wiktionary page of the word's English translation
  (logos, icons and sound files are skipped), as an 800 px copy. Each word is looked up once a day,
  and a picture is sent once per answer. If Telegram can't fetch the picture's link, the bot
  downloads the picture itself and uploads it.

The Neolatino texts (*Non se han tropato coincidèntias*, *Pròva:*, *Actualizzando…*) come from the
website's interface. A fluent speaker should still read them; they're all in `TEXT` in `replies.py`.
