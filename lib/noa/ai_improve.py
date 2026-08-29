# ai_improve.py - self-evolving long-term memory for the gpt assistants.
#
# The assistants keep a SMALL markdown file under /sd/Documents/ai_memory that
# records what they have learned: the user's stable preferences, which tools /
# commands worked, which failed, and useful facts about the device. The file is
# loaded back into the system prompt in agent mode (see memory_block), so the
# assistant carries its experience across sessions -- a simple self-improving
# loop. /improve (and the update_memory tool, and gpt_rt's periodic auto-run)
# all funnel through improve() below.
#
# The file is kept deliberately small: a bloated memory dilutes the assistant's
# focus, so the summarizer is told to prune and merge, and write_memory() caps
# the result with a hard character limit.

import os

try:
  import ujson
except ImportError:
  import json as ujson

try:
  import urequests as _requests
except ImportError:
  _requests = None

MEMORY_DIR = '/sd/Documents/ai_memory'
MEMORY_PATH = MEMORY_DIR + '/ai_memory.md'

# Cheap, fast text model for the summarization step, used when the caller passes
# no model (gpt_rt: its own model is a realtime/audio one and cannot do chat
# completions). The text frontends pass their active model, so this is gpt_rt's.
SUMMARY_MODEL = 'gpt-5.4-mini'
# It's still a reasoning model, and rewriting a memory file does not need deep
# thought - without this it thinks at the default effort and the tool call
# stalls the turn for minutes. Only sent to gpt-5* models; other endpoints
# would reject the field.
SUMMARY_EFFORT = 'low'
# No socket timeout on the summarizer POST. With SUMMARY_USES_ACTIVE_MODEL the
# rewrite runs on the active reasoning model, which sends nothing at all while
# it thinks, so any fixed guard just kills a call that was working. Trade-off:
# a genuinely stalled socket now hangs the update_memory tool until the app is
# restarted.

# Hard cap on the saved memory. A large file blurs the assistant's goal, so this
# is intentionally tight. Applied after the model rewrites the file.
MAX_MEMORY_CHARS = 2400
# How much recent context to feed the summarizer.
_MAX_CONVO_CHARS = 6000


def load_memory():
  """Return the saved memory text, or '' if there is none yet."""
  try:
    with open(MEMORY_PATH) as f:
      return f.read()
  except OSError:
    return ''


def memory_block():
  """The memory wrapped for injection into a system prompt, or '' if empty."""
  mem = load_memory().strip()
  if not mem:
    return ''
  return ("\n\n----- Learned memory -----\n"
          "These are your own evolving notes about this user and what works on "
          "this device, distilled from past sessions. Trust and apply them; keep "
          "them in mind, but don't recite them verbatim.\n%s\n" % mem)


_SYS = (
  "You maintain a COMPACT long-term memory file for an on-device AI assistant "
  "(voice and text) running on a small handheld device called Pocket Deck. You "
  "are given the assistant's existing memory and a recent conversation. Output "
  "an UPDATED version of the memory file.\n"
  "Record only durable, reusable knowledge:\n"
  "- the user's stable preferences (language, tone, recurring tasks, names, paths)\n"
  "- what WORKED: which function calls / tools and which shell commands succeeded\n"
  "- what FAILED or should be avoided: commands that errored, dead ends, mistakes\n"
  "- useful facts about this device and the user's files and workflow\n"
  "Rules:\n"
  "- Output ONLY the memory file content as markdown. No preamble, no code fences.\n"
  "- Keep it SMALL and high-signal: well under %d characters. A bloated memory "
  "blurs the assistant's focus, so prune stale or low-value lines and merge "
  "duplicates rather than appending endlessly.\n"
  "- Preserve still-useful existing notes; refine rather than discard them.\n"
  "- Never store secrets, API keys, or one-off chatter that won't matter next "
  "session.\n"
  "- If there is genuinely nothing worth remembering, return the existing memory "
  "unchanged." % MAX_MEMORY_CHARS
)


