# gpt_c.py - ChatGPT client built on the Chat Completions API instead of the
# OpenAI-proprietary Responses API used by gpt.py.
#
# Why a separate frontend: the Responses API keeps conversation state on the
# server (previous_response_id), uses a flat tool schema and a built-in
# web_search tool, and ships input/output item shapes unique to OpenAI. The Chat
# Completions API (/v1/chat/completions) is the portable lingua franca that every
# provider and local server speaks: client-side `messages` history, a nested tool
# schema, and `tool`-role results. Talking Chat Completions means you can swap
# models/endpoints just by changing -m and the base URL. No reasoning_effort is
# sent, so plain (non-reasoning) models on any provider work unchanged.
#
# This reuses gpt.py (imported as `gpt`) and gpt_l.py (as `gptl`) for all the
# shared plumbing: the function tools and their implementations, the read_line
# editor, present_response, role/instruction assembly, STT/TTS, logging and the
# thinking animation. Only the API-specific seams are overridden here:
#   - build_tools_c(): wrap gpt.build_tools' flat function dicts into the nested
#     Chat Completions format (so the tool descriptions live in one place).
#   - chatgpt_chat: a chatgpt_agent subclass whose ask_agent drives a client-side
#     `messages` list (replacing previous_response_id) over /v1/chat/completions.
#   - conversation persistence to local JSON for --resume / --resume-id (Chat
#     Completions has no server-side state to resume).
#
# Differences from gpt.py (by design):
#   - No built-in web_search. The agent can still fetch pages with `curl` via
#     command_with_return.
#   - Full history is sent each round (Chat Completions is stateless), so long
#     agent turns cost more tokens; _prune_old_images() bounds memory by dropping
#     stale screenshots from history.

import sys
# On a PC (CPython) install stand-ins for the device-only modules before any are
# imported. Importing gpt below already does this, but be explicit/idempotent.
_IS_PC = sys.implementation.name != 'micropython'
if _IS_PC:
  import pc_compat
  pc_compat.install()

import ujson
import ubinascii
import time
import os
import gc
import pdeck
import pdeck_utils as pu
import gpt          # the Responses-API frontend; we reuse its helpers/tools
import gpt_l as gptl

el = gptl.el


# ----------------------------------------------------------------------------
# Endpoint. The model registry (which base_url / model to use) now lives in
# gpt.py (/config/gpt.json); this module is an internal client the unified gpt
# frontend constructs for 'chat'-api entries. The API key stays separate in
# /config/openai_api_key; local endpoints (Ollama, etc.) need no key.
# ----------------------------------------------------------------------------

DEFAULT_BASE = "https://api.openai.com/v1"


def chat_url(base_url=None):
  return (base_url or DEFAULT_BASE).rstrip("/") + "/chat/completions"


# ----------------------------------------------------------------------------
# Conversation persistence (Chat Completions has no server-side state, so to
# continue a conversation across invocations we save the messages list locally
# and reuse gpt_l's rolling session-id list to remember which file is latest).
# ----------------------------------------------------------------------------

def conv_dir():
  if _IS_PC:
    d = os.path.expanduser("~/.config/gpt")
    try:
      os.makedirs(d, exist_ok=True)
    except Exception:
      pass
    return d
  return "/sd/log"


def conv_path(cid):
  return conv_dir() + "/gptconv_" + cid + ".json"


def make_conv_id():
  t = time.gmtime(time.time() + pu.timezone * 60 * 15)
  return "%02d%02d_%02d%02d%02d" % (t[1], t[2], t[3], t[4], t[5])


def save_conversation(messages, cid):
  try:
    with open(conv_path(cid), "w") as f:
      ujson.dump(messages, f)
    return True
  except Exception:
    return False


def load_conversation(cid):
  """Return the saved messages list for `cid`, or None if missing/unreadable."""
  try:
    with open(conv_path(cid), "r") as f:
      data = ujson.load(f)
    if isinstance(data, list):
      return data
  except Exception:
    pass
  return None


# ----------------------------------------------------------------------------
# Tool schema: reuse gpt.build_tools (flat function format) and wrap each into
# the nested Chat Completions shape. web_search is intentionally not included.
# ----------------------------------------------------------------------------

def build_tools_c(app_list, agent=False):
  flat = gpt.build_tools(app_list, agent=agent, web_search=False)
  tools = []
  for t in flat:
    if t.get("type") != "function":
      continue
    tools.append({
      "type": "function",
      "function": {
        "name": t.get("name", ""),
        "description": t.get("description", ""),
        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
      },
    })
  return tools


# ----------------------------------------------------------------------------
# Chat Completions agent client
# ----------------------------------------------------------------------------

