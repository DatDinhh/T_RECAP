# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 HPS userspace streamer Makefile.
# File class: [1] hand-written HPS build infrastructure.
#
# This Makefile builds only the HPS transport/control program. It must not
# compile or hide FFT, IFFT, STFT/WOLA, magnitude-mask, reconstruction, or
# signal-quality algorithms. The FPGA fabric owns the signal-processing path;
# HPS reads committed DDR ring records, validates records, forwards UDP, accepts
# PC commands, and writes CSRs through generated contract headers.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := all

# -----------------------------------------------------------------------------
# Repository paths.
# -----------------------------------------------------------------------------
HPS_DIR       := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
REPO_ROOT     := $(abspath $(HPS_DIR)/../..)
SRC_DIR       := $(HPS_DIR)/src
INC_DIR       := $(HPS_DIR)/include
GEN_INC_DIR   := $(INC_DIR)/generated
CONFIG_DIR    := $(HPS_DIR)/config
SCRIPT_DIR    := $(HPS_DIR)/scripts
TEST_DIR      := $(HPS_DIR)/tests

BUILD_DIR     ?= $(REPO_ROOT)/build/hps
OBJ_DIR       ?= $(BUILD_DIR)/obj
BIN_DIR       ?= $(BUILD_DIR)/bin
RUNS_DIR      ?= $(REPO_ROOT)/runs/hps
OUT_DIR       ?= $(REPO_ROOT)/out/hps

TARGET_NAME   ?= trecap_udp_streamer
TARGET_BIN    ?= $(BIN_DIR)/$(TARGET_NAME)
STEP13_TEST_BIN ?= $(BIN_DIR)/test_step13_hps_transport
STEP14_TEST_BIN ?= $(BIN_DIR)/test_step14_command_path
CONFIG        ?= $(CONFIG_DIR)/trecap_hps_config.json

# -----------------------------------------------------------------------------
# Toolchain.
#
# Native host smoke build:
#   make -C sw/hps CC=gcc
#
# DE1-SoC cross build example:
#   make -C sw/hps CROSS_COMPILE=arm-linux-gnueabihf-
# -----------------------------------------------------------------------------
CROSS_COMPILE ?=
ifeq ($(origin CC),default)
CC := $(CROSS_COMPILE)gcc
endif
ifeq ($(origin AR),default)
AR := $(CROSS_COMPILE)ar
endif
ifeq ($(origin STRIP),default)
STRIP := $(CROSS_COMPILE)strip
endif

PYTHON        ?= python3
INSTALL       ?= install
MKDIR_P       ?= mkdir -p
RM            ?= rm -f
RMDIR         ?= rm -rf

# -----------------------------------------------------------------------------
# Sources specified by the repository architecture.
# The source files are intentionally listed explicitly so a missing module fails
# with a clear message instead of being silently omitted by a wildcard.
# -----------------------------------------------------------------------------
HPS_SOURCES := \
  $(SRC_DIR)/main.c \
  $(SRC_DIR)/trecap_udp_streamer.c \
  $(SRC_DIR)/config.c \
  $(SRC_DIR)/csr_map.c \
  $(SRC_DIR)/ring_reader.c \
  $(SRC_DIR)/udp_sender.c \
  $(SRC_DIR)/command_server.c \
  $(SRC_DIR)/command_bridge.c \
  $(SRC_DIR)/status_patch.c

HPS_PUBLIC_HEADERS := \
  $(INC_DIR)/trecap_hps_config.h \
  $(INC_DIR)/csr_map.h \
  $(INC_DIR)/ring_reader.h \
  $(INC_DIR)/trecap_ring_device.h \
  $(INC_DIR)/udp_sender.h \
  $(INC_DIR)/command_server.h \
  $(INC_DIR)/command_bridge.h \
  $(INC_DIR)/status_patch.h

GENERATED_HEADERS := \
  $(GEN_INC_DIR)/trecap_csr.h \
  $(GEN_INC_DIR)/trecap_packet.h

OBJECTS := $(patsubst $(SRC_DIR)/%.c,$(OBJ_DIR)/%.o,$(HPS_SOURCES))
DEPS    := $(OBJECTS:.o=.d)

