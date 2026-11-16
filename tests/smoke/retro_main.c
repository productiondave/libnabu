// Retro link test (make smoke): touches every function the Retro overlay replaces, plus the
// features nabu-games uses (G1 mode, sprites, plotting, scrolling, AY on 0xB0/0xB1).
#define FONT_STANDARD
#include "patterns.h"
#include "NABU-LIB.h"

#ifndef TARGET_RETRO
#error "retro smoke test must be built with the Retro headers"
#endif

uint8_t pat[8] = {0xFF, 0x81, 0x81, 0x81, 0x81, 0x81, 0x81, 0xFF};
uint8_t col[8] = {0xF4, 0xF4, 0xF4, 0xF4, 0xF4, 0xF4, 0xF4, 0xF4};

void main() {
  initNABULib();
  vdp_initG1Mode(0x4, false, false, false, false);
  vdp_loadPatternToId(1, pat);
  vdp_loadColorToId(1, col);
  vdp_setCharAtLocationBuf(1, 1, 1);
  vdp_initTextMode(0xF, 0x4, true);
  vdp_loadASCIIFont(ASCII);
  vdp_print("Hello retro");
  vdp_scrollTextUp(0, 23);
  vdp_clearScreen();
  ayWrite(7, 0x38);
  playNoteDelay(0, 40, 10);
  while (1) {
    vdp_waitVDPReadyInt();
    vdp_refreshViewPort();
    if (getJoyStatus(0) & Joy_Button)
      vdp_write(getKey());
    if (isKeyPressed())
      vdp_write(getChar());
    if (isCloudCPM())
      vdp_removeISR();
  }
}
