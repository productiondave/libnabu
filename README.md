# libnabu

A multi-object [z88dk](https://github.com/z88dk/z88dk) library for the NABU PC, generated from
the upstream single-header [NABU-LIB](https://github.com/DJSures/NABU-LIB).

Upstream NABU-LIB is one translation unit: `NABU-LIB.h` `#include`s `NABU-LIB.c`, so every program
compiles the whole library. libnabu splits it into many small objects packed into `.lib` files,
so the linker only includes what a program actually calls. A G1-mode program doesn't carry the
text printer, sprites, the RetroNET file store, or the three fonts it didn't pick.

The upstream author keeps the single-header pattern, so libnabu is not a fork. The library
sources are **generated** from upstream by a script and regenerated whenever upstream changes.

## Build

Requirements: z88dk 2.5 with SDCC (default location `../z88dk-2.5/z88dk`), Python 3 with
PyYAML, and an upstream checkout (default `../NABU-LIB/NABULIB`).

```sh
make              # generate gen/ and build both libraries
make smoke        # link-only smoke test against both libraries
make clean        # remove build/   (distclean also empties gen/)
```

Override locations in `Make.local` (see `Make.local.example`) or on the command line:

```sh
make Z88DIR=/path/to/z88dk UPSTREAM=/path/to/NABU-LIB/NABULIB
```

Outputs:

| File | Target | Flags |
|---|---|---|
| `build/nabu/nabu_hb.lib` | NABU homebrew (`000001.nabu`) | `+nabu -DBIN_TYPE=BIN_HOMEBREW` |
| `build/cpm/nabu_cpm.lib` | NABU CP/M (`.com`) | `+cpm -DBIN_TYPE=BIN_CPM -O3 --opt-code-speed` |
| `gen/include/*.h` | headers to compile against | |

## Using the library

Your source stays the same as with upstream, including `BIN_TYPE`, `DISABLE_*` and `FONT_*`.
Only the build line changes: add `gen/include` to the include path and link the library.

```c
#define FONT_STANDARD
#include "patterns.h"
#include "NABU-LIB.h"

void main() {
  initNABULib();
  vdp_initTextMode(0xF, 0x4, true);
  vdp_loadASCIIFont(ASCII);
  vdp_print("Hello libnabu");
}
```

```sh
# NABU homebrew
zcc +nabu -vn -compiler=sdcc -DBIN_TYPE=BIN_HOMEBREW -I libnabu/gen/include main.c \
    -Llibnabu/build/nabu -lnabu_hb -m -create-app -o 000001.nabu

# CP/M
zcc +cpm -compiler=sdcc -DBIN_TYPE=BIN_CPM -I libnabu/gen/include main.c \
    -Llibnabu/build/cpm -lnabu_cpm -m -create-app -o hello.com
```

See `examples/tetris` for a complete program (`make -C examples/tetris`).

### Differences from upstream you may notice

- **`DISABLE_*`** still works. Where upstream uses it inside a function (`initNABULib`,
  `getChar`), the library has one prebuilt variant per combination and the header picks the right
  one from your defines. Define them *before* including `NABU-LIB.h`, as before.
- **Fonts**: `#define FONT_STANDARD` and `ASCII` work as before, but only the chosen font is linked.
- **`inline`** helpers (`ayWrite`, `vdp_setRegister`, ...) are ordinary calls, not expanded at the
  call site, so they are a little slower than upstream.
- **`DirEntryReader`** needs your program to define `uint8_t copyBuf[N]` (N >= 128) and
  `void UpperStr(uint8_t *s)`, as it does upstream. If missing you get `undefined symbol
  _copyBuf` at link time, and only if you use it. `COPY_BUF_LEN` is fixed at 128 inside the
  library.

## How it works

```
manifest.yaml  --+
                 +--> tools/split.py --> gen/include/*.h, gen/src/<unit>.c --> zcc -c --> .o --> z80asm -x --> .lib
upstream NABULIB-+                                                          (tools/order_objs.py orders the objects)
```

- `manifest.yaml` is the only hand-maintained input: which upstream files to process and which
  unit (object) each symbol belongs in.
- `tools/split.py` parses the upstream C, turns definitions into declarations for the headers,
  and writes one `.c` per unit.
- `tools/order_objs.py` orders objects so dependents come first (z80asm scans a library once) and
  fails the build if units depend on each other in a cycle.

`gen/` and `build/` are output and are not committed (`gen/.gitkeep` keeps the folder).

## Updating when upstream changes

Rebuild with `make`, then fix anything reported in `gen/report.txt` by editing `manifest.yaml`
(or `tools/split.py` for a genuinely new kind of construct). Never edit `gen/`.
The full procedure, a table of how each upstream construct is handled, known failure modes and
the report to produce are in [AGENT.md](AGENT.md), written so an agent can repeat the process.

## Layout

```
manifest.yaml        symbol -> unit mapping and per-file settings
tools/split.py       generator
tools/order_objs.py  object ordering / cycle check
Makefile             build
AGENT.md             regeneration procedure
tests/smoke/         link-only smoke test
examples/tetris/     example program (copy of nabu-games/tetris)
gen/                 generated headers and sources (not committed)
build/               objects and libraries (not committed)
```

## Status

Compiles and links for both targets with z88dk 2.5 (v26997-37960a1a59-20261111); verified by
link checks only (no emulator or hardware
testing yet). Not yet done: an automated check that every public prototype has a library symbol.

## Licence and credits

NABU-LIB is by DJ Sures (<https://nabu.ca>, <https://github.com/DJSures/NABU-LIB>) and the generated
library contains his code; see upstream for its licence. The tetris example comes from
nabu-games, which is under its own licence (`LICENSE.md` in that project).