STEP13_TEST_SOURCE := $(TEST_DIR)/test_step13_hps_transport.c
STEP13_TEST_LINK_SOURCES := \
  $(SRC_DIR)/csr_map.c \
  $(SRC_DIR)/ring_reader.c \
  $(SRC_DIR)/udp_sender.c \
  $(SRC_DIR)/command_server.c \
  $(SRC_DIR)/command_bridge.c \
  $(SRC_DIR)/status_patch.c

STEP14_TEST_SOURCE := $(TEST_DIR)/test_step14_command_path.c
STEP14_TEST_LINK_SOURCES := \
  $(SRC_DIR)/config.c \
  $(SRC_DIR)/csr_map.c \
  $(SRC_DIR)/ring_reader.c \
  $(SRC_DIR)/udp_sender.c \
  $(SRC_DIR)/command_server.c \
  $(SRC_DIR)/command_bridge.c

# -----------------------------------------------------------------------------
# Compiler/linker flags.
# -----------------------------------------------------------------------------
CPPFLAGS += \
  -I$(INC_DIR) \
  -I$(GEN_INC_DIR) \
  -D_POSIX_C_SOURCE=200809L \
  -D_DEFAULT_SOURCE \
  -DTRECAP_HPS_DEFAULT_CONFIG='"$(CONFIG)"'

CFLAGS ?= -O2 -g
CFLAGS += \
  -std=c11 \
  -pipe \
  -Wall \
  -Wextra \
  -Wpedantic \
  -Wconversion \
  -Wsign-conversion \
  -Wshadow \
  -Wformat=2 \
  -Wstrict-prototypes \
  -Wmissing-prototypes \
  -Werror=implicit-function-declaration \
  -ffunction-sections \
  -fdata-sections

LDFLAGS += -Wl,--gc-sections
LDLIBS  += -lm

WERROR ?= 0
ifeq ($(WERROR),1)
CFLAGS += -Werror
endif

SANITIZE ?= 0
ifeq ($(SANITIZE),1)
CFLAGS  += -fsanitize=address,undefined -fno-omit-frame-pointer
LDFLAGS += -fsanitize=address,undefined
endif

# -----------------------------------------------------------------------------
# Runtime/install/deploy knobs.
# -----------------------------------------------------------------------------
PREFIX       ?= /usr/local
BINDIR       ?= $(PREFIX)/bin
SYSCONFDIR   ?= /etc/trecap
DESTDIR      ?=
DEPLOY_HOST  ?= root@192.168.10.2
DEPLOY_DIR   ?= /usr/local/bin
DEPLOY_CONF  ?= /etc/trecap
RUN_ARGS     ?= --config $(CONFIG)

.PHONY: all
all: build ## Build the HPS UDP streamer binary.

.PHONY: help
help: ## Show available HPS Makefile targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nT-RECAP Phase 2 HPS targets:\n\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2} END {printf "\nCommon overrides: CC=..., CROSS_COMPILE=arm-linux-gnueabihf-, WERROR=1, SANITIZE=1\n\n"}' $(MAKEFILE_LIST)

.PHONY: show-config
show-config: ## Print resolved HPS build configuration.
	@printf '%-28s %s\n' 'HPS_DIR' '$(HPS_DIR)'
	printf '%-28s %s\n' 'REPO_ROOT' '$(REPO_ROOT)'
	printf '%-28s %s\n' 'BUILD_DIR' '$(BUILD_DIR)'
	printf '%-28s %s\n' 'TARGET_BIN' '$(TARGET_BIN)'
	printf '%-28s %s\n' 'CONFIG' '$(CONFIG)'
	printf '%-28s %s\n' 'CC' '$(CC)'
	printf '%-28s %s\n' 'CROSS_COMPILE' '$(CROSS_COMPILE)'
	printf '%-28s %s\n' 'CPPFLAGS' '$(CPPFLAGS)'
	printf '%-28s %s\n' 'CFLAGS' '$(CFLAGS)'
	printf '%-28s %s\n' 'LDFLAGS' '$(LDFLAGS)'
	printf '%-28s %s\n' 'LDLIBS' '$(LDLIBS)'

