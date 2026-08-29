#!/usr/bin/env python3
# Self-check for the update_memory path (ai_improve.improve + the gpt.py
# transcript hook). Run from the repo root:
#   python3 -B test_ai_improve.py
# Desktop (CPython) only -- the HTTP client is faked, nothing is sent.

import json
import os
import sys
import types

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
                for p in ('lib', 'lib/noa')]

sys.modules['ujson'] = json
import pc_compat
pc_compat.install()

import ai_improve
import gpt
import gpt_tools

TMP = '/tmp/claude-1000/test_ai_improve'


class FakeRequests:
  """Stands in for urequests: records the call, returns a canned reply."""
  def __init__(self):
    self.kw = None
    self.payload = None

  def post(self, url, headers=None, data=None, **kw):
    self.kw = kw
    self.payload = json.loads(data)
    fake = types.SimpleNamespace()
    fake.json = lambda: {"choices": [{"message": {"content": "# memory\n- prefers short answers\n"}}]}
    fake.close = lambda: None
    return fake


def setup():
  os.makedirs(TMP, exist_ok=True)
  ai_improve.MEMORY_DIR = TMP
  ai_improve.MEMORY_PATH = TMP + '/ai_memory.md'
  fake = FakeRequests()
  ai_improve._requests = fake
  return fake


def test_request_has_no_socket_timeout():
  # The summarizer runs on the active reasoning model, which sends nothing while
  # it thinks; any fixed timeout aborts a call that was still working.
  fake = setup()
  ai_improve.improve('sk-test', conversation='User: hi\n\nAI: hello')
  assert 'timeout' not in fake.kw, fake.kw


def test_reasoning_effort_only_for_gpt5():
  fake = setup()
  ai_improve.improve('sk-test', conversation='User: hi', model='gpt-5.4-mini')
  assert fake.payload['reasoning_effort'] == ai_improve.SUMMARY_EFFORT, fake.payload

  fake = setup()
  ai_improve.improve('', conversation='User: hi', model='qwen3:8b',
                     base_url='http://localhost:11434/v1')
  assert 'reasoning_effort' not in fake.payload, fake.payload


def test_conversation_reaches_the_summarizer():
  # The Responses client keeps its context server-side, so without gpt.py's
  # turn_log the summarizer would be handed an empty conversation.
  fake = setup()
  a = gpt.chatgpt_agent(sys.stdout)
  a.api_key = 'sk-test'
  a.base_url = 'https://api.openai.com/v1'
  a.model = 'gpt-5.4'
  a._log_turn('User', 'how do I list files?')
  a._log_turn('AI', 'use ls /sd')

  ok, msg = a.run_self_improve('user asked me to remember')
  assert ok, msg
  sent = fake.payload['messages'][1]['content']
  assert 'how do I list files?' in sent, sent
  assert 'use ls /sd' in sent, sent
  assert 'Trigger: user asked me to remember' in sent, sent
  with open(ai_improve.MEMORY_PATH) as f:
    assert 'prefers short answers' in f.read()


def test_summarizer_follows_the_active_model():
  # The user's /model choice must drive the memory rewrite, on its own endpoint.
  fake = setup()
  a = gpt.chatgpt_agent(sys.stdout)
  a.api_key = 'sk-test'
  a.base_url = 'https://api.openai.com/v1'
  a.model = 'gpt-5.5'
  a._log_turn('User', 'hi')
  ok, msg = a.run_self_improve()
  assert ok, msg
  assert fake.payload['model'] == 'gpt-5.5', fake.payload['model']

  # A local endpoint keeps its own model and its own base_url.
  fake = setup()
  a = gpt.chatgpt_agent(sys.stdout)
  a.api_key = ''
  a.base_url = 'http://localhost:11434/v1'
  a.model = 'qwen3:8b'
  a._log_turn('User', 'hi')
  ok, msg = a.run_self_improve()
  assert ok, msg
  assert fake.payload['model'] == 'qwen3:8b', fake.payload['model']
  assert 'reasoning_effort' not in fake.payload


def test_realtime_agent_keeps_the_text_model():
  # gpt_rt's self.model is a realtime/audio model: sending it to
  # /chat/completions would fail, so it must fall back to SUMMARY_MODEL.
  fake = setup()

  class FakeRealtime(gpt_tools.ToolExecBase):
    SUMMARY_USES_ACTIVE_MODEL = False
    api_key = 'sk-test'
    base_url = 'wss://api.openai.com/v1'
    model = 'gpt-realtime-audio'

    def _improve_conversation(self):
      return 'User: hi\n\nAI: hello'

  ok, msg = FakeRealtime().run_self_improve()
  assert ok, msg
  assert fake.payload['model'] == ai_improve.SUMMARY_MODEL, fake.payload['model']


def test_turn_log_is_bounded():
  a = gpt.chatgpt_agent(sys.stdout)
  for i in range(a._TURN_LOG_MAX * 3):
    a._log_turn('User', 'turn %d' % i)
  assert len(a.turn_log) == a._TURN_LOG_MAX, len(a.turn_log)
  a._log_turn('AI', None)          # a failed turn has no text
  assert len(a.turn_log) == a._TURN_LOG_MAX


if __name__ == '__main__':
  for name, fn in sorted(globals().items()):
    if name.startswith('test_'):
      fn()
      print('ok  %s' % name)
  print('all passed')
