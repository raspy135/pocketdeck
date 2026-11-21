#!/usr/bin/env python3
# Self-check for the /config/gpt.json "search_engine" engine chain (device-side
# web_search). Run from the repo root:
#   python3 -B test_search_engines.py
# Desktop (CPython) only -- everything network-facing is stubbed or sandboxed;
# the live RustXNG instance is never contacted.

import json
import os
import shutil
import sys
import tempfile

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
                for p in ('lib', 'lib/noa')]

import pc_compat
pc_compat.install()

import gpt_l
import gpt_tools as gt


class FakeVS:
  """Minimal vscreen sink: collects what would land on the device screen."""
  def __init__(self):
    self.buf = []
  def write(self, s):
    if isinstance(s, (bytes, bytearray)):
      s = s.decode('utf-8', 'replace')
    self.buf.append(s)
  def poll(self):
    return False
  def read(self, n=1):
    return ''


TMP = tempfile.mkdtemp(prefix='test_search_engines')
REG = os.path.join(TMP, 'gpt.json')
LEGACY_KEY = os.path.join(TMP, 'tavily_api_key')

# Point the registry and the legacy key file at the sandbox, never at the
# user's real ~/.config/gpt/gpt.json.
gpt_l.registry_path = lambda: REG
gt.TAVILY_KEY_PATH = LEGACY_KEY


def write_reg(search_engine=None):
  reg = {"default": "x", "models": [{"name": "x", "api": "chat",
                                    "model": "x"}]}
  if search_engine is not None:
    reg["search_engine"] = search_engine
  with open(REG, 'w') as f:
    json.dump(reg, f)


def fresh_agent():
  class Agent(gt.ToolExecBase):
    pass
  a = Agent()
  a.vs = FakeVS()
  return a


def test_legacy_key_file_still_selects_tavily():
  write_reg()                                   # no search_engine key
  with open(LEGACY_KEY, 'w') as f:
    f.write('  legacy-tavily-key  \n')
  eng = gt.resolve_search_engines(FakeVS())
  assert eng == [{"type": "tavily",
                  "endpoint": "https://api.tavily.com/search",
                  "api_key": "legacy-tavily-key"}], eng
  os.unlink(LEGACY_KEY)
  print("ok  test_legacy_key_file_still_selects_tavily")


def test_registry_list_is_normalized_and_validated():
  write_reg([{"type": " RustXNG ", "endpoint": "192.168.11.206"},
             {"type": "bogus", "endpoint": "x"},
             "not-a-dict",
             {"type": "searxng", "endpoint": "https://s.example.org/"},
             {"type": "searxng", "endpoint": "192.168.11.206:7777"},
             {"type": "tavily", "api_key": "tvly-abc"}])
  vs = FakeVS()
  eng = gt.resolve_search_engines(vs)
  assert eng == [
      {"type": "rustxng", "endpoint": "http://192.168.11.206:8888",
       "api_key": ""},
      {"type": "searxng", "endpoint": "https://s.example.org",
       "api_key": ""},
      {"type": "searxng", "endpoint": "http://192.168.11.206:7777",
       "api_key": ""},
      {"type": "tavily", "endpoint": "https://api.tavily.com/search",
       "api_key": "tvly-abc"}], eng
  assert "skipped an unusable search_engine record" in "".join(vs.buf)
  print("ok  test_registry_list_is_normalized_and_validated")


def test_no_engines_configured_stays_on_duckduckgo():
  write_reg()                                   # no list, no legacy key
  a = fresh_agent()
  seen = []
  a._search_ddg = lambda q, n: (True, "DDG-RESULTS") or seen.append((q, n))
  out = a.execute_web_search('{"query": "test"}')
  assert out == "DDG-RESULTS", out
  print("ok  test_no_engines_configured_stays_on_duckduckgo")


def test_engine_failure_falls_through_with_a_note():
  # First engine (dead port) fails, second answers: the result must carry a
  # note naming the failure, and the screen must see both events.
  write_reg([{"type": "rustxng", "endpoint": "192.168.11.206:9"},
             {"type": "rustxng", "endpoint": "192.168.11.206"}])

  def fake_rustxng(query, num, engine):
    if engine["endpoint"].endswith(":9"):
      return False, "Error: connection refused"
    return True, "Web search results for '%s':" % query
  a = fresh_agent()
  a._search_rustxng = fake_rustxng
  out = a.execute_web_search('{"query": "tokio runtime"}')
  assert out.startswith("(note: fell back to rustxng after"), out[:80]
  assert "Web search results" in out
  screen = "".join(a.vs.buf)
  assert "trying the next configured engine" in screen
  assert "fell back to rustxng after" in screen
  print("ok  test_engine_failure_falls_through_with_a_note")


def test_all_engines_failing_reports_every_failure():
  write_reg([{"type": "rustxng", "endpoint": "192.168.11.206:9"},
             {"type": "tavily", "api_key": "k"}])
  a = fresh_agent()
  a._search_rustxng = lambda q, n, e: (False, "Error: connection refused")
  a._search_tavily = lambda q, n, e: (False, "Error: HTTP 401")
  a._search_ddg = lambda q, n: (False, "Error: HTTP 403")
  out = a.execute_web_search('{"query": "test"}')
  assert out.startswith("Error: web search failed on every configured engine"), out[:80]
  assert "rustxng: Error: connection refused" in out
  assert "tavily: Error: HTTP 401" in out
  assert "duckduckgo: Error: HTTP 403" in out
  print("ok  test_all_engines_failing_reports_every_failure")


def test_page_text_cap():
  assert gt.SEARCH_SNIPPET_MAX == 500 and gt.SEARCH_PAGE_MAX == 4000
  capped = gt._clip_text("A" * 4500, gt.SEARCH_PAGE_MAX)
  assert capped == "A" * gt.SEARCH_PAGE_MAX + "..."
  assert gt._clip_text("short", gt.SEARCH_PAGE_MAX) == "short"
  a = fresh_agent()
  out = a._format_web_results("q", [
      ("t1", "http://x/1", "snippet", "P" * 4500),
      ("t2", "http://x/2", "snippet", None)])
  assert out.count("----- page text of result 1 -----") == 1
  assert out.count("----- page text of result 2 -----") == 0
  assert len(out) < 4500 + len("P") * 0 + 400, len(out)   # clipped, not verbatim
  print("ok  test_page_text_cap")


def test_argument_validation():
  write_reg()                                   # no engines configured
  assert not os.path.exists(LEGACY_KEY)
  a = fresh_agent()
  a._search_ddg = lambda q, n: (True, "DDG-RESULTS")
  assert a.execute_web_search('not json') == "Error: invalid arguments"
  assert a.execute_web_search('{}') == "Error: no query specified"
  out = a.execute_web_search('{"query": "q", "num_results": 99}')
  assert out == "DDG-RESULTS"        # 99 clamped to 10, then stubbed DDG ran
  print("ok  test_argument_validation")


if __name__ == '__main__':
  test_legacy_key_file_still_selects_tavily()
  test_registry_list_is_normalized_and_validated()
  test_no_engines_configured_stays_on_duckduckgo()
  test_engine_failure_falls_through_with_a_note()
  test_all_engines_failing_reports_every_failure()
  test_page_text_cap()
  test_argument_validation()
  shutil.rmtree(TMP, ignore_errors=True)
  print('all passed')
