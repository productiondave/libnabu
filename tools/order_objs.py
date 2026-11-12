#!/usr/bin/env python3
"""
order_objs.py - print object files ordered for a z80asm library (dependents first).

z80asm scans a library in a single pass, so a module must appear *before* the modules
whose symbols it references; otherwise a program can fail to link ('undefined symbol')
even though the symbol is in the library. Order is derived from each object's
'Symbols' (G = global definition) and 'Externs' (U) as printed by z88dk-z80nm.

usage: order_objs.py <z80nm> obj1.o obj2.o ...      (prints ordered list, one line)
Cyclic dependencies cannot be satisfied by any order: they are reported on stderr and the
exit status is 1 (the Makefile then fails). Fix them by regrouping symbols in manifest.yaml.
"""
import subprocess
import sys


def read(nm, obj):
    defs, refs, section = set(), set(), None
    out = subprocess.run([nm, obj], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('Symbols:'):
            section = 'S'
        elif s.startswith('Externs:'):
            section = 'E'
        elif section == 'S' and s.startswith('G '):
            defs.add(s.split()[3])
        elif section == 'E' and s.startswith('U '):
            refs.add(s.split()[1])
        elif s.startswith('Object') or s.startswith('Name:') or s.startswith('Section'):
            if not s.startswith('Section'):
                section = None
    return defs, refs


def main():
    nm, objs = sys.argv[1], sys.argv[2:]
    info = {o: read(nm, o) for o in objs}
    owner = {}
    for o, (defs, _) in info.items():
        for d in defs:
            owner.setdefault(d, o)
    deps = {o: sorted({owner[r] for r in refs if r in owner and owner[r] != o})
            for o, (_, refs) in info.items()}
    order, state = [], {}
    cycles = []

    def visit(o, stack):
        if state.get(o) == 2:
            return
        if state.get(o) == 1:
            cyc = stack[stack.index(o):] + [o]
            cycles.append(cyc)
            print('order_objs: dependency cycle: ' + ' -> '.join(cyc), file=sys.stderr)
            return
        state[o] = 1
        for d in deps[o]:
            visit(d, stack + [o])
        state[o] = 2
        order.append(o)          # dependencies first (post-order) ...

    for o in objs:
        visit(o, [])
    print(' '.join(reversed(order)))   # ... then reversed: dependents first
    if cycles:
        print('order_objs: unit cycles cannot be linked reliably - fix the grouping in '
              'manifest.yaml', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
