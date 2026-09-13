# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 root build orchestrator.
# File class: [1] hand-written repository infrastructure.
#
# This Makefile is intentionally a root-level orchestrator. It does not replace
# the reference-model Makefile, Quartus scripts, HPS Makefile, or Python
# dashboard tooling. It provides one stable command surface for the Phase 2
# implementation repository.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Tool selection. Override from the command line or CI environment.
# -----------------------------------------------------------------------------
PYTHON              ?= python3
PYTHONDONTWRITEBYTECODE ?= 1
export PYTHONDONTWRITEBYTECODE
PIP                 ?= $(PYTHON) -m pip
CMAKE               ?= cmake
CTEST               ?= ctest
VLOG                ?= vlog
VLOG_FLAGS          ?= -sv -suppress 2892
VLIB                ?= vlib
VMAP                ?= vmap
VSIM                ?= vsim
QUARTUS_SH          ?= quartus_sh
QUARTUS_PGM         ?= quartus_pgm
MAKE_JOBS           ?= $(shell nproc 2>/dev/null || echo 4)

# -----------------------------------------------------------------------------
# Repository paths.
# Use sw/reference_model during current implementation. sw/golden remains a
# compatibility fallback because the spec text and imported reference package may
# still use golden naming internally.
# -----------------------------------------------------------------------------
ROOT_DIR            := $(CURDIR)
BUILD_DIR           ?= build
RUNS_DIR            ?= runs
OUT_DIR             ?= out
REFERENCE_DIR       ?= $(firstword $(wildcard sw/reference_model sw/golden))
REFERENCE_DIR       := $(if $(REFERENCE_DIR),$(REFERENCE_DIR),sw/reference_model)
REFERENCE_PROMOTION_MAP ?= config/reference_import_promotions.json
REFERENCE_SOURCE_ARCHIVE ?=
HPS_DIR             ?= sw/hps
PC_DASHBOARD_DIR    ?= sw/pc_dashboard
# Keep BRAM replay as the fail-closed default. LINE-IN and ADC live capture are
# always selected explicitly through their dedicated profile/build targets.
PROFILE             ?= config/profiles/de1soc_bram_replay.json
LINEIN_PROFILE      ?= config/profiles/de1soc_linein_demo.json
ADC_PROFILE         ?= config/profiles/de1soc_adc_demo.json
BOARD               ?= de1soc
QUARTUS_PROJECT     ?= platform/de1soc/quartus/trecap_de1soc
CMAKE_BUILD_TYPE    ?= RelWithDebInfo
CMAKE_ARGS          ?=

# RTL filelists required by the architecture contract.
CORE_FILELIST       ?= filelists/rtl_core_plus_fft.f
TELEM_FILELIST      ?= filelists/rtl_telemetry.f
CORE_TELEM_FILELIST ?= filelists/rtl_core_telemetry.f
HPS_BRIDGE_FILELIST ?= filelists/rtl_hps_bridge.f
BRAM_REPLAY_SYSTEM_FILELIST ?= filelists/rtl_bram_replay_system.f
FULL_FILELIST       ?= filelists/rtl_de1soc_full.f
STEP14_RTL_CHECKER  ?= sim/check_step14_command_rtl.py

# The Step-14 RTL checker is a dependency-free structural/model gate. It is
# intentionally optional until its source lands, and is not a native RTL
# simulation replacement.
STEP14_OPTIONAL_SOURCE_GATES :=
ifneq ($(wildcard $(STEP14_RTL_CHECKER)),)
STEP14_OPTIONAL_SOURCE_GATES += check-step14-rtl
endif

# Generated contract outputs that must be committed and checked for drift.
GENERATED_OUTPUTS := \
  rtl/include/generated/trecap_core_pkg.sv \
  rtl/include/generated/trecap_csr_pkg.sv \
  rtl/include/generated/trecap_packet_pkg.sv \
  rtl/include/generated/trecap_iface_pkg.sv \
  sw/hps/include/generated/trecap_csr.h \
  sw/hps/include/generated/trecap_packet.h \
  sw/pc_dashboard/generated/trecap_packet.py \
  sw/reference_model/generated/trecap_config.py

REQUIRED_ROOT_FILES := README.md Makefile CMakeLists.txt .gitignore

REQUIRED_DIRS := \
  docs/specs docs/architecture docs/bringup docs/deprecation \
  spec/generated spec/schemas spec/normative \
  config/profiles config/boards \
  scripts scripts/quartus scripts/bringup \
  filelists \
  rtl/include/generated rtl/common rtl/interfaces rtl/sources rtl/core rtl/fft rtl/telemetry rtl/hps_bridge rtl/platform/de1soc rtl/top \
  sw/reference_model sw/hps/include/generated sw/hps/src sw/hps/config sw/hps/scripts sw/hps/systemd sw/hps/tests sw/pc_dashboard/generated sw/pc_dashboard/trecap_dashboard \
  artifacts/coefficients artifacts/test_vectors artifacts/reference_outputs artifacts/manifests artifacts/telemetry_captures \
  constraints/de1soc platform/de1soc/qsys platform/de1soc/address_map platform/de1soc/generated_notes platform/de1soc/linux \
  ci/github ci/docker legacy/phase1 legacy/deprecated_phase2_docs runs

# Files that are known Phase 1/root-dump artifacts and must be moved under
# legacy/phase1/ before this repository is accepted.
FORBIDDEN_PHASE1_ROOT_FILES := \
  t_recap_demo_top.sv golden_model.cpp viz.py run.py \
  x.memh y.memh sup.memh metrics.json \
  tb_top.sv tb_pkg.sv board_if.sv tap_if.sv bind_taps.sv board_driver.sv \
  ref_model_phase1.sv golden_files_loader.sv \
  x_stream_monitor.sv y_stream_monitor.sv pair_monitor.sv io_monitor.sv metrics_monitor.sv \
  scoreboard_pairs.sv scoreboard_y_stream.sv scoreboard_metrics.sv \
  cov_phase1.sv sva_phase1_bind.sv \
  test_base.sv test_bypass_lossless.sv test_golden_thresh16.sv test_threshold_sweep.sv test_clear_metrics_midrun.sv test_mode_switch_stress.sv

