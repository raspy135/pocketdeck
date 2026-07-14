
# gpt

`gpt` is a ChatGPT frontend for Pocket Deck. It supports text queries, voice input/output, file and image attachments, and an **agent mode** in which the model uses native function calling (tools) to write files, run and debug code, and even see and drive other apps on the device. **conversation mode** keeps context across turns.

Requires an OpenAI API key stored at `/config/openai_api_key`.

> The previous markdown-code-block agent (the older `gpt`) is still shipped as
> `gpt_l` ("legacy") if you need it. The library plumbing it provides
> (`chatgpt_util`, STT/TTS, logging) also lives in `gpt_l`.

## Basic Usage

```
gpt [options] [question]
```

With no question argument, an interactive prompt opens for multi-line input
(single-shot). In conversation mode (`-C`) a prompt opens that keeps talking to
you turn after turn.

**Quick examples:**

```
gpt what is the capital of France
gpt -f notes.txt notes2.txt -q summarize this
gpt -v
gpt -a write a temp script that prints the first 10 primes and run it
gpt -C -a  # Conversation mode with agent mode
gpt -Ca -r coder -f pd/app_development.md         # Set role as coder, agent mode, and let AI read development documentation
```

## Options

Option | Description
-------|------------
`-q text or file` | Explicit question. If a single filename is given, its content is used as the question.
`content` | Positional question text (alternative to `-q`).
`-a` | Agent mode — turn on the function-calling tools. See [Agent Mode](#agent-mode-a).
`-C` | Conversation mode — keep context across turns. See [Conversation Mode](#conversation-mode-c).
`-P` | Start in Plan mode (confirm each `command_with_return` / `write_file` before it runs). Default is Auto.
`-r name|text` | Role / persona. Presets: `assistant` (default) or `coder` (also turns tools on). Or a `/sd/roles/<name>.txt` file, or literal role text.
`-f file [file...]` | Attach one or more files as reference context. Also accepts URLs.
`-i img [img...]` | Attach image files or URLs for vision queries.
`-c` | Use clipboard content as reference text.
`-m model` | Model to use — a `name` from `/config/gpt.json`, a shortcut (`f`/`fast` → gpt-5.4-mini, `m`/`medium` → ngpt-5.4, `h`/`high` → gpt-5.5), or a raw model id. Default: the registry `default`. See [Model configuration](#model-configuration-configgptjson).
`--base-url url` | Override the endpoint base URL for this run.
`-e level` | Reasoning effort: `low`, `medium` (default), or `high`. Responses models only.
`-j` | Answer in Japanese. Also switches terminal font to Unicode automatically.
`-v` | Voice mode: record audio → STT → ask GPT → TTS reads answer aloud.
`-vt type` | TTS voice type. Options: `alloy`, `coral` (default), `echo`, `fable`, `onyx`, `nova`, `shimmer`.
`-n` | Do not save the response log.
`-nf` | No formatting (skip bold/markdown rendering).
`-s` | Silent mode — suppress progress indicators.
`--log-file file` | Internal: reuse a specific log filename across turns/iterations.

## Voice Mode (`-v`)

Voice mode combines STT and TTS into a single conversational interaction:

1. Records audio from the microphone (press any key to stop).
2. Transcribes audio via OpenAI Whisper (STT).
3. Sends transcription to GPT, optimized for spoken response.
4. Reads the response aloud via OpenAI TTS.

```
gpt -v
gpt -v -vt nova
```

By default STT/TTS use OpenAI (`gpt-4o-mini-transcribe` and `tts-1-hd`, WAV
output streamed straight to the audio engine). The speech backend is separate
from the LLM, so you can run a local LLM and still use OpenAI — or a local
OpenAI-compatible speech server — for voice. See [Audio backend](#audio-backend-sttts).

> Note: voice mode with a **local LLM** used to error because STT/TTS still went
> to OpenAI using the (empty) local key. STT/TTS now follow the configured audio
> backend; if you don't configure one, they use OpenAI and need a valid
> `/config/openai_api_key` even when the LLM is local.

## Inline Directives

Inside your message, you can embed `[[options]]` blocks to override options
per-message without re-typing flags on the command line.

```
[[options]]
```

Supported inline options:

Option | Effect
-------|-------
`-m model` | Override the model for this message.
`-e level` | Set reasoning effort (`low`/`medium`/`high`).
`-j` | Answer in Japanese.
`-c` | Include clipboard as reference.
`-nf` | Disable formatting.
`-n` | Do not save the log.
`-v` | Enable voice output.
`-vt type` | Set TTS voice type.
`-i img [img...]` | Attach image file(s) or URL(s).

`-f` is **not** accepted inside `[[...]]`; use a bare file reference instead (see
below).

## Prompt file syntax

You can give a file as a prompt, `gpt -q prompt.md`. It is useful with agent
mode `-a`. In the file you can use the following syntax:

### File reference

You can use an Obsidian-style file link to attach a file as reference context.

```markdown
[[note.md]]
Analyze note.md.
```

You can also set options inline with `[[...]]`:

```markdown
[[pd/app_development.md]]
[[-m gpt-5.5]]
[[-e high]]
[[/sd/py/hello.py]]

Modify hello.py so it prints hello in multiple languages, then run it.
```

To run such a prompt in agent mode:

```
gpt -a -q prompt.md
```

## Log Files

Responses are saved to `/sd/log/` by default (created automatically). The log
filename is copied to the clipboard after each session. Use `-n` to skip saving.

## File attachment (`-f`)

File attachment (-f) is one of the powerful option in gpt command. By attaching files, you can teach extra instruction or knowledge to AI. You can specify multiple files to AI.

## Agent Mode (`-a`)

Agent mode gives the AI model to read/write file, check status and make an application on the fly.

In agent mode, the AI knows what Pocket Deck is and how to operate the device. In coder role (-r coder), it also knows how to code.

When the model invokes a tool you'll see a `[Call]` line and a `[Result]` line.

### Tools in agent mode

AI can do the following things in agent mode.

- Command execution
- **Web search** — a `web_search` tool returns ranked results (title, URL, snippet) so the model gets current information without scraping search pages with `curl`. On genuine OpenAI models this uses OpenAI's hosted web search; on every other endpoint (local/Chat-Completions models, non-OpenAI providers, the voice agent) it runs on-device against DuckDuckGo, keyless. Drop a [Tavily](https://www.tavily.com) key at `/config/tavily_api_key` to upgrade the device-side search to Tavily's LLM-native results (free tier available).
- PEM file editing. AI can read the editor status and edit the currently open file.
- Read / write files. The old files are copied to /sd/backup.
- Launch application
- Take screenshot
- Send keycode
- Read the console output (scrollback) of a command-line app, so you can ask things like "what's the error in the console?"
- Read the device activity log at `/sd/elog/YYYY-MM-DD.md` (one file per day: app launches, file opens/saves, commands) to see what you've recently been doing or resume your work.
- (Voice agent only) Run a **timed routine** — a stretch or yoga sequence, workout intervals, guided breathing — pacing itself through the schedule with `wait_and_resume` (it speaks each move, then holds for the right number of seconds before the next).

In the voice agent (`gpt_rt -a`), press **`u`** for a quick "what's up?" — it silently checks today's activity log and what you're currently editing in PEM, then speaks a one-line summary (or says things look quiet).

**Timed programs (voice agent).** Ask the voice agent to walk you through anything with a timeline — e.g. *"instruct me through the stretch routine in stretch.md, following the timing."* It speaks the current step, then waits the right number of seconds and speaks the next one, and so on. The wait runs **in the background with the mic still live**, so you can interrupt hands-free at any time ("hold on", "my back hurts", "how many left?"); doing so pauses the program, and the agent picks the routine back up when you're ready.

**Skills.** Put reusable procedures in `/sd/Documents/skills/`, one markdown file per skill — a routine with steps and timings, a recurring workflow (a morning writing setup), or a document format to follow. The agent knows the folder: ask by name (*"do my morning ritual"*, *"coach me through the surf warm-up"*) or ask *"what skills do I have?"* and it reads the file and follows it. You can also invoke a skill explicitly, Claude-CLI style, by typing a slash and its name — `/morning_ritual` (press **Tab** to complete the name) — with `/skills` to list them. Built-in system skills ship in `/sd/lib/skills/` (e.g. `dashboard_design` for building graphical apps); your own skills in `/sd/Documents/skills/` take precedence on a name clash. When you teach it a procedure worth repeating, it can save the procedure there as a new skill.


### Auto vs Plan mode

Two execution modes control the effectful tools (`command_with_return` and
`write_file`):

- **Auto** (default) — tools run without asking.
- **Plan** (`-P`, or toggle at runtime) — each `command_with_return` /
  `write_file` is shown and you confirm it first. Press Enter / `y` to run, `n`
  to skip, or type a reason to decline (the reason is sent back to the model as
  feedback). Other tools (screen/app inspection) always run.

In conversation mode, **Shift-Tab** toggles Auto/Plan, or use `/mode`,
`/auto`, `/plan`.

## Conversation Mode (`-C`)

`gpt -C` opens an interactive session that keeps context across turns, so you can
have a back-and-forth without re-sending history (Responses models keep it
server-side via `previous_response_id`; Chat Completions models keep it locally).
Combine with `-a`/`-r coder` for an interactive coding assistant.

Line editing: arrows move the cursor, Up/Down browse history, Ctrl-A/E jump to
start/end, Ctrl-K/U kill to end/start, Ctrl-C cancels the current line.

**Japanese input:** Alt+` or Alt+j toggles a kana (romaji → kana → kanji) IME.
Use `-j` so the Unicode terminal font is loaded first.

### Slash commands

Command | Effect
--------|-------
`/help` | Show command help.
`/quit`, `/exit` | Leave the conversation.
`/clear`, `/reset` | Start fresh (clear the conversation context).
`/model [name]` | Show or set the model — a `name` from `/config/gpt.json`, a shortcut (`f`/`m`/`h`), or a raw id. Switching to a different endpoint resets the context.
`/models` | List the models configured in `/config/gpt.json`.
`/effort [level]` | Show or set reasoning effort (`low`/`medium`/`high`). Responses models only.
`/role [name\|text]` | Show or set the role (`assistant` or `coder`; resets context).
`/tools` | Toggle the function-calling tools on/off.
`/file <path>` | Attach a file as reference for the next message.
`/skills` | List available skills (your own plus the built-in system skills).
`/<skill-name>` | Run a skill by name, e.g. `/morning_ritual` (hyphens, underscores and spaces all match). Press **Tab** while typing the name to complete it, or to list the matching skills when several share the prefix. The agent reads the skill file and carries it out; anything after the name is passed as extra input.
`/compact` | Summarize and shrink the running context now. Chat Completions models only.
`/auto-compact [n]` | Auto-compact every `n` turns (`off` to disable). Chat Completions models only.
`/improve` | Improve AI agent knowledge. Save learned preferences and stable behavior notes from recent interaction history into a long-term memo; does not change core system rules or persona.
`/auto-improve [n]` | Auto-run `/improve` every `n` completed turns (`off` to disable). On by default (every 8 turns); shows the current setting when given no argument.

## Roles (`-r`)

A role sets the assistant's persona / system prompt.

- `assistant` (default) — a plain, concise helper.
- `coder` (aliases `coding`, `code`) — an expert MicroPython coding assistant
  for Pocket Deck; **this preset turns the tools on**.
- A path or a name under `/sd/roles/<name>.txt` — your own role text from a file.
- Any other text is used verbatim as the role.

## Model configuration (`/config/gpt.json`)

If you just use OpenAI APIs, skip this part.

`gpt` is the single frontend for every model. Which models are available — and
which API each one speaks — is defined in `/config/gpt.json`, an Ollama-style
registry. It's created with OpenAI defaults the first time `gpt` runs.

```json
{
  "default": "gpt-5.4",
  "models": [
    { "name": "gpt-5.4", "api": "responses", "model": "gpt-5.4" },
    { "name": "gpt-5.5", "api": "responses", "model": "gpt-5.5" },
    { "name": "llama3",  "api": "chat",
      "base_url": "http://192.168.1.50:11434/v1", "model": "llama3.1" }
  ]
}
```

Per-entry fields (only `name` is required):

Field | Meaning
------|--------
`name` | The label you pass to `-m` and `/model` (e.g. `-m llama3`).
`api` | `responses` — OpenAI's Responses API (server-side context, reasoning `effort`, and OpenAI's hosted web search on genuine OpenAI endpoints). `chat` — the portable Chat Completions API used by Ollama, local servers, and other providers. Both get web search: non-OpenAI endpoints fall back to the on-device `web_search` tool.
`base_url` | Endpoint base. Default: `https://api.openai.com/v1`.
`model` | The actual model id sent to the API. Default: same as `name`.
`effort` | Optional default reasoning effort for a `responses` entry.
`key` | Optional API key (bearer token) for this entry, for a provider that needs its own — e.g. xAI. With no `key`, an OpenAI endpoint uses `/config/openai_api_key` and any other endpoint is called without authorization.

`default` names the entry used when `-m` is omitted. An OpenAI endpoint with no
`key` falls back to `/config/openai_api_key`; a third-party provider (e.g. xAI)
carries its own `key`; local endpoints (Ollama, etc.) need none.

```json
{ "name": "grok", "api": "responses",
  "base_url": "https://api.x.ai/v1", "model": "grok-4",
  "key": "xai-..." }
```

**Selecting a model:** `gpt -m llama3 ...`, or in conversation mode `/model llama3`
(with `/models` to list them). You can even switch between an OpenAI model and a
local model in the middle of one conversation — the context resets on the switch.

`/compact` and `/auto-compact [n]` (summarize and shrink the running context) are
offered for `chat` models, where the whole history is resent each turn; `/effort`
applies to `responses` models. A raw model id or a shortcut (`f`/`m`/`h`) still
works with `-m` even if it isn't registered — it's treated as an OpenAI Responses
model.

> The Chat Completions client lives in the internal `gpt_c` module; you don't run
> it directly anymore. An old `gpt_c ...` command still works — it's routed
> through `gpt`.

### Audio backend (STT/TTS)

If you just use OpenAI APIs, skip this part.

Speech is configured in the **same** `/config/gpt.json`, as an entry with
`api: "audio"` — so voice can use a different endpoint than the LLM. This is what
lets you run a **local LLM** while keeping OpenAI (or a local speech server) for
voice. With no audio entry selected, `gpt` defaults to OpenAI.

An audio entry speaks the OpenAI audio API shape — `POST {base_url}/audio/speech`
and `POST {base_url}/audio/transcriptions`. Several local servers implement it:
[speaches](https://github.com/speaches-ai/speaches) and LocalAI for STT;
openedai-speech, [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), and
LocalAI for TTS. 

Audio-entry fields:

Field | Meaning
------|--------
`name` | The label other entries reference via their `audio` field.
`api` | Must be `audio`.
`base_url` | Speech endpoint base (`http://` allowed for local servers). Default: `https://api.openai.com/v1`.
`key` | Bearer token for the speech server. Omit for a keyless local server; on an OpenAI `base_url` it falls back to `/config/openai_api_key`.
`tts_model` | TTS model id. Default: `tts-1-hd`.
`stt_model` | STT model id. Default: `gpt-4o-mini-transcribe`.
`voice` | Default TTS voice (overridable per run with `-vt`). Default: `coral`.
`format` | TTS `response_format`. Default: `wav`. The device can only play **WAV (16-bit PCM)** — leave this as `wav`; `mp3`/`opus`/etc. won't play. Any sample rate is fine (read from the WAV header).

The TTS server must **stream** its response; the device plays audio as it arrives.

Two ways to select the audio backend:

- **Per LLM entry** — add `"audio": "<name>"` to a model entry.
- **Registry default** — add a top-level `"audio": "<name>"` used whenever the
  active LLM entry has no `audio` of its own.

```json
{
  "default": "local",
  "audio": "openai-voice",
  "models": [
    { "name": "local", "api": "chat",
      "base_url": "http://192.168.1.50:11434/v1", "model": "llama3.1",
      "audio": "kokoro" },

    { "name": "openai-voice", "api": "audio" },

    { "name": "kokoro", "api": "audio",
      "base_url": "http://192.168.1.50:8880/v1",
      "tts_model": "kokoro", "stt_model": "Systran/faster-whisper-small",
      "voice": "af_sky", "format": "wav" }
  ]
}
```

Here `-m local` uses the `kokoro` speech server; any other model with no `audio`
field falls back to `openai-voice` (the registry default). An `audio` entry is
never selectable with `-m` — it's only referenced by name.
