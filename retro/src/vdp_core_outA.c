// Z80-Retro: VRAM write pacing helpers (retro/DELTA.md section 5). All tunable in manifest `retro.vram_pad`.
// The TMS9918A needs a long gap between data-port accesses outside the blanking window. The fork's
// per-byte spacing (C loop + vdp_put's call/djnz/ret) is about 12 us at 10 MHz, so these aim for that.
// Both helpers preserve every register and all flags.

// nl_outA: write a to VRAM, then wait. T-states after the OUT (incl. ret) = 16*N + 44, N = vram_pad.a
void nl_outA() __naked {

  __asm

  ; ------------------------------------------------------------------------
  ; nl_outA: write a to VRAM, then pad
  ;   in:  a = byte
  ;   out: everything kept
  ; ------------------------------------------------------------------------
  nl_outA:

    out (_IO_VDPDATA), a
    push af
    ld a, @PAD_A@
  nl_oaPad:
    dec a
    jr nz, nl_oaPad
    pop af
    ret

  __endasm;
}

// nl_vramDelay: called right after an `out (_IO_VDPDATA),a` inside upstream's own tight loops
// (vdp_print, vdp_printPart, vdp_loadASCIIFontWithInverse; inserted by manifest `retro.patch`).
// Cost = 16*N + 50 T-states including the call, N = vram_pad.loop.
void nl_vramDelay() __naked {

  __asm

  ; ------------------------------------------------------------------------
  ; nl_vramDelay: wait, keeping all registers and flags
  ; ------------------------------------------------------------------------
  nl_vramDelay:

    push af
    ld a, @PAD_LOOP@
  nl_vdPad:
    dec a
    jr nz, nl_vdPad
    pop af
    ret

  __endasm;
}