# -----------------------------------------------------------------------------
# Helpers.
# -----------------------------------------------------------------------------
define require_file
	@test -f "$(1)" || { echo "ERROR: required file missing: $(1)"; exit 2; }
endef

define require_dir
	@test -d "$(1)" || { echo "ERROR: required directory missing: $(1)"; exit 2; }
endef

define require_script
	@test -f "$(1)" || { echo "ERROR: script missing: $(1)"; exit 2; }
endef

define require_ref_makefile
	@test -f "$(REFERENCE_DIR)/Makefile" || { echo "ERROR: reference model Makefile missing at $(REFERENCE_DIR)/Makefile"; echo "       Restore an independently verified reference tree under sw/reference_model/ first."; exit 2; }
endef

.PHONY: help
help: ## Show available root targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nT-RECAP Phase 2 root targets:\n\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2} END {printf "\nVariables: PYTHON=$(PYTHON), REFERENCE_DIR=$(REFERENCE_DIR), PROFILE=$(PROFILE), LINEIN_PROFILE=$(LINEIN_PROFILE), ADC_PROFILE=$(ADC_PROFILE)\n\n"}' $(MAKEFILE_LIST)

.PHONY: show-config
show-config: ## Print root build configuration.
	@printf '%-26s %s\n' 'ROOT_DIR' '$(ROOT_DIR)'
	@printf '%-26s %s\n' 'BUILD_DIR' '$(BUILD_DIR)'
	@printf '%-26s %s\n' 'RUNS_DIR' '$(RUNS_DIR)'
	@printf '%-26s %s\n' 'REFERENCE_DIR' '$(REFERENCE_DIR)'
	@printf '%-26s %s\n' 'HPS_DIR' '$(HPS_DIR)'
	@printf '%-26s %s\n' 'PC_DASHBOARD_DIR' '$(PC_DASHBOARD_DIR)'
	@printf '%-26s %s\n' 'PROFILE' '$(PROFILE)'
	@printf '%-26s %s\n' 'LINEIN_PROFILE' '$(LINEIN_PROFILE)'
	@printf '%-26s %s\n' 'ADC_PROFILE' '$(ADC_PROFILE)'
	@printf '%-26s %s\n' 'CORE_FILELIST' '$(CORE_FILELIST)'
	@printf '%-26s %s\n' 'CORE_TELEM_FILELIST' '$(CORE_TELEM_FILELIST)'
	@printf '%-26s %s\n' 'BRAM_REPLAY_SYSTEM_FILELIST' '$(BRAM_REPLAY_SYSTEM_FILELIST)'

# -----------------------------------------------------------------------------
# R0: repository skeleton and quarantine.
# -----------------------------------------------------------------------------
.PHONY: bootstrap-tree
bootstrap-tree: ## Create the Phase 2 directory skeleton with .gitkeep files.
	@for d in $(REQUIRED_DIRS); do mkdir -p "$$d"; done
	@find docs spec config scripts filelists rtl sw artifacts constraints platform ci legacy runs -type d -empty -exec sh -c 'touch "$$0/.gitkeep"' {} \;
	@echo "bootstrap-tree: OK"

.PHONY: check-layout
check-layout: ## Verify required folders exist and Phase 1 files are quarantined.
	@if [[ -f scripts/lint_repo_layout.py ]]; then \
		$(PYTHON) scripts/lint_repo_layout.py; \
	else \
		missing=0; \
		for f in $(REQUIRED_ROOT_FILES); do \
			if [[ ! -f "$$f" ]]; then echo "MISSING root file: $$f"; missing=1; fi; \
		done; \
		for d in $(REQUIRED_DIRS); do \
			if [[ ! -d "$$d" ]]; then echo "MISSING directory: $$d"; missing=1; fi; \
		done; \
		for f in $(FORBIDDEN_PHASE1_ROOT_FILES); do \
			if [[ -e "$$f" ]]; then echo "FORBIDDEN Phase 1 root artifact: $$f  -> move under legacy/phase1/"; missing=1; fi; \
		done; \
		if find . -maxdepth 1 -type f \( -name 'tb_top.sv.bak*' -o -name '*.wlf' -o -name '*.vcd' -o -name 'transcript' \) | grep -q .; then \
			echo "FORBIDDEN root simulation dump or backup file found"; missing=1; \
		fi; \
		if [[ $$missing -ne 0 ]]; then exit $$missing; fi; \
		echo "check-layout: OK (fallback checks)"; \
	fi

.PHONY: check-reference-import
check-reference-import: ## Verify every vendored/promoted byte and the v3 import provenance manifest.
	$(call require_ref_makefile)
	@PYTHONPATH="$(REFERENCE_DIR)/python" $(PYTHON) "$(REFERENCE_DIR)/tools/artifact_check.py" \
		--artifacts artifacts \
		--schemas spec/schemas \
		--output-subdir reference_outputs \
		--source-root "$(REFERENCE_DIR)" \
		--architecture-root . \
		--import-manifest artifacts/manifests/reference_import_manifest.json

.PHONY: refresh-reference-import
refresh-reference-import: ## Rebuild proxy provenance without claiming source-ZIP verification.
	@$(PYTHON) scripts/reference_import.py refresh-proxy \
		--repo-root . \
		--promotion-map "$(REFERENCE_PROMOTION_MAP)" \
		--proxy-id phase2-revJ-v69-lf-derived-embedded-proxy \
		--output-manifest "$(REFERENCE_DIR)/import_manifest.json" \
		--output-manifest artifacts/manifests/reference_import_manifest.json \
		--replace-manifests

