# Z80-Retro delta from upstream NABU-LIB

Status: implemented as the `retro:` section of `manifest.yaml` plus `retro/src/*.c`; builds, links and passes
`make check` / `make smoke`. Hardware-tested: snake, tetris and invaders run correctly on a Z80-Retro and on the Nouveau board (VRAM pacing `block: 6, a: 4, loop: 1`).

Source of truth: `z80retro-lib` at c4beae0 plus its uncommitted working-tree edit.
Fork baseline: upstream be9c795 (2023-03-28). Re-based onto upstream 050d623 by the `retro` target in this repo.
Target: Z80-Retro SBC, 10 MHz, VDP rev2 board, CP/M only, no AY-3-8910, no RetroNET.

Each row says what the Retro target must do. "replace" = hand-written unit in `retro/src/`,
"define" = header prelude override, "exclude" = not generated or linked for Retro.

## 1. I/O ports  (define)

| Symbol | NABU (upstream) | Retro |
|---|---|---|
| `IO_VDPDATA` / `IO_VDPLATCH` | 0xA0 / 0xA1 | 0x80 / 0x81 |
| `IO_AYLATCH` / `IO_AYDATA` | 0x41 / 0x40 | 0xB0 / 0xB1 (nouveau card, optional hardware). Note latch and data are in swapped order vs NABU. |
| `IO_JOY0` / `IO_JOY1` | n/a | 0xA8 / 0xA9 (volatile) |
| `IO_HCCA`, `IO_KEYBOARD`, `IO_KEYBOARD_STATUS`, `IO_CONTROL` | 0x80, 0x90, 0x91, 0x00 | exclude. NABU 0x80 would collide with Retro's VDP. |
| `CONTROL_*`, `INT_MASK_*`, `INTERUPT_VECTOR_*`, `IOPORTA/B` | present | exclude |
| SIO | n/a | 0x30 data, 0x32 control/status (used by `isKeyPressed`/`getChar`) |

## 2. Joystick  (define + replace)

- `JOYSTICKENUM` bit values: Left 0x04, Down 0x40, Right 0x20, Up 0x80, Button 0x01 (upstream: 0x01/0x02/0x04/0x08/0x10).
- `getJoyStatus(n)`: returns `~IO_JOY0` for 0, `~IO_JOY1` for 1, else 0 (hardware is active-low).
  Upstream makes `getJoyStatus` a macro over the keyboard ISR's joystick variables, so the Retro version is a replacement function plus a macro override.
- README says joy0 = 0xA9, the code maps joystick 0 to 0xA8. Code wins. Fix the README in the doc pass.

## 3. Console input  (replace)

- `getKey()`: `return getk();` (z88dk libc, CP/M BDOS call 6, 0 if no key). Replaces upstream's ring-buffer `getKey`.
- `isKeyPressed()`: `in a,(0x32)` then `and 1` (SIO RR0 receive-ready). Ported as is. Fork comment calls it "dubious".
- `getChar()`: single `in a,(0x30)` with no wait for ready. Ported as is (decision: behaviour not changed in this update).
- `readLine`: unchanged from upstream apart from calling the above.

## 4. Init and interrupts  (replace / exclude)

- `initNABULib()`: only seed `_randomSeed` from the `R` register, `srand`, then `initNABULIBAudio()`. No ROM-select write to port 0, no `im 2`, no vector table at 0xFF00, no AY port-A interrupt mask.
  Upstream's `initNABULib` has `DISABLE_*` variants that libnabu builds per combination. The Retro replacement has one variant and the header must not redirect it.
- `isrHCCARX`, `isrKeyboard`, HCCA buffers and every `hcca_*` function: exclude.
- `vdp_addISR`, `vdp_removeISR`, `waitVdpISR`: replace with no-ops.
- `vdp_enableVDPReadyInt`: set `_vdpInterruptEnabled`, then `vdp_setRegister(1, _vdpReg1Val | 0x20)`.
- `vdp_disableVDPReadyInt`: `vdp_setRegister(1, _vdpReg1Val)`.
- `vdp_waitVDPReadyInt()`: busy-wait while `(IO_JOY0 & 0x02) != 0` (rev2 board routes the VDP INT line to joystick port bit 1, active low), then `vdpStatusRegVal = IO_VDPLATCH`.
  Hangs on a rev1 board (accepted, rev2 only). Upstream makes this a macro; Retro replaces the macro with a function.

## 5. VDP timing  (replace)

