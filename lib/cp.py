# cp.py (MicroPython)
# Usage:
#   cp SRC... DST
# Options:
#   -r, -R   recursive (copy directories)
#   * and ?  basic wildcards in SRC (glob-like)
#
# Notes:
# - Wildcards are supported only in SRC arguments (not in DST).
# - If multiple sources (or wildcard expands to multiple), DST must be a directory.
# - Copies file data in chunks (good for small RAM boards).

import os

try:
    from uerrno import EISDIR
except ImportError:
    EISDIR = 21  # fallback

# --------- small helpers ---------

def _is_dir(path):
    try:
        st = os.stat(path)
        return (st[0] & 0x4000) != 0  # stat.S_IFDIR (MicroPython uses bitmask)
    except OSError:
        return False

def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def _join(a, b):
    if not a or a.endswith("/"):
        return a + b
    return a + "/" + b

def _basename(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    return p if i < 0 else p[i + 1 :]

def _dirname(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    if i < 0:
        return ""
    return p[:i] or "/"

def _mkdirs(path):
    # mkdir -p behavior
    if not path or path == "/":
        return
    parts = []
    while path and path not in ("/", ""):
        parts.append(path)
        path = _dirname(path)
    for p in reversed(parts):
        if not _exists(p):
            try:
                os.mkdir(p)
            except OSError:
                pass

def _write(vs, s):
    try:
        vs.write(s)
    except TypeError:
        vs.write(s.encode())

# --------- wildcard matching and expansion ---------

def _match(pat, name):
    # supports '*' and '?'
    pi = ni = 0
    star = -1
    mark = 0
    while ni < len(name):
        if pi < len(pat) and (pat[pi] == "?" or pat[pi] == name[ni]):
            pi += 1
            ni += 1
        elif pi < len(pat) and pat[pi] == "*":
            star = pi
            pi += 1
            mark = ni
        elif star != -1:
            pi = star + 1
            mark += 1
            ni = mark
        else:
            return False
    while pi < len(pat) and pat[pi] == "*":
        pi += 1
    return pi == len(pat)

def _has_wildcards(s):
    return ("*" in s) or ("?" in s)

def _expand_one(pattern):
    # Only supports wildcards in last path component: dir/pat
    # If no wildcard, returns [pattern] (even if missing).
    if not _has_wildcards(pattern):
        return [pattern]

    d = _dirname(pattern)
    if d in ("", None):
        d = "."
    pat = _basename(pattern)

    try:
        names = os.listdir(d)
    except OSError:
        return []

    out = []
    for n in names:
        if _match(pat, n):
            out.append(_join(d if d != "." else "", n) if d != "." else n)
    return out

def _expand_sources(src_list):
    out = []
    for s in src_list:
        ex = _expand_one(s)
        if ex:
            out.extend(ex)
        else:
            # If wildcard matched nothing, behave like many shells: keep as-is -> error later
            out.append(s)
    return out

# --------- copy primitives ---------

def _copy_file(src, dst):
    # dst may be a file path; parent dirs should exist
    # Copy in chunks
    bufsize = 1024*64
    b = bytearray(bufsize)
    mv = memoryview(b)
    with open(src, "rb") as rf:
        with open(dst, "wb") as wf:
            while True:
                numread = rf.readinto(b)
                if numread == 0:
                    break
                wf.write(mv[:numread])

def _copy_tree(src_dir, dst_dir):
    # dst_dir is directory path (created if needed)
    if not _exists(dst_dir):
        os.mkdir(dst_dir)
    for name in os.listdir(src_dir):
        s = _join(src_dir, name)
        d = _join(dst_dir, name)
        if _is_dir(s):
            _copy_tree(s, d)
        else:
            _copy_file(s, d)

# --------- main cp command ---------

def main(vs, args):
    # Parse options
    recursive = False
    args = args[1:]
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-r", "-R"):
            recursive = True
        else:
            paths.append(a)
        i += 1

    if len(paths) < 2:
        _write(vs, "usage: cp [-r|-R] SRC... DST\n")
        return 2

    dst = paths[-1]
    srcs = _expand_sources(paths[:-1])

    dst_is_dir = _is_dir(dst)
    multiple = len(srcs) > 1

    if multiple and not dst_is_dir:
        _write(vs, "cp: destination must be a directory when copying multiple sources\n")
        return 1

    # If dst doesn't exist but multiple sources, error (cannot infer)
    if multiple and not _exists(dst):
        _write(vs, "cp: destination directory does not exist: %s\n" % dst)
        return 1

    for src in srcs:
        if not _exists(src):
            _write(vs, "cp: cannot stat '%s': No such file or directory\n" % src)
            return 1

        if _is_dir(src):
            if not recursive:
                _write(vs, "cp: -r not specified; omitting directory '%s'\n" % src)
                return 1

            if dst_is_dir or multiple:
                out_dir = _join(dst, _basename(src)) if dst_is_dir or multiple else dst
            else:
                out_dir = dst

            # If dst exists and is a file -> error
            if _exists(out_dir) and not _is_dir(out_dir):
                _write(vs, "cp: cannot overwrite non-directory '%s' with directory '%s'\n" %
                          (out_dir, src))
                return 1

            # Ensure parent exists (in case out_dir includes parents)
            _mkdirs(_dirname(out_dir))
            _copy_tree(src, out_dir)
        else:
            if dst_is_dir or multiple:
                out_file = _join(dst, _basename(src))
            else:
                out_file = dst

            _mkdirs(_dirname(out_file))
            _copy_file(src, out_file)

    return 0

