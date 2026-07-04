importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js');

let pyodide = null;
let ready = false;
let running = false;

const STUB_FILES = [
  '_runner.py', 'vscreen.py', 'pdeck.py', 'esclib.py',
  'dsplib.py', 'xbmreader.py', 'pdeck_utils.py', 'overlay.py', 'audio.py',
  'ujson.py', 'network.py', 'termios.py', 'machine.py', 'micropython.py',
  // Japanese input (PEM): socket bridges HTTP to sync-XHR for henkan; fontloader
  // is a no-op since the browser renders CJK glyphs itself.
  'socket.py', 'fontloader.py',
  // Network request and audio-file stubs (analog_clock uses both; audio ignored).
  'urequests.py', 'wav_loader.py',
];

// ── Bundled demo apps ────────────────────────────────────────────────────────
const BUILTIN_APPS = {

  // ── Real Pocket Deck apps, imported from the served lib/ tree ──────────────
  'pem': {
    label: 'PEM Editor',
    desc: 'PEM is emacs-style editor',
    // Open the demo welcome.md on launch (resolved against /sd/Documents cwd).
    code: `import pem
def main(vs, args):
  pem.main(vs, ['pem', 'welcome.md'])
`
  },

  'home': {
    label: 'Home',
    desc: 'The home app. Function is limited, it won\'t launch apps. Just for demo.',
    code: `import home
def main(vs, args):
  home.main(vs, args)
`
  },

  'analog_clock': {
    label: 'Analog Clock',
    desc: 'Clock, calendar and kitchen timer. BS/B = toggle timer. C = copy date.',
    code: `import analog_clock
def main(vs, args):
  analog_clock.main(vs, args)
`
  },

  'journal': {
    label: 'Journal',
    desc: 'Visualizes journal.md habits and graphs. Up/Down = month, Left/Right = graph.',
    code: `import journal
def main(vs, args):
  journal.main(vs, args)
`
  },

  'graph': {
    label: 'Graph',
    desc: 'Obsidian-style link graph of /sd/Documents. D-Pad/touchpad pan, slider zooms, Enter opens, q quits. Ctrl-s to start incremental search. Bottom right button to re-root node, Bottom left button to go its parent',
    // Open the demo vault's hub note (home.md) so the graph is well connected.
    code: `import graph
def main(vs, args):
  graph.main(vs, ['graph', 'home.md'])
`
  },

  'dashboard_bars': {
    label: 'Dashboard · Bars',
    desc: 'Flat bar-chart dashboard example. Left/Right = switch metric, q = quit.',
    code: `import dashboard_bars
def main(vs, args):
  dashboard_bars.main(vs, args)
`
  },

  'dashboard_line': {
    label: 'Dashboard · Line',
    desc: 'Line/area trend dashboard example. Left/Right = switch metric, q = quit.',
    code: `import dashboard_line
def main(vs, args):
  dashboard_line.main(vs, args)
`
  },

  'dashboard_gauge': {
    label: 'Dashboard · Gauge',
    desc: 'Radial gauge dashboard example. Left/Right = scenario, r = refresh, q = quit.',
    code: `import dashboard_gauge
def main(vs, args):
  dashboard_gauge.main(vs, args)
`
  },

/*
  'boot_anim': {
    label: 'Boot Splash',
    desc: 'The device boot animation: dots crawl the edges of an isometric cube. On hardware this runs in C during boot; press any key to quit.',
    code: `import boot_anim
def main(vs, args):
  boot_anim.main(vs, args)
`
  },
*/
};

// ── Worker machinery ─────────────────────────────────────────────────────────

async function loadStubs() {
  for (const name of STUB_FILES) {
    const resp = await fetch(`./stubs/${name}`);
    if (!resp.ok) throw new Error(`Cannot load stub: ${name}`);
    pyodide.FS.writeFile(`/home/pyodide/${name}`, await resp.text());
  }
}