.PHONY: check-reference-source-verified
check-reference-source-verified: ## Signoff gate: require independently verified source-archive provenance.
	$(call require_ref_makefile)
	@test -n "$(REFERENCE_SOURCE_ARCHIVE)" || { \
		echo "ERROR: set REFERENCE_SOURCE_ARCHIVE to the independently hash-pinned clean ZIP"; \
		exit 2; \
	}
	@PYTHONPATH="$(REFERENCE_DIR)/python" $(PYTHON) "$(REFERENCE_DIR)/tools/artifact_check.py" \
		--artifacts artifacts \
		--schemas spec/schemas \
		--output-subdir reference_outputs \
		--source-root "$(REFERENCE_DIR)" \
		--architecture-root . \
		--import-manifest artifacts/manifests/reference_import_manifest.json \
		--require-verified-source \
		--source-archive "$(REFERENCE_SOURCE_ARCHIVE)"

# -----------------------------------------------------------------------------
# R1: generated contract flow.
# -----------------------------------------------------------------------------
.PHONY: gen-headers
gen-headers: ## Generate SV, C, and Python constants from spec/generated/.
	$(call require_script,scripts/gen_headers.py)
	@$(PYTHON) scripts/gen_headers.py

.PHONY: check-generated
check-generated: ## Regenerate generated files and fail if checked-in outputs drift.
	@if [[ -f scripts/check_generated.py ]]; then \
		$(PYTHON) scripts/check_generated.py; \
	else \
		$(MAKE) --no-print-directory gen-headers; \
		git diff --exit-code -- spec/generated/gen_manifest.json $(GENERATED_OUTPUTS); \
	fi

.PHONY: check-profiles
check-profiles: ## Validate all runtime/build profiles and their generated-contract references.
	$(call require_script,scripts/check_profiles.py)
	@$(PYTHON) scripts/check_profiles.py --all

.PHONY: check-hps-platform
check-hps-platform: ## Validate the frozen DE1-SoC Platform Designer/HPS source contract.
	$(call require_script,scripts/check_hps_platform.py)
	@$(PYTHON) scripts/check_hps_platform.py

.PHONY: check-address-map
check-address-map: ## Validate the Step-4 source-frozen address map and every source mirror.
	$(call require_script,scripts/check_address_map.py)
	@$(PYTHON) scripts/check_address_map.py

.PHONY: check-csr-adapter
check-csr-adapter: ## Validate the Step-5 Avalon-MM CSR adapter source contract and RTL integration.
	$(call require_script,scripts/check_csr_adapter.py)
	@$(PYTHON) scripts/check_csr_adapter.py

.PHONY: check-platform-wrapper
check-platform-wrapper: ## Validate the Step-6 Platform Designer wrapper and board/Qsys source wiring.
	$(call require_script,scripts/check_platform_designer_wrapper.py)
	@$(PYTHON) scripts/check_platform_designer_wrapper.py

.PHONY: check-source-core-integration
check-source-core-integration: ## Validate the Step-7 source-to-core integration source contract.
	$(call require_script,scripts/check_source_core_integration.py)
	@$(PYTHON) scripts/check_source_core_integration.py

.PHONY: check-core-telemetry-composition
check-core-telemetry-composition: ## Validate the Step-8 core plus telemetry composition source contract.
	$(call require_script,scripts/check_core_telemetry_composition.py)
	@$(PYTHON) scripts/check_core_telemetry_composition.py

.PHONY: check-de1soc-board-top
check-de1soc-board-top: ## Validate the Step-9 physical board-top source-integration contract.
	$(call require_script,scripts/check_de1soc_board_top.py)
	@$(PYTHON) scripts/check_de1soc_board_top.py

.PHONY: check-de1soc-clock-reset
check-de1soc-clock-reset: ## Validate the Step-10 DE1-SoC clock/reset source architecture.
	$(call require_script,scripts/check_de1soc_clock_reset.py)
	@$(PYTHON) scripts/check_de1soc_clock_reset.py

.PHONY: check-de1soc-audio-path
check-de1soc-audio-path: ## Validate the Step-16 DE1-SoC LINE-IN PLL/I2C/I2S/CDC source contract.
	$(call require_script,scripts/check_de1soc_audio_path.py)
	@$(PYTHON) scripts/check_de1soc_audio_path.py

.PHONY: check-step16-audio-model
check-step16-audio-model: ## Run the dependency-free Step-16 audio architecture model; this is not RTL simulation.
	$(call require_script,scripts/sim/check_step16_audio_model.py)
	@$(PYTHON) scripts/sim/check_step16_audio_model.py

.PHONY: check-de1soc-linein-profile
check-de1soc-linein-profile: ## Validate the explicit Step-16 LINE-IN Quartus build profile.
	$(call require_script,scripts/check_profiles.py)
	@$(PYTHON) scripts/check_profiles.py \
		--profile "$(LINEIN_PROFILE)" \
		--require-build \
		--expect-target de1soc_full \
		--expect-top de1_soc_trecap_top \
		--expect-platform de1soc \
		--expect-profile-name de1soc_linein_demo \
		--expect-input-kind audio_wrapper \
		--expect-project "$(QUARTUS_PROJECT)"

.PHONY: check-de1soc-adc-path
check-de1soc-adc-path: ## Validate the Step-17 DE1-SoC LTC2308 SPI/CDC/source-mux contract.
	$(call require_script,scripts/check_de1soc_adc_path.py)
	@$(PYTHON) scripts/check_de1soc_adc_path.py

.PHONY: check-step17-adc-model
check-step17-adc-model: ## Run the dependency-free Step-17 ADC protocol/CDC model; this is not RTL simulation.
	$(call require_script,scripts/sim/check_step17_adc_model.py)
	@$(PYTHON) scripts/sim/check_step17_adc_model.py