class chatgpt_chat(gpt.chatgpt_agent):
  # Capability flags the shared driver in gpt.main() reads (override the
  # Responses defaults on gpt.chatgpt_agent): no server-side reasoning effort,
  # no built-in web_search, and this client can compact its local history.
  API = "chat"
  USE_EFFORT = False
  USE_WEB_SEARCH = False
  CAN_COMPACT = True

  def __init__(self, vs, base_url=None):
    super().__init__(vs)
    # /v1/chat/completions on the configured base (default OpenAI).
    self.base_url = base_url or DEFAULT_BASE
    self.url = chat_url(base_url)
    # Client-side conversation state. messages[0] is the system prompt; user /
    # assistant / tool turns accumulate here (replaces prev_response_id).
    self.messages = []
    # Set by resume_from/persist_session so a resumed session is saved back to
    # the same conversation id.
    self.conv_id = None

  # --- uniform client interface (shared driver in gpt.main() calls these) ----

  def reset_context(self):
    self.messages = []

  def build_tools_for(self, app_list, agent):
    return build_tools_c(app_list, agent=agent)

  def resume_from(self, rid, vs=None, silent=False):
    """Load a saved messages list ('last' = most recent). Returns the id resumed
    from, or None if nothing was loaded."""
    resolved = gptl.last_session_id() if rid == 'last' else rid
    msgs = load_conversation(resolved) if resolved else None
    if msgs:
      self.messages = msgs
      self.conv_id = resolved
      if not silent and vs is not None:
        print("Resuming session %s" % resolved, file=vs)
      return resolved
    if not silent and vs is not None:
      print("No previous session to resume; starting new.", file=vs)
    return None

  def persist_session(self, turn_message, resumed_from):
    """Save the conversation so a later --resume-id can continue it."""
    if not self.messages:
      return
    cid = resumed_from or self.conv_id or make_conv_id()
    if save_conversation(self.messages, cid):
      gptl.save_session(cid, turn_message, replace_id=resumed_from)

  # --- request payload -------------------------------------------------------

  def _build_user_content(self, message, references, images):
    """Chat Completions user content: a plain string when text-only, otherwise a
    content list mixing text and image_url parts."""
    if references:
      ref_text = ("I put some attached text files as reference. Then answer the "
                  "question by using attached information. You are not limited to "
                  "reference the attached text, you can use all your knowledge. \n")
      for i, item in enumerate(references):
        ref_text += "----- reference %d -----\n%s\n" % (i, item)
      ref_text += "----- Question -----\n"
      message = ref_text + message
    if not images:
      return message
    content = [{"type": "text", "text": message}]
    for img in images:
      if type(img) == str:
        url = img
      else:
        b64 = ubinascii.b2a_base64(img).decode('utf-8').strip()
        url = "data:image/jpeg;base64," + b64
      content.append({"type": "image_url", "image_url": {"url": url}})
    return content

  def _prune_old_images(self):
    """Drop image_url parts from prior messages so a long conversation full of
    screenshots doesn't exhaust the heap (Chat Completions resends everything
    each round). Images only need to live for the turn they're used in."""
    for m in self.messages:
      c = m.get("content")
      if not isinstance(c, list):
        continue
      kept = []
      dropped = False
      for it in c:
        if isinstance(it, dict) and it.get("type") == "image_url":
          dropped = True
          continue
        kept.append(it)
      if not dropped:
        continue
      if not kept:
        m["content"] = "[image omitted to save memory]"
      elif len(kept) == 1 and isinstance(kept[0], dict) and kept[0].get("type") == "text":
        m["content"] = kept[0].get("text", "")
      else:
        m["content"] = kept

  def _ensure_system(self, instructions):
    """Keep messages[0] as the current system prompt so role/tool/instruction
    changes mid-conversation take effect on the next turn."""
    if not instructions:
      return
    if self.messages and self.messages[0].get("role") == "system":
      self.messages[0]["content"] = instructions
    else:
      self.messages.insert(0, {"role": "system", "content": instructions})

  @staticmethod
  def _content_text(content):
    """Assistant content is usually a string; some providers return a list of
    parts. Reduce either to plain text."""
    if isinstance(content, str):
      return content
    if isinstance(content, list):
      out = ""
      for it in content:
        if isinstance(it, dict) and it.get("type") in ("text", "output_text"):
          out += it.get("text", "")
      return out
    return ""

  @staticmethod
  def _slim_tool_calls(tool_calls):
    """Reconstruct only the fields Chat Completions needs when the assistant's
    tool_calls are echoed back on the next request (drops index/extra fields)."""
    out = []
    for tc in tool_calls:
      fn = tc.get("function", {}) or {}
      out.append({
        "id": tc.get("id", ""),
        "type": "function",
        "function": {
          "name": fn.get("name", ""),
          "arguments": fn.get("arguments", "") or "",
        },
      })
    return out

  def ask_agent(self, message, references, images, model, instructions,
                effort=None, tools=None, silent=False, max_iters=25):
    """Run one user turn over Chat Completions: append the user message, resolve
    any tool calls, and return the model's final text. self.messages carries the
    whole conversation so the next turn (conversation mode) continues it. `effort`
    is accepted for a uniform signature with the Responses client but unused
    here (Chat Completions has no server-side reasoning effort)."""
    self._prune_old_images()
    self._ensure_system(instructions)
    pre_len = len(self.messages)   # rollback point if the turn fails outright
    self.messages.append({"role": "user",
                          "content": self._build_user_content(message, references, images)})

    final_text = None
    got_assistant = False
    pdeck.led(2, 0)  # clear the "result ready" indicator at the start of a turn

    ask_stop = False  # set when the model calls ask_user: next round is text-only
    for i in range(max_iters + 1):
      force_final = (i == max_iters) or ask_stop
      gc.collect()  # large JSON/base64 each round-trip fragments the small heap
      payload = {
        "model": model,
        "messages": self.messages,
      }
      if tools:
        payload["tools"] = tools
        if force_final:
          payload["tool_choice"] = "none"

      pdeck.led(1, 40)  # working: waiting for the model's response
      if not silent:
        _anim = gptl.ThinkingAnimation(self.vs, "Asking GPT..")
      response = self.post(self.url, ujson.dumps(payload).encode('utf-8'))
      try:
        data = response.json()
      except:
        if not silent:
          _anim.stop()
        print("Error: Non-JSON response (%s)" % response.status_code, file=self.vs)
        print(response.text[:200], file=self.vs)
        response.close()
        pdeck.led(1, 0)
        break
      response.close()
      if not silent:
        _anim.stop()
      pdeck.led(1, 0)  # got the response

      if data.get("error"):
        err = data["error"]
        msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)
        print("API Error: %s" % msg, file=self.vs)
        break

      choices = data.get("choices") or []
      if not choices:
        print("API Error: no choices returned", file=self.vs)
        break
      msg = choices[0].get("message", {}) or {}
      content = msg.get("content")
      tool_calls = msg.get("tool_calls") or []

      # Record the assistant turn. The tool_calls must be echoed verbatim on the
      # next request so the following tool results can reference their ids.
      assistant_msg = {"role": "assistant", "content": self._content_text(content)}
      if tool_calls:
        assistant_msg["tool_calls"] = self._slim_tool_calls(tool_calls)
      self.messages.append(assistant_msg)
      got_assistant = True
      text_out = self._content_text(content)
      if text_out:
        final_text = text_out

      if not tool_calls:
        break

      if force_final:
        # Model ignored tool_choice="none" and still asked for calls. Answer them
        # with stubs so the history stays valid (an assistant message with
        # tool_calls must be followed by a tool result for every call).
        for tc in tool_calls:
          self.messages.append({
            "type": "tool", "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "content": "[Reached tool-call limit; not executed.]",
          })
        print("\n[Reached tool-call limit; stopping here.]", file=self.vs)
        break

      # Execute the requested calls; each appends a tool-role result message.
      self.pending_image = None
      for tc in tool_calls:
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        call_id = tc.get("id", "")
        arguments = fn.get("arguments", "") or ""
        print("\n%s[Call]%s %s" % (el.bold(), el.bold_off(), self._call_display(name, arguments)), file=self.vs)
        # Plan mode: the two effectful tools must be confirmed before they run.
        if self.mode == 'plan' and name in ('command_with_return', 'write_file'):
          approved, feedback = self.confirm_tool(name, arguments)
          if not approved:
            result = "User declined to run %s (Plan mode)." % name
            if feedback:
              result += " User feedback: " + feedback
            print("%s[Skipped]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            continue
        try:
          result = self.execute_function_call(call_id, name, arguments)
        except BaseException as e:
          # Never let a tool (e.g. a module raising SystemExit) kill the session.
          result = "Error: %r" % (e,)
        print("%s[Result]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": result})

      # A capture_screen call leaves a base64 PNG to feed back as a user image.
      # It must come AFTER every tool result (each tool_call needs its answer
      # first), as a fresh user turn.
      if self.pending_image is not None:
        self.messages.append({
          "role": "user",
          "content": [{
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + self.pending_image},
          }],
        })
        self.pending_image = None

      # An ask_user call ends the turn: the next round is text-only so the
      # model states its question and control returns to the user.
      if self.user_question is not None:
        ask_stop = True
        self.user_question = None

    # A turn that produced nothing (hard failure) is rolled back so it doesn't
    # leave an orphan user message that would confuse the next turn.
    if final_text is None and not got_assistant:
      del self.messages[pre_len:]
    return final_text

  # --- context compaction ----------------------------------------------------
  # Chat Completions is stateless, so the whole `messages` list is resent each
  # turn and grows without bound. Compaction asks the model to summarize the
  # conversation, then replaces the history with [system, summary, ack] so we
  # keep the gist at a fraction of the tokens. This is the standard approach.

  COMPACT_INSTRUCTION = (
    "Summarize the conversation so far as a concise but complete briefing so it "
    "can continue seamlessly with no loss of important context. Preserve: the "
    "user's goal and any constraints or preferences they stated, key facts and "
    "decisions, the current state of any files/code/tasks (include exact paths "
    "and names), and anything still open or in progress. Use compact bullet "
    "points. Omit pleasantries; output only the summary.")

  def _chat_once(self, messages, model, silent=False, label="Asking GPT.."):
    """One plain (no-tools) Chat Completions call returning the assistant text,
    or None on failure. Used by compaction."""
    gc.collect()
    payload = {"model": model, "messages": messages}
    pdeck.led(1, 40)
    if not silent:
      _anim = gptl.ThinkingAnimation(self.vs, label)
    response = self.post(self.url, ujson.dumps(payload).encode('utf-8'))
    try:
      data = response.json()
    except:
      if not silent:
        _anim.stop()
      response.close()
      pdeck.led(1, 0)
      return None
    response.close()
    if not silent:
      _anim.stop()
    pdeck.led(1, 0)
    if data.get("error"):
      err = data["error"]
      print("API Error: %s" % (err.get("message", "Unknown error") if isinstance(err, dict) else err), file=self.vs)
      return None
    choices = data.get("choices") or []
    if not choices:
      return None
    return self._content_text(choices[0].get("message", {}).get("content"))

  def compact(self, model, silent=False):
    """Replace the conversation history with a model-written summary. Returns the
    summary text on success, or None (history unchanged) on failure / nothing to
    do. The original system prompt is preserved as messages[0]."""
    sys_msg = None
    if self.messages and self.messages[0].get("role") == "system":
      sys_msg = self.messages[0]
    # Nothing meaningful to compress yet (just system + at most one exchange).
    convo_len = len(self.messages) - (1 if sys_msg else 0)
    if convo_len < 3:
      return None
    self._prune_old_images()  # don't spend tokens summarizing old screenshots
    req = list(self.messages)
    req.append({"role": "user", "content": self.COMPACT_INSTRUCTION})
    summary = self._chat_once(req, model, silent=silent, label="Compacting context..")
    if not summary:
      return None
    new_msgs = []
    if sys_msg:
      new_msgs.append(sys_msg)
    new_msgs.append({"role": "user",
                     "content": "Summary of the conversation so far (continue from this point):\n\n" + summary})
    new_msgs.append({"role": "assistant",
                     "content": "Understood — I'll continue from that summary."})
    self.messages = new_msgs
    gc.collect()
    return summary

  def _improve_conversation(self):
    """Recent transcript for the self-evolving memory (run_self_improve). Built
    from the local message history, skipping the system prompt and tool plumbing."""
    lines = []
    for m in self.messages:
      role = m.get("role")
      if role == "system":
        continue
      text = self._content_text(m.get("content"))
      if not text:
        continue
      who = "User" if role == "user" else ("AI" if role == "assistant" else role)
      lines.append("%s: %s" % (who, text))
    return "\n\n".join(lines[-24:])

# gpt_c is one of the assistant modules refused by command_with_return's
# recursion guard (gpt_tools.ToolExecBase.RECURSIVE_GUARD), so no override is
# needed here — the shared executors are inherited via gpt.chatgpt_agent.


# ----------------------------------------------------------------------------
# main - gpt_c is now an internal module. The user-facing frontend is `gpt`,
# which constructs chatgpt_chat for 'chat'-api entries in /config/gpt.json. This
# shim keeps an old `gpt_c ...` invocation working by routing it through gpt so
# nothing that referenced gpt_c directly breaks.
# ----------------------------------------------------------------------------

def main(vs, args_in):
  import gpt
  return gpt.main(vs, ['gpt'] + list(args_in[1:]))


# On a PC: `python3 gpt_c.py ...` still works, routed through the gpt frontend.
if __name__ == '__main__':
  main(pc_compat.PCStream(), ['gpt_c'] + sys.argv[1:])
