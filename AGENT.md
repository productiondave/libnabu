# AGENT.md - regenerating libnabu from upstream NABU-LIB

libnabu turns the upstream **single-header** NABU-LIB (`NABU-LIB.h` `#include`s `NABU-LIB.c`)
into a proper z88dk library: one object per *unit*, packed into `nabu_hb.lib` (+nabu,
`BIN_TYPE=BIN_HOMEBREW`) and `nabu_cpm.lib` (+cpm, `BIN_TYPE=BIN_CPM`). Upstream will not move
away from the single-header pattern, so this conversion is **repeatable**: it is redone whenever
upstream changes. This file is the procedure for doing that.

## Ground rules

- **Upstream is read-only.** Default location `../NABU-LIB/NABULIB` (override: `UPSTREAM=...` on
  the make line, or in `Make.local`). Never edit it. `../nabu-games` is also off limits.
- **Never edit `gen/` or `build/`.** They are output (gitignored; `gen/.gitkeep` keeps the folder).
  Fixes go in exactly one of:
  - `manifest.yaml` - which unit a symbol lives in, which files are processed, per-file settings;
  - `tools/split.py` - how upstream constructs are transformed (a *general* problem);
  - `tools/order_objs.py`, `Makefile` - build mechanics.
- Prefer a manifest change over a script change. Change the script only for a new *kind* of
  upstream construct, and then handle it generally, not for one symbol.
- No emulator/runtime testing. Success = it generates, compiles, links, and the checks below pass.
- Do not commit unless asked.

## Layout

```
manifest.yaml        hand-maintained: sources, symbol->unit rules, special files
tools/split.py       upstream -> gen/   (headers, units, units.txt, symbols.txt, report.txt)
tools/order_objs.py  orders objects dependents-first for the .lib; fails on unit cycles
Makefile             make [gen|libs|nabu|cpm|smoke|clean|distclean]
tests/smoke/         tiny program linked against each lib (link-only check)
examples/tetris/     real program built against the libs (copy of nabu-games/tetris)
gen/include/         headers users compile against (-I gen/include)
gen/src/             one .c per unit
```

Toolchain defaults to z88dk 2.5 at `../z88dk-2.5/z88dk` (`Z88DIR`; override in `Make.local` or on
the make line). `PyYAML` is required. Last verified with z88dk v26997-37960a1a59-20261111.
It is fine to adapt the generator/manifest to a newer z88dk, as long as the process stays
repeatable (no hand edits of `gen/`).

## The procedure

1. **Check upstream changed**: `git -C ../NABU-LIB log -1 --format=%h` / diff of `NABULIB/*`
   (the previous values are in the old `gen/report.txt`; copy it aside before regenerating).
2. **Regenerate and build**: `make` (runs `tools/split.py` then builds both libs).
   Read `gen/report.txt`; its header records the upstream commit, the `NABU-LIB.h` "last updated"
   date and the z88dk version used, so a changed result can be attributed to upstream or to the
   compiler. Include these in your report.
3. **Triage anything unmapped.** `report.txt` lists `UNMAPPED` symbols that fell to
   `default_unit` (`misc`). Run `python3 tools/split.py --strict` to make that a hard failure.
   Give each new symbol a home in `manifest.yaml` `rules` (first match wins), grouping by
   *what is always used together*, and rare/big things (fonts, filestore, sprites, multiplayer)
   apart. `python3 tools/split.py --list` prints every item the parser found.
4. **Fix compile errors** (see the table below), re-run `make`.
5. **Fix unit cycles.** `make` fails with `order_objs: dependency cycle: a -> b -> a`. z80asm scans
   a library once, so no ordering satisfies a cycle. Move the one or two symbols that close the
   loop into the right unit (the loop is usually a single symbol; `z88dk-z80nm build/nabu/x.o`
   shows Symbols (`G`) and Externs (`U`)).