.PHONY: check-de1soc-adc-profile
check-de1soc-adc-profile: ## Validate the explicit Step-17 ADC-live Quartus build profile.
	$(call require_script,scripts/check_profiles.py)
	@$(PYTHON) scripts/check_profiles.py \
		--profile "$(ADC_PROFILE)" \
		--require-build \
		--expect-target de1soc_full \
		--expect-top de1_soc_trecap_top \
		--expect-platform de1soc \
		--expect-profile-name de1soc_adc_demo \
		--expect-input-kind adc_live \
		--expect-project "$(QUARTUS_PROJECT)"

.PHONY: check-bram-replay-path
check-bram-replay-path: ## Validate the Step-11 BRAM-to-core-to-DDR/HPS source contract.
	$(call require_script,scripts/check_bram_replay_path.py)
	@$(PYTHON) scripts/check_bram_replay_path.py

.PHONY: check-ddr-ring-ownership
check-ddr-ring-ownership: ## Validate the Step-12 DDR-ring ownership, reservation, reset, and WRAP source contract.
	$(call require_script,scripts/check_ddr_ring_ownership.py)
	@$(PYTHON) scripts/check_ddr_ring_ownership.py

.PHONY: check-step12-ring-model
check-step12-ring-model: ## Run the dependency-free Step-12 DDR-ring boundary and ownership model.
	$(call require_script,scripts/sim/check_step12_ddr_ring_model.py)
	@$(PYTHON) scripts/sim/check_step12_ddr_ring_model.py

.PHONY: check-hps-transport
check-hps-transport: ## Validate the Step-13 HPS ring/UDP/malformed/dummy transport source contract.
	$(call require_script,scripts/check_hps_transport.py)
	@$(PYTHON) scripts/check_hps_transport.py

.PHONY: check-command-path
check-command-path: ## Validate the Step-14 PC/HPS/CSR command-path source contract.
	$(call require_script,scripts/check_command_path.py)
	@$(PYTHON) scripts/check_command_path.py

ifneq ($(wildcard $(STEP14_RTL_CHECKER)),)
.PHONY: check-step14-rtl
check-step14-rtl: ## Run the Step-14 structural RTL command model/source check; this is not native RTL simulation.
	$(call require_script,$(STEP14_RTL_CHECKER))
	@$(PYTHON) $(STEP14_RTL_CHECKER)
endif

.PHONY: platform-validate
platform-validate: ## Validate the frozen Platform Designer/HPS source contract without Intel tools.
	$(call require_script,platform/de1soc/qsys/generate_system.sh)
	@platform/de1soc/qsys/generate_system.sh --mode validate --print-summary

.PHONY: platform-construct
platform-construct: ## Explicitly construct and normalize system.qsys from the frozen source contract.
	$(call require_script,platform/de1soc/qsys/generate_system.sh)
	@platform/de1soc/qsys/generate_system.sh --mode construct --print-summary

.PHONY: platform-generate
platform-generate: ## Generate Platform Designer HDL/IP from an existing normalized system.qsys.
	$(call require_script,platform/de1soc/qsys/generate_system.sh)
	@platform/de1soc/qsys/generate_system.sh --mode generate --print-summary

.PHONY: rtl-filelist
rtl-filelist: ## Generate SystemVerilog compile/synthesis filelists.
	$(call require_script,scripts/gen_filelists.py)
	@$(PYTHON) scripts/gen_filelists.py

.PHONY: check-contracts
check-contracts: check-generated check-profiles check-hps-platform check-address-map check-csr-adapter check-platform-wrapper check-source-core-integration check-core-telemetry-composition check-de1soc-board-top check-de1soc-clock-reset check-bram-replay-path check-ddr-ring-ownership check-step12-ring-model check-hps-transport check-command-path $(STEP14_OPTIONAL_SOURCE_GATES) check-de1soc-audio-path check-step16-audio-model rtl-filelist ## Run generated and architecture source-contract checks through Step 16 without claiming native Step-16 RTL or hardware evidence.

# -----------------------------------------------------------------------------
# R2/R3: reference model and artifacts.
# These targets intentionally keep the spec-compatible target name "golden", but
# the current imported package is treated as a reference model until artifacts are
# frozen and accepted.
# -----------------------------------------------------------------------------
.PHONY: reference-check-layout
reference-check-layout: check-reference-import ## Check imported reference model staging under this repo policy.
	@echo "reference-check-layout: OK"

.PHONY: reference-build
reference-build: ## Build the imported C++ reference model package.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) build

.PHONY: reference-test
reference-test: ## Run the imported reference model self-tests.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) test

.PHONY: coeffs
coeffs: ## Generate coefficient memh files and coefficient manifest.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) coeffs
	@if [[ -d "$(REFERENCE_DIR)/artifacts/coefficients" ]]; then \
		mkdir -p artifacts/coefficients; \
		cp -a "$(REFERENCE_DIR)/artifacts/coefficients/." artifacts/coefficients/; \
	fi

.PHONY: vectors
vectors: ## Generate or validate frozen/provisional input vectors.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) vectors
	@if [[ -d "$(REFERENCE_DIR)/artifacts/test_vectors" ]]; then \
		mkdir -p artifacts/test_vectors; \
		cp -a "$(REFERENCE_DIR)/artifacts/test_vectors/." artifacts/test_vectors/; \
	fi

.PHONY: golden
golden: ## Run the reference model and emit expected artifacts; name kept for spec compatibility.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) golden
	@if [[ -d "$(REFERENCE_DIR)/artifacts/golden" ]]; then \
		mkdir -p artifacts/reference_outputs; \
		cp -a "$(REFERENCE_DIR)/artifacts/golden/." artifacts/reference_outputs/; \
	elif [[ -d "$(REFERENCE_DIR)/artifacts/reference_outputs" ]]; then \
		mkdir -p artifacts/reference_outputs; \
		cp -a "$(REFERENCE_DIR)/artifacts/reference_outputs/." artifacts/reference_outputs/; \
	fi

