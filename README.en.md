# Gadak

Keep the thread of long chats. Gadak sits beside your conversations with an LLM, redraws each one as a transit map, and tells you first about what slipped past. It never answers for the model.

- **Read a chat as a map.** One question is one station. A decision is a large dot with a bold name, a side trip is a grey branch dropping below the line, and a red dot shows where you are. Click a station to jump there.
- **Hear about missed work first.** A file that changed without being asked, a request that never got an answer, the context to carry into a new chat. Gadak rereads the record, lists only what it could verify, and keeps a decision trace.
- **See a month on one sheet.** The system map lays every project out as a coloured line over the last 7, 15 or 30 days.
- **Float it over the app you are in** (macOS). A Gadak button rests at the edge of the screen and opens the map of your current chat.
- **Look ahead.** Gadak reads where the chat is heading and offers up to three ways forward — questions to take to your LLM, never answers.

Site and live demo: https://hanhws.github.io/AI-agent/en/

## Install

Download from the site, https://hanhws.github.io/AI-agent/en/download/, or from GitHub Releases, [`v0.1.0-en`](https://github.com/Hanhws/AI-agent/releases/tag/v0.1.0-en).

| Computer | File |
|---|---|
| Mac · Apple silicon (macOS 12+) | `Gadak-0.1.0-arm64.dmg` |
| Mac · Intel (macOS 13+) | `Gadak-0.1.0-x86_64.dmg` |
| Windows 10 · 11 (64-bit) | `Gadak-0.1.0-windows-x64-setup.exe` (or `Gadak-0.1.0-windows-x64.zip` to run without installing) |
| Chrome (reads Claude and ChatGPT on the web) | `Gadak-0.1.0-chrome-extension.zip` |

The illustrated guide is [`docs/gadak-install-guide.pdf`](docs/gadak-install-guide.pdf) and the full guide is [`docs/usage-guide.en.md`](docs/usage-guide.en.md). Gadak has no paid signature, so the first launch needs one confirmation (Mac: System Settings → Privacy & Security → Open Anyway · Windows: More info → Run anyway). The Windows version has been checked only under Wine on a Mac, not on a real PC.

## Two editions

| | Korean edition | English edition |
|---|---|---|
| Source | the top of `main` | the `english` branch (a copy of it is kept in the `english/` folder on `main`) |
| App | `가닥.app` | `Gadak.app` |
| Download | [site](https://hanhws.github.io/AI-agent/download/) · release `v0.1.0` | [site](https://hanhws.github.io/AI-agent/en/download/) · release `v0.1.0-en` |

The code is the same and only the language differs: the screens, the prompts, the made-up example and the install guide. In the English edition the station names and summaries Gadak writes are in English whatever language you chat in. Both editions can be installed side by side, but they share the same records (`~/.gadak`) and port, so run one at a time.

To build the English edition from source on a Mac, open the English tree (the `english/` folder on `main`, or the top of the `english` branch) and double-click `Install Gadak.command`. It builds `Gadak.app`, puts it in Applications and opens it.

## Connect an AI

Gadak sorts your chats with one AI you already have: a Claude subscription (Pro · Max), a ChatGPT subscription (Plus · Pro), or an LLM API key (Anthropic · OpenAI · Gemini). Choose it under **Connect AI** in the Gadak window. Without one, Gadak only reads and shows your chats.

## Where chats come from

- Claude Code and Codex: read automatically.
- Cursor (Mac): **Sources → Connect** once.
- Claude and ChatGPT on the web: the Chrome extension in `extension/` (Developer mode → Load unpacked).
- Past chats in bulk: an export file via **Sources → Choose file**.

## Privacy

Chats are stored only on your computer (`~/.gadak`). Only while sorting does a slice of a turn go to the AI you connected. API keys live only in the macOS Keychain or Windows Credential Manager. Gadak sends nothing itself except the two kinds you switch on (undoing an unrequested change, a summary to carry on).

## Development

Run these from the top of the English tree: the `english/` folder on `main`, or the `english` branch.

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.launch          # opens the Gadak window
.venv/bin/python -m unittest discover -s tests
```

Open the window with `?demo` to see a made-up example. The site for both editions is built from the top of `main` (`homepage/`). Changes to the English edition are made on the `english` branch, and the `english/` folder is refreshed from it. The full project handoff (in Korean) is [`README.md`](README.md), and how the English edition is kept is in [`docs/handoff-english.md`](docs/handoff-english.md) (in Korean).

Made as a team project for the AI applications course of the SNU Big Data & FinTech programme (KDT), cohort 13. Not affiliated with Anthropic, OpenAI or Google.