6. **Run the checks** (all must pass, for both libs):
   - `make check` (public API cross-check): every function/variable upstream's headers declare must
     exist in each lib. `MISSING` = upstream defines it but the lib lacks it (fix grouping/
     transformation; exit 1). `WARNING ... never defined upstream` = upstream bug (declared, no
     body; e.g. `vt_foregroundColor`) - not an error, mention it in the report.
   - `make smoke` links `tests/smoke/main.c` against both libs.
   - `make -C examples/tetris` builds `000001.nabu` and `tetris.com`.
   - Confirm pruning still works: in the `.map` of the smoke/tetris build, units for features the
     program doesn't use (`vdp_sprite`, `vdp_gfx`, `rn_*`, `multiplayer`, other `font_*`,
     `nabutracker`) must NOT appear; a G1-only program must not link `vdp_text`.
   - With `-DDISABLE_HCCA_RX_INT`, the `initNABULib__no_HCCA_RX_INT` variant links and `hcca_rx`
     does not.
7. **Report** (below).

## How upstream constructs are handled (so you know what is deliberate)

| Upstream | In the library |
|---|---|
| `NABU-LIB.h` ends with `#include "NABU-LIB.c"` | include dropped; definitions move to units |
| globals defined in the header | `extern` in the header, defined once in a unit |
| `static` functions/vars | `static` stripped; private ones declared in `<stem>_internal.h` |
| non-static function in `.c` with no prototype in `.h` | prototype added to the public header (needed: SDCC emits no `EXTERN` for undeclared calls) |
| `inline` | stripped (real calls); inlining across units is not possible |
| `__at (0xADDR)` variables | pointer macro `#define X (*(T *)0xADDR)` (no symbol; a header definition gives duplicate-symbol link errors) |
| anonymous `struct {..} var` | named `struct __t_var`, type in header, `extern` + definition split |
| `#ifndef DISABLE_*` around top-level items | treated as "not defined": always compiled; the linker prunes |
| `DISABLE_*` **inside** a function/asm body (`initNABULib`, `getChar`) | one unit per combination (`name__no_X__no_Y`); header redirects `name` by macro from the user's `DISABLE_*` defines |
| units listed in `per_function` (manifest) | exploded into one object per symbol after rule assignment; symbols that reference each other cyclically are merged automatically (reported in `gen/report.txt`) |
| `BIN_TYPE` conditionals | preserved; library built once per `BIN_TYPE`; CP/M-only units are skipped for homebrew via `units.txt` |
| `FONT_*` (`selector_prefixes`) | each guarded `ASCII` becomes `ASCII_<FONT>` in its own unit; header does `#define ASCII ASCII_<FONT>` |
| header-only RetroNET files (functions defined in `.h`) | prototypes in header, bodies in units |
| `.c` with no `.h` meant to be included (`DirEntryReader.c`, `public_c_files`) | public `<stem>.h` generated; `unit_prelude` declares what the program must supply |
| empty `#warning` lines in headers | dropped (`strip_empty_warnings`): z88dk 2.5 prints uninitialised memory as the message. `#warning` lines *with* text are kept |

`DirEntryReader.c` expects the *program* to define `copyBuf`, `COPY_BUF_LEN`, `UpperStr()`.
`copyBuf`/`UpperStr` become link-time requirements; `COPY_BUF_LEN` is fixed at 128 in the library
(see the `unit_prelude` comment in `manifest.yaml`). If upstream changes that contract, revisit.

## Failure modes seen so far

| Symptom | Cause | Fix |
|---|---|---|
| `error 91 ... mismatches with declaration` | prototype attribute differs from the definition (e.g. `__naked`) | split.py strips `__naked` from prototypes; extend for other definition-only attributes |
| `duplicate definition: ... __at var` at link | `__at` variable defined in a header | already converted to macros; check a new `__at` form is parsed (`at_macro`) |
| `error: undefined symbol: _foo` **at compile** of the user program | function defined in upstream `.c` but never declared in a `.h` | handled generally (public header gets a prototype); if it still happens the item was classified wrongly - check with `--list` |
| `undefined symbol` at link although the unit exists | unit cycle / wrong object order | fix grouping; `order_objs.py` reports cycles |
| `too many parameters` / implicit-declaration errors in a unit | unit missing an include (e.g. `<string.h>`) | add to `public_c_files.<file>.includes` or the per-file include lists in split.py |
| `undefined symbol _copyBuf/_UpperStr` | program does not supply what `DirEntryReader` needs | expected; that is the contract |
| a whole feature gets linked into a program that doesn't use it | a symbol in a generic unit references a specialised unit | move the shared symbol into a generic unit (e.g. `vdp_buffer`, `vdp_state`) |