.PHONY: check-artifacts
check-artifacts: ## Check memh line counts, hashes, CSV rows, and JSON schema.
	$(call require_ref_makefile)
	@$(MAKE) -C $(REFERENCE_DIR) check-artifacts
	@PYTHONPATH="$(REFERENCE_DIR)/python" $(PYTHON) "$(REFERENCE_DIR)/tools/artifact_check.py" \
		--artifacts artifacts \
		--schemas spec/schemas \
		--output-subdir reference_outputs \
		--source-root "$(REFERENCE_DIR)" \
		--architecture-root . \
		--import-manifest artifacts/manifests/reference_import_manifest.json

.PHONY: package-artifacts
package-artifacts: check-artifacts ## Package only after the full frozen/import hash DAG passes.
	@if [[ -f scripts/package_artifacts.py ]]; then \
		$(PYTHON) scripts/package_artifacts.py; \
	else \
		$(MAKE) -C $(REFERENCE_DIR) package-artifacts; \
	fi

# -----------------------------------------------------------------------------
# R4/R5/R6/R7: RTL compile smoke targets.
# These are implementation smoke checks, not the verification architecture.
# -----------------------------------------------------------------------------
.PHONY: compile-core
compile-core: ## Compile core + FFT using filelists/rtl_core_plus_fft.f for Cut C0.
	$(call require_file,$(CORE_FILELIST))
	@mkdir -p $(RUNS_DIR)/compile-core/work
	@cd $(RUNS_DIR)/compile-core && \
		$(VLIB) work >/dev/null && $(VMAP) work work >/dev/null && \
		$(VLOG) $(VLOG_FLAGS) -work work -f ../../$(CORE_FILELIST) | tee compile.log

.PHONY: compile-telemetry
compile-telemetry: ## Compile telemetry packetizers and packet FIFO only.
	$(call require_file,$(TELEM_FILELIST))
	@mkdir -p $(RUNS_DIR)/compile-telemetry/work
	@cd $(RUNS_DIR)/compile-telemetry && \
		$(VLIB) work >/dev/null && $(VMAP) work work >/dev/null && \
		$(VLOG) $(VLOG_FLAGS) -work work -f ../../$(TELEM_FILELIST) | tee compile.log

.PHONY: compile-core-telemetry
compile-core-telemetry: ## Compile the standalone normalized-source core + telemetry composition.
	$(call require_file,$(CORE_TELEM_FILELIST))
	@mkdir -p $(RUNS_DIR)/compile-core-telemetry/work
	@cd $(RUNS_DIR)/compile-core-telemetry && \
		$(VLIB) work >/dev/null && $(VMAP) work work >/dev/null && \
		$(VLOG) $(VLOG_FLAGS) -work work -f ../../$(CORE_TELEM_FILELIST) | tee compile.log

.PHONY: compile-hps-bridge
compile-hps-bridge: ## Compile CSR bank, pointer control, record builder, and DDR ring writer.
	$(call require_file,$(HPS_BRIDGE_FILELIST))
	@mkdir -p $(RUNS_DIR)/compile-hps-bridge/work
	@cd $(RUNS_DIR)/compile-hps-bridge && \
		$(VLIB) work >/dev/null && $(VMAP) work work >/dev/null && \
		$(VLOG) $(VLOG_FLAGS) -work work -f ../../$(HPS_BRIDGE_FILELIST) | tee compile.log

.PHONY: compile-bram-replay-system
compile-bram-replay-system: ## Compile the pin-agnostic Step-11 BRAM replay/core/telemetry/HPS closure.
	$(call require_file,$(BRAM_REPLAY_SYSTEM_FILELIST))
	@mkdir -p $(RUNS_DIR)/compile-bram-replay-system
	@test -e $(RUNS_DIR)/compile-bram-replay-system/work/_info || \
		{ test ! -e $(RUNS_DIR)/compile-bram-replay-system/work || \
		  { echo "ERROR: stale non-library work path"; exit 2; }; \
		  $(VLIB) $(RUNS_DIR)/compile-bram-replay-system/work >/dev/null; } && \
		$(VLOG) $(VLOG_FLAGS) -work $(RUNS_DIR)/compile-bram-replay-system/work \
		-f $(BRAM_REPLAY_SYSTEM_FILELIST) | tee $(RUNS_DIR)/compile-bram-replay-system/compile.log

.PHONY: sim-step11-bram-e2e
sim-step11-bram-e2e: ## Run the fail-closed Step-11 impulse replay through STATUS DDR commit.
	$(call require_file,sim/filelists/step11_bram_e2e.f)
	$(call require_file,sim/tb/tb_trecap_step11_bram_e2e.sv)
	@mkdir -p $(RUNS_DIR)/step11-bram-e2e
	@test -e $(RUNS_DIR)/step11-bram-e2e/work/_info || \
		{ test ! -e $(RUNS_DIR)/step11-bram-e2e/work || \
		  { echo "ERROR: stale non-library work path"; exit 2; }; \
		  $(VLIB) $(RUNS_DIR)/step11-bram-e2e/work >/dev/null; } && \
		$(VLOG) $(VLOG_FLAGS) -work $(RUNS_DIR)/step11-bram-e2e/work \
		-f sim/filelists/step11_bram_e2e.f | tee $(RUNS_DIR)/step11-bram-e2e/compile.log && \
		$(VSIM) -c -lib $(RUNS_DIR)/step11-bram-e2e/work tb_trecap_step11_bram_e2e \
		-do "run -all; quit -f" | tee $(RUNS_DIR)/step11-bram-e2e/sim.log && \
		grep -q 'STEP11_BRAM_E2E_PASS' $(RUNS_DIR)/step11-bram-e2e/sim.log && \
		! grep -Eiq '(^|[[:space:]])(Error:|Fatal:|MISMATCH|STEP11_BRAM_E2E_FAIL)' \
		$(RUNS_DIR)/step11-bram-e2e/compile.log $(RUNS_DIR)/step11-bram-e2e/sim.log

