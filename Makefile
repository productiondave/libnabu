# libnabu - multi-object z88dk library generated from upstream NABU-LIB.
#
#   make            generate sources (tools/split.py) and build both libraries
#   make gen        only (re)generate gen/
#   make nabu|cpm   only one library
#   make clean      remove build/ (gen/ is kept; make distclean removes it too)
#
# Outputs: build/nabu/nabu_hb.lib   (+nabu,  BIN_TYPE=BIN_HOMEBREW)
#          build/cpm/nabu_cpm.lib   (+cpm,   BIN_TYPE=BIN_CPM)
#          gen/include/*.h          headers to use with the libraries

TOP := $(CURDIR)

# Defaults mirror nabu-games: z88dk checked out next to this project.
Z88DIR   ?= $(TOP)/../z88dk
UPSTREAM ?=
-include $(TOP)/Make.local

export PATH := $(Z88DIR)/bin:$(PATH)
export ZCCCFG := $(Z88DIR)/lib/config
ZCC   := $(Z88DIR)/bin/zcc
Z80ASM := $(Z88DIR)/bin/z88dk-z80asm
PYTHON ?= python3

INC := -I$(TOP)/gen/include
NABU_FLAGS := +nabu -vn -compiler=sdcc -DBIN_TYPE=BIN_HOMEBREW $(INC)
CPM_FLAGS  := +cpm  -compiler=sdcc -DBIN_TYPE=BIN_CPM -O3 --opt-code-speed $(INC)

SPLIT_ARGS := $(if $(UPSTREAM),--upstream $(UPSTREAM),) $(SPLIT_EXTRA)

.PHONY: all gen nabu cpm clean distclean libs smoke

all: gen
	$(MAKE) libs

libs: nabu cpm

gen:
	$(PYTHON) tools/split.py $(SPLIT_ARGS)

# Unit lists come from gen/units.txt ("<unit> <hb,cpm>")
UNITS_HB  = $(shell awk '$$2 ~ /hb/  {print $$1}' gen/units.txt 2>/dev/null)
UNITS_CPM = $(shell awk '$$2 ~ /cpm/ {print $$1}' gen/units.txt 2>/dev/null)

OBJS_HB  = $(UNITS_HB:%=build/nabu/%.o)
OBJS_CPM = $(UNITS_CPM:%=build/cpm/%.o)

nabu: build/nabu/nabu_hb.lib
cpm:  build/cpm/nabu_cpm.lib

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

clean:
	rm -rf build

distclean: clean
	find gen -mindepth 1 ! -name .gitkeep -delete
