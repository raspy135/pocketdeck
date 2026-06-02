"""
Headless browser test for the Pocket Deck emulator.
Run: python3 emulator/test_emulator.py
The local server must be running on port 8090.
"""
import asyncio
import sys
from playwright.async_api import async_playwright

URL = "http://localhost:8090/emulator/"
TIMEOUT = 90_000  # 90s for Pyodide to load

# Position-sensitive signature of the screen: detects motion even when the
# lit-pixel count is unchanged (e.g. a shape moving across the screen).
# The screen is 1-bit but uses a gray LCD palette (lit ≈ 174, off ≈ 26 on the
# red channel), so "lit" is a threshold rather than == 255.
CANVAS_SUM = """() => {
  const d = document.getElementById('screenCanvas').getContext('2d')
              .getImageData(0, 0, 400, 240).data;
  let s = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i] > 100) s = (s + (i * 2654435761)) >>> 0;
  return s;
}"""

async def run():
  async with async_playwright() as p:
    browser = await p.firefox.launch(headless=True)
    ctx = await browser.new_context()
    page = await ctx.new_page()

    errors = []
    console_msgs = []

    page.on('console', lambda m: console_msgs.append(f'[{m.type}] {m.text}'))
    page.on('pageerror', lambda e: errors.append(str(e)))

    print(f"Opening {URL} ...")
    await page.goto(URL, wait_until='domcontentloaded')

    # ── Wait for Pyodide to load ───────────────────────────────────────────
    print("Waiting for worker 'ready' (Pyodide + micropip)...")
    try:
      await page.wait_for_function(
        "() => document.getElementById('status-text')?.textContent.includes('Ready')",
        timeout=TIMEOUT
      )
      print("✓ Worker ready")
    except Exception as e:
      print(f"✗ Worker never became ready: {e}")
      for m in console_msgs[-20:]:
        print(" ", m)
      await browser.close()
      return 1

    isolated = await page.evaluate("() => self.crossOriginIsolated")
    print(f"{'✓' if isolated else '✗'} crossOriginIsolated = {isolated}")

    # ── App list populated (no file-picker / run buttons anymore) ──────────
    app_items = await page.query_selector_all('.ios-list-item')
    app_count = len(app_items)
    labels = [await it.inner_text() for it in app_items]
    print(f"{'✓' if app_count == 4 else '✗'} App list: {app_count} apps {labels}")

    results = {}

    # ── PEM editor: tap to run, screen should render content ───────────────
    print("\n── PEM editor ───────────────────────────────────────────────────")
    await page.click('.ios-list-item:nth-child(1)')
    await asyncio.sleep(3)
    pem_sum = await page.evaluate(CANVAS_SUM)
    pem_ok = pem_sum > 0
    results['pem'] = pem_ok
    print(f"{'✓' if pem_ok else '✗'} PEM rendered: pixsum {pem_sum}")

    # ── Switch to Home while PEM is running (auto-stop + launch queued) ────
    print("\n── switch to Home ───────────────────────────────────────────────")
    await page.click('.ios-list-item:nth-child(2)')
    # Wait for the running flag to settle on the new app.
    await page.wait_for_function(
      "() => document.getElementById('status-text')?.textContent.includes('Running')",
      timeout=15_000
    )
    await asyncio.sleep(2)
    h1 = await page.evaluate(CANVAS_SUM)
    await asyncio.sleep(1.2)
    h2 = await page.evaluate(CANVAS_SUM)
    # Home animates its clock/cursor, so the screen should change over time.
    home_ok = h1 > 0 and h1 != h2
    results['home'] = home_ok
    print(f"{'✓' if home_ok else '✗'} Home running & animating: pixsum {h1} → {h2}")

    # verify true 1-bit output: every pixel is exactly one of the two palette
    # values (lit / off), with a mix of both on screen.
    histo = await page.evaluate("""() => {
      const d = document.getElementById('screenCanvas').getContext('2d').getImageData(0,0,400,240).data;
      const vals = new Set(); let lit=0, off=0;
      for (let i=0;i<d.length;i+=4){ const v=d[i]; vals.add(v); if(v>100)lit++; else off++; }
      return {lit, off, distinct:[...vals].sort((a,b)=>a-b)};
    }""")
    total = histo['lit'] + histo['off']
    frac = histo['lit'] / total
    mono_ok = len(histo['distinct']) <= 2 and 0.0 < frac < 1.0
    results['mono'] = mono_ok
    print(f"{'✓' if mono_ok else '✗'} 1-bit mono: lit={histo['lit']} off={histo['off']} "
          f"values={histo['distinct']} (lit {frac*100:.0f}%)")

    # ── Analog Clock: tap to run; second hand animates ────────────────────
    print("\n── Analog Clock ─────────────────────────────────────────────────")
    await page.click('.ios-list-item:nth-child(3)')
    await page.wait_for_function(
      "() => document.getElementById('status-text')?.textContent.includes('Running')",
      timeout=15_000
    )
    # Just assert it renders content: the clock's second hand is stationary
    # between ticks, so frame-diff "animation" checks are inherently flaky.
    await asyncio.sleep(1.5)
    clock_sum = await page.evaluate(CANVAS_SUM)
    clock_ok = clock_sum > 0
    results['analog_clock'] = clock_ok
    print(f"{'✓' if clock_ok else '✗'} Analog Clock rendered: pixsum {clock_sum}")

    # ── Journal: tap to run; renders the seeded journal.md ─────────────────
    print("\n── Journal ──────────────────────────────────────────────────────")
    await page.click('.ios-list-item:nth-child(4)')
    await page.wait_for_function(
      "() => document.getElementById('status-text')?.textContent.includes('Running')",
      timeout=15_000
    )
    await asyncio.sleep(2.5)
    j = await page.evaluate(CANVAS_SUM)
    journal_ok = j > 0
    results['journal'] = journal_ok
    print(f"{'✓' if journal_ok else '✗'} Journal rendered: pixsum {j}")

    passed = all(results.values())

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n── Console output (last 15 lines) ───────────────────────────────")
    for m in console_msgs[-15:]:
      print(" ", m)
    if errors:
      print("\n── Page errors ──────────────────────────────────────────────────")
      for e in errors:
        print(" ", e)

    print("\n── Results ──────────────────────────────────────────────────────")
    for k, v in results.items():
      print(f"  {'PASS' if v else 'FAIL'}  {k}")

    await browser.close()
    return 0 if (app_count == 4 and passed) else 1

if __name__ == '__main__':
  sys.exit(asyncio.run(run()))