.PHONY: bootstrap
bootstrap: ## Create HPS source/include/config/script/test folders and .gitkeep files.
	@$(MKDIR_P) '$(SRC_DIR)' '$(INC_DIR)' '$(GEN_INC_DIR)' '$(CONFIG_DIR)' '$(SCRIPT_DIR)' '$(TEST_DIR)' '$(BUILD_DIR)' '$(RUNS_DIR)' '$(OUT_DIR)'
	for d in '$(SRC_DIR)' '$(INC_DIR)' '$(GEN_INC_DIR)' '$(CONFIG_DIR)' '$(SCRIPT_DIR)' '$(TEST_DIR)'; do
	  if [[ -d "$$d" && -z "$$(find "$$d" -mindepth 1 -maxdepth 1 -type f ! -name .gitkeep -print -quit)" ]]; then
	    touch "$$d/.gitkeep"
	  fi
	done
	printf 'bootstrap: OK\n'

.PHONY: check-layout
check-layout: ## Check HPS directory shape and generated-header placement.
	@missing=0
	for d in '$(SRC_DIR)' '$(INC_DIR)' '$(GEN_INC_DIR)' '$(CONFIG_DIR)' '$(SCRIPT_DIR)' '$(TEST_DIR)' '$(HPS_DIR)/systemd'; do
	  if [[ ! -d "$$d" ]]; then echo "ERROR: missing directory: $$d"; missing=1; fi
	done
	for f in $(GENERATED_HEADERS); do
	  if [[ ! -f "$$f" ]]; then echo "ERROR: missing generated header: $$f"; missing=1; fi
	done
	if [[ ! -f '$(CONFIG)' ]]; then echo "ERROR: missing HPS runtime config: $(CONFIG)"; missing=1; fi
	if find '$(HPS_DIR)' -path '*/include/generated/*' -type f | grep -vE '/(trecap_(csr|packet)\.h|\.gitkeep)$$' | grep -q .; then
	  echo 'ERROR: unexpected file under sw/hps/include/generated/';
	  find '$(HPS_DIR)' -path '*/include/generated/*' -type f | grep -vE '/(trecap_(csr|packet)\.h|\.gitkeep)$$' || true;
	  missing=1;
	fi
	if [[ $$missing -ne 0 ]]; then exit $$missing; fi
	printf 'check-layout: OK\n'

.PHONY: check-generated
check-generated: ## Require deterministic generated CSR/packet headers from root generator.
	@if [[ -f '$(REPO_ROOT)/scripts/check_generated.py' ]]; then
	  '$(PYTHON)' '$(REPO_ROOT)/scripts/check_generated.py' --root '$(REPO_ROOT)' --headers-only --quiet
	else
	  for f in $(GENERATED_HEADERS); do [[ -f "$$f" ]] || { echo "ERROR: missing generated header: $$f"; exit 2; }; done
	fi

