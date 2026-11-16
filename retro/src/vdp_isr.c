// Z80-Retro replacements for the VDP "interrupt" functions (see retro/DELTA.md section 4).
// The Retro VDP interrupt is not wired to the CPU. On the rev2 VDP board the INT line is
// readable on joystick port 0 bit 1 (active low), so the frame sync is polled.

void vdp_waitVDPReadyInt() {
  while ((IO_JOY0 & 0x02) != 0)
    ;
  vdpStatusRegVal = IO_VDPLATCH;      // reading status also clears the VDP INT
  vdpIsReady = true;
}

void waitVdpISR() {
  ;
}

void vdp_enableVDPReadyInt() {
  _vdpInterruptEnabled = true;
  vdp_setRegister(1, _vdpReg1Val | 0b00100000);
}

void vdp_disableVDPReadyInt() {
  vdp_setRegister(1, _vdpReg1Val);
}

void vdp_addISR(void (*isr)()) __z88dk_fastcall {
  (void)isr;
}

void vdp_removeISR() {
  ;
}
