#!/usr/bin/env python3
# Self-check for the ESC interrupt during a GPT turn. Run from the repo root:
#   python3 -B test_gpt_interrupt.py
# Desktop (CPython) only -- drives the animation and the tool gate with fakes.

import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
                for p in ('lib', 'lib/noa')]

import json

import gpt_l as gptl
import gpt
import gpt_c


class FakeV:
  """Just enough vscreen for ThinkingAnimation: a key queue and a sink."""
  def __init__(self, keys=b''):
    self.keys = keys
    self.injected = b''
    self.cb = None

  def callback(self, fn):
    self.cb = fn

  def finished(self):
    pass

  def set_draw_color(self, c):
    pass

  def read_nb_bytes(self, n):
    d, self.keys = self.keys[:n], self.keys[n:]
    return (len(d), d)

  def send_char(self, d):
    self.injected += d


class FakeVS:
  def __init__(self, keys=b''):
    self.v = FakeV(keys)
    self.out = []

  def write(self, s):
    self.out.append(s)

  def text(self):
    return ''.join(self.out)


def test_animation_interrupt():
  gptl._IS_PC = False           # take the device path (callback + key polling)
  try:
    vs = FakeVS(b'hi\x1bthere')
    a = gptl.ThinkingAnimation(vs, 'Asking GPT.. (ESC to interrupt)',
                               'Asking GPT.. (ESC pressed, waiting for AI)')
    assert vs.v.cb is not None, 'frame callback not registered'
    for _ in range(4):
      a.update(False)
    assert a.interrupted
    assert a.label == 'Asking GPT.. (ESC pressed, waiting for AI)', a.label
    a.stop()
    assert vs.v.injected == b'hithere', vs.v.injected  # type-ahead handed back

    vs2 = FakeVS(b'abc')
    b = gptl.ThinkingAnimation(vs2, 'x')   # no interrupt label: never changes
    for _ in range(4):
      b.update(False)
    assert not b.interrupted
    assert b.label == 'x'
    b.stop()
    assert vs2.v.injected == b'abc'
  finally:
    gptl._IS_PC = True


def sse_body(events):
  """Encode events the way the API does: chunked framing is stripped by the
  reader above us, so this is the de-chunked SSE byte stream."""
  import json
  out = b''
  for e in events:
    if 'type' in e:                       # Responses names its events
      out += b'event: ' + e['type'].encode() + b'\n'
    out += b'data: ' + json.dumps(e).encode() + b'\n\n'
  out += b'data: [DONE]\n\n'
  return out


class FakeResp:
  def __init__(self, body, sse=True, status_code=200):
    self.sse = sse
    self.status_code = status_code
    self.closed = False
    self.raw = FakeRaw(body)

  def close(self):
    self.closed = True


class FakeRaw:
  def __init__(self, body):
    self.body = body

  def read(self, n):
    d, self.body = self.body[:n], self.body[n:]
    return d


def test_stream_round():
  final = {"id": "resp_1", "output": [
    {"type": "function_call", "name": "command_with_return",
     "call_id": "c1", "arguments": '{"command": "ls /sd"}'}]}
  body = sse_body([
    {"type": "response.reasoning_summary_text.delta", "delta": "Listing "},
    {"type": "response.reasoning_summary_text.delta", "delta": "the card."},
    {"type": "response.output_item.added",
     "item": {"type": "function_call", "name": "command_with_return"}},
    {"type": "response.function_call_arguments.delta", "delta": '{"command": '},
    {"type": "response.function_call_arguments.delta", "delta": '"ls /sd"}'},
    {"type": "response.completed", "response": final},
  ])
  vs = FakeVS()
  agent = gpt.chatgpt_agent(vs)
  resp = FakeResp(body)
  agent.stream_post = lambda url, payload: resp

  data = agent._stream_round({"model": "m", "reasoning": {"effort": "low"}})
  assert data == final, data
  out = vs.text()
  assert '[Thinking]' in out and 'Listing the card.' in out, out
  assert '[Call]' in out and 'command_with_return' in out, out
  # a blank line closes the thinking block, and only one
  assert 'Listing the card.' + gptl.el.reset_font_color() + '\n\n' \
         + gptl.el.bold() + '[Call]' in out, repr(out)
  assert '{"command": "ls /sd"}' in out, out
  assert resp.closed

  # the request itself must ask for a summary, and must not mutate the caller's
  # payload (it is reused by the blocking fallback)
  payload = {"model": "m", "reasoning": {"effort": "low"}}
  sent = {}
  agent.stream_post = lambda url, data: (sent.update(json.loads(data)),
                                         FakeResp(body))[1]
  agent._stream_round(payload)
  assert sent['stream'] is True
  assert sent['reasoning']['summary'] == 'auto'
  assert payload == {"model": "m", "reasoning": {"effort": "low"}}, payload


def test_stream_arg_echo_is_capped():
  huge = '{"path": "/sd/x.py", "content": "' + 'A' * 4000 + '"}'
  body = sse_body([
    {"type": "response.output_item.added",
     "item": {"type": "function_call", "name": "write_file"}},
    {"type": "response.function_call_arguments.delta", "delta": huge},
    {"type": "response.completed", "response": {"id": "r", "output": []}},
  ])
  vs = FakeVS()
  agent = gpt.chatgpt_agent(vs)
  agent.stream_post = lambda url, payload: FakeResp(body)
  agent._stream_round({"model": "m"})
  out = vs.text()
  assert '/sd/x.py' in out                       # the useful part still shows
  assert out.count('A') <= agent.ARG_ECHO_MAX    # but not the whole file
  assert '...' in out