.PHONY: check-config
check-config: ## Validate HPS runtime config against generated header versions and ring rules.
	@'$(PYTHON)' -c 'import json,sys; from pathlib import Path; p=Path(r"$(CONFIG)"); hook=lambda pairs: dict(pairs) if len(pairs)==len(dict(pairs)) else (_ for _ in ()).throw(ValueError("duplicate JSON key")); cfg=json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=hook); exact={"schema":"trecap_phase2_hps_runtime_config_v1","project":"T_RECAP_Phase2","board":"de1soc"}; bad_exact=[k for k,v in exact.items() if type(cfg.get(k)) is not str or cfg.get(k)!=v]; bad_exact and sys.exit("ERROR: invalid config identity field(s): "+", ".join(bad_exact)); int_fields=("csr_span_bytes","ring_size_bytes","ring_guard_bytes","telemetry_dst_port","command_listen_port","trusted_command_peer_port","transport_version_major","transport_version_minor"); bad_int=[k for k in int_fields if type(cfg.get(k)) is not int]; bad_int and sys.exit("ERROR: config integer field has wrong JSON type: "+", ".join(bad_int)); str_fields=("csr_base_phys","ring_base_hps_phys","ring_base_fpga","telemetry_dst_ip","trusted_command_peer"); bad_str=[k for k in str_fields if type(cfg.get(k)) is not str]; bad_str and sys.exit("ERROR: config string field has wrong JSON type: "+", ".join(bad_str)); bool_fields=("require_trusted_peer","use_nonblocking_udp","allow_cached_ring_mapping","stop_on_malformed_record"); bad_bool=[k for k in bool_fields if type(cfg.get(k)) is not bool]; bad_bool and sys.exit("ERROR: config boolean field has wrong JSON type: "+", ".join(bad_bool))'
	@'$(PYTHON)' -c 'import json,re,sys; from pathlib import Path; cfg_path=Path(r"$(CONFIG)"); csr_path=Path(r"$(GEN_INC_DIR)/trecap_csr.h"); pkt_path=Path(r"$(GEN_INC_DIR)/trecap_packet.h"); [p.exists() or sys.exit(f"ERROR: missing required file: {p}") for p in (cfg_path, csr_path, pkt_path)]; cfg=json.load(open(cfg_path, encoding="utf-8")); req=["schema","project","board","csr_base_phys","csr_span_bytes","ring_base_hps_phys","ring_base_fpga","ring_size_bytes","ring_guard_bytes","telemetry_dst_ip","telemetry_dst_port","command_listen_port","trusted_command_peer","trusted_command_peer_port","transport_version_major","transport_version_minor","require_trusted_peer","use_nonblocking_udp","allow_cached_ring_mapping","stop_on_malformed_record"]; missing=[k for k in req if k not in cfg]; missing and sys.exit("ERROR: config missing keys: "+", ".join(missing)); csr=csr_path.read_text(encoding="utf-8"); pkt=pkt_path.read_text(encoding="utf-8"); get=lambda text,name: int(re.search(r"^#define\s+"+re.escape(name)+r"\s+(?:UINT\d+_C\()?((?:0x)?[0-9a-fA-F]+)\)?[uU]?\b", text, re.M).group(1),0); pmj=get(pkt,"TPKT_TRANSPORT_VERSION_MAJOR"); pmi=get(pkt,"TPKT_TRANSPORT_VERSION_MINOR"); cmj=get(csr,"TCSR_VERSION_MAJOR"); cmi=get(csr,"TCSR_VERSION_MINOR"); (pmj,pmi)==(cmj,cmi) or sys.exit(f"ERROR: generated version mismatch: packet={pmj}.{pmi} csr={cmj}.{cmi}"); (int(cfg["transport_version_major"]),int(cfg["transport_version_minor"]))==(pmj,pmi) or sys.exit(f"ERROR: config transport version {cfg['transport_version_major']}.{cfg['transport_version_minor']} does not match generated {pmj}.{pmi}"); int(str(cfg["csr_base_phys"]),0)==0xff200000 or sys.exit("ERROR: csr_base_phys must equal 0xff200000"); int(cfg["csr_span_bytes"])==4096 or sys.exit("ERROR: csr_span_bytes must equal 4096"); int(str(cfg["ring_base_hps_phys"]),0)==0x3e000000 and int(str(cfg["ring_base_fpga"]),0)==0x3e000000 and int(cfg["ring_size_bytes"])==0x02000000 and int(cfg["ring_guard_bytes"])==64 or sys.exit("ERROR: ring geometry differs from frozen Step-12 carveout"); cfg["require_trusted_peer"] is True or sys.exit("ERROR: require_trusted_peer must be true"); cfg["use_nonblocking_udp"] is True or sys.exit("ERROR: canonical socket policy must be nonblocking"); cfg["allow_cached_ring_mapping"] is False or sys.exit("ERROR: cached ring mapping is forbidden"); cfg["stop_on_malformed_record"] is False or sys.exit("ERROR: canonical malformed policy must be latch-and-stay-alive"); bad_ports=[k for k in ("telemetry_dst_port","command_listen_port","trusted_command_peer_port") if not (1<=int(cfg[k])<=65535)]; bad_ports and sys.exit("ERROR: invalid UDP port field(s): "+", ".join(bad_ports)); int(cfg["trusted_command_peer_port"])==5007 or sys.exit("ERROR: trusted command source port must equal 5007"); print("check-config: OK")'