.PHONY: compile-step12-ddr-ring
compile-step12-ddr-ring: ## Compile the Step-12 DDR-ring ownership and boundary regression.
	$(call require_file,sim/filelists/step12_ddr_ring_ownership.f)
	$(call require_file,sim/tb/tb_trecap_step12_ddr_ring_ownership.sv)
	@mkdir -p $(RUNS_DIR)/step12-ddr-ring-ownership
	@test -e $(RUNS_DIR)/step12-ddr-ring-ownership/work/_info || \
		{ test ! -e $(RUNS_DIR)/step12-ddr-ring-ownership/work || \
		  { echo "ERROR: stale non-library work path"; exit 2; }; \
		  $(VLIB) $(RUNS_DIR)/step12-ddr-ring-ownership/work >/dev/null; } && \
		$(VLOG) $(VLOG_FLAGS) -work $(RUNS_DIR)/step12-ddr-ring-ownership/work \
		-f sim/filelists/step12_ddr_ring_ownership.f | tee $(RUNS_DIR)/step12-ddr-ring-ownership/compile.log

.PHONY: sim-step12-ddr-ring-ownership
sim-step12-ddr-ring-ownership: check-step12-ring-model compile-step12-ddr-ring ## Run the fail-closed Step-12 DDR-ring ownership and WRAP regression.
	@$(VSIM) -c -lib $(RUNS_DIR)/step12-ddr-ring-ownership/work \
		tb_trecap_step12_ddr_ring_ownership -do "run -all; quit -f" \
		| tee $(RUNS_DIR)/step12-ddr-ring-ownership/sim.log && \
		grep -q 'STEP12_DDR_RING_OWNERSHIP_PASS' $(RUNS_DIR)/step12-ddr-ring-ownership/sim.log && \
		! grep -Eiq '(^|[[:space:]])(Error:|Fatal:|MISMATCH|STEP12_DDR_RING_OWNERSHIP_FAIL)' \
		$(RUNS_DIR)/step12-ddr-ring-ownership/compile.log \
		$(RUNS_DIR)/step12-ddr-ring-ownership/sim.log

# -----------------------------------------------------------------------------
# R8: Quartus / DE1-SoC build wrappers.
# -----------------------------------------------------------------------------
.PHONY: quartus-core-smoke
quartus-core-smoke: ## Build a reduced core-only Quartus project if the script exists.
	@if [[ -x scripts/quartus/build_core_smoke.sh ]]; then \
		scripts/quartus/build_core_smoke.sh; \
	else \
		echo "ERROR: scripts/quartus/build_core_smoke.sh missing or not executable"; exit 2; \
	fi

.PHONY: quartus-de1soc
quartus-de1soc: ## Build the full DE1-SoC Quartus project.
	@if [[ -x scripts/quartus/build_de1soc.sh ]]; then \
		scripts/quartus/build_de1soc.sh --project "$(QUARTUS_PROJECT)" --profile "$(PROFILE)"; \
	else \
		$(QUARTUS_SH) --flow compile $(QUARTUS_PROJECT); \
	fi

.PHONY: quartus-de1soc-linein
quartus-de1soc-linein: check-de1soc-linein-profile ## Explicitly build the full board with the Step-16 LINE-IN profile; the default remains BRAM replay.
	@if [[ -x scripts/quartus/build_de1soc.sh ]]; then \
		scripts/quartus/build_de1soc.sh --project "$(QUARTUS_PROJECT)" --profile "$(LINEIN_PROFILE)"; \
	else \
		echo "ERROR: scripts/quartus/build_de1soc.sh missing or not executable"; exit 2; \
	fi

.PHONY: quartus-de1soc-adc
quartus-de1soc-adc: check-de1soc-adc-profile ## Explicitly build the full board with the Step-17 ADC-live profile; the default remains BRAM replay.
	@if [[ -x scripts/quartus/build_de1soc.sh ]]; then \
		scripts/quartus/build_de1soc.sh --project "$(QUARTUS_PROJECT)" --profile "$(ADC_PROFILE)"; \
	else \
		echo "ERROR: scripts/quartus/build_de1soc.sh missing or not executable"; exit 2; \
	fi

.PHONY: quartus-de1soc-adc-dry-run
quartus-de1soc-adc-dry-run: check-de1soc-adc-profile check-de1soc-adc-path check-step17-adc-model ## Validate and dry-run the explicit Step-17 ADC-live Quartus profile without vendor tools.
	@if [[ -x scripts/quartus/build_de1soc.sh ]]; then \
		scripts/quartus/build_de1soc.sh \
			--project "$(QUARTUS_PROJECT)" \
			--profile "$(ADC_PROFILE)" \
			--run-dir "$(RUNS_DIR)/quartus/de1soc/step17-adc-dry-run" \
			--dry-run --skip-contract-checks --skip-platform-generate \
			--allow-missing-constraints; \
	else \
		echo "ERROR: scripts/quartus/build_de1soc.sh missing or not executable"; exit 2; \
	fi

.PHONY: program-sof
program-sof: ## Program the selected DE1-SoC .sof file. Usage: make program-sof SOF=path/to/file.sof
	@test -n "$(SOF)" || { echo "ERROR: set SOF=path/to/file.sof"; exit 2; }
	@if [[ -x scripts/quartus/program_sof.sh ]]; then \
		scripts/quartus/program_sof.sh --sof "$(SOF)"; \
	else \
		$(QUARTUS_PGM) -m JTAG -o "p;$(SOF)"; \
	fi

