// Z80-Retro replacement for initNABULib (see retro/DELTA.md section 4).
// No ROM-select write, no IM2 / vector table, no AY interrupt mask: the Retro has no
// keyboard, HCCA or VDP interrupts. Only the RNG seed and the (optional) AY card init remain.
void initNABULib() {

  __asm
    push af
    ld a, r
    ld (__randomSeed), a
    pop af
  __endasm;

  srand(_randomSeed);

  initNABULIBAudio();
}