- **`vdp_refreshViewPort()`: fixed contract, copy verbatim.** The shipping loop (commit 8262f71) is:
  set write address inline via `out (0x81)` (low byte, then high byte | 0x40), then `outi` / `jp nz` (26 T-states = 2.6 us per byte at 10 MHz) with an outer `dec d` / `jp nz` for 256-byte blocks, then `in a,(0x81)` to clear the status flag.
  Inputs: `__vdp_textBuffer`, `__vdpPatternNameTableAddr`, `__vdpTextBufferSize`.
  The README's 48 T-state table describes the older loop replaced by 8262f71. It is stale.
  This function must fit in the blanking window so refresh holds 60 fps. Do NOT add pacing.
- **`vdp_put(c)`** (fastcall): `IO_VDPDATA = c` then `ld b,2 / djnz` delay. Used for all non-blanking-critical streamed writes (fill, clear, loaders, sprites, print, scroll). Upstream does these through `_vdp_outBlock` / `_vdp_fill` / `nl_outA` which are paced for 3.58 MHz, so the Retro target replaces those helpers with versions that use the `vdp_put` delay as one named macro.
- Reads (`vdp_setReadAddress` then `IO_VDPDATA`) are not delayed in the fork. Upstream's `nl_rdAddr` has its own delay. Keep the fork's behaviour for reads unless testing shows otherwise.
- `vdpStatusRegVal` (renamed from the upstream status variable) is saved in the wait loop, because reading status resets the VRAM pointer. Streaming code must not read the status register mid-write.
- VDP rev2 support: commits 859eb8b, f9fc33b, 11bf892, 7969077.

## 6. Video modes  (verify)

- G1 mode (`VDP_MODE_G1`, `vdp_initG1Mode`): registers 2=0x05, 3=0x80, 4=0x01, 5=0x20, 6=0x00, `fgColor` forced 0, `_vdpCursorMaxX` 31, `_vdpCursorMaxXFull` 32, text buffer size 768. Upstream now has G1 (enum value changed to 5 because `VDP_MODE_TEXT80` was added as 4). **Verified:** upstream's G1 row sets R0=0x00, R1=0xC0|sprite bits, R2=0x05, R3=0x80, R4=0x01, R5=0x20, R6=0x00, name table 0x1400, pattern generator 0x0800, color table 0x2000, sprite attributes 0x1000, 32 columns, 768-byte buffer: identical to the fork. No Retro override needed.
- `vdp_initTextMode80` and `VDP_MODE_TEXT80`: exclude (V9938/F18A only). The enum numbering stays as upstream so shared game code keeps compiling.
- `vdp_loadColorToId`, `vdp_printJustified`, `vdp_loadPatternToId`: now in upstream. Drop the fork versions. The fork's `vdp_loadColorToId` still writes `IO_VDPDATA` directly in a few places, which was probably an oversight and should not be carried forward.
- `vdp_setPatternColor`: stays in nabu-games (commit 95a6ffc).

## 7. Sound  (define, keep)

- `ayWrite`/`ayRead`, `initNABULIBAudio`, `playNoteDelay`, NabuTracker: keep, using ports 0xB0/0xB1. They are harmless on a stock Retro (writes go nowhere).
- Upstream's current `initNABULIBAudio` already writes the same values the fork used (6=0, 8-10=0, 7=0x78, 11-13=0), but it does `ld c,_IO_AYLATCH / outi / dec c / outi`, assuming data = latch - 1 (NABU 0x41/0x40). On the Retro mapping (latch 0xB0, data 0xB1) that would send data to 0xAF, so `retro/src/ay.c` replaces it with explicit `out (_IO_AYLATCH)` / `out (_IO_AYDATA)`. All other upstream AY code names both ports explicitly, so the remap carries through.

## 8. CP/M terminal functions  (replace / verify)

- `isCloudCPM()` returns false. Upstream reads NABU BIOS memory at 0xFF29.
- `vt_*` functions: **audited, no change needed.** The only BIOS variable they read is `_EMULATION_MODE` at 0xFF12, the same address and test (`== 0`) the fork already used. `_CLOUD_CPM_KEY` (0xFF29) is only read by `isCloudCPM` (replaced). `_SCREEN_COLOR` (0xFF25) and `_CPM_COLUMN_WIDTH` (0xFF2E) are declared in the header but not used by any library code.

## 9. Excluded entirely

`RetroNET-FileStore`, `RetroNET-IAControl`, `RetroNET-Multiplayer`, `RetroNET-CPMDrive`, all `hcca_*`.
`DirEntryReader` is pure CP/M BDOS and stays (it needs the program to supply `copyBuf`/`UpperStr`).

## 10. Do not carry over

- The uncommitted `x >> 3` / `y >> 3` rewrite in `vdp_plotHires`/`vdp_plotColor` (upstream rewrote these).
- `(void)` prototypes, `__z88dk_fastcall` added to prototypes, `#warning` removals (upstream covers these, and `-DNABU_NO_CONFIG_WARNINGS` handles warnings).