# -----------------------------------------------------------------------------
# R9/R10: HPS software and PC dashboard.
# -----------------------------------------------------------------------------
.PHONY: hps-build
hps-build: ## Build the HPS UDP streamer.
	@if [[ -f "$(HPS_DIR)/Makefile" ]]; then \
		$(MAKE) -C $(HPS_DIR); \
	elif [[ -f "$(HPS_DIR)/CMakeLists.txt" ]]; then \
		$(CMAKE) -S $(HPS_DIR) -B $(BUILD_DIR)/hps -DCMAKE_BUILD_TYPE=$(CMAKE_BUILD_TYPE) $(CMAKE_ARGS); \
		$(CMAKE) --build $(BUILD_DIR)/hps --parallel $(MAKE_JOBS); \
	else \
		echo "ERROR: no HPS build file found under $(HPS_DIR)"; exit 2; \
	fi

.PHONY: hps-step12-build
hps-step12-build: ## Build the Step-12 HPS streamer with warnings as errors in an isolated temporary tree.
	@trecap_hps_tmp="$$(mktemp -d /tmp/trecap-step12-hps.XXXXXX)"; \
	trap 'rm -rf -- "$$trecap_hps_tmp"' EXIT; \
	$(MAKE) --no-print-directory -C $(HPS_DIR) \
		BUILD_DIR="$$trecap_hps_tmp/build" \
		RUNS_DIR="$$trecap_hps_tmp/runs" \
		OUT_DIR="$$trecap_hps_tmp/out" \
		PYTHON="$(PYTHON)" WERROR=1 build; \
	"$$trecap_hps_tmp/build/bin/trecap_udp_streamer" \
		--config "$(HPS_DIR)/config/trecap_hps_config.json" --dry-run --quiet >/dev/null; \
	echo "hps-step12-build: WERROR build and config dry-run PASS"

.PHONY: hps-step13-test
hps-step13-test: ## Run the Step-13 RAM-backed HPS transport suite with ASan/UBSan and warnings as errors.
	@trecap_hps_tmp="$$(mktemp -d /tmp/trecap-step13-hps.XXXXXX)"; \
	trap 'rm -rf -- "$$trecap_hps_tmp"' EXIT; \
	$(MAKE) --no-print-directory -C $(HPS_DIR) \
		BUILD_DIR="$$trecap_hps_tmp/build" \
		RUNS_DIR="$$trecap_hps_tmp/runs" \
		OUT_DIR="$$trecap_hps_tmp/out" \
		PYTHON="$(PYTHON)" WERROR=1 SANITIZE=1 test-step13-transport; \
	$(MAKE) --no-print-directory -C $(HPS_DIR) \
		BUILD_DIR="$$trecap_hps_tmp/prod-build" \
		RUNS_DIR="$$trecap_hps_tmp/prod-runs" \
		OUT_DIR="$$trecap_hps_tmp/prod-out" \
		PYTHON="$(PYTHON)" WERROR=1 build; \
	"$$trecap_hps_tmp/prod-build/bin/trecap_udp_streamer" \
		--config "$(HPS_DIR)/config/trecap_hps_config.json" \
		--dummy-udp-counter --dry-run --quiet >/dev/null; \
	bash -n "$(HPS_DIR)/scripts/run_udp_streamer.sh"; \
	echo "hps-step13-test: ASan/UBSan RAM transport, dummy CLI dry-run, and launcher syntax PASS"

.PHONY: hps-step14-test
hps-step14-test: ## Run the Step-14 command-path HPS suite with ASan/UBSan, then build the production streamer.
	@trecap_hps_tmp="$$(mktemp -d /tmp/trecap-step14-hps.XXXXXX)"; \
	trap 'rm -rf -- "$$trecap_hps_tmp"' EXIT; \
	$(MAKE) --no-print-directory -C $(HPS_DIR) \
		BUILD_DIR="$$trecap_hps_tmp/test-build" \
		RUNS_DIR="$$trecap_hps_tmp/test-runs" \
		OUT_DIR="$$trecap_hps_tmp/test-out" \
		PYTHON="$(PYTHON)" WERROR=1 SANITIZE=1 test-step14-command-path; \
	$(MAKE) --no-print-directory -C $(HPS_DIR) \
		BUILD_DIR="$$trecap_hps_tmp/prod-build" \
		RUNS_DIR="$$trecap_hps_tmp/prod-runs" \
		OUT_DIR="$$trecap_hps_tmp/prod-out" \
		PYTHON="$(PYTHON)" WERROR=1 build; \
	"$$trecap_hps_tmp/prod-build/bin/trecap_udp_streamer" \
		--config "$(HPS_DIR)/config/trecap_hps_config.json" \
		--dummy-udp-counter --dry-run --quiet >/dev/null; \
	echo "hps-step14-test: ASan/UBSan command-path suite and WERROR production build PASS"

.PHONY: dashboard-import
dashboard-import: ## Import Python dashboard/parser modules and verify generated constants load.
	@PYTHONPATH=$(PC_DASHBOARD_DIR):$(PC_DASHBOARD_DIR)/generated $(PYTHON) -c "import importlib, pathlib; [importlib.import_module(m) for m in ['trecap_dashboard.packet_parser','trecap_dashboard.udp_receiver','trecap_dashboard.ring_buffers','trecap_dashboard.plots','trecap_dashboard.dashboard','trecap_dashboard.config','trecap_dashboard.command_client']]; p=pathlib.Path('$(PC_DASHBOARD_DIR)/generated/trecap_packet.py'); assert p.exists(), f'missing generated packet constants: {p}'; print('dashboard-import: OK')"

.PHONY: dashboard-step14-test
dashboard-step14-test: ## Run the dependency-free Step-14 PC command-client contract test.
	@PYTHONPATH="$(PC_DASHBOARD_DIR):$(PC_DASHBOARD_DIR)/generated" \
		$(PYTHON) "$(PC_DASHBOARD_DIR)/tests/test_step14_command_client.py"

.PHONY: dashboard-step15-test
dashboard-step15-test: ## Run the dependency-free Step-15 PC dashboard host regression.
	@PYTHONPATH="$(PC_DASHBOARD_DIR):$(PC_DASHBOARD_DIR)/generated" \
		$(PYTHON) "$(PC_DASHBOARD_DIR)/tests/test_step15_dashboard.py"

