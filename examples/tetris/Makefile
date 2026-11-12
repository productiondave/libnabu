# Builds the tetris example against libnabu (run 'make' in the libnabu root first).
#   make nabu   -> 000001.nabu  (+nabu, nabu_hb.lib)
#   make cpm    -> TETRIS.COM   (+cpm,  nabu_cpm.lib)
LIBNABU := $(abspath ../..)
Z88DIR  ?= $(LIBNABU)/../z88dk
-include $(LIBNABU)/Make.local

export PATH := $(Z88DIR)/bin:$(PATH)
export ZCCCFG := $(Z88DIR)/lib/config
ZCC := $(Z88DIR)/bin/zcc

INC := -I$(LIBNABU)/gen/include -I.
NABU_FLAGS := +nabu -vn -compiler=sdcc -DBIN_TYPE=BIN_HOMEBREW --list -m -create-app $(INC)
CPM_FLAGS  := +cpm -compiler=sdcc -DBIN_TYPE=BIN_CPM --list -m -create-app -O3 --opt-code-speed $(INC)

.PHONY: all nabu cpm clean
all: nabu cpm
nabu: 000001.nabu
cpm: tetris.com

$(LIBNABU)/build/nabu/nabu_hb.lib $(LIBNABU)/build/cpm/nabu_cpm.lib:
	$(MAKE) -C $(LIBNABU) libs

000001.nabu: tetris.c $(LIBNABU)/build/nabu/nabu_hb.lib
	$(ZCC) $(NABU_FLAGS) -L$(LIBNABU)/build/nabu -lnabu_hb -o $@ tetris.c

tetris.com: tetris.c $(LIBNABU)/build/cpm/nabu_cpm.lib
	$(ZCC) $(CPM_FLAGS) -L$(LIBNABU)/build/cpm -lnabu_cpm -o $@ tetris.c

clean:
	rm -f *.com *.COM *.nabu *.NABU *.lis *.map tetris
