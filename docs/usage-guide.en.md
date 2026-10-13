# Gadak usage guide — leave it on and it reads by itself

Turn Gadak on once and it finds how you use LLMs on this computer, reads the chats it can read, sorts them into a transit map and shows them in the Gadak window.

> As of 13 October 2026. This is the guide to the **English edition** of Gadak (branch `english`, release `v0.1.0-en`). It follows the Korean guide, [`usage-guide.md`](usage-guide.md). The two editions run the same code and differ only in language, so unless it says otherwise, “checked” below means checked on the Korean edition. What was checked on the English builds themselves is listed in 1-1 and 1-3. If you are new to Gadak, start with the illustrated [`gadak-install-guide.pdf`](gadak-install-guide.pdf) (nine pages, Mac and Windows; the same file is inside the disk image and the Windows packages).
>
> **What works now**: starting Gadak as an app (the downloaded app, or the app built from this repository), reading Claude Code and Codex chats by itself, sorting the chat you are looking at first (main line · side trips · decisions · sections · split requests · answer summaries), finding missed work (missed request · unrequested change · carry on) with a decision trace, the Gadak window (strip map · To do · Decided · Files · Ahead · search), searching chats and removing them from the list, reading Claude and ChatGPT web chats through a Chrome extension (reading claude.ai has been seen working; chatgpt.com is not confirmed), auto-run for the kinds you approve (confirmed in Claude Code; Cursor is not confirmed), the floating Gadak button and its button editor, three engines (Claude subscription · ChatGPT subscription · API key) chosen and connected on screen under **Connect AI**. **Not built yet**: a rail and map attached beside a web chat, a desktop MCP entry. How well the sorting works was measured on 6 October with the Korean prompts (README 3-5, in Korean): it finds six or seven side trips out of ten, and the Decided mark still wavers. The English prompts are translations and no separate measurement has been recorded for them.

## 1. Starting Gadak

**On a Mac, Gadak is an ordinary app.** Find “Gadak” in Launchpad or Spotlight (⌘ Space). One window opens and an icon appears in the Dock. There are two ways to install it: drag in the downloaded app (1-1), or build it from this repository (1-2). **On Windows you install it with an installer (1-3).**

- Quit with ⌘Q. The reading and sorting in the background stop too. While the **floating button** (5-3) is showing, closing the window leaves Gadak running; if you have hidden the button, closing the window quits Gadak.
- To keep it in the Dock, right-click the Dock icon → Options → Keep in Dock.
- The window keeps its size and place the next time you start it.
- **Decision trace** opens in a second window.

### 1-1. Download and use — a disk image (dmg), no terminal

You need no Python, no Xcode and no repository folder. For an Apple silicon Mac (M1 or later) the file is `Gadak-0.1.0-arm64.dmg`; for an Intel Mac (macOS 13 or later) it is `Gadak-0.1.0-x86_64.dmg`. To see which you have, open the Apple menu → About This Mac and read the Chip or Processor line.

1. Open the downloaded `.dmg` and drag Gadak onto the Applications folder beside it.
2. Open Gadak from Applications. **The first time, macOS blocks it** (“unidentified developer” or “Apple could not verify …”). Press Done, then go to **System Settings → Privacy & Security** and press **Open Anyway** near the bottom. On macOS 14 or earlier, right-click Gadak → Open → Open also works. After the first time it opens normally.
3. When it starts, Gadak finds and reads the chat records on this Mac. If no AI is ready to use, the **Connect AI** window opens by itself. Pick a Claude subscription, a ChatGPT subscription or an API key and press **Connect** (section 3). You never need a terminal. Without an AI, Gadak only reads and shows your chats.

- Why it is blocked the first time: Gadak was made as a class project and has no Apple developer signature (US$99 a year). The same instructions are in ‘How to open Gadak.txt’ inside the disk image.
- **Move it before you start it.** If you start it from inside the disk image or from the Downloads folder, macOS runs it from a temporary place and the Cursor and Claude Code connections (section 4) will not work.
- Chats are stored only on this Mac, in `~/.gadak`. To remove them, move Gadak to the Trash and delete that folder too.
- The disk image holds Gadak, ‘How to open Gadak.txt’ and ‘Gadak install guide.pdf’. **Where to get it**: the download page of the site (`https://hanhws.github.io/AI-agent/en/download/`) or GitHub Releases (`v0.1.0-en`). To build it yourself, run `./.venv/bin/python -m backend.macapp --dmg` in the English tree (the `english/` folder on `main`, or the `english` branch; the file appears in `dist/`; it needs PyInstaller: `./.venv/bin/python -m pip install pyinstaller`).
- **Checked on the English builds (13 Oct)**: both disk images open and hold the three items; the signature is intact; the app, copied out of the image, starts with a throwaway profile and shows English screens (the Intel build under Rosetta); the floating button’s self-check passes. **Not checked**: downloading and opening it on another, clean Mac (the Open Anyway step), a real Intel Mac, and macOS versions below 26.

### 1-2. Use it from this repository — for people developing it

The English edition is the `english` branch of this repository, and a copy of it is kept in the `english/` folder on `main` (the top of `main` is the Korean edition). **Install once.** In that English tree, double-click `Install Gadak.command` in Finder. It downloads what is needed (about a minute), builds the Gadak app, puts it in Applications and starts it.

