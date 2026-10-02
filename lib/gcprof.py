# How much does the incremental GC freeze the interpreter?
#
# Samples gc.stats() over a window and reports the difference, so the numbers
# describe the running workload rather than the whole uptime.
#
# Two numbers matter.  "worst pause" is the longest single stall, because it
# runs to completion inside one allocation -- that is what drops a frame.
# "GC costs" is throughput: the mark and sweep rows are spread over hundreds
# of allocations, so they cost time overall but are never felt as a hitch.
import argparse
import gc
import time

_SLICED = (("mark", "mark_us"), ("sweep", "walk_us"))

# Root scans run twice per cycle: once at cycle start, once at cycle end.
# gc.stats() sums both, so only half lands in the end-of-cycle pause.
_PAUSED = (("root scan x2", "roots_us"),
           ("final drain", "drain_us"),
           ("finalisers", "fin_us"))

_KEYS = ("cycles", "slices", "slice_ends", "overflows", "max_gray") + tuple(
    k for _, k in _SLICED + _PAUSED)


def _snap():
  s = gc.stats()
  return dict((k, s[k]) for k in _KEYS)


def _report(vs, a, b, elapsed_ms):
  cycles = b["cycles"] - a["cycles"]
  if cycles <= 0:
    print("gcprof: no GC cycle completed in %d ms -- try a longer window "
          "or a busier workload" % elapsed_ms, file=vs)
    return
  per = lambda key: (b[key] - a[key]) // cycles
  slices = ((b["slices"] + b["slice_ends"]) -
            (a["slices"] + a["slice_ends"])) // cycles
  total = sum(per(k) for _, k in _SLICED + _PAUSED)
  pause = sum(per(k) for _, k in _PAUSED) - per("roots_us") // 2

  print("gcprof: %d cycles in %d ms" % (cycles, elapsed_ms), file=vs)
  print("  spread over %d slices/cycle:" % slices, file=vs)
  for name, key in _SLICED:
    print("    %-14s %7d us/cycle" % (name, per(key)), file=vs)
  print("  paid in one allocation:", file=vs)
  for name, key in _PAUSED:
    print("    %-14s %7d us/cycle" % (name, per(key)), file=vs)
  print("    %-14s %7d us   <- longest stall" % ("worst pause", pause), file=vs)
  print("  GC costs %.1f%% of wall clock"
        % (total * cycles / (elapsed_ms * 10.0)), file=vs)
  if b["overflows"] - a["overflows"]:
    print("  gray set overflowed (max_gray %d): raise "
          "MICROPY_ALLOC_GC_STACK_SIZE" % b["max_gray"], file=vs)


def main(vs, args_in):
  parser = argparse.ArgumentParser(vs=vs,
      description='report how long the GC freezes the interpreter')
  parser.add_argument('seconds', nargs='?', type=float, default=5.0,
                      help='sample window in seconds (default 5)')
  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  if not hasattr(gc, 'stats'):
    print('gcprof: this firmware has no gc.stats() '
          '(needs MICROPY_GC_INCREMENTAL)', file=vs)
    return

  window_ms = int(args.seconds * 1000)
  if window_ms < 1:
    print('gcprof: seconds must be positive', file=vs)
    return

  before = _snap()
  start = time.ticks_ms()
  try:
    # Sleep in slices so Ctrl-C lands promptly on a long window.
    while time.ticks_diff(time.ticks_ms(), start) < window_ms:
      time.sleep_ms(100)
  except KeyboardInterrupt:
    pass
  _report(vs, before, _snap(), time.ticks_diff(time.ticks_ms(), start))
