// Z80-Retro replacements for the keyboard / joystick functions (see retro/DELTA.md sections 2-3).
// There is no NABU keyboard ISR on the Retro, so the ring buffer is not used.

extern int getk(void);   // z88dk libc: CP/M BDOS call 6, returns 0 if no key is waiting

// Non-blocking console read, 0 if nothing waiting (same contract as upstream's getKey()).
uint8_t getKey() {
  return getk();
}

// Ported exactly as the z80retro-lib fork has it (SIO channel A status, bit 0 = rx ready).
uint8_t isKeyPressed() __naked {
  __asm
    in   a, (0x32)
    and  1
    ld   l, a
    ret
  __endasm;
}

// Ported exactly as the fork has it: one raw read of SIO channel A data. It does NOT wait
// for the receiver-ready bit.
uint8_t getChar() __naked {
  __asm
    in   a, (0x30)
    ld   l, a
    ret
  __endasm;
}

// Joysticks are active low on IO_JOY0 (0xA8) / IO_JOY1 (0xA9). Returns the inverted value so
// the Joy_* masks work as on the NABU.
uint8_t getJoyStatus(uint8_t joyNum) {
  switch (joyNum) {
    case 0:  return ~IO_JOY0;
    case 1:  return ~IO_JOY1;
  }
  return 0;
}
