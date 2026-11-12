// Link smoke test: not meant to run, only to prove the libraries link and that
// unused units (sprites, hcca, filestore, other fonts, ...) are NOT pulled in.
// BIN_TYPE is supplied by the Makefile (-DBIN_TYPE=...).
#define FONT_STANDARD
#include "patterns.h"
#include "NABU-LIB.h"

void main() {
  initNABULib();
  vdp_initTextMode(0xF, 0x4, true);
  vdp_loadASCIIFont(ASCII);
  vdp_print("Hello libnabu");
  ayWrite(7, 0x38);
  while (1) {
    if (isKeyPressed())
      vdp_write(getChar());
  }
}
