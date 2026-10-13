# Gadak — English edition

This tree is the English edition of Gadak (가닥), an agent that redraws long LLM chats as a transit map and tells you first about what slipped past. The code is the same as the Korean edition. The screens, the prompts, the made-up example and the install guide are in English.

**Start with [`README.en.md`](README.en.md)**: what Gadak is, how the agent works and what was measured.

| | |
|---|---|
| Where this tree lives | The `english` branch is the source. The [`english/`](https://github.com/Hanhws/AI-agent/tree/main/english) folder on `main` is a copy of it |
| Download | [hanhws.github.io/AI-agent/en/download](https://hanhws.github.io/AI-agent/en/download/) · release [`v0.1.0-en`](https://github.com/Hanhws/AI-agent/releases/tag/v0.1.0-en) |
| Live demo | [hanhws.github.io/AI-agent/en/demo](https://hanhws.github.io/AI-agent/en/demo/) |
| Guides | [`docs/gadak-install-guide.pdf`](docs/gadak-install-guide.pdf) · [`docs/usage-guide.en.md`](docs/usage-guide.en.md) |
| Korean edition | The top of [`main`](https://github.com/Hanhws/AI-agent) · [한국어 README](https://github.com/Hanhws/AI-agent/blob/main/README.md) |

## Run from source

From the top of this tree:

```sh
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.launch                 # opens the Gadak window. Add ?demo to the address for the made-up example
.venv/bin/python -m unittest discover -s tests     # 387 tests
```

On a Mac, double-clicking `Install Gadak.command` builds `Gadak.app` and puts it in Applications.

## Changing this edition

Change the `english` branch, then refresh the `english/` folder on `main` from it. The site for both editions is built from the top of `main` (`homepage/`), so the copy of `homepage/` in this tree is not used. The steps are in [`docs/handoff-english.md`](docs/handoff-english.md) (in Korean).

The rest of `docs/` is in Korean: the design spec ([`docs/spec.md`](docs/spec.md)) and the development log ([`docs/CHANGES.md`](docs/CHANGES.md)).