self.onmessage = async (e) => {
  const msg = e.data;

  // ── init ─────────────────────────────────────────────────────────────────
  if (msg.type === 'init') {
    try {
      // SharedArrayBuffer layout (created by main thread):
      //   meta   : Int32Array  at byte 0  — [0]=head [1]=tail [2]=stop
      //   data   : Uint8Array  at byte 64 — keystroke byte ring
      //   kstate : Uint8Array  after ring — HID-keycode -> 0/1 state table
      const sab = msg.sab;
      const RING = 2048, KSTATE = 256;
      self.emulator_meta   = new Int32Array(sab, 0, 16);
      self.emulator_data   = new Uint8Array(sab, 64, RING);
      self.emulator_kstate = new Uint8Array(sab, 64 + RING, KSTATE);
      // kMeta[4] = dial position (0..255, 0xff = not touched)
      // kMeta[5]/[6] = touchpad X (0..100) / Y (0..80), 0xff = not touched
      // kMeta[7] = touchpad button bits (bit0 = left pad, bit1 = right pad)
      Atomics.store(self.emulator_meta, 4, 255);
      Atomics.store(self.emulator_meta, 5, 255);
      Atomics.store(self.emulator_meta, 6, 255);
      Atomics.store(self.emulator_meta, 7, 0);

      // Allow Python (send_char) to inject keys into the same ring.
      self.emulator_push_key = (str) => {
        const meta = self.emulator_meta, data = self.emulator_data;
        const bytes = new TextEncoder().encode(str);
        let head = Atomics.load(meta, 0);
        // Mirror device hid_insert_str: normalize injected newlines to CR so
        // send_char matches a physical Enter ('\r'), collapsing CRLF to one CR.
        // Consumers like pem's dialogs match '\r' only; a bare '\n' fails them.
        let prev = 0;
        for (const b of bytes) {
          let ch = b;
          if (ch === 0x0a) {            // LF
            if (prev === 0x0d) { prev = ch; continue; }  // swallow LF of CRLF
            ch = 0x0d;                  // CR
          }
          data[head % RING] = ch; head++;
          prev = ch;
        }
        Atomics.store(meta, 0, head);
        Atomics.notify(meta, 0);
      };

      self.emulator_post_raw = (jsonStr) => {
        try { self.postMessage(JSON.parse(jsonStr)); }
        catch (_) { self.postMessage({ type: 'error', message: jsonStr }); }
      };

      // Clipboard: a worker-side buffer shared across apps (persists between runs).
      // Copy also mirrors to the system clipboard on the main thread.
      self.emulator_clipboard = '';
      self.emulator_clip_set = (s) => {
        self.emulator_clipboard = String(s);
        self.postMessage({ type: 'clipboard_copy', data: String(s) });
      };
      self.emulator_clip_get = () => self.emulator_clipboard;

      // Synchronous fetch so Python's (synchronous) import machinery can pull
      // modules from the served /lib tree on demand. Workers allow sync XHR.
      self.emulator_fetch_text = (url) => {
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('GET', url, false);
          xhr.send();
          return xhr.status === 200 ? xhr.responseText : null;
        } catch (_) { return null; }
      };

      // Binary variant for asset files (xbmr images, etc.). Reads the body as a
      // raw byte string (x-user-defined keeps bytes 1:1) and returns a Uint8Array.
      self.emulator_fetch_bytes = (url) => {
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('GET', url, false);
          xhr.overrideMimeType('text/plain; charset=x-user-defined');
          xhr.send();
          if (xhr.status !== 200) return null;
          const s = xhr.responseText;
          const out = new Uint8Array(s.length);
          for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 0xff;
          return out;
        } catch (_) { return null; }
      };

      pyodide = await loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.2/full/',
      });

      await pyodide.runPythonAsync(`
import sys
if '/home/pyodide' not in sys.path:
    sys.path.insert(0, '/home/pyodide')
`);

      await loadStubs();

      // Drop any stdlib 'socket' Pyodide pre-imported so our /home/pyodide stub
      // (loaded above) is the one jp_input picks up on first import.
      await pyodide.runPythonAsync(`
import sys
for _m in ('socket', 'fontloader'):
    sys.modules.pop(_m, None)
`);

      // Seed the device-like filesystem so apps that read /config and /sd work.
      try {
        for (const d of ['/config', '/config/ssh', '/sd', '/sd/Documents', '/sd/work', '/sd/py', '/sd/lib', '/sd/lib/data', '/sd/Documents/pd'])
          try { pyodide.FS.mkdirTree(d); } catch (_) {}
        const apps = [
          ["Pem",          { type:"program", command:[["pem"]],          description:"Pem text editor" }],
          ["Analog Clock", { type:"program", command:[["analog_clock"]], description:"Clock, calendar and timer" }],
          ["Journal",        { type:"program", command:[["journal"]],        description:"Habbit tracker" }],
          ["Graph",      { type:"program", command:[["graph"]],      description:"Markdown graph" }],
          ["Music",        { type:"program", command:[["music"]],        description:"Music player" }],
        ];
        pyodide.FS.writeFile('/config/apps.json', JSON.stringify(apps));
        pyodide.FS.writeFile('/config/settings.json', '{}');

        // Load the demo documents (sd_template/Documents) into /sd/Documents so
        // PEM and other apps open into a folder with real content.
        const manifest = self.emulator_fetch_text('../sd_template/Documents/_manifest.json');
        if (manifest) {
          for (const name of JSON.parse(manifest)) {
            const body = self.emulator_fetch_text('../sd_template/Documents/' + name);
            if (body != null) pyodide.FS.writeFile('/sd/Documents/' + name, body);
          }
        }
        // Loads PEM manual
        const body = self.emulator_fetch_text('../docs/pem_readme.md');
        pyodide.FS.writeFile('/sd/Documents/pd/pem_readme.md', body);

        // Seed the binary image assets (xbmr) from lib/data into /sd/lib/data,
        // so apps that load images work — e.g. analog_clock's cat animation and
        // home's nunomo logo splash. Files are binary, so fetch as bytes.
        // Only image assets — skip the large .wav files (audio is stubbed out,
        // and invader.wav alone is ~8 MB), keeping startup fast.
        const dataManifest = self.emulator_fetch_text('../lib/data/_manifest.json');
        if (dataManifest) {
          for (const name of JSON.parse(dataManifest)) {
            if (!/\.(xbm|xbmr)$/i.test(name)) continue;
            const bytes = self.emulator_fetch_bytes('../lib/data/' + name);
            if (bytes) pyodide.FS.writeFile('/sd/lib/data/' + name, bytes);
          }
        }
      } catch (e) { /* non-fatal */ }

      // Install an import hook: any module not satisfied by the built-in stubs
      // is fetched from the served Pocket Deck /lib tree (lib/ and lib/examples/).
      // Appended to meta_path so our emulator stubs in /home/pyodide win first.
      await pyodide.runPythonAsync(`
import sys, importlib.abc, importlib.util
from js import emulator_fetch_text

_LIB_DIRS = ['../lib/', '../lib/noa/', '../lib/examples/']
_src_cache = {}

def _fetch_lib(name):
    if name in _src_cache:
        return _src_cache[name]
    for d in _LIB_DIRS:
        src = emulator_fetch_text(d + name + '.py')
        if src is not None:
            _src_cache[name] = (src, d + name + '.py')
            return _src_cache[name]
    _src_cache[name] = None
    return None

class _LibFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path, target=None):
        if '.' in name:
            return None
        if _fetch_lib(name) is None:
            return None
        return importlib.util.spec_from_loader(name, self)
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        src, fname = _fetch_lib(module.__name__)
        exec(compile(src, fname, 'exec'), module.__dict__)

if not any(isinstance(f, _LibFinder) for f in sys.meta_path):
    sys.meta_path.append(_LibFinder())
`);

      ready = true;
      self.postMessage({
        type: 'ready',
        apps: Object.entries(BUILTIN_APPS).map(([id, a]) => ({
          id, label: a.label, desc: a.desc
        }))
      });
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) });
    }
    return;
  }

  if (!ready) {
    self.postMessage({ type: 'error', message: 'Worker not initialised yet' });
    return;
  }

  // ── run ──────────────────────────────────────────────────────────────────
  if (msg.type === 'run') {
    if (running) {
      self.postMessage({ type: 'error', message: 'An app is already running — stop it first' });
      return;
    }
    const appEntry = BUILTIN_APPS[msg.app];
    const code = (appEntry && appEntry.code) || '';
    if (!code) {
      self.postMessage({ type: 'error', message: 'Unknown app: ' + msg.app });
      return;
    }
    const args = JSON.stringify(msg.args || [msg.app || 'app']);
    pyodide.FS.writeFile('/home/pyodide/_userapp.py', code);

    // Clear the stop flag and drain any stale input before starting.
    Atomics.store(self.emulator_meta, 2, 0);                 // stop = 0
    Atomics.store(self.emulator_meta, 1, Atomics.load(self.emulator_meta, 0)); // tail = head

    running = true;
    try {
      // run_app blocks this worker thread (Atomics.wait) until the app exits.
      await pyodide.runPythonAsync(`
import sys
for _m in ['vscreen', 'pdeck', '_runner', 'overlay', 'anm', 'pdeck_utils']:
    sys.modules.pop(_m, None)
from _runner import run_app
run_app('/home/pyodide/_userapp.py', ${args})
`);
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) });
    } finally {
      running = false;
    }
    return;
  }

  // Note: while an app is running this worker is blocked in Atomics.wait,
  // so 'key' / 'stop' are delivered via the SharedArrayBuffer from the main
  // thread, not through these message handlers.
};
