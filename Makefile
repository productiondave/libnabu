# libnabu - multi-object z88dk library generated from upstream NABU-LIB.
#
#   make            generate sources (tools/split.py) and build both libraries
#   make gen        only (re)generate gen/
#   make nabu|cpm   only one library
#   make clean      remove build/ (gen/ is kept; make distclean removes it too)
#
# Outputs: build/nabu/nabu_hb.lib   (+nabu,  BIN_TYPE=BIN_HOMEBREW)
#          build/cpm/nabu_cpm.lib   (+cpm,   BIN_TYPE=BIN_CPM)
#          build/retro/nabu_retro.lib (+cpm, Z80-Retro overlay, -DTARGET_RETRO; see retro/DELTA.md)
#          gen/include/*.h          headers to use with the libraries (gen/retro/include for retro)

TOP := $(CURDIR)

# Default: z88dk 2.5 checked out next to this project (override in Make.local or on the make line).
Z88DIR   ?= $(TOP)/../z88dk-2.5/z88dk
UPSTREAM ?=
-include $(TOP)/Make.local

export PATH := $(Z88DIR)/bin:$(PATH)
export ZCCCFG := $(Z88DIR)/lib/config
ZCC   := $(Z88DIR)/bin/zcc
Z80ASM := $(Z88DIR)/bin/z88dk-z80asm
PYTHON ?= python3

INC := -I$(TOP)/gen/include
NABU_FLAGS := +nabu -vn -compiler=sdcc -DBIN_TYPE=BIN_HOMEBREW -Cs--disable-warning -Cs283 $(INC)
CPM_FLAGS  := +cpm  -compiler=sdcc -DBIN_TYPE=BIN_CPM -O3 --opt-code-speed -Cs--disable-warning -Cs283 $(INC)
# Z80-Retro: same compiler setup as CP/M, Retro headers (retro/DELTA.md), -DTARGET_RETRO
RETRO_FLAGS := +cpm -compiler=sdcc -DBIN_TYPE=BIN_CPM -DTARGET_RETRO -O3 --opt-code-speed -Cs--disable-warning -Cs283 -I$(TOP)/gen/retro/include

Z88DK_VERSION := $(shell $(ZCC) 2>&1 | head -1 | sed 's/^zcc - Frontend for the z88dk Cross-C Compiler - //')
SPLIT_ARGS := $(if $(UPSTREAM),--upstream $(UPSTREAM),) --z88dk-version '$(Z88DK_VERSION)' $(SPLIT_EXTRA)

.PHONY: all gen nabu cpm retro clean distclean libs smoke check

all: gen
	$(MAKE) libs

libs: nabu cpm retro

gen:
	$(PYTHON) tools/split.py $(SPLIT_ARGS)
	$(PYTHON) tools/split.py --target retro $(SPLIT_ARGS)

# Unit lists come from gen/units.txt ("<unit> <hb,cpm>"); the Retro overlay has its own gen/retro/units.txt
UNITS_HB  = $(shell awk '$$2 ~ /hb/  {print $$1}' gen/units.txt 2>/dev/null)
UNITS_CPM = $(shell awk '$$2 ~ /cpm/ {print $$1}' gen/units.txt 2>/dev/null)
UNITS_RETRO = $(shell awk '$$2 ~ /cpm/ {print $$1}' gen/retro/units.txt 2>/dev/null)

OBJS_HB  = $(UNITS_HB:%=build/nabu/%.o)
OBJS_CPM = $(UNITS_CPM:%=build/cpm/%.o)
OBJS_RETRO = $(UNITS_RETRO:%=build/retro/%.o)

nabu: build/nabu/nabu_hb.lib
cpm:  build/cpm/nabu_cpm.lib
retro: build/retro/nabu_retro.lib

build/retro/%.o: gen/retro/src/%.c $(wildcard gen/retro/include/*.h)
	@mkdir -p $(@D)
	$(ZCC) $(RETRO_FLAGS) -c -o $@ $<

build/retro/nabu_retro.lib: $(OBJS_RETRO)
	rm -f $@
	o=$$($(PYTHON) tools/order_objs.py $(Z88DIR)/bin/z88dk-z80nm $(OBJS_RETRO)) && $(Z80ASM) -x$(basename $@) $$o

build/nabu/%.o: gen/src/%.c $(wildcard gen/include/*.h)
	@mkdir -p $(@D)
	$(ZCC) $(NABU_FLAGS) -c -o $@ $<

build/cpm/%.o: gen/src/%.c $(wildcard gen/include/*.h)
	@mkdir -p $(@D)
	$(ZCC) $(CPM_FLAGS) -c -o $@ $<

build/nabu/nabu_hb.lib: $(OBJS_HB)
	rm -f $@
	o=$$($(PYTHON) tools/order_objs.py $(Z88DIR)/bin/z88dk-z80nm $(OBJS_HB)) && $(Z80ASM) -x$(basename $@) $$o

build/cpm/nabu_cpm.lib: $(OBJS_CPM)
	rm -f $@
	o=$$($(PYTHON) tools/order_objs.py $(Z88DIR)/bin/z88dk-z80nm $(OBJS_CPM)) && $(Z80ASM) -x$(basename $@) $$o

# Link-only smoke test (no emulator): tiny program against each library; see the .map files
smoke: libs
	@mkdir -p build/smoke
	$(ZCC) $(NABU_FLAGS) -m -create-app tests/smoke/main.c -Lbuild/nabu -lnabu_hb -o build/smoke/smoke_nabu
	$(ZCC) $(CPM_FLAGS)  -m -create-app tests/smoke/main.c -Lbuild/cpm  -lnabu_cpm -o build/smoke/smoke_cpm
	$(ZCC) $(RETRO_FLAGS) -DNABU_NO_CONFIG_WARNINGS -m -create-app tests/smoke/retro_main.c -Lbuild/retro -lnabu_retro -o build/smoke/smoke_retro

# Public API cross-check: every symbol upstream's headers declare must exist in each library
check: libs
	$(PYTHON) tools/check_api.py --z88dk $(Z88DIR) $(if $(UPSTREAM),--upstream $(UPSTREAM),)

clean:
	rm -rf build

distclean: clean
	find gen -mindepth 1 ! -name .gitkeep -delete