# -----------------------------------------------------------------------------
# Host CMake convenience targets.
# -----------------------------------------------------------------------------
.PHONY: configure
configure: ## Configure host-side C/C++ builds through root CMake.
	@$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CMAKE_BUILD_TYPE) $(CMAKE_ARGS)

.PHONY: build-host
build-host: configure ## Build host-side C/C++ targets through root CMake.
	@$(CMAKE) --build $(BUILD_DIR) --parallel $(MAKE_JOBS)

.PHONY: test-host
test-host: build-host ## Run CTest for host-side targets.
	@$(CTEST) --test-dir $(BUILD_DIR) --output-on-failure

# -----------------------------------------------------------------------------
# Hygiene and aggregate targets.
# -----------------------------------------------------------------------------
.PHONY: lint-basic
lint-basic: ## Run syntax/style hygiene checks. This is not verification.
	@if [[ -x scripts/lint.sh ]]; then \
		scripts/lint.sh --basic; \
	else \
		find scripts sw -type f -name '*.py' -print0 2>/dev/null | xargs -0 -r $(PYTHON) -m py_compile; \
		echo "lint-basic: fallback Python syntax check complete"; \
	fi

.PHONY: format
format: ## Format source files where local tools are available.
	@if [[ -x scripts/format.sh ]]; then \
		scripts/format.sh; \
	else \
		if command -v black >/dev/null 2>&1; then black scripts sw || true; fi; \
		if command -v clang-format >/dev/null 2>&1; then find rtl sw -type f \( -name '*.sv' -o -name '*.v' -o -name '*.c' -o -name '*.h' -o -name '*.cpp' -o -name '*.hpp' \) -print0 2>/dev/null | xargs -0 -r clang-format -i; fi; \
		echo "format: fallback complete"; \
	fi

.PHONY: c0
c0: check-layout check-contracts check-artifacts compile-core ## Check the committed frozen artifacts, then run the core-first Cut C0 gate.

.PHONY: t0
t0: compile-telemetry compile-hps-bridge hps-build dashboard-import ## Run the transport Cut T0 smoke gate after C0 is stable.

.PHONY: step11
step11: check-layout check-contracts check-artifacts compile-bram-replay-system sim-step11-bram-e2e ## Run the complete Step-11 source, artifact, compile, and E2E simulation gate.

.PHONY: step12-source
step12-source: check-layout check-contracts check-artifacts hps-step12-build ## Run every simulator-independent Step-12 source, model, artifact, and HPS build gate.

.PHONY: step12
step12: step12-source sim-step12-ddr-ring-ownership ## Run the complete Step-12 gate; ModelSim/Questa execution is mandatory.

.PHONY: step13-source
step13-source: check-layout check-contracts check-artifacts hps-step12-build hps-step13-test ## Run every simulator-independent Step-13 source, artifact, HPS build, and host transport-test gate.

.PHONY: step13
step13: step13-source sim-step12-ddr-ring-ownership ## Run the complete Step-13 gate; prior Step-12 RTL simulation remains mandatory.

.PHONY: step14-source
step14-source: check-layout check-contracts check-artifacts hps-step12-build hps-step13-test hps-step14-test dashboard-import dashboard-step14-test $(STEP14_OPTIONAL_SOURCE_GATES) ## Run cumulative simulator-independent Step-14 generated, layout, artifact, HPS, PC, and checker gates.

.PHONY: step14
step14: step14-source sim-step12-ddr-ring-ownership ## Run the cumulative Step-14 gate; retains prior Step-12 native RTL simulation without claiming a Step-14 native simulation.

.PHONY: step15-source
step15-source: step14-source dashboard-import dashboard-step15-test ## Run the cumulative simulator-independent Step-15 source and PC dashboard host-test gates.

.PHONY: step15
step15: step15-source sim-step12-ddr-ring-ownership ## Run the cumulative Step-15 gate; retains prior Step-12 native RTL simulation without claiming live dashboard or Step-15 hardware evidence.

.PHONY: step16-source
step16-source: step15-source check-de1soc-linein-profile check-de1soc-audio-path check-step16-audio-model ## Run cumulative simulator-independent Step-16 source, contract, profile, and architecture-model gates.

.PHONY: step16
step16: step16-source sim-step12-ddr-ring-ownership ## Run the cumulative Step-16 gate; retains prior Step-12 native RTL simulation without claiming Step-16 RTL, Quartus, timing, live-audio, or hardware evidence.

.PHONY: step17-source
step17-source: step16-source check-de1soc-adc-profile check-de1soc-adc-path check-step17-adc-model ## Run cumulative simulator-independent Step-17 source, contract, profile, and protocol-model gates.

.PHONY: step17
step17: step17-source sim-step12-ddr-ring-ownership ## Run the cumulative Step-17 gate; retains prior Step-12 native RTL simulation without claiming Step-17 RTL, Quartus, timing, ADC-waveform, or hardware evidence.

.PHONY: ci
ci: c0 ## Default CI gate for the current core-first implementation stage.

.PHONY: clean-runs
clean-runs: ## Remove generated run outputs while preserving runs/.gitkeep.
	@mkdir -p $(RUNS_DIR)
	@find $(RUNS_DIR) -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +
	@touch $(RUNS_DIR)/.gitkeep
	@echo "clean-runs: OK"

.PHONY: clean
clean: clean-runs ## Remove local build outputs.
	@rm -rf $(BUILD_DIR) $(OUT_DIR)
	@echo "clean: OK"

.PHONY: distclean
distclean: clean ## Remove common simulator and Quartus generated output.
	@rm -rf db incremental_db output_files simulation transcript work audio_work adc_work vsim.wlf *.wlf *.vcd *.fst *.ghw
	@echo "distclean: OK"
