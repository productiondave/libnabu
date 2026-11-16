// Z80-Retro: bulk VRAM writers, paced for 10 MHz (retro/DELTA.md section 5).
// Per byte: nl_outBlock = 16*N + 28 T-states, nl_fill = 16*N + 27 (N = manifest retro.vram_pad.block;
// N=6 -> 124 T-states = 12.4 us at 10 MHz, about the spacing the fork's C loop + vdp_put() produces).
// (An earlier N=2, 6 us, was too fast: patterns loaded garbled on hardware.) The padding goes BEFORE outi because outi's Z flag
// drives the loop branch. e is free after the counts are split into b (inner) and d (outer).
// vdp_refreshViewPort does NOT use these: it has its own unpadded loop (vdp_buffer unit).
void _vdp_outBlock(uint8_t *src, uint16_t len) __naked {

  (void)src;
  (void)len;

  __asm

    pop bc
    pop hl
    pop de
    push de
    push hl
    push bc

  ; ------------------------------------------------------------------------
  ; nl_outBlock: stream bytes to VRAM at the current write address
  ;   in:  hl = source, de = count (0 is allowed)
  ;   out: a, bc, de, hl changed
  ; ------------------------------------------------------------------------
  nl_outBlock:

    ld a, d
    or e
    ret z

    ; b = inner count (0 means 256), d = outer passes
    ld b, e
    dec de
    inc d
    ld c, _IO_VDPDATA

  nl_obLoop:

    ld e, @PAD_BLOCK@
  nl_obPad:
    dec e
    jr nz, nl_obPad

    outi
    jp nz, nl_obLoop

    dec d
    jp nz, nl_obLoop

    ret

  __endasm;
}

void _vdp_fill(uint16_t len, uint8_t value) __naked {

  (void)len;
  (void)value;

  __asm

    pop bc
    pop de
    pop hl
    push hl
    push de
    push bc
    ld a, l

  ; ------------------------------------------------------------------------
  ; nl_fill: write the same value to VRAM at the current write address
  ;   in:  de = count (0 is allowed), a = value
  ;   out: a and hl kept. bc, de changed
  ; ------------------------------------------------------------------------
  nl_fill:

    ld c, a
    ld a, d
    or e
    ld a, c
    ret z

    ld b, e
    dec de
    inc d
    ld c, _IO_VDPDATA

  nl_flLoop:

    out (c), a
    ld e, @PAD_BLOCK@
  nl_flPad:
    dec e
    jr nz, nl_flPad
    djnz nl_flLoop

    dec d
    jr nz, nl_flLoop

    ret

  __endasm;
}
