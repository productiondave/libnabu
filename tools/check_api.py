#!/usr/bin/env python3
"""
check_api.py - verify the libraries export the public API that upstream's headers declare.

For every upstream header listed in manifest.yaml `sources` (*.h), collect the functions and
variables it declares/defines (DISABLE_* evaluated as "not defined", BIN_TYPE guards evaluated
per target), then check that each has a symbol in the library built for that target.

  * declared AND defined upstream, but missing from a library -> ERROR (exit status 1)
  * declared upstream but defined nowhere upstream (an upstream bug: it would not link there
    either)                              -> WARNING, reported but not an error
  * exported by a library but declared in no public header (generated headers included)
                                          -> listed for information only

usage: check_api.py [--upstream DIR] [--z88dk DIR] [--manifest FILE] [--gen DIR] [--build DIR]
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split  # noqa: E402
import yaml  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lib_symbols(nm, lib):
    out = subprocess.run([nm, lib], capture_output=True, text=True, check=True).stdout
    syms, sec = set(), None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('Symbols:'):
            sec = 'S'
        elif s.startswith('Externs:'):
            sec = 'E'
        elif sec == 'S' and s.startswith('G '):
            syms.add(s.split()[3])
    return syms


def declared(path, selectors, kinds=('proto', 'funcdef', 'var')):
    """-> list of (name, guards) for functions/variables a header declares or defines."""
    with open(path, encoding='utf-8', errors='replace') as f:
        items = split.scan(f.read(), os.path.basename(path))
    split.annotate(items)
    names = []
    for it in items:
        split.classify(it)
        if it.dead or it.kind not in kinds or not it.name:
            continue
        if it.kind == 'var':
            sel = next((m.group(1) for g in it.guards for p in selectors
                        if (m := re.fullmatch(r'defined\((' + re.escape(p) + r'\w+)\)', g))), None)
            if sel:
                name = f'{it.name}_{sel.split("_", 1)[1]}'
                names.append((name, [g for g in it.guards if g != f'defined({sel})']))
                continue
        names.append((it.name, it.guards))
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'manifest.yaml'))
    ap.add_argument('--upstream')
    ap.add_argument('--z88dk', default=os.environ.get('Z88DIR'))
    ap.add_argument('--gen', default=os.path.join(ROOT, 'gen'))
    ap.add_argument('--build', default=os.path.join(ROOT, 'build'))
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.manifest))
    up = a.upstream or cfg.get('upstream', '../NABU-LIB/NABULIB')
    if not os.path.isabs(up):
        up = os.path.normpath(os.path.join(ROOT, up))
    z88 = a.z88dk or os.path.join(ROOT, '../z88dk-2.5/z88dk')
    nm = os.path.join(z88, 'bin', 'z88dk-z80nm')
    selectors = cfg.get('selector_prefixes', ['FONT_'])

    libs = {'hb': os.path.join(a.build, 'nabu', 'nabu_hb.lib'),
            'cpm': os.path.join(a.build, 'cpm', 'nabu_cpm.lib')}
    for t, l in libs.items():
        if not os.path.exists(l):
            sys.exit(f'{l} not found - run make first')

    api = {}   # name -> (guards, header)
    for fname in cfg['sources']:
        if fname.endswith('.h'):
            for name, guards in declared(os.path.join(up, fname), selectors):
                api.setdefault(name, (guards, fname))
    # .c files that are public headers upstream-style (DirEntryReader.c): their definitions are API
    for fname, _ in (cfg.get('public_c_files') or {}).items():
        for name, guards in declared(os.path.join(up, fname), selectors):
            api.setdefault(name, (guards, fname))

    # everything upstream actually defines (functions/variables with a body/storage), any file
    defined = set()
    for fname in cfg['sources']:
        defined.update(n for n, _ in declared(os.path.join(up, fname), selectors, ('funcdef', 'var')))

    # all names declared by the *generated* public headers (for the reverse, informational check)
    gen_decl = set()
    inc = os.path.join(a.gen, 'include')
    for h in os.listdir(inc):
        if h.endswith('.h') and not h.endswith('_internal.h'):
            gen_decl.update(n for n, _ in declared(os.path.join(inc, h), selectors))

    failed = False
    for t, lib in libs.items():
        syms = lib_symbols(nm, lib)
        names = {s[1:] for s in syms if s.startswith('_')}
        expected = {n: h for n, (g, h) in api.items() if split.guard_active(g, t)}
        absent = sorted(n for n in expected if n not in names)
        missing = [n for n in absent if n in defined]
        upstream_bug = [n for n in absent if n not in defined]
        undeclared = sorted(n for n in names if n not in gen_decl and not n.startswith('_'))
        print(f'== {os.path.basename(lib)}: {len(expected)} public symbols expected, '
              f'{len(expected) - len(absent)} present, {len(missing)} missing'
              + (f', {len(upstream_bug)} undefined upstream' if upstream_bug else ''))
        for n in missing:
            print(f'   MISSING  {n}   (declared in {expected[n]})')
        for n in upstream_bug:
            print(f'   WARNING  {n}: declared in {expected[n]} but never defined upstream '
                  f'(would not link there either)')
        if undeclared:
            print(f'   info: {len(undeclared)} exported symbols not declared in any public header: '
                  + ', '.join(undeclared[:12]) + (' ...' if len(undeclared) > 12 else ''))
        failed |= bool(missing)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