.PHONY: check-sources
check-sources: ## Fail fast if required HPS C source/header files are still missing.
	@missing=0
	for f in $(HPS_SOURCES) $(HPS_PUBLIC_HEADERS); do
	  if [[ ! -f "$$f" ]]; then echo "ERROR: missing HPS source/header: $$f"; missing=1; fi
	done
	if [[ $$missing -ne 0 ]]; then
	  echo 'HPS source tree is incomplete. Write sw/hps/src/*.c and sw/hps/include/*.h before make build.'
	  exit $$missing
	fi
	printf 'check-sources: OK\n'

.PHONY: check-no-signal-processing
check-no-signal-processing: ## Guard against accidentally adding core algorithms to HPS C code.
	@bad=0
	if find '$(SRC_DIR)' '$(INC_DIR)' -type f \( -name '*.c' -o -name '*.h' \) ! -path '*/include/generated/*' -print -quit | grep -q .; then
	  if grep -RInE '\b(stft|wola|ifft|fft_radix|hermitian|analysis_window|synthesis_window|trecap_fft|trecap_ifft)\b' '$(SRC_DIR)' '$(INC_DIR)' --include='*.c' --include='*.h' --exclude-dir=generated; then
	    echo 'ERROR: HPS code appears to contain signal-processing algorithm terms. Keep FFT/IFFT/WOLA/mask in FPGA/reference layers.'
	    bad=1
	  fi
	fi
	if [[ $$bad -ne 0 ]]; then exit $$bad; fi
	printf 'check-no-signal-processing: OK\n'

.PHONY: preflight
preflight: check-layout check-generated check-config check-no-signal-processing ## Checks that can pass before HPS C source files exist.

.PHONY: lint
lint: preflight ## Run HPS build hygiene checks without compiling incomplete source tree.
	@if [[ -x '$(REPO_ROOT)/scripts/lint.sh' ]]; then
	  '$(REPO_ROOT)/scripts/lint.sh' --basic --no-generated --quiet
	else
	  printf 'lint: root scripts/lint.sh not present; preflight completed only\n'
	fi

.PHONY: build
build: check-sources preflight $(TARGET_BIN) ## Compile and link the HPS UDP streamer.
	@printf 'build: %s\n' '$(TARGET_BIN)'

$(TARGET_BIN): $(OBJECTS) $(GENERATED_HEADERS) $(CONFIG)
	@$(MKDIR_P) '$(dir $(TARGET_BIN))'
	$(CC) $(LDFLAGS) -o '$@' $(OBJECTS) $(LDLIBS)

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c $(GENERATED_HEADERS)
	@$(MKDIR_P) '$(dir $@)'
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c '$<' -o '$@'

.PHONY: syntax
syntax: check-sources preflight ## Compile each HPS source with -fsyntax-only.
	@for src in $(HPS_SOURCES); do
	  echo "syntax: $$src";
	  $(CC) $(CPPFLAGS) $(CFLAGS) -fsyntax-only "$$src";
	done
	printf 'syntax: OK\n'

$(STEP13_TEST_BIN): $(STEP13_TEST_SOURCE) $(SRC_DIR)/config.c \
                   $(SRC_DIR)/trecap_udp_streamer.c $(STEP13_TEST_LINK_SOURCES) \
                   $(HPS_PUBLIC_HEADERS) $(GENERATED_HEADERS) $(MAKEFILE_LIST)
	@$(MKDIR_P) '$(dir $(STEP13_TEST_BIN))'
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) \
	  -Wl,--wrap=sendmsg \
	  -Wl,--wrap=trecap_csr_commit_ring_rd \
	  -Wl,--wrap=trecap_csr_set_control_levels \
	  -o '$@' '$(STEP13_TEST_SOURCE)' $(STEP13_TEST_LINK_SOURCES) $(LDLIBS)

.PHONY: test-step13-transport
test-step13-transport: check-sources preflight $(STEP13_TEST_BIN) ## Run RAM-backed Step-13 HPS transport tests.
	@ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
	 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
		 '$(STEP13_TEST_BIN)'

