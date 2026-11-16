// Z80-Retro vdp_refreshViewPort: FIXED CONTRACT, do not pace or "improve" (retro/DELTA.md section 5).
//
// This is the z80retro-lib routine from commit 8262f71, instruction for instruction. The inner
// loop is `outi` + `jp nz` = 16 + 10 = 26 T-states per byte (2.6 us at 10 MHz), which is what lets
// a full refresh complete inside the VDP blanking window and keeps the 60 fps frame rate.
// Upstream's version calls nl_wrAddr and then nl_outBlock (30 T-states, tuned for 3.58 MHz).
//
// Only differences from the fork (none touch the loop):
//   - port numbers come from the _IO_VDPDATA / _IO_VDPLATCH symbols (0x80 / 0x81 on the Retro)
//   - a zero length returns immediately (the fork would write 65536 bytes)
//   - the VDP status register read at the end is `in a,(_IO_VDPLATCH)` as before
void vdp_refreshViewPort() __naked {

  __asm

    ld hl, __vdp_textBuffer
    ld de, (__vdpPatternNameTableAddr)
    ld bc, (__vdpTextBufferSize)
    ld a, b
    or c
    ret z
    ld a, e
    out (_IO_VDPLATCH), a
    ld a, d
    or 0x40
    out (_IO_VDPLATCH), a

    ld d, b
    ld e, c

    ld c, _IO_VDPDATA
    ld b, e
    inc e
    dec e
    jr z, vdp_write_loop
    inc d

  vdp_write_loop:
    outi
    jp nz, vdp_write_loop
    dec d
    jp nz, vdp_write_loop
    in a, (_IO_VDPLATCH)
    ret

  __endasm;
}