- Building the app uses the Swift compiler. If it says there is none, run `xcode-select --install` in a terminal to install the Xcode command line tools. If you use git, you already have them.
- The app runs the code in this repository folder. After you change code, just restart the app. **If you move or rename the folder, run `Install Gadak.command` again.**
- If you got the repository as a zip, macOS may block `Install Gadak.command` the first time. Allow it with right-click → Open; if it is still blocked, press Open Anyway in System Settings → Privacy & Security.
- To remove it, move Gadak from Applications to the Trash. To remove the chats it read as well, delete the `~/.gadak` folder.
- The app follows whatever branch the folder is on. Both editions also share `~/.gadak` and port 7311, so run one at a time.

To start it without the app, or on something other than macOS, run this in the repository folder. It opens in a browser window; stop it with **Quit** on screen or Ctrl+C.

```bash
./.venv/bin/python -m backend.launch
```

What Gadak does once it is on

1. **Find** — it looks for Claude Code and Codex record files, whether Cursor is installed, and whether the Chrome extension has connected. **Sources** in the Gadak window shows what it found.
2. **Read** — it copies the chats in those files into `~/.gadak/gadak.db`. While it is on, it reads only what was added every 2.5 seconds, so it follows the chat you are having now.
3. **Sort** — it sorts the chat on screen first, with the AI you connected. Until then, the start of each question stands in as the station name.
4. **Find missed work** — if, while sorting, it sees a request that seems to have been skipped, a file changed more widely than asked, or a new chat in the same project, it rereads the record to check, and if something was missed it adds a to-do (section 5).
5. **Show** — the chat list on the left, the strip map at the top, the chat in the middle and the lists on the right.

### 1-3. Windows — an installer, no terminal

Windows 10 or 11 (64-bit). You do not need to install Python; it comes with Gadak.

1. Open `Gadak-0.1.0-windows-x64-setup.exe`. **If a blue “Windows protected your PC” window appears, press More info → Run anyway.** Gadak has no paid signature, so this check is needed once.
2. Press **Install**, then **Finish**. It installs for your account only, so no administrator password is needed (`%LOCALAPPDATA%\Programs\Gadak`).
3. Start **Gadak** from the Start menu or the desktop. The Gadak window opens by itself (an Edge or Chrome window without an address bar). **Closing that window quits Gadak.**
4. Pick one under **Connect AI** at the bottom left. If Claude Code or Codex is installed on this PC and signed in, just pick it; otherwise paste an LLM API key (3-2). The key is kept only in Windows Credential Manager on this PC.

- To use it without installing, unzip `Gadak-0.1.0-windows-x64.zip` and run ‘Start Gadak.cmd’ inside it.
- You get the files from the same place as the Mac ones (1-1).
- ‘Gadak install guide.pdf’ (page 3 is Windows) is in the zip and in the installed folder.
- **Not in the Windows version yet**: the floating Gadak button (5-3), fetching Claude Code or Codex for you with one **Connect** (install them yourself and Gadak finds them), the Cursor connection (4-2) and auto-run (5-2), and the Claude usage gauge.
- Chats are stored only on this PC, in `C:\Users\your name\.gadak`. To remove them, uninstall Gadak under Settings → Apps and delete that folder too. What Gadak says while running is written to `gadak.log` in that folder (look there if it does not start).
- To build it: `./.venv/bin/python -m backend.winapp --zip --installer` (this works on a Mac too; the installer needs NSIS and, on a Mac, Wine — see the header of `backend/winapp.py`).
- **Checked and not checked**: the makers have no Windows PC, so it was **checked only under Wine** (a tool that runs Windows programs on a Mac). On the English build (13 Oct): the contents of the zip, a silent install, the shortcuts, starting it and getting English screens from it, uninstalling, and the test suite. **It has never been started on a real Windows PC**: the “protected your PC” window, the Edge window actually opening and Gadak quitting when it closes, how antivirus reacts, and sorting with Claude Code or Codex on Windows.

## 2. Depending on what you use