$(STEP14_TEST_BIN): $(STEP14_TEST_SOURCE) $(STEP14_TEST_LINK_SOURCES) \
                    $(HPS_PUBLIC_HEADERS) $(GENERATED_HEADERS) $(MAKEFILE_LIST)
	@$(MKDIR_P) '$(dir $(STEP14_TEST_BIN))'
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) \
	  -o '$@' '$(STEP14_TEST_SOURCE)' $(STEP14_TEST_LINK_SOURCES) $(LDLIBS)

.PHONY: test-step14-command-path
test-step14-command-path: check-sources preflight $(STEP14_TEST_BIN) ## Run deterministic Step-14 command/bridge tests.
	@ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
	 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
	 '$(STEP14_TEST_BIN)'

.PHONY: size
size: build ## Print binary size.
	@ls -lh '$(TARGET_BIN)'
	@if command -v size >/dev/null 2>&1; then size '$(TARGET_BIN)' || true; fi

.PHONY: strip
strip: build ## Copy and strip the binary into OUT_DIR.
	@$(MKDIR_P) '$(OUT_DIR)'
	cp '$(TARGET_BIN)' '$(OUT_DIR)/$(TARGET_NAME).stripped'
	'$(STRIP)' '$(OUT_DIR)/$(TARGET_NAME).stripped'
	ls -lh '$(OUT_DIR)/$(TARGET_NAME).stripped'

.PHONY: install
install: build ## Install binary and runtime config under DESTDIR/PREFIX.
	@$(INSTALL) -d '$(DESTDIR)$(BINDIR)' '$(DESTDIR)$(SYSCONFDIR)'
	$(INSTALL) -m 0755 '$(TARGET_BIN)' '$(DESTDIR)$(BINDIR)/$(TARGET_NAME)'
	$(INSTALL) -m 0644 '$(CONFIG)' '$(DESTDIR)$(SYSCONFDIR)/trecap_hps_config.json'
	printf 'install: %s and %s\n' '$(DESTDIR)$(BINDIR)/$(TARGET_NAME)' '$(DESTDIR)$(SYSCONFDIR)/trecap_hps_config.json'

.PHONY: run
run: build ## Run the streamer locally. Usually requires root on HPS for /dev/mem.
	@exec '$(TARGET_BIN)' $(RUN_ARGS)

.PHONY: deploy
deploy: build ## Copy binary/config to DE1-SoC HPS over SSH. Override DEPLOY_HOST as needed.
	@ssh '$(DEPLOY_HOST)' 'mkdir -p $(DEPLOY_DIR) $(DEPLOY_CONF)'
	scp '$(TARGET_BIN)' '$(DEPLOY_HOST):$(DEPLOY_DIR)/$(TARGET_NAME)'
	scp '$(CONFIG)' '$(DEPLOY_HOST):$(DEPLOY_CONF)/trecap_hps_config.json'
	printf 'deploy: copied to %s\n' '$(DEPLOY_HOST)'

.PHONY: print-sources
print-sources: ## Print the exact hand-written source/header list expected by this Makefile.
	@printf 'Sources:\n'
	for f in $(HPS_SOURCES); do printf '  %s\n' "$$f"; done
	printf '\nHeaders:\n'
	for f in $(HPS_PUBLIC_HEADERS); do printf '  %s\n' "$$f"; done
	printf '\nGenerated headers:\n'
	for f in $(GENERATED_HEADERS); do printf '  %s\n' "$$f"; done

.PHONY: clean
clean: ## Remove HPS build objects and binary.
	@$(RMDIR) '$(BUILD_DIR)'
	printf 'clean: removed %s\n' '$(BUILD_DIR)'

.PHONY: clean-runs
clean-runs: ## Remove HPS run logs while preserving the runs/hps directory.
	@$(MKDIR_P) '$(RUNS_DIR)'
	find '$(RUNS_DIR)' -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +
	touch '$(RUNS_DIR)/.gitkeep'
	printf 'clean-runs: OK\n'

.PHONY: distclean
distclean: clean clean-runs ## Remove HPS local output packages as well.
	@$(RMDIR) '$(OUT_DIR)'
	printf 'distclean: removed %s\n' '$(OUT_DIR)'

-include $(DEPS)
