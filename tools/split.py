#!/usr/bin/env python3
"""
split.py - turn the upstream single-header NABU-LIB into multi-unit library sources.

Reads the upstream sources named in manifest.yaml (read-only), and writes into
<out>/ (default gen/):

  include/*.h      public headers: upstream headers with definitions turned into
                   declarations (extern/prototypes), '#include "x.c"' removed,
                   __at() variables turned into pointer macros
  include/*_internal.h
                   declarations for symbols that upstream keeps private/static
  src/<unit>.c     one translation unit per library object
  units.txt        '<unit> <targets>'  targets = hb,cpm (which BIN_TYPEs need it)
  symbols.txt      '<symbol> <unit> <kind> <origin file>'
  report.txt       warnings (unmapped symbols, variants, ...)

Nothing in <out>/ is meant to be edited by hand: fix manifest.yaml or this script.

How config macros are handled (see AGENT.md):
  * DISABLE_* around top-level items are evaluated as "not defined" - everything is
    compiled; the linker drops what a program does not reference.
  * DISABLE_* inside a function body/asm block cannot be a link-time choice, so the
    function is emitted once per combination ("variants", one unit each) and the public
    header redirects the name with a macro according to the user's DISABLE_* defines.
  * FONT_* style selectors: each guarded variable becomes NAME_<SELECTOR>, and the
    header does '#define NAME NAME_<SELECTOR>' under the same guard.
  * BIN_TYPE conditionals are preserved; the library is built once per BIN_TYPE.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from itertools import combinations

try:
    import yaml
except ImportError:
    sys.exit("split.py needs PyYAML (apt install python3-yaml / pip install pyyaml)")

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("warning: " + msg, file=sys.stderr)


# ----------------------------------------------------------------------------
# Scanning: split a C file into top-level items (directives, decls, functions)
# ----------------------------------------------------------------------------
IDENT = re.compile(r'[A-Za-z_]\w*')


class Item:
    def __init__(self, src, line, lead, body, is_dir=False):
        self.src = src            # file name
        self.line = line          # 1-based line of first code line
        self.lead = lead          # comments/blank lines before the item
        self.body = body          # the code (or directive) text
        self.is_dir = is_dir
        self.dkind = None         # directive keyword
        self.darg = None
        self.guards = []          # evaluated guard list (strings), outermost first
        self.dead = False         # inside a branch that is always false
        self.kind = ''            # funcdef var proto typedef sfr at_var directive trivia
        self.name = None
        if is_dir:
            m = re.match(r'\s*#\s*(\w+)[ \t]*(.*)', body, re.S)
            if m:
                self.dkind = m.group(1)
                arg = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', m.group(2), flags=re.S)
                self.darg = arg.replace('\\\n', ' ').strip()


def is_func_head(head):
    return '(' in head and '=' not in head


def scan(text, src):
    lines = text.splitlines(keepends=True)
    n = len(lines)
    items = []
    cur = []
    first_code = None
    depth = paren = 0
    in_c = in_asm = seen_brace = False
    head = []
    code_started = False
    i = 0
    while i < n:
        line = lines[i]
        if not code_started and not in_c and line.lstrip().startswith('#'):
            dl = [line]
            start = i
            while dl[-1].rstrip('\r\n').endswith('\\') and i + 1 < n:
                i += 1
                dl.append(lines[i])
            items.append(Item(src, start + 1, ''.join(cur), ''.join(dl), True))
            cur = []
            i += 1
            continue
        cur.append(line)
        j, L, ended = 0, len(line), False
        while j < L:
            if in_asm:
                k = line.find('__endasm', j)
                if k < 0:
                    j = L
                    break
                in_asm = False
                j = k + 8
                continue
            if in_c:
                k = line.find('*/', j)
                if k < 0:
                    j = L
                    break
                in_c = False
                j = k + 2
                continue
            ch = line[j]
            if line.startswith('//', j):
                break
            if line.startswith('/*', j):
                in_c = True
                j += 2
                continue
            if ch in '"\'':
                k = j + 1
                while k < L and line[k] != ch:
                    if line[k] == '\\':
                        k += 1
                    k += 1
                if not seen_brace:
                    head.append(line[j:k + 1])
                code_started = True
                j = k + 1
                continue
            if ch.isspace():
                if not seen_brace:
                    head.append(ch)
                j += 1
                continue
            code_started = True
            m = IDENT.match(line, j)
            if m:
                w = m.group(0)
                j = m.end()
                if w == '__asm':
                    in_asm = True
                    continue
                if not seen_brace:
                    head.append(w)
                continue
            if ch == '(':
                paren += 1
            elif ch == ')':
                paren -= 1
            elif ch == '{':
                depth += 1
                seen_brace = True
            elif ch == '}':
                depth -= 1
                if depth == 0 and paren == 0 and is_func_head(''.join(head)):
                    ended = True
            elif ch == ';' and depth == 0 and paren == 0:
                ended = True
            if not seen_brace:
                head.append(ch)
            j += 1
            if ended:
                break
        if code_started and first_code is None:
            first_code = len(cur) - 1
        if ended:
            rest = line[j:].strip()
            if rest and not rest.startswith('//') and not rest.startswith('/*'):
                warn(f"{src}:{i + 1}: code after end of item ignored/kept verbatim: {rest[:40]}")
            fc = first_code if first_code is not None else 0
            items.append(Item(src, i + 1 - (len(cur) - 1 - fc), ''.join(cur[:fc]), ''.join(cur[fc:])))
            cur = []
            first_code = None
            depth = paren = 0
            seen_brace = code_started = False
            head = []
        i += 1
    if code_started:
        warn(f"{src}: unterminated item at end of file")
    tail = ''.join(cur)
    if tail.strip():
        it = Item(src, n, '', tail)
        it.kind = 'trivia'
        items.append(it)
    return items


# ----------------------------------------------------------------------------
# Preprocessor condition evaluation (DISABLE_* are "undefined")
# ----------------------------------------------------------------------------
def strip_comments(s):
    return re.sub(r'//[^\n]*|/\*.*?\*/', ' ', s, flags=re.S)


def _safe_eval(e):
    e = e.replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'!(?!=)', ' not ', e)
    return bool(eval(e, {"__builtins__": {}}, {}))


def ev(expr, defset=frozenset()):
    """bool if fully decidable from DISABLE_* knowledge, else a (substituted) string."""
    def dsub(m):
        name = m.group(1) or m.group(2)
        return '1' if name in defset else '0'
    e = re.sub(r'defined\s*\(\s*(DISABLE_\w+)\s*\)|defined\s+(DISABLE_\w+)', dsub, expr)
    e = e.strip()
    if re.fullmatch(r'[\s0-9()!&|]+', e or 'x'):
        try:
            return _safe_eval(e)
        except Exception:
            return e
    return e


def vnot(a):
    return (not a) if isinstance(a, bool) else f'!({a})'


def vand(a, b):
    if a is False or b is False:
        return False
    if a is True:
        return b
    if b is True:
        return a
    return f'({a}) && ({b})'


def vor(a, b):
    if a is True or b is True:
        return True
    if a is False:
        return b
    if b is False:
        return a
    return f'({a}) || ({b})'


def cond_of(kind, arg):
    if kind == 'ifdef':
        return f'defined({arg})'
    if kind == 'ifndef':
        return f'!defined({arg})'
    return arg


def annotate(items):
    stack = []
    for idx, it in enumerate(items):
        if it.is_dir:
            k = it.dkind
            if k in ('if', 'ifdef', 'ifndef'):
                v = ev(cond_of(k, it.darg))
                fr = {'own': [v], 'cur': v}
                if k == 'ifndef' and not stack:
                    nxt = next((x for x in items[idx + 1:] if x.is_dir), None)
                    if nxt and nxt.dkind == 'define' and nxt.darg.split()[0:1] == [it.darg]:
                        fr['cur'] = True          # include guard
                stack.append(fr)
            elif k == 'elif':
                fr = stack[-1]
                v = ev(it.darg)
                prev = False
                for o in fr['own']:
                    prev = vor(prev, o)
                fr['own'].append(v)
                fr['cur'] = vand(vnot(prev), v)
            elif k == 'else':
                fr = stack[-1]
                prev = False
                for o in fr['own']:
                    prev = vor(prev, o)
                fr['cur'] = vnot(prev)
            elif k == 'endif':
                if stack:
                    stack.pop()
        curs = [f['cur'] for f in stack]
        it.dead = any(c is False for c in curs)
        it.guards = [c for c in curs if c is not True]


def wrap(guards, text):
    if not guards:
        return text
    cond = ' && '.join(f'({g})' for g in guards)
    if not text.endswith('\n'):
        text += '\n'
    return f'#if {cond}\n{text}#endif\n'


# ----------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------
def match_brace(s, i):
    depth = 0
    for k in range(i, len(s)):
        if s[k] == '{':
            depth += 1
        elif s[k] == '}':
            depth -= 1
            if depth == 0:
                return k
    return -1


def decl_head(clean):
    """text at brace-depth 0 up to the initializer '=' or ';'"""
    out, depth = [], 0
    for ch in clean:
        if ch == '{':
            depth += 1
            continue
        if ch == '}':
            depth -= 1
            continue
        if depth == 0:
            if ch in '=;':
                break
            out.append(ch)
    return ''.join(out)


def last_ident(h):
    h = re.sub(r'\[[^\]]*\]', ' ', h)
    m = re.search(r'\(\s*\*\s*(\w+)', h)
    if m:
        return m.group(1)
    ids = IDENT.findall(h)
    return ids[-1] if ids else None


def classify(it):
    if it.is_dir:
        it.kind = 'directive'
        return
    if it.kind == 'trivia':
        return
    clean = strip_comments(it.body).strip()
    h0 = clean.split('{', 1)[0].split('=', 1)[0]
    if re.search(r'\b__sfr\b', clean):
        it.kind = 'sfr'
        it.name = last_ident(decl_head(clean))
        return
    if re.search(r'\b__at\b', clean):
        it.kind = 'at_var'
        it.name = last_ident(re.sub(r'__at\s*\(?\s*\w+\s*\)?', ' ', decl_head(clean)))
        return
    if re.match(r'typedef\b', clean):
        it.kind = 'typedef'
        return
    if re.match(r'(struct|union|enum)\b[^;{=()]*\{', clean):
        close = match_brace(clean, clean.index('{'))
        if close >= 0 and clean[close + 1:].strip() == ';':   # pure type, no declarator
            it.kind = 'typedef'
            return
    if '{' in clean and is_func_head(h0):
        it.kind = 'funcdef'
        m = re.search(r'(\w+)\s*\(', h0)
        it.name = m.group(1) if m else None
        return
    if re.match(r'extern\b', clean):
        it.kind = 'proto'
        it.name = last_ident(decl_head(clean))
        return
    pre_eq = clean.split('=', 1)[0]
    # prototype: at least two identifiers (type + name) before the first '('.
    # 'void (*fp)();' has only one, so it is a function-pointer variable.
    if '(' in pre_eq and len(IDENT.findall(pre_eq.split('(', 1)[0])) >= 2:
        it.kind = 'proto'
        m = re.search(r'(\w+)\s*\(', pre_eq)
        it.name = m.group(1) if m else None
        return
    it.kind = 'var'
    it.name = last_ident(decl_head(clean))


# ----------------------------------------------------------------------------
# Text transforms
# ----------------------------------------------------------------------------
def head_split(body):
    """(head, rest): head = text before first '{' or '=' (declaration specifiers/declarator)."""
    m = re.search(r'[{=]', body)
    if not m:
        return body, ''
    return body[:m.start()], body[m.start():]


def strip_storage(body, strip_inline=True):
    head, rest = head_split(body)
    head = re.sub(r'\bstatic\b[ \t]*', '', head)
    if strip_inline:
        head = re.sub(r'\binline\b[ \t]*', '', head)
    return head + rest


def split_type_body(body, name):
    """'struct {..} x = ..;' -> ('struct __t_x {..};', 'struct __t_x x = ..;') else ('', body)"""
    m = re.match(r'(\s*(?:(?:static|extern|const|volatile)\s+)*)(struct|union)\s*(\w+)?\s*\{', body)
    if not m:
        return '', body
    open_i = body.index('{', m.start())
    close_i = match_brace(body, open_i)
    if close_i < 0:
        return '', body
    tag = m.group(3) or f'__t_{name}'
    tdef = f'{m.group(2)} {tag} {body[open_i:close_i + 1]};\n'
    new = f'{m.group(1)}{m.group(2)} {tag}{body[close_i + 1:]}'
    return tdef, new


def cut_initializer(s):
    depth = 0
    for k, ch in enumerate(s):
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
        elif ch == '=' and depth == 0:
            return s[:k]
    return s


def make_extern(body, name):
    """-> (typedef_text, extern_decl_text) for a variable definition"""
    tdef, b = split_type_body(body, name)
    b = strip_storage(b)
    b = cut_initializer(b).strip().rstrip(';').rstrip()
    if not re.match(r'extern\b', b):
        b = 'extern ' + b
    return tdef, b + ';\n'


def make_proto(body):
    head, _ = head_split(body)
    head = strip_storage(head)
    head = re.sub(r'[ \t]*\b__naked\b', '', head).rstrip()   # definition-only attribute
    return head + ';\n'


def at_macro(body, name):
    """__at() memory-mapped variable -> (typedef_text, '#define name (*(T *)addr)')"""
    clean = strip_comments(body).strip()
    m = re.search(r'__at\s*\(?\s*(0x[0-9A-Fa-f]+|\d+)\s*\)?', clean)
    if not m:
        raise ValueError(f'cannot parse __at() in: {clean[:60]}')
    addr = m.group(1)
    tdef = ''
    c2 = clean[:m.start()] + ' ' + clean[m.end():]
    mm = re.match(r'\s*((?:(?:volatile|const)\s+)*)(struct|union)\s*(\w+)?\s*\{', c2)
    if mm:
        o = c2.index('{', mm.start())
        cl = match_brace(c2, o)
        tag = mm.group(3) or f'__t_{name}'
        tdef = f'{mm.group(2)} {tag} {c2[o:cl + 1]};\n'
        typ = f'{mm.group(1)}{mm.group(2)} {tag}'.strip()
    else:
        c2 = c2.rstrip().rstrip(';')
        typ = re.sub(r'\b' + re.escape(name) + r'\s*$', '', c2.strip()).strip()
    return tdef, f'#define {name} (*({typ} *){addr})\n'


# ----------------------------------------------------------------------------
# Variants for DISABLE_* inside function bodies
# ----------------------------------------------------------------------------
DIRLINE = re.compile(r'^[ \t]*#[ \t]*(if|ifdef|ifndef|elif|else|endif)\b(.*)$')


def body_disable_macros(body):
    found = set()
    for line in body.splitlines():
        m = DIRLINE.match(line)
        if m and m.group(1) in ('if', 'ifdef', 'ifndef', 'elif'):
            found.update(re.findall(r'DISABLE_\w+', m.group(2)))
    return sorted(found)


def resolve_body(text, defset):
    out, stack = [], []

    def active():
        return all(f['on'] for f in stack if f['rel'])

    for line in text.splitlines(keepends=True):
        m = DIRLINE.match(line)
        if not m:
            if active():
                out.append(line)
            continue
        k, arg = m.group(1), strip_comments(m.group(2)).strip()
        if k in ('if', 'ifdef', 'ifndef'):
            rel, v = 'DISABLE_' in arg, None
            if rel:
                v = ev(cond_of(k, arg), defset)
                if not isinstance(v, bool):
                    rel, v = False, None
            stack.append({'rel': rel, 'on': v if rel else True, 'taken': bool(v)})
            if not rel and active():
                out.append(line)
        elif k == 'elif':
            fr = stack[-1]
            if fr['rel']:
                v = ev(arg, defset)
                v = v if isinstance(v, bool) else False
                fr['on'] = (not fr['taken']) and v
                fr['taken'] = fr['taken'] or fr['on']
            elif active():
                out.append(line)
        elif k == 'else':
            fr = stack[-1]
            if fr['rel']:
                fr['on'] = not fr['taken']
                fr['taken'] = True
            elif active():
                out.append(line)
        else:  # endif
            fr = stack.pop()
            if not fr['rel'] and active():
                out.append(line)
    return ''.join(out)


def variant_suffix(defset):
    return ''.join('__no_' + d[len('DISABLE_'):] for d in sorted(defset))


# ----------------------------------------------------------------------------
# Target (BIN_TYPE) evaluation of guards
# ----------------------------------------------------------------------------
def guard_active(guards, target):
    env = {'BIN_TYPE': {'hb': 100, 'cpm': 200}[target], 'BIN_HOMEBREW': 100, 'BIN_CPM': 200}
    for g in guards:
        e = g
        ids = [w for w in IDENT.findall(e) if w != 'defined']
        if any(w not in env for w in ids) or 'defined' in e:
            continue                       # unknown -> assume active
        for w, val in env.items():
            e = re.sub(r'\b' + w + r'\b', str(val), e)
        e = e.replace('&&', ' and ').replace('||', ' or ')
        e = re.sub(r'!(?!=)', ' not ', e)
        try:
            if not eval(e, {"__builtins__": {}}, {}):
                return False
        except Exception:
            pass
    return True


# ----------------------------------------------------------------------------
# Main generator
# ----------------------------------------------------------------------------
class Gen:
    def __init__(self, cfg, upstream, out):
        self.cfg = cfg
        self.up = upstream
        self.out = out
        self.rules = cfg.get('rules', [])
        for r in self.rules:
            r['_re'] = [re.compile(p) for p in r.get('match', [])]
            r['_sym'] = set(r.get('symbols', []))
        self.file_defaults = cfg.get('file_defaults', {})
        self.default_unit = cfg.get('default_unit', 'misc')
        self.selectors = cfg.get('selector_prefixes', ['FONT_'])
        self.public_c = cfg.get('public_c_files', {}) or {}
        self.base_header = cfg.get('base_header', 'NABU-LIB.h')
        # z88dk 2.5's preprocessor prints uninitialised memory for a '#warning' with no text,
        # and upstream uses empty ones as spacers. Dropping them loses nothing.
        self.strip_empty_warnings = cfg.get('strip_empty_warnings', True)
        self.units = {}          # name -> dict(chunks, origins, guards)
        self.symbols = []        # (symbol, unit, kind, src)
        self.defined = {}        # symbol -> src (duplicate detection)
        self.headers = {}        # header name -> text
        self.variant_blocks = {}  # header name -> list of text
        self.unmapped = []
        self.unit_order = []
        self.pub_names = set()   # names declared by public (.h) headers
        self.provenance = []
        self.preludes = {}       # origin include name -> text injected into units only

    # -- unit assignment ------------------------------------------------
    def assign(self, name, src):
        for r in self.rules:
            if name in r['_sym'] or any(p.search(name) for p in r['_re']):
                return r['unit']
        fd = self.file_defaults.get(src)
        if fd:
            return fd
        self.unmapped.append((name, src))
        return self.default_unit

    def add_chunk(self, unit, text, guards, origin_include, src, symbol=None, kind=None):
        u = self.units.setdefault(unit, {'chunks': [], 'inc': [], 'guards': [], 'syms': []})
        u['chunks'].append(wrap(guards, text))
        u['syms'].append(symbol)
        u['guards'].append(guards)
        if origin_include and origin_include not in u['inc']:
            u['inc'].append(origin_include)
        if symbol:
            if symbol in self.defined and self.defined[symbol] != (src, unit):
                warn(f"symbol {symbol} defined in both {self.defined[symbol]} and {(src, unit)}")
            self.defined[symbol] = (src, unit)
            self.symbols.append((symbol, unit, kind, src))
        if unit not in self.unit_order:
            self.unit_order.append(unit)

    # -- per-file processing -----------------------------------------------
    def process(self, fname):
        path = os.path.join(self.up, fname)
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
        items = scan(text, fname)
        annotate(items)
        for it in items:
            classify(it)
        stem, ext = os.path.splitext(fname)
        is_header = ext == '.h'
        public_c = (not is_header) and fname in self.public_c
        if is_header:
            origin_inc = fname
        elif public_c:
            origin_inc = stem + '.h'
            prelude = (self.public_c[fname] or {}).get('unit_prelude')
            if prelude:
                self.preludes[origin_inc] = prelude.rstrip('\n') + '\n'
        else:
            origin_inc = stem + '_internal.h'

        pieces = []                 # in-place header text (headers) / decl text (c files)
        pub_pieces = []             # undeclared-but-public decls from a .c, for its paired .h
        variant_protos = []

        for it in items:
            kind = it.kind
            if kind == 'trivia':
                if is_header:
                    pieces.append(it.body)
                continue
            if it.is_dir:
                if is_header:
                    if it.dkind == 'include' and re.search(r'"[^"]+\.c"', it.darg or ''):
                        pieces.append(it.lead)
                        continue
                    if self.strip_empty_warnings and it.dkind == 'warning' and not it.darg:
                        pieces.append(it.lead)       # z88dk 2.5 prints garbage for empty #warning
                        continue
                    if it.dkind == 'warning' and it.darg:
                        # informational config notices: let programs silence them
                        pieces.append(it.lead + '#ifndef NABU_NO_CONFIG_WARNINGS\n'
                                      + it.body.lstrip('\n').rstrip('\n') + '\n#endif\n')
                        continue
                    pieces.append(it.lead + it.body)
                else:
                    if it.dkind in ('define', 'undef', 'pragma') or (
                            it.dkind == 'include' and not re.search(r'"[^"]+\.c"', it.darg or '')):
                        if not it.dead:
                            pieces.append(wrap(it.guards, it.lead + it.body))
                continue

            # ---- code items -----------------------------------------------
            hdr_text = None         # replacement text in header / decl text
            if is_header and kind in ('proto', 'funcdef', 'var') and it.name:
                self.pub_names.add(it.name)
            if not is_header and not it.dead and kind in ('proto', 'funcdef', 'var') \
                    and it.name in self.pub_names:
                if kind == 'proto':
                    continue                  # already declared in a public header
                hdr_text = ''                 # skip the internal declaration, keep definition
                if kind == 'funcdef':
                    self.handle_funcdef(it, fname, origin_inc, is_header, variant_protos)
                else:
                    self.handle_var(it, fname, origin_inc, is_header)
                continue
            if kind in ('typedef', 'sfr', 'proto'):
                hdr_text = it.lead + strip_storage(it.body, strip_inline=True) if kind == 'proto' else it.lead + it.body
            elif kind == 'at_var':
                tdef, mac = at_macro(it.body, it.name)
                hdr_text = it.lead + tdef + mac
            elif kind == 'funcdef':
                hdr_text = it.lead + make_proto(it.body)
                self.handle_funcdef(it, fname, origin_inc, is_header, variant_protos)
            elif kind == 'var':
                hdr_text = self.handle_var(it, fname, origin_inc, is_header)
            if hdr_text is None:
                continue
            if is_header:
                pieces.append(hdr_text)
            elif not it.dead:
                piece = wrap(self.strip_selectors(it.guards), hdr_text)
                # Upstream's .c is #included, so every non-static function/variable it defines is
                # callable even without a prototype in the .h. A library user needs a public
                # declaration (SDCC emits no EXTERN for undeclared functions), so those go to the
                # paired public header; static (private) ones stay in the internal header.
                if (kind in ('funcdef', 'var') and not public_c and (stem + '.h') in self.cfg['sources']
                        and not re.search(r'\bstatic\b', head_split(it.body)[0])):
                    pub_pieces.append(piece)
                else:
                    pieces.append(piece)

        # ---- compose header / internal header ----------------------------
        guard = re.sub(r'\W', '_', (stem + ('' if (is_header or public_c) else '_internal')).upper()) + '_GEN_H'
        if is_header:
            body = ''.join(pieces)
            hname = fname
            body = '#include <stdint.h>\n' + body
        else:
            inc = []
            if public_c:
                for i in (self.public_c[fname] or {}).get('includes', []):
                    inc.append(f'#include {i}\n')
                hname = stem + '.h'
            else:
                hname = stem + '_internal.h'
                inc.append(f'#include "{self.base_header}"\n')
                if os.path.exists(os.path.join(self.up, stem + '.h')) and stem + '.h' != self.base_header:
                    inc.append(f'#include "{stem}.h"\n')
            body = (f'#ifndef {guard}\n#define {guard}\n#include <stdint.h>\n#include <stdbool.h>\n'
                    + ''.join(inc) + '\n' + ''.join(pieces) + '\n#endif\n')
        self.headers.setdefault(hname, '')
        self.headers[hname] += body
        if pub_pieces:
            ph = stem + '.h'
            extra = ('\n// ---- generated: functions/variables that upstream defines in ' + fname +
                     ' without declaring them in ' + ph + ' ----\n' + ''.join(pub_pieces))
            cur = self.headers[ph]
            k = cur.rfind('#endif')          # keep inside the include guard
            self.headers[ph] = (cur[:k] + extra + '\n' + cur[k:]) if k >= 0 else cur + extra
        if variant_protos:
            self.variant_blocks.setdefault(stem + '.h' if (is_header or public_c) else
                                           (stem + '.h' if os.path.exists(os.path.join(self.up, stem + '.h'))
                                            else hname), []).extend(variant_protos)

    def strip_selectors(self, guards):
        out = []
        for g in guards:
            if any(re.fullmatch(r'defined\(' + re.escape(p) + r'\w+\)', g) for p in self.selectors):
                continue
            out.append(g)
        return out

    def find_selector(self, guards):
        for g in guards:
            for p in self.selectors:
                m = re.fullmatch(r'defined\((' + re.escape(p) + r'\w+)\)', g)
                if m:
                    return m.group(1), p
        return None, None

    def handle_var(self, it, fname, origin_inc, is_header):
        name = it.name
        sel, prefix = self.find_selector(it.guards)
        body = it.body
        newname = name
        extra = ''
        if sel and prefix:
            newname = f'{name}_{sel[len(prefix):]}'
            head, rest = head_split(body)
            body = re.sub(r'\b' + re.escape(name) + r'\b', newname, head, count=1) + rest
            extra = f'#define {name} {newname}\n'
        tdef, ext = make_extern(body, newname)
        hdr_text = it.lead + tdef + ext + extra
        if not it.dead:
            _, unit_body = split_type_body(strip_storage(body), newname)
            if sel:
                unit = sel.lower()
                unit_guards = self.strip_selectors(it.guards)
            else:
                unit = self.assign(newname, fname)
                unit_guards = it.guards
            lead = '' if is_header else it.lead
            self.add_chunk(unit, lead + unit_body + ('' if unit_body.endswith('\n') else '\n'),
                           unit_guards, origin_inc, fname, newname, 'var')
        return hdr_text

    def handle_asm_split(self, it, body, lead, fname, origin_inc):
        """A __naked function that only holds a library of asm helpers (manifest 'asm_split').

        Each helper starts with a comment header '; nl_name: ...' (preceded by a dashes line).
        Split it into one naked function per helper, named after the label, so each can be
        assigned to its own unit by the normal rules and the linker only pulls in the helpers
        used. Cross-helper references become PUBLIC/EXTERN in link_asm_labels(). Helpers must
        not fall through into the next one; that is checked."""
        m = re.search(r'__asm\b(.*)__endasm', body, re.S)
        if not m:
            return False
        lines = m.group(1).split('\n')
        starts = []
        for i, l in enumerate(lines):
            h = re.match(r'\s*;\s*([A-Za-z_]\w*):', l)
            if h and i and re.match(r'\s*;\s*-{5,}\s*$', lines[i - 1]) and \
                    re.search(r'^\s*%s:' % re.escape(h.group(1)), '\n'.join(lines[i:]), re.M):
                starts.append((i - 1, h.group(1)))
        if not starts:
            return False
        starts[0] = (0, starts[0][1])
        for k, (a, name) in enumerate(starts):
            b = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
            grp = lines[a:b]
            code = [re.sub(r';.*', '', l).strip() for l in grp]
            code = [c for c in code if c and not c.endswith(':')]
            if not code or not re.match(r'(ret\b|jp\s+[^(,]+$|jr\s+[^,]+$|reti|retn|def[bwms]\b|db\b|dw\b)', code[-1]):
                warn(f"{fname}: asm helper {name} in {it.name} may fall through (ends with "
                     f"'{code[-1] if code else ''}')")
            text = (f'void {name}() __naked {{\n\n  __asm\n' + '\n'.join(grp).rstrip() +
                    '\n\n  __endasm;\n}\n')
            self.add_chunk(self.assign(name, fname), (lead if k == 0 else '') + text, it.guards,
                           origin_inc, fname, name, 'asm-helper')
        return True

    def handle_funcdef(self, it, fname, origin_inc, is_header, variant_protos):
        if it.dead:
            return
        body = strip_storage(it.body)
        dm = body_disable_macros(it.body)
        lead = '' if is_header else it.lead
        if not dm and it.name in (self.cfg.get('asm_split') or []):
            if self.handle_asm_split(it, body, lead, fname, origin_inc):
                return
        if not dm:
            unit = self.assign(it.name, fname)
            self.add_chunk(unit, lead + body + '\n', it.guards, origin_inc, fname, it.name, 'func')
            return
        # one unit per DISABLE_* combination
        warn(f"{fname}:{it.line}: {it.name}() uses {', '.join(dm)} inside its body -> "
             f"{2 ** len(dm)} variants (each its own unit, selected by macro in the header)")
        for r in range(len(dm) + 1):
            for sub in combinations(dm, r):
                defset = frozenset(sub)
                vname = it.name + variant_suffix(defset)
                text = resolve_body(body, defset)
                text = re.sub(r'\b' + re.escape(it.name) + r'(\s*\()', vname + r'\1', text, count=1)
                self.add_chunk(vname, lead + text + '\n', it.guards, origin_inc, fname, vname, 'func-variant')
                if r:
                    variant_protos.append((it.name, vname, dm, defset, make_proto(text), it.guards))
        # prototype for variants' base is the normal one in the header

    # -- per-symbol objects ----------------------------------------------
    def explode(self):
        """Split every unit listed in manifest 'per_function' into one unit per symbol.

        Symbols that reference each other cyclically cannot live in separate objects (z80asm
        scans a library once), so strongly connected components are merged into one unit.
        References are found by identifier scan, including asm blocks (which use '_name')."""
        for uname in self.cfg.get('per_function', []) or []:
            u = self.units.get(uname)
            if not u:
                continue
            n = len(u['chunks'])
            if any(sy is None for sy in u['syms']):
                warn(f"per_function: {uname} has chunks without a symbol; left whole")
                continue
            idx = {}
            for i, sy in enumerate(u['syms']):
                idx.setdefault(sy, []).append(i)
            edges = [set() for _ in range(n)]
            for i, text in enumerate(u['chunks']):
                for t in set(re.findall(r'\w+', text)):
                    for cand in (t, t[1:] if t.startswith('_') else None):
                        for j in idx.get(cand, ()):
                            if j != i:
                                edges[i].add(j)
            # Tarjan SCC (iterative-safe sizes are small; recursion is fine)
            index, low, on, stack, comp = {}, {}, set(), [], {}
            counter = [0]
            def strong(v):
                index[v] = low[v] = counter[0]; counter[0] += 1
                stack.append(v); on.add(v)
                for w in sorted(edges[v]):
                    if w not in index:
                        strong(w); low[v] = min(low[v], low[w])
                    elif w in on:
                        low[v] = min(low[v], index[w])
                if low[v] == index[v]:
                    members = []
                    while True:
                        w = stack.pop(); on.discard(w); members.append(w)
                        if w == v:
                            break
                    for m in members:
                        comp[m] = min(members)
            for v in range(n):
                if v not in index:
                    strong(v)
            groups = {}
            for i in range(n):
                groups.setdefault(comp[i], []).append(i)
            newnames = {}
            for rep, members in sorted(groups.items()):
                base = u['syms'][rep].lstrip('_') or u['syms'][rep]
                nm = base
                while nm in self.units and nm != uname or nm in newnames.values():
                    nm = nm + '_'
                newnames[rep] = nm
                if len(members) > 1:
                    warn(f"per_function: {uname}: {', '.join(u['syms'][m] for m in members)} "
                         f"are mutually dependent -> kept together as {nm}")
            owner = {}
            for rep, members in groups.items():
                for m in members:
                    owner[u['syms'][m]] = newnames[rep]
            for rep, members in sorted(groups.items()):
                nm = newnames[rep]
                self.units[nm] = {'chunks': [u['chunks'][m] for m in members],
                                  'inc': list(u['inc']),
                                  'guards': [u['guards'][m] for m in members],
                                  'syms': [u['syms'][m] for m in members]}
            self.unit_order = [x for o in self.unit_order
                               for x in ([newnames[r] for r in sorted(groups)] if o == uname else [o])]
            if uname not in newnames.values():
                del self.units[uname]
            self.symbols = [(sy, owner.get(sy, un) if un == uname else un, k, src)
                            for sy, un, k, src in self.symbols]

    # -- asm labels shared between functions ------------------------------
    ASM_BLOCK = re.compile(r'(__asm\b)(.*?)(__endasm)', re.S)
    ASM_LABEL = re.compile(r'^[ \t]*([A-Za-z_]\w*):', re.M)

    def link_asm_labels(self):
        """Asm blocks may jump/call labels defined in *another* function's asm block (upstream is
        one translation unit, so that just works). Once the functions are in different objects the
        label must be PUBLIC in its defining object and EXTERN in each referencing one. Only labels
        defined in exactly one unit and referenced from another unit are exported."""
        def code(asm):
            return re.sub(r';[^\n]*', '', asm)
        defs = {}                                   # label -> set(unit)
        for un, u in self.units.items():
            for text in u['chunks']:
                for m in self.ASM_BLOCK.finditer(text):
                    for l in self.ASM_LABEL.findall(code(m.group(2))):
                        defs.setdefault(l, set()).add(un)
        defs = {l: next(iter(us)) for l, us in defs.items() if len(us) == 1}
        refs = {}                                   # unit -> labels it needs from elsewhere
        exported = set()
        for un, u in self.units.items():
            for text in u['chunks']:
                for m in self.ASM_BLOCK.finditer(text):
                    for t in set(re.findall(r'[A-Za-z_]\w*', code(m.group(2)))):
                        if t in defs and defs[t] != un:
                            refs.setdefault(un, set()).add(t)
                            exported.add(t)
        def patch(un, text):
            def sub(m):
                body = code(m.group(2))
                lines = []
                for l in sorted(exported):
                    if defs[l] == un and re.search(r'^[ \t]*%s:' % re.escape(l), body, re.M):
                        lines.append(f'      PUBLIC {l}')
                for l in sorted(refs.get(un, ())):
                    if re.search(r'\b%s\b' % re.escape(l), body):
                        lines.append(f'      EXTERN {l}')
                if not lines:
                    return m.group(0)
                inner = m.group(2)
                # jr cannot reach another object: relative jumps to external labels become jp
                for l in sorted(refs.get(un, ())):
                    inner = re.sub(r'(?m)^([ \t]*(?:\w+:[ \t]*)?)jr([ \t]+(?:(?:nz|z|nc|c)[ \t]*,[ \t]*)?%s\b)'
                                   % re.escape(l), r'\1jp\2', inner)
                    if re.search(r'(?m)^[^;\n]*\bdjnz[ \t]+%s\b' % re.escape(l), inner):
                        warn(f"asm in unit {un}: djnz to external label {l} cannot be linked")
                return m.group(1) + '\n' + '\n'.join(lines) + inner + m.group(3)
            return self.ASM_BLOCK.sub(sub, text)
        for un, u in self.units.items():
            u['chunks'] = [patch(un, t) for t in u['chunks']]
        self.asm_labels = sorted(exported)

    # -- outputs ---------------------------------------------------------
    def variant_text(self, hname):
        blocks = self.variant_blocks.get(hname)
        if not blocks:
            return ''
        out = ['\n// ---- generated: DISABLE_* variants (selected at compile time by the macros below) ----\n']
        by_name = {}
        for base, vname, dm, defset, proto, guards in blocks:
            by_name.setdefault(base, {'dm': dm, 'v': []})['v'].append((vname, defset, proto, guards))
        for base, info in by_name.items():
            for vname, defset, proto, guards in info['v']:
                out.append(wrap(guards, proto))
            first = True
            for vname, defset, proto, guards in info['v']:
                conds = [(f'defined({d})' if d in defset else f'!defined({d})') for d in info['dm']]
                out.append(f"#{'if' if first else 'elif'} " + ' && '.join(conds) + '\n')
                out.append(f'  #define {base} {vname}\n')
                first = False
            out.append('#endif\n')
        return ''.join(out)

    def write(self):
        out = self.out
        for sub in ('include', 'src'):
            d = os.path.join(out, sub)
            if os.path.isdir(d):
                shutil.rmtree(d)
            os.makedirs(d)
        for name, text in self.headers.items():
            text = text + self.variant_text(name)
            banner = f'// GENERATED by tools/split.py - DO NOT EDIT. Edit manifest.yaml / split.py instead.\n'
            with open(os.path.join(out, 'include', name), 'w') as f:
                f.write(banner + text)
        unit_lines = []
        for name in self.unit_order:
            u = self.units[name]
            targets = []
            for t in ('hb', 'cpm'):
                if any(guard_active(g, t) for g in u['guards']):
                    targets.append(t)
            if not targets:
                continue
            inc = ''.join(f'#include "{i}"\n' for i in u['inc'])
            inc += ''.join(self.preludes.get(i, '') for i in u['inc'])
            with open(os.path.join(out, 'src', name + '.c'), 'w') as f:
                f.write('// GENERATED by tools/split.py - DO NOT EDIT.\n' + inc + '\n' + '\n'.join(u['chunks']))
            unit_lines.append(f"{name} {','.join(targets)}\n")
        with open(os.path.join(out, 'units.txt'), 'w') as f:
            f.writelines(unit_lines)
        with open(os.path.join(out, 'symbols.txt'), 'w') as f:
            for s in self.symbols:
                f.write(' '.join(s) + '\n')
        with open(os.path.join(out, 'report.txt'), 'w') as f:
            f.write('\n'.join(self.provenance) + '\n\n')
            f.write('\n'.join(WARNINGS) + '\n')
            if self.unmapped:
                f.write('\nUNMAPPED (fell back to default unit):\n')
                for n, s in self.unmapped:
                    f.write(f'  {n}  ({s})\n')


def upstream_info(up):
    """Human-readable provenance of the upstream sources (commit, dirty flag, library version)."""
    lines = [f'upstream dir:      {up}']
    try:
        def git(*a):
            return subprocess.run(['git', '-C', up, *a], capture_output=True, text=True, check=True).stdout.strip()
        commit = git('rev-parse', '--short', 'HEAD')
        dirty = git('status', '--porcelain', '--', '.')
        subject = git('log', '-1', '--format=%s')
        lines.append(f'upstream commit:   {commit}{" (+ uncommitted changes)" if dirty else ""}  {subject}')
    except Exception:
        lines.append('upstream commit:   unknown (not a git checkout)')
    try:
        with open(os.path.join(up, 'NABU-LIB.h'), encoding='utf-8', errors='replace') as f:
            m = re.search(r'Last updated on (\S+)', f.read(4000))
        lines.append(f'NABU-LIB.h:        last updated {m.group(1) if m else "unknown"}')
    except OSError:
        pass
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--manifest', default=os.path.join(root, 'manifest.yaml'))
    ap.add_argument('--upstream', help='upstream NABULIB directory (overrides manifest)')
    ap.add_argument('--out', default=os.path.join(root, 'gen'))
    ap.add_argument('--z88dk-version', default='unknown', help='toolchain version string to record in report.txt')
    ap.add_argument('--strict', action='store_true', help='fail if any symbol is unmapped')
    ap.add_argument('--list', action='store_true', help='just list items found (for writing the manifest)')
    a = ap.parse_args()

    with open(a.manifest) as f:
        cfg = yaml.safe_load(f)
    up = a.upstream or cfg.get('upstream', '../NABU-LIB/NABULIB')
    if not os.path.isabs(up):
        up = os.path.normpath(os.path.join(root, up))
    if not os.path.isdir(up):
        sys.exit(f'upstream dir not found: {up}')

    g = Gen(cfg, up, a.out)
    g.provenance = upstream_info(up) + [f'z88dk:             {a.z88dk_version}']
    if a.list:
        for fname in cfg['sources']:
            with open(os.path.join(up, fname), encoding='utf-8', errors='replace') as f:
                items = scan(f.read(), fname)
            annotate(items)
            for it in items:
                classify(it)
                if it.kind in ('funcdef', 'var', 'proto', 'at_var', 'sfr'):
                    print(f'{fname}:{it.line}\t{it.kind}\t{it.name}\t{"DEAD" if it.dead else ""}\t{it.guards}')
        return

    for fname in cfg['sources']:
        g.process(fname)
    g.explode()
    g.link_asm_labels()
    os.makedirs(a.out, exist_ok=True)
    g.write()
    # keep gen/.gitkeep
    open(os.path.join(a.out, '.gitkeep'), 'a').close()
    print('\n'.join(g.provenance))
    print(f'{len(g.units)} units, {len(g.symbols)} symbols, {len(WARNINGS)} warnings; '
          f'{len(g.unmapped)} unmapped -> {a.out}')
    if a.strict and g.unmapped:
        for n, s in g.unmapped:
            print(f'  unmapped: {n} ({s})', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