## Report format (what to tell the user after a run)

- upstream version / commit, and whether anything changed;
- units added/removed/renamed, symbols added/removed/moved (compare `gen/symbols.txt` before/after:
  `cp gen/symbols.txt /tmp/before.txt` before regenerating, then `diff`);
- new manifest rules you added and why; any script change and the general construct it handles;
- warnings in `report.txt` (variants, unmapped);
- result of each check in step 6, with object counts (`make` output), the `make check` summary
  and the module lists from the maps;
- anything that needs the user's decision (e.g. a new upstream dependency on the including
  program, like `DirEntryReader`'s).

## Known gaps

- `nabu-games.{h,c}`-style helpers (the games' own header-includes-.c layer) are not part of
  this library; the tetris example carries its own copies.
- Inline assembly stays inline; no `.asm` extraction. Asm blocks reference C symbols by name and
  rely on z80asm auto-extern - a missing symbol shows up as a link error, not at generation time.

## Z80-Retro target (`nabu_retro.lib`)

`make` also builds `build/retro/nabu_retro.lib` and `gen/retro/include/` for the Z80-Retro SBC
(10 MHz, TMS9118A VDP on 0x80/0x81, CP/M, no AY chip, no interrupts, no RetroNET). It is the
CP/M build plus an **overlay**; the `nabu` and `cpm` outputs are unaffected (regenerating them
must stay byte-identical, check with a `diff -r` of `gen/include`, `gen/src`).

- **Where it lives:** `manifest.yaml` section `retro:` (`exclude_sources`, `remove`, `replace`,
  `api_excluded`, `header`), hand-written units in `retro/src/`, and the rationale for every
  difference in `retro/DELTA.md`. Generated with `tools/split.py --target retro` (-> `gen/retro`).
- **How it works:** symbols matching `retro.remove` are dropped from whichever unit upstream puts
  them in; each `retro.replace` file is appended to the named unit as one chunk (before `explode`
  and `link_asm_labels`, so it gets PUBLIC/EXTERN labels like generated code); `retro.header`
  patches port numbers / `Joy_*` bits in the generated `NABU-LIB.h` and appends overrides
  (`#undef` of upstream macros that become functions).
- **`vdp_refreshViewPort` is a fixed contract.** `retro/src/vdp_buffer_refresh.c` is the fork's
  routine (z80retro-lib 8262f71): `outi` / `jp nz`, 26 T-states per byte, so a full refresh fits the
  VDP blanking window at 60 fps. Never replace it with upstream's `nl_outBlock` call or add pacing.
  After any change run the check below. The other bulk writers (`nl_outA`, `nl_outBlock`, `nl_fill`)
  are padded to the fork's `vdp_put` spacing (about 5.6-6.0 us per byte at 10 MHz).
- **After an upstream update**, for each `retro.replace` file compare it with the upstream function
  it replaces (`git -C ../NABU-LIB diff <old>..<new> -- NABULIB/NABU-LIB.c`) and re-check:
  1. register contracts of the `nl_*` helpers the replacements call or replace (`nl_outA`,
     `nl_outBlock`, `nl_fill`: which registers are preserved);
  2. symbols the refresh routine reads (`_vdp_textBuffer`, `_vdpPatternNameTableAddr`,
     `_vdpTextBufferSize`);
  3. anything new upstream that touches NABU-only hardware (HCCA, AY, keyboard ISR, `0xFF2x` BIOS
     variables, the `dec c` latch/data trick in `initNABULIBAudio`). Add it to `retro.remove` or
     `retro.replace` and to `retro/DELTA.md`.
  Then `make`, `make check` (reports the intentionally absent set), `make smoke`, and verify the
  refresh loop bytes (`ed a3 c2 ..` = `outi` / `jp nz`) in the linked `smoke_retro` binary.
- **Test status:** snake, tetris and invaders (nabu-games) verified on a Z80-Retro and on the Nouveau board with `vram_pad: {block: 6, a: 4, loop: 1}`. The audio path (0xB0/0xB1) is exercised by the Nouveau only. Not covered: `vdp_plotHires`/`vdp_plotColor`, `vdp_getCharAtLocationVRAM` (read-back path, still upstream's 3.58 MHz read delay).
