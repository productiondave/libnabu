// Z80-Retro replacement for initNABULIBAudio (see retro/DELTA.md section 7).
// Upstream's loop does `ld c,_IO_AYLATCH / outi / dec c / outi`, i.e. it assumes the AY data port is
// ONE BELOW the latch port (NABU: latch 0x41, data 0x40). On the Retro (optional "nouveau" audio
// card) latch = 0xB0 and data = 0xB1, so `dec c` would send the data to 0xAF. Here both ports are
// named explicitly. Register values are upstream's: 6=0, 8..10=0, 7=0x78, 11..13=0.
void initNABULIBAudio() __naked {

  __asm

      ld hl, nl_audioInitTable
      ld b, 8

    nl_audioInitLoop:

      ld a, (hl)
      inc hl
      out (_IO_AYLATCH), a
      ld a, (hl)
      inc hl
      out (_IO_AYDATA), a
      djnz nl_audioInitLoop

      ret

    nl_audioInitTable:

      defb 6, 0x00
      defb 8, 0x00
      defb 9, 0x00
      defb 10, 0x00
      defb 7, 0x78
      defb 11, 0x00
      defb 12, 0x00
      defb 13, 0x00

  __endasm;
}