def build_messages(existing, conversation, stats):
  if conversation and len(conversation) > _MAX_CONVO_CHARS:
    conversation = conversation[-_MAX_CONVO_CHARS:]
  user = ("===== EXISTING MEMORY =====\n%s\n\n"
          "===== RECENT CONVERSATION =====\n%s\n" % (
            existing.strip() or '(empty)',
            conversation.strip() or '(none)'))
  if stats:
    user += "\n===== THIS SESSION'S TOOL OUTCOMES =====\n%s\n" % stats
  return [{"role": "system", "content": _SYS},
          {"role": "user", "content": user}]


def _request(api_key, messages, model, base_url=None, response_format=None):
  """Default summarizer call (Chat Completions). Returns the assistant text.

  `response_format` (e.g. {"type": "json_object"}) is forwarded when given so
  callers that need strict JSON get reliable output."""
  if _requests is None:
    raise Exception("no HTTP client available")
  url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
  payload = {"model": model, "messages": messages}
  if response_format is not None:
    payload["response_format"] = response_format
  if model and model.startswith("gpt-5"):
    payload["reasoning_effort"] = SUMMARY_EFFORT
  headers = {"Content-Type": "application/json",
             "Authorization": "Bearer " + api_key}
  r = _requests.post(url, headers=headers, data=ujson.dumps(payload).encode('utf-8'))
  try:
    data = r.json()
  finally:
    try:
      r.close()
    except Exception:
      pass
  if data.get("error"):
    e = data["error"]
    raise Exception(e.get("message", "error") if isinstance(e, dict) else str(e))
  choices = data.get("choices") or []
  if not choices:
    raise Exception("no choices returned")
  return choices[0].get("message", {}).get("content") or ''


def _ensure_dir():
  # Best-effort mkdir -p of MEMORY_DIR.
  cur = ''
  for p in MEMORY_DIR.strip('/').split('/'):
    cur += '/' + p
    try:
      os.stat(cur)
    except OSError:
      try:
        os.mkdir(cur)
      except OSError:
        pass


def write_memory(text):
  """Write the memory, enforcing the size cap. Returns the saved length."""
  text = text.strip()
  if len(text) >= MAX_MEMORY_CHARS:
    # Reserve one char for the trailing newline so the file never exceeds the cap.
    text = text[:MAX_MEMORY_CHARS - 1].rstrip() + "\n"
  _ensure_dir()
  with open(MEMORY_PATH, 'w') as f:
    f.write(text)
  return len(text)


def improve(api_key, conversation='', stats=None, model=None, base_url=None,
            requester=None):
  """Analyze the recent conversation and rewrite the compact memory.

  Returns (ok: bool, message: str). `requester` overrides the network call
  (signature: requester(api_key, messages, model, base_url) -> str) and is used
  by the tests."""
  existing = load_memory()
  if not ((conversation or '').strip() or existing.strip()):
    return (False, 'nothing to learn from yet')
  # A key is only required for OpenAI's hosted endpoint; local / self-hosted
  # OpenAI-compatible servers (Ollama, LM Studio, ...) run keyless.
  is_openai = (not base_url) or base_url.rstrip('/') == 'https://api.openai.com/v1'
  if is_openai and not api_key:
    return (False, 'no API key configured')
  messages = build_messages(existing, conversation or '', stats)
  call = requester or _request
  try:
    new_mem = call(api_key, messages, model or SUMMARY_MODEL, base_url)
  except Exception as e:
    return (False, 'memory update failed: %s' % str(e))
  if not new_mem or not new_mem.strip():
    return (False, 'the summarizer returned nothing')
  try:
    n = write_memory(new_mem)
  except Exception as e:
    return (False, 'could not save memory: %s' % str(e))
  return (True, 'memory updated (%d chars saved)' % n)