def chat_chunk(delta):
  return {"choices": [{"delta": delta, "index": 0}]}


def test_chat_stream_round():
  """Chat Completions has no 'completed' event: the deltas are the message, so
  they must be reassembled into what the loop parses."""
  body = sse_body([
    chat_chunk({"reasoning_content": "The user wants "}),
    chat_chunk({"reasoning_content": "a listing."}),
    chat_chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "command_with_return",
                                             "arguments": '{"comm'}}]}),
    chat_chunk({"tool_calls": [{"index": 0,
                                "function": {"arguments": 'and": "ls /sd"}'}}]}),
    chat_chunk({"content": "Here you go."}),
  ])
  vs = FakeVS()
  agent = gpt_c.chatgpt_chat(vs)
  agent.stream_post = lambda url, payload: FakeResp(body)

  data = agent._stream_round({"model": "m", "messages": []})
  msg = data["choices"][0]["message"]
  assert msg["content"] == "Here you go.", msg
  tc = msg["tool_calls"][0]
  assert tc["id"] == "call_1"
  assert tc["function"]["name"] == "command_with_return"
  assert tc["function"]["arguments"] == '{"command": "ls /sd"}', tc
  out = vs.text()
  assert '[Thinking]' in out and 'The user wants a listing.' in out, out
  assert '[Call]' in out and 'ls /sd' in out, out
  assert 'Here you go.' in out and agent.text_shown

  # an empty stream is not a valid message: fall back and re-ask
  agent2 = gpt_c.chatgpt_chat(FakeVS())
  agent2.stream_ok = True
  agent2.stream_post = lambda url, payload: FakeResp(sse_body([]))
  assert agent2._stream_round({"model": "m"}) is None
  assert agent2.stream_ok is False


def test_stream_falls_back():
  vs = FakeVS()
  agent = gpt.chatgpt_agent(vs)
  assert agent.stream_ok is False, 'streaming must be opt-in (--stream / /stream)'
  agent.stream_ok = True
  # endpoint answered with a plain body: no SSE, so the blocking path takes over
  agent.stream_post = lambda url, payload: FakeResp(b'{}', sse=False, status_code=400)
  assert agent._stream_round({"model": "m"}) is None
  assert agent.stream_ok is False
  assert 'no event stream' in vs.text() and '400' in vs.text(), vs.text()
  # SSE that stops before response.completed is also a fallback
  agent.stream_ok = True
  agent.stream_post = lambda url, payload: FakeResp(sse_body(
    [{"type": "response.reasoning_summary_text.delta", "delta": "hm"}]))
  assert agent._stream_round({"model": "m"}) is None
  assert agent.stream_ok is False
  assert 'ended without a complete response' in vs.text(), vs.text()


def test_gate_tool():
  agent = gpt.chatgpt_agent(FakeVS())
  answers = []
  agent.confirm_tool = lambda name, args: answers.pop(0)

  # auto mode: nothing is gated
  agent.mode = 'auto'
  assert agent.gate_tool('command_with_return', '{}') is None

  # plan mode gates only the effectful tools
  agent.mode = 'plan'
  assert agent.gate_tool('read_file', '{}') is None
  answers.append((True, ''))
  assert agent.gate_tool('write_file', '{}') is None
  answers.append((False, 'do it differently'))
  out = agent.gate_tool('write_file', '{}')
  assert 'declined' in out and 'do it differently' in out, out

  # after an ESC interrupt every call is gated, whatever the mode
  agent.mode = 'auto'
  agent.interrupted = True
  answers.append((True, ''))
  assert agent.gate_tool('read_file', '{}') is None
  answers.append((False, ''))
  assert 'declined' in agent.gate_tool('read_file', '{}')
  assert not answers, 'confirm_tool was not called as expected'


def test_interrupt_is_one_round_only():
  """The tool loop clears the flag after each batch, so the chain resumes in
  the standing mode instead of staying stuck in plan mode."""
  import re
  for path, marker in (('lib/gpt.py', 'next_input.append'),
                       ('lib/gpt_c.py', 'self.messages.append')):
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), path)).read()
    body = src.split('declined = self.gate_tool', 1)[1]
    clear = body.index('self.interrupted = False')
    assert body.index(marker) < clear, path        # cleared after the batch runs
    assert clear < body.index('pending_image'), path


def test_note_interrupt():
  agent = gpt.chatgpt_agent(FakeVS())
  assert agent.interrupted is False
  agent.note_interrupt(False)
  assert agent.interrupted is False
  agent.note_interrupt(True)
  assert agent.interrupted is True


if __name__ == '__main__':
  test_animation_interrupt()
  test_stream_round()
  test_stream_arg_echo_is_capped()
  test_chat_stream_round()
  test_stream_falls_back()
  test_gate_tool()
  test_interrupt_is_one_round_only()
  test_note_interrupt()
  print('OK')
