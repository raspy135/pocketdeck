#!/usr/bin/env python3
# Self-check for the -T / --training JSONL capture. Run from the repo root:
#   python3 -B test_training_capture.py
# Desktop (CPython) only -- nothing is sent, only files are written.

import json
import os
import shutil
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
                for p in ('lib', 'lib/noa')]

sys.modules['ujson'] = json
import pc_compat
pc_compat.install()

import gpt
import gpt_c

TMP = '/tmp/claude-1000/test_training_capture'


def setup():
  shutil.rmtree(TMP, ignore_errors=True)
  return TMP + '/nested/train0101_0000.jsonl'


def test_filename_is_jsonl_under_training_data():
  p = gpt.make_training_filename()
  assert p.endswith('.jsonl'), p
  assert 'training_data' in p, p


def test_append_creates_parent_and_appends_one_line_each():
  path = setup()
  assert not os.path.exists(os.path.dirname(path))
  assert gpt.append_training_example(path, {"messages": [{"role": "user", "content": "hi"}]})
  assert gpt.append_training_example(path, {"messages": [{"role": "user", "content": "again"}]})
  lines = open(path).read().splitlines()
  assert len(lines) == 2, lines
  assert json.loads(lines[0])['messages'][0]['content'] == 'hi'


def test_unserializable_record_is_reported_not_swallowed():
  path = setup()
  out = []
  class VS:
    def write(self, s): out.append(s)
  assert gpt.append_training_example(path, {"messages": object()}, VS()) is False
  assert 'could not serialize' in ''.join(out), out
  assert not os.path.exists(path)


def test_tools_are_nested_for_fine_tuning():
  flat = [{"type": "function", "name": "run", "description": "d", "parameters": {"type": "object"}}]
  out = gpt._tools_for_training(flat)
  assert out == [{"type": "function",
                  "function": {"name": "run", "description": "d",
                               "parameters": {"type": "object"}}}], out
  # already-nested and hosted tools pass through untouched
  nested = [{"type": "function", "function": {"name": "x"}}, {"type": "web_search"}]
  assert gpt._tools_for_training(nested) == nested
  assert gpt._tools_for_training(None) == []


def test_chat_client_dumps_a_turn():
  # Drive the capture block in gpt_c.ask_agent directly off a prepared message
  # list: the turn is already resolved, only the dump is under test.
  path = setup()
  c = gpt_c.chatgpt_chat.__new__(gpt_c.chatgpt_chat)
  c.vs = sys.stdout
  c.training_file = path
  c.messages = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "[refs...] what is 2+2"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "run"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "x" * (gpt.TRAIN_MAX_FIELD + 50)},
    {"role": "user", "content": "<image bytes>"},
    {"role": "assistant", "content": "4"},
  ]
  gpt_c.chatgpt_chat._dump_training_example(
    c, message="what is 2+2", references=['a.md'], images=None,
    model='gpt-5.4', tools=[{"type": "function", "name": "run"}],
    pre_len=1, silent=True)

  rec = json.loads(open(path).read().splitlines()[0])
  roles = [m['role'] for m in rec['messages']]
  assert roles == ['system', 'user', 'assistant', 'tool', 'user', 'assistant'], roles
  # the clean prompt is recorded, not the reference-augmented content that was sent
  assert rec['messages'][1]['content'] == 'what is 2+2'
  assert rec['messages'][3]['content'].endswith('...[truncated]')
  assert len(rec['messages'][3]['content']) == gpt.TRAIN_MAX_FIELD + len('...[truncated]')
  assert rec['messages'][4]['content'] == '[screen capture image omitted]'
  assert rec['tools'][0]['function']['name'] == 'run'
  assert rec['attachments'] == {'files': 1, 'images': 0}, rec['attachments']
  assert rec['model'] == 'gpt-5.4'


if __name__ == '__main__':
  for name, fn in sorted(globals().items()):
    if name.startswith('test_'):
      fn()
      print('ok  %s' % name)
  print('all passed')