| What you use | How Gadak reads it | What you do | State |
|---|---|---|---|
| Claude Code (VS Code extension · terminal · the Code tab of the desktop app) | Reads the record files by itself | Nothing | Works |
| Codex (terminal · VS Code extension) | Reads the record files by itself | Nothing | Works (checked with one chat) |
| Cursor | Receives new chats through a Cursor hook | **Sources → Connect**, once | Connecting works (a real chat is not confirmed yet) |
| Claude and ChatGPT on the web (Chrome) | The Chrome extension reads chats you open | Add the extension to Chrome **once** (4-3) | claude.ai seen working; chatgpt.com not confirmed |
| Past chats you never opened · chats in the desktop apps | Those chats live on the service’s server. You add an export file | **Sources → Choose file** (4-4) | Checked only with made-up files (a real export is not confirmed) |
| No paid LLM | See the example chat | Add `?demo` to the address, or before installing use the demo on the site (https://hanhws.github.io/AI-agent/en/demo/) | Works |

The LLM used for sorting (the engine) is separate from where chats are read. See section 3.

## 3. Choosing an engine — Connect AI in the Gadak window

The engine is the LLM Gadak uses to sort your chats. **Choose and connect it under Connect AI at the bottom left of the Gadak window.** If no AI is ready to use, this window opens by itself the first time.

| Row | What it does |
|---|---|
| Claude subscription (Pro · Max) | Press **Connect**. If Claude Code is not installed, Gadak fetches it (Anthropic’s official installer, about a minute) and opens a sign-in page in your browser. When you finish signing in it shows Connected |
| ChatGPT subscription (Plus · Pro) | Press **Connect**. If Codex is not installed, Gadak fetches it (OpenAI’s official release, into `~/.gadak/bin`) and opens a sign-in page in your browser |
| LLM API key (Anthropic · OpenAI · Gemini) | Paste a key you have and press **Save**. Gadak works out which company it is from, checks with that company that the key is valid, and puts it in the macOS Keychain (on Windows, Credential Manager) (3-2) |

- If more than one is connected, pick with **Sort with this**. Gadak remembers the choice. **Let Gadak choose** makes Gadak pick in the order below. **Use without AI** makes Gadak only read and show your chats.
- The order when Gadak chooses: **Claude subscription if Claude Code is there → API key if there is one → ChatGPT subscription if Codex is signed in → none.** If Claude Code is installed but not signed in, it uses another way (key or ChatGPT).
- If you have not chosen on screen, the starting value is `GADAK_ENGINE` in `backend/.env` (for the downloaded app, `~/.gadak/.env`): `auto` · `claude_cli` · `codex_cli` · `anthropic_api` · `none`. For the API key engine, `openai_api` and `gemini_api` mean the same; whichever name you write, it follows the company of the key you have.
- **Gadak fetches a program only when you press Connect.** It fetches from two places only: `https://claude.ai/install.sh` (Claude Code) and the releases at `github.com/openai/codex` (Codex). The sign-in is done by that tool in your browser; Gadak never sees a password or token.
- If connecting does not finish within five minutes it stops. Press again. While waiting you can stop it with **Cancel**.

### 3-1. Claude subscription engine (`claude_cli`) — Pro · Max

Gadak calls the Claude Code that is signed in on your computer. **No API key and no extra charge.**

Things to know

- **It shares your subscription’s usage limit.** That is why Gadak does not sort all your past chats at once; it sorts the chat on screen and turns that have just ended. It makes at most 150 calls per run and then stops (change it with `GADAK_MAX_CALLS`). Finding missed work uses the same limit.
- **Finding missed work makes two to five calls per turn it checks.** Not every turn: only turns that were flagged while sorting (a request that seems skipped · a wide change · a new chat). The cap on calls per turn is `GADAK_MAX_STEPS` (default 5), and the model is `GADAK_CHECK_MODEL` (empty means the same model as sorting).
- **It asks about six to eight turns at a time, and a call takes about ten seconds** (measured 3 Oct: a nine-turn chat took two calls, 15–28 seconds). A fifty-turn chat takes a little over a minute.
- Even if `ANTHROPIC_API_KEY` is in your environment, this engine uses the subscription sign-in.
- The Claude Code that Gadak calls does not load your settings (hooks · MCP · CLAUDE.md) and leaves nothing in your chat list.
- **It cannot be used in a Gadak deployed on a server.** The subscription sign-in exists only on your computer.
- Checked with Claude Code 2.1.267. Behaviour may change with other versions.
- Change the model with `GADAK_ENGINE_MODEL` (`haiku` · `sonnet` · `opus`, default `haiku`).
- To check from a terminal: `./.venv/bin/python -m backend.engines --ping` (it makes one call).

### 3-2. API key engine (`anthropic_api` · `openai_api` · `gemini_api`) — when you have no subscription

Gadak calls the provider directly with an LLM API key you have. **What it uses is billed to that key.** Keys from three companies are accepted.

| Company | Key starts with | Engine | Models (`haiku` · `sonnet` · `opus`) | Price of the small model (per million tokens · input / output) |
|---|---|---|---|---|
| Anthropic | `sk-ant-` | `anthropic_api` | Claude Haiku 4.5 · Sonnet 5.5 · Opus 5.5 | $1 / $5 |
| OpenAI | `sk-` | `openai_api` | GPT-6 Luna · GPT-6.1 Sol · GPT-6 Astra | $0.1 / $0.5 |
| Google Gemini | `AIza` · `AQ.` | `gemini_api` | Gemini 3.5 Flash-Lite · 3.8 Flash · 3.1 Pro (preview) | $0.3 / $2.5 · free tier costs nothing |

With an Anthropic key, asking Haiku about eight turns at once costs one or two cents a call (measured 6 Oct on a 58-turn chat: about 0.3 cents a turn). The prices for the other two were read from their price lists on 8 Oct; what they cost in practice has not been measured.

- **Paste the key into the LLM API key row under Connect AI.** There is one box. Gadak tells which company the key is from by how it starts. The characters are hidden. When Gadak receives a key it checks once, **with that company only**, that the key is valid (a request that costs nothing) and, if it is, stores it in the login Keychain as ‘Gadak · LLM API key’. An invalid key is not stored. It is never written to a file such as `.env`.
- **One key is kept.** To change to another company’s key, press **Delete key** and add the new one.
- The screen shows only the company name and the start and last four characters of the key. The key goes to that company only, never to another company and never to the Gadak team’s server.
- If the key is wrong or stops working, the status line at the bottom left of the Gadak window says “The API key is not valid. Please enter it again.” Limit, credit and connection problems appear on the same line. For passing problems such as a rate limit or an overloaded server, Gadak waits as long as the server says (up to a minute), retries up to twice, and only then tells you.
- The model is set with `GADAK_ENGINE_MODEL`, as for the subscription engine. `haiku` · `sonnet` · `opus` mean small · medium · large and map to that company’s models in the table. You can also write that company’s model name directly (`claude-…` · `gpt-…` · `gemini-…`). If another company’s model name is written there, the small model is used.
- **A free Gemini key.** A key from Google AI Studio (aistudio.google.com) works without billing. Its per-minute and daily limits are low, so sorting may stop on a limit, and **on the free tier what you send is used by Google to improve its products** (the ‘Used to improve our products: Yes’ line on Google’s price list, checked 8 Oct). The large model (Pro) is not on the free tier. Since 28 May 2026 AI Studio issues keys starting with `AQ.`; older `AIza` keys are accepted too.
- Gadak tells OpenAI not to keep what is sent and returned (`store: false`; otherwise it is kept for 30 days).
- Looking things up on the web (`look_up` in Look ahead) does not work with the API key engine.
- If Claude Code is installed, the subscription engine still comes first when Gadak chooses, even after you add a key. To use the key, press **Sort with this** under Connect AI.
- Where the key is kept: the macOS Keychain, or Windows Credential Manager. On a system with neither (Linux) it is not stored, and Gadak uses the environment variable `GADAK_API_KEY` if it is set (the old name `ANTHROPIC_API_KEY` is still read). **`OPENAI_API_KEY` and `GEMINI_API_KEY` set for other tools are not read**, so that a key you never gave Gadak is never charged.
- **A real answer has not been received with a real key** (the makers have no API key). All three companies are covered by tests that swap in a fake sender. On 8 Oct two things were tried against the real servers with a made-up key: the three companies reject a wrong key and Gadak reports it as an invalid key; and Gemini’s server accepts the field names and values Gadak sends. Whether the answer format (schema) is accepted, and whether OpenAI accepts the request, needs a real key.
- **How well OpenAI and Gemini models sort has not been measured.** The numbers in README 3-5 were measured with Claude. If you have a key, try one call with `./.venv/bin/python -m backend.engines --ping` (it costs a little) and measure with `python -m eval`.

### 3-3. ChatGPT subscription engine (`codex_cli`) · no engine (`none`)

**ChatGPT subscription** — Gadak calls the Codex that is signed in on your computer (`codex exec`). No API key and no extra charge. It shares the Codex usage limit of your ChatGPT subscription.

- Codex does not have to be installed as a terminal command. Gadak looks in this order: the `codex` command → the copy Gadak fetched (`~/.gadak/bin/codex`) → the copy inside the ChatGPT extension of VS Code or Cursor.
- The Codex that Gadak calls leaves nothing in your chat list (`--ephemeral`), does not load your settings, and cannot change anything (read-only).
- It uses the model Codex picks by default. Gadak’s model names (`haiku` · `sonnet` · `opus`) become reasoning effort (low · medium · high). To set the model, use `GADAK_CODEX_MODEL`.
- One call took about six seconds (7 Oct, sorting three made-up turns for real: a side trip, a decision, a missed request and summaries came out). Each call carries about 13,000 tokens of Codex’s own base instructions.
- Looking things up on the web (`look_up` in Look ahead) does not work with this engine.
- **It has not been run on a long real chat yet.** Accuracy (README 3-5) has not been measured with this engine either.

**No engine** — press **Use without AI** under Connect AI, or set `GADAK_ENGINE=none`, and Gadak only reads and shows your chats. Station names stay as the start of each question, and side trips and decisions are not told apart.

### 3-4. Look ahead (once when you press it; by itself if you turn that on)

Use it in **Ahead**, the fourth tab of the lists on the right of the Gadak window. Press **Look ahead** at the top and Gadak reads what you are trying to do from where you are now and looks once for ways forward. The line under the button shows how far it has got: looking · n paths · found no path worth offering · why it could not look. Turn on **Look ahead automatically** below the To do tab and it looks by itself whenever the road forks (while that is on, the Look ahead button is not shown). Leaving it on uses more of your Claude limit. The settings below are only for when you want to change something: write them in `backend/.env` (for the downloaded app, `~/.gadak/.env`) and restart Gadak.

```
GADAK_AHEAD=0          # hide both controls (they show by default)
GADAK_AHEAD_AUTO=1     # start with Look ahead automatically on (what you set on screen comes first)
GADAK_AHEAD_WEB=1      # search the web too (search terms taken from the chat leave your computer; Claude subscription engine only)
```

- **When it runs**: pressing **Look ahead** looks once from where the chat is now (its last turn). With **Look ahead automatically** on, it runs by itself when you have just decided something, when the section changes, or when you ask something like “what next?” (at most once per eight turns in one chat). Gadak remembers whether it is on.
- **Where it shows**: after 30 seconds to 2 minutes the paths gather under Paths found in the Ahead tab as `Carry on · …`, `Another way · …` and `Prepare first · …` (they also show among the suggestions in To do). If a word is unfamiliar, see **Help** at the bottom left of the Gadak window (in the Mac app, the Help menu). **See this path** shows the reason, what was looked up and the text to send; **Ask this way** copies that text. Gadak does not send it for you.
- **Nothing may appear.** A path with nothing found behind it, or one that only repeats the chat you just had, is dropped. Why it was dropped is in **Decision trace** at the bottom left.
- **What it reads**: your chat records as Gadak stored them, text files in that chat’s working folder (not files git ignores, not names like `.env`, not broad folders such as your home or Documents; turn this off with `GADAK_AHEAD_FILES=0`), and the web only if you turned that on.
- **What it costs**: each press calls the large model (Sonnet) two to four times, plus a search or two if the web is on. Measured, that is about 0.7% of a Claude Pro five-hour limit (about 27 seconds, without the web). Change the model with `GADAK_AHEAD_MODEL` (empty means the same model as missed-work checks; Haiku is not recommended because it repeats the chat you just had).
- **Measuring usefulness**: `python -m eval.ahead run --web` makes a sheet, two people grade it separately, then `python -m eval.ahead compare A.csv B.csv` (docs/changes-detail.md 22-6, in Korean; the sheet’s labels are in Korean). With fewer than ten paths graded by both, no verdict is given; `--need 7` lowers that, and the result says it was lowered.

## 4. Where chats are read from

### 4-1. Claude Code · Codex — by itself

- Where: session files under `~/.claude/projects/` and `~/.codex/sessions/`. **Gadak only reads them and does not touch either tool’s settings.**
- What: the questions you typed, the answer text, and the before and after of changed files (Claude Code). Tool output and thinking are not copied.
- The project is the name of the working folder the chat started in.
- Something you sent before the answer came is joined to the question before it and counts as one station.
- If you rewound a chat in Claude Code and rewrote a question, the removed question may still show as a station.
- Reading 95 record files (314 MB) for the first time took 0.5 seconds on the makers’ Mac.
- To let Gadak send by itself (5-2), press **Connect auto-run** under Sources; it adds two hooks. Reading chats needs no hook.

### 4-2. Cursor — connect once

Press **Sources → Connect** in the Gadak window. It creates `~/.cursor/hooks.json` and `~/.cursor/hooks/gadak.sh`, and from then on Gadak reads Agent chats in every project.

- It reads chats from after you connect. Earlier chats cannot be read yet.
- If you already have a `hooks.json`, it is not overwritten. Merge in the entries that `python3 cursor-hooks/install.py cursor` prints.
- To attach it to one project only: `python3 cursor-hooks/install.py cursor --project /path/to/project`.
- Chats that happen while Gadak is off pile up in `~/.gadak/spool.jsonl` and come in the next time you start it.
- To turn it off, remove the Gadak entries from `~/.cursor/hooks.json`.
- Some hooks do not run in Cursor Cloud Agent, so use it with the local Agent.

Checked with Cursor 3.22 up to installing and running the launcher the way Cursor calls it. Whether a real Agent chat comes in is not confirmed.

### 4-3. Claude and ChatGPT on the web — a Chrome extension (add once)

With the extension added, chats you open on Claude (claude.ai) and ChatGPT (chatgpt.com) in Chrome are read and sent to Gadak. You do not need to export anything.

**Adding it** (once)

1. Enter `chrome://extensions` in Chrome’s address bar.
2. Turn on **Developer mode** at the top right.
3. Press **Load unpacked** and choose the extension folder. **Sources → Copy folder path** in the Gadak window copies the path of the copy inside the app; in the folder picker press ⌘⇧G and paste it. From the repository, it is the `extension` folder.
4. Reload any Claude or ChatGPT tabs that were already open.

To get the extension without the app, unzip `Gadak-0.1.0-chrome-extension.zip` from GitHub Releases (`v0.1.0-en`) and choose the `gadak-extension` folder inside.

**Using it**

- With Gadak on, open or carry on a chat. The chat appears in the list in the Gadak window, and a new question shows as the Now station within a few seconds.
- A past chat is read **when you open it**. A chat you only opened is sorted when you look at it in the Gadak window; turns that end while you watch are sorted right away.
- Click the extension icon to see whether Gadak is on and how many stations it read in this tab. Turn off **Read chats in this browser** and it stops reading.
- For chats that happened while Gadak was off: if the tab is still open they come in within about 20 seconds of starting Gadak; if you closed it, they come in when you open that chat again.
- On ChatGPT a chat inside a project is grouped under that project’s name, and on Claude too when the project name is shown. Otherwise it goes under ‘(No project)’.
- Opening a chat you first brought in from an export file does not duplicate its stations.

**Not read**: ChatGPT temporary chats, Claude incognito chats, Chrome incognito windows, other sites. Folded parts of an answer such as thinking, and button labels, are left out. Names of attachments and generated files are not copied yet.

**Things to know**

- **Reading claude.ai has been seen working; chatgpt.com has not been confirmed on the real site.** The places it reads on the page (selectors) may be out of date. If the extension’s popup says “Could not find the chat text”, press **Copy diagnostics** and send it to the makers. What is copied is only the page structure (tag and class names), never chat text.
- A chat’s date is the day it was first read (the page shows no time per message). Chats brought in from an export file have their real dates.
- Claude’s page has no number per message, so Gadak recognises stations by the question text and their order. If you rewrite a question a new station appears and the earlier one stays.
- If the popup says “The running Gadak is an older version”, quit Gadak and start it again.
- To turn it off, disable or remove Gadak in `chrome://extensions`.

### 4-4. Past chats in bulk · chats in the desktop apps — an export file

Chats on Claude and ChatGPT live on their servers. To bring in past chats you never opened, or if you do not use Chrome, add an export file. After that the Chrome extension (4-3) carries on reading.

1. Request a data export under Settings in each service. The file takes a while to arrive by email.
2. Under **Sources → Choose file** in the Gadak window, choose the zip you received (or the `conversations.json` inside it).
3. The chats come in under ‘(No project)’. Adding the same file again does not duplicate them.

This has not been confirmed with a real export file. It was tried only with files made in the known format, so please tell the makers if yours is not read.

### 4-5. Planned, not built yet

- The Chrome extension attaching a rail and map beside the chat, and putting text into the message box.
- An MCP entry for the Claude desktop app.

## 5. Reading the Gadak window

- **Black bar at the top**: **System map** (every project and chat of the last 30 days on one sheet), the **Gadak button** switch (shows or hides the floating button; Mac), and **Day · Night**.
- **Left**: every project as a heading with its chats under it, most recent first, and **Search chats** above. At the bottom, one status line, then **Connect AI · Sources · Decision trace · Help · Quit**.
- **Removing from the list**: hover over a chat and press **×**. The × beside a project name removes all of that project’s chats. Bring them back with **Undo** in the note that pops up, or under **n removed · Show** at the bottom of the list. A removed chat is not found by search and is not sorted. The text Gadak read stays on this computer (to delete everything, see the end of section 6).
- **Search chats** (top left): type a word and Gadak searches every chat in every project. Chats whose title, project name or source (ChatGPT · Cursor · Claude Code …) match come first, then chats whose text matches. Click one to go to that place in that chat. Clear the box or press Esc to go back to the list.
- **Strip map card at the top**: [This chat | Whole project]. The main line is a thick line in the project’s colour. A small black dot is an ordinary question, a **large black dot with a bold name is a decision**, the **red dot with a glow is where the chat is now**, a grey branch dropping below is a side trip, a small dot with a file name is a file, a red ring is a to-do still open and a grey ring is one that is done. Fold and unfold the card with Esc.
- **Middle**: that chat, read-only. Click a station to go to that message. Long text shows its start; **Show all** unfolds it.
- **Right**: four tabs — **To do** (Missed · Suggestions), **Decided**, **Files**, **Ahead** — with a search box above them, and below them the usage-limit gauge for Claude and ChatGPT.
- Light or dark follows your system until you choose with **Day · Night**; your choice is kept on this computer.

### 5-1. To-dos and the decision trace

- While sorting, if Gadak sees one of the three below it rereads that turn’s record to check. While it checks, the status line says “Checking for anything missed”.
  - **Missed request** — one message held several requests and one seems to be missing from the answer. Gadak reads the whole answer; if it really is missing, **Ask again** appears.
  - **Unrequested change** — a file seems to have changed more widely than asked. Gadak compares the changed lines with the request; if they are outside it, **See what changed → Ask to undo** appears.
  - **Carry on** — you opened a new chat in the same project (the first turn of that project’s newest chat). Gadak finds what was decided in the earlier chat and makes **Paste summary**.
- Three more kinds are made without calling the AI, from the sorting result: **Unfinished side trip**, **Repeated question** and **Topic change**.
- The chat you are looking at comes first, and within it, turns nearest to now. Whether to look at earlier turns or earlier chats is decided by Gadak each time.
- A conclusion whose evidence Gadak did not see for itself is not raised as a to-do.
- A button copies text to the clipboard. Paste it into the chat and send it yourself.
- Press **Decision trace** at the bottom left to see, for each turn it checked, which tools Gadak used in what order and what it saw before concluding (`/trace`). Dropped conclusions and the reasons are shown too.

### 5-2. Letting Gadak send by itself (auto-run)

Normally Gadak only copies text and you do the sending. **Only the kinds you turn on** are sent by Gadak itself. There are two.

| Kind | What Gadak does | When |
|---|---|---|
| Unrequested change | Follows up with “I didn’t ask for that part. Put it back.” | When a turn ends, and only if Gadak has looked at the change itself and confirmed it is outside the request |
| Carry on | Puts what was decided in the last chat of the same project into the new chat | When a new chat starts |

**Turning it on**

1. Under **What Gadak sends by itself**, at the bottom of the **To do** list on the right of the Gadak window, press **Turn on** for that kind. It changes to On.
2. Ticking **Do this automatically from now on** in a note does the same.
3. For Claude Code, once: **Sources → Connect auto-run**. It adds two Gadak hooks (`Stop` · `SessionStart`) to the Claude Code settings (`~/.claude/settings.json`). Your existing settings are left as they are, and the file as it was is kept as `settings.json.gadak-backup`. It works from the next chat you open.
   For Cursor, if you have connected, there is nothing more to do.

**What you see**

- In Claude Code, after the answer ends, “Stop hook feedback: …” appears and the change is undone. The ‘Stop hook error’ shown on screen is just what Claude Code calls this kind of follow-up; it is not an error.
- The note stays in the to-do list of the Gadak window, marked “sent by Gadak”.
- While it is on, a turn **in which files changed** takes up to about 40 seconds longer to end, waiting for Gadak’s check. Turns with no file changes, and everything when it is off, are unchanged.
- Gadak does not send again on a turn that followed from text it sent.

**Turning it off**: **Turn off** in the same place. To remove the Claude Code hooks as well, **Sources → Disconnect auto-run**.

Confirmed for real in Claude Code. For Cursor it was built to the documentation but has not been confirmed in a real Cursor. On the web (Chrome extension) and in the desktop apps Gadak cannot send by itself yet.

### 5-3. The floating Gadak button (watching over other apps)

You do not have to go to the Gadak window to see the map. When the Gadak app is on, a **Gadak button rests half over the left edge** of the screen, and it stays on top while you use other apps.

1. **Hover** and the button comes out fully with buttons fanned around it (six at first). When the pointer leaves or you click elsewhere, it rests again.
2. **Click** and the strip map window appears at the top of the screen, just under the menu bar.

| Button | What it does |
|---|---|
| Gadak (centre) | Shows or hides the strip map window |
| Map | The strip map of the chat you are in |
| To do · Decided · Files | Opens a separate list window on that tab |
| Search | Opens the Gadak window at the chat search box |
| Window | Opens the Gadak window |
| Ahead · Help (can be added) | The Ahead tab of the list window · the help window |
| Project buttons (can be added) | Shows that project’s strip map (its most recent chat) without opening the Gadak window |

**Edit Buttons** — **right-click the Gadak button → Edit Buttons…** (or View → Edit Floating Buttons… in the menu bar) to open a small window. **Remove, add and reorder** the buttons around it, up to six. Press a project below to make a **project button**: it has a border in that project’s line colour, and pressing it shows the strip map of the chat most recently used in that project. Press again to close it; press Map or the Gadak button to go back to the chat you are in. The name on a project button can be up to four characters. Changes save right away and reach the button within a few seconds. **Reset to default** goes back to the six.

- **The strip map window** shows the chat you are in (the one whose latest turn is most recent) and keeps drawing as the chat goes on. Click a station to open that place in the Gadak window. Close it with **Collapse** on the card, the Gadak button, or the same button again. Clicking elsewhere does not close it, so you can watch while you work.
- **Moving**: drag the Gadak button and drop it, and it sticks to the nearest edge (left · right · top · bottom). It can sit over the menu bar and the Dock, and it keeps its place the next time. It steers clear of the camera housing at the top centre of the screen.
- **The red number** is how many to-dos are open in the chat you are in.
- **Hiding**: right-click the button → **Hide Button**. To show it again, use the **Gadak button** switch at the top right of the Gadak window, ⇧⌘B, the menu **View → Floating Button**, or right-click the Gadak icon in the Dock → **Show Floating Button**.
- While the button is showing, **closing the Gadak window does not quit Gadak** (open it again with Window). To quit, press ⌘Q or right-click the button → Quit Gadak.
- Clicking the button does not bring Gadak to the front, so what you were typing in another app is not interrupted. A click in the empty space between buttons goes to the app underneath.
- When the strip map window appears it takes the keyboard straight away, so **pressing Esc closes it without clicking**. After that the keyboard goes back to the app you were using.

Only in the Mac app.

## 6. Where your chats go

| What | Where |
|---|---|
| Chat text, and the before and after of changed files | `~/.gadak/gadak.db` on your computer (outside the repository) |
| Web chats the Chrome extension read | Only to the Gadak on your computer (`127.0.0.1:7311`), into the same file. The extension has no way to send anywhere else |
| Chats a Cursor hook received while Gadak was off | They pile up in `~/.gadak/spool.jsonl` and come in the next time you start it |
| While sorting: the first 500 characters of that turn’s question, 220 characters from each end of the answer, and the names and line counts of changed files | Sent to the engine you chose. With a Claude subscription, to Anthropic under your Claude account; with a ChatGPT subscription, to OpenAI; with an API key, to that key’s company (Anthropic · OpenAI · Google). With a free Gemini key, Google may use it to improve its products (3-2) |
| While checking for missed work, what Gadak reads with its tools: that turn’s question (up to 4,000 characters), 3,000 characters from each end of the answer, the changed lines (up to 200), and what was decided and which to-dos are open in the same project | Sent to the same engine, only for turns being checked |
| Usage records (what you clicked, whether a note was acted on, numbers such as how many turns a chat has) | Kept in the same file on your computer. They go to the Gadak team’s server **only if you agreed to send them** (6-1) |
| Never copied | The account email Cursor passes to hooks, tool output, thinking |

- Gadak accepts requests only from your own computer (127.0.0.1).
- The Gadak window fetches one font stylesheet (Pretendard) from cdn.jsdelivr.net. No chat content goes with it.
- The web demo on the site shows only an example sorted in advance. It has no way to upload your chats, so nothing goes there.
- To delete all records, quit Gadak and delete the `~/.gadak` folder. The next time you start it, it reads the record files again from the beginning.

### 6-1. Sending usage records (your choice)

These are records the Gadak team collects to learn how to improve Gadak. Only a Gadak that was built with the team’s server address asks, once, the first time it starts. **The downloads on the site and in GitHub Releases were built without that address, so they never ask and never send.**

| | |
|---|---|
| Sent | How it was started and how many chats per source, what you clicked on screen (scope · tab · search · a station …), notes shown and acted on or put off, the shape of chats (number of turns · side trips · decisions · turns with several requests · turns with file changes), how long sorting took and why it stopped |
| Not sent | Chat text, station names, what was decided, file names and paths, project names, words typed into search, account · email · computer name |
| Who sent it | One random number attached to the Gadak on this computer. Chats are told apart only by a mark mixed with that number so that it cannot be reversed |
| When | Only records written after you agreed, every five minutes. Records from before you agreed stay on your computer |

- Turn it on and off under **Sources → Send usage records**. **See what is sent** shows the records exactly as they go to the server.
- **Delete from server** deletes your records on the server and turns sending off. Turning it on again starts with a new number.
- Everything that can be collected is written in `backend/usage_schema.py`. Anything not there is dropped, on your computer and on the server.

For the Gadak team (whoever runs the server)

```bash
GADAK_SERVER_TOKEN=a-password ./.venv/bin/python -m server.app     # http://127.0.0.1:7321 · open this address and enter the password for the statistics
```

- To make Gadak send to this server, write `GADAK_COLLECT_URL=http://127.0.0.1:7321` in `backend/.env`. Leave it empty and Gadak neither asks nor sends.
- On the internet, set `GADAK_SERVER_DB` to a place that is not wiped and the statistics password `GADAK_SERVER_TOKEN`, and use an https address. The address and password are not written in the repository.

## 7. When something does not work

| What you see | Where to look |
|---|---|
| The app says “Could not find the Gadak folder.” | The repository folder was moved or renamed. Run `Install Gadak.command` in that folder again |
| The app says “Gadak could not start.” | Read the text shown with it. If a port is taken, see the next row but one; if it says `No module named flask`, run `Install Gadak.command` again |
| (Started without the app) the Gadak window does not open | Enter the address printed in the terminal (`http://127.0.0.1:7311`) in a browser yourself |
| “Another program is using port 7311.” | Write another number, such as `GADAK_PORT=7312`, in `backend/.env` (for the downloaded app, `~/.gadak/.env`). It may also be the other edition of Gadak; run one at a time |
| The downloaded app will not open: “unidentified developer” | System Settings → Privacy & Security → Open Anyway (1-1). If that does not help, check that you moved it to Applications |
| (Windows) opening the installer shows “Windows protected your PC” | More info → Run anyway (1-3) |
| (Windows) nothing opens when you start Gadak | Look at `C:\Users\your name\.gadak\gadak.log`. If it says another program is using port 7311, quit that program or set another number in the environment variable `GADAK_PORT` |
| (Windows) the installer stops with “Gadak is running.” | Close the Gadak window and try again |
| The status line says “Not signed in to Claude Code.” | Claude Code is installed but not signed in. Press **Connect** for the Claude subscription under **Connect AI** at the bottom left, or connect another AI (section 3). Then press **Resume sorting** |
| **Connect** never finishes | Check that you finished signing in in the browser. It stops after five minutes. If it stopped while fetching, check your internet connection and press again |
| The status line says “The API key is not valid.” · “Not enough API credit.” · “Hit the API rate limit.” | That is what the API key engine got back from the key’s company (Anthropic · OpenAI · Gemini). Enter the key again (3-2) or check that company’s console, then press **Resume sorting**. A free Gemini key has low per-minute and daily limits; after “Used up the daily Gemini limit.” press it once the limit resets |
| After pasting a key: “That does not look like an API key.” | Gadak accepts Anthropic (`sk-ant-`), OpenAI (`sk-`) and Gemini (`AIza` · `AQ.`) keys. Check that no characters are missing at either end. Keys from other providers (OpenRouter and the like) are not accepted |
| The status line says “You've hit your session limit” | That is your Claude subscription’s usage limit. Press **Resume sorting** after the time shown. Gadak’s sorting and your own Claude Code use share the same limit |
| You changed code but the new behaviour does not show | Restart Gadak. If an older Gadak is still running in the background, it is stopped and replaced with the current code |
| No chats show at all | Look at the number of record files under Sources. If you only used Claude Code on another computer, there are no records on this one |
| Station names are just the start of the questions | Read the status line at the bottom left. Either there is no engine (section 3) or it stopped on a limit. Press **Resume sorting** |
| No to-dos appear | Open Decision trace. If no turn was checked, nothing was flagged while sorting. If a turn was checked and nothing came of it, the dropped conclusions are shown |
| `--ping` fails | Check the sign-in with `claude auth status`, and your subscription’s usage limit |
| A web chat does not come in | Click the extension icon. If it says Gadak is off, start Gadak; if it says the running Gadak is an older version, restart Gadak; if it says it could not find the chat text, send the diagnostics. Reload tabs that were open before you added the extension |
| Gadak does not send by itself | Check ① that **What Gadak sends by itself** is under the to-do list, ② that Sources shows auto-run connected (it must be a chat opened after you connected), ③ that a note was made for that turn. If Gadak cannot finish its check within 40 seconds it does not send, and the note stays |
| The floating button is not showing | See whether View → Floating Button is ticked in Gadak’s menu bar. If it is, look along all four edges of the screen (it remembers where you put it) |
| Clicking the button only makes a sound and no strip map window appears | Gadak is still starting. Click again once the Gadak window shows its screen |
| A Cursor chat does not come in | In Cursor, look at Customize → Hooks and the Hooks output channel to see whether the hook ran |
| Cursor is slow after adding the hook | The hook waits for Gadak for at most 1.5 seconds. If it is still slow, remove the hook entries and tell the makers |
