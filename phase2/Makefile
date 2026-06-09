# SPDX-License-Identifier: MIT
# T-RECAP golden-model build and artifact workflow.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
CMAKE ?= cmake
CTEST ?= ctest
BUILD_DIR ?= build
OUT_DIR ?= out
RUNS_DIR ?= runs
SUITE ?= configs/suites/smoke.json
RELEASE_CONFIG ?= configs/releases/phase2_revJ_dev.json
RELEASE ?= configs/releases/phase2_revJ_dev.json
CMAKE_BUILD_TYPE ?= RelWithDebInfo
CMAKE_ARGS ?=

ROOT_FILES := README.md CHANGELOG.md LICENSE Makefile CMakeLists.txt pyproject.toml requirements.lock .gitignore .editorconfig .clang-format .pre-commit-config.yaml
DOC_FILES := docs/golden_model_overview.md docs/arithmetic_contract.md docs/fixed_point_widths.md docs/fft_ifft_contract.md docs/stft_wola_contract.md docs/artifact_contract.md docs/canonical_memh_hashing.md docs/vector_freeze_process.md docs/quality_bounds_process.md docs/release_process.md docs/dev_guide.md
JSON_SCHEMA_FILES := spec/schemas/core_config.schema.json spec/schemas/coeff_manifest.schema.json spec/schemas/test_vectors.schema.json spec/schemas/vector_config.schema.json spec/schemas/metrics.schema.json spec/schemas/quality_bounds.schema.json spec/schemas/artifact_index.schema.json spec/schemas/frozen_release_manifest.schema.json
CSV_SCHEMA_DOCS := spec/schemas/frame_stats.schema.md spec/schemas/bin_stats.schema.md
SCHEMA_FILES := $(JSON_SCHEMA_FILES) $(CSV_SCHEMA_DOCS)
SUITE_CONFIG_FILES := configs/suites/smoke.json configs/suites/signoff_minimal.json configs/suites/signoff_full.json configs/suites/debug_near_threshold.json
VECTOR_CONFIG_FILES := configs/vectors/zero_Ns4096_thr0.json configs/vectors/no_suppression_multitone_thr0.json configs/vectors/impulse_step.json configs/vectors/exact_bin_tone_sweep.json configs/vectors/off_bin_tone_sweep.json configs/vectors/near_threshold_multitone.json configs/vectors/noise_only_xorshift32.json configs/vectors/high_amplitude_headroom.json configs/vectors/short_finite_stream.json
RELEASE_CONFIG_FILES := configs/releases/phase2_revJ_dev.json configs/releases/phase2_revJ_signoff.json
SELF_CHECK_FILES := tests/golden_selfcheck/smoke_suite_expected_manifest.json tests/golden_selfcheck/README.md
SCRIPT_FILES := scripts/bootstrap.sh scripts/format.sh scripts/lint.sh scripts/clean_outputs.sh scripts/regenerate_all.sh scripts/check_reproducible.sh scripts/ci_entrypoint.sh
CI_FILES := ci/github/build.yml ci/github/lint.yml ci/github/artifact_check.yml ci/github/reproducibility.yml ci/docker/Dockerfile ci/docker/README.md
LOCAL_OUTPUT_KEEPERS := out/.gitkeep runs/.gitkeep
LEGACY_FILES := legacy/phase1/README.md
SOURCE_FILES := src/fixed_point.cpp src/widths.cpp src/signed_int.cpp src/rounding.cpp src/saturation.cpp src/q_format.cpp src/complex_int.cpp src/coeffs.cpp src/twiddles.cpp src/window.cpp src/fft_radix2_int.cpp src/ifft_radix2_int.cpp src/hermitian.cpp src/mask.cpp src/stft_wola_model.cpp src/finite_stream.cpp src/metrics.cpp src/generators.cpp src/memh.cpp src/csv_io.cpp src/json_io.cpp src/canonical_hash.cpp src/artifact_writer.cpp src/artifact_checker.cpp src/version.cpp
HEADER_FILES := include/trecap_golden/fixed_point.hpp include/trecap_golden/widths.hpp include/trecap_golden/signed_int.hpp include/trecap_golden/rounding.hpp include/trecap_golden/saturation.hpp include/trecap_golden/q_format.hpp include/trecap_golden/complex_int.hpp include/trecap_golden/coeffs.hpp include/trecap_golden/twiddles.hpp include/trecap_golden/window.hpp include/trecap_golden/fft_radix2_int.hpp include/trecap_golden/ifft_radix2_int.hpp include/trecap_golden/hermitian.hpp include/trecap_golden/mask.hpp include/trecap_golden/stft_wola_model.hpp include/trecap_golden/finite_stream.hpp include/trecap_golden/metrics.hpp include/trecap_golden/generators.hpp include/trecap_golden/memh.hpp include/trecap_golden/csv_io.hpp include/trecap_golden/json_io.hpp include/trecap_golden/canonical_hash.hpp include/trecap_golden/artifact_writer.hpp include/trecap_golden/artifact_checker.hpp include/trecap_golden/version.hpp
TOOL_FILES := tools/phase2_golden_model.cpp tools/gen_coeffs.py tools/gen_vectors.py tools/run_vector.py tools/run_suite.py tools/artifact_check.py tools/make_quality_bounds.py tools/freeze_release.py tools/compare_artifacts.py tools/inspect_memh.py tools/inspect_frame_stats.py tools/hash_memh.py tools/package_artifacts.py tools/_trecap_tool_common.py
PYTHON_GENERATOR_FILES := python/trecap_golden/generators/__init__.py python/trecap_golden/generators/constant.py python/trecap_golden/generators/impulse.py python/trecap_golden/generators/step.py python/trecap_golden/generators/sine.py python/trecap_golden/generators/cosine.py python/trecap_golden/generators/multitone.py python/trecap_golden/generators/xorshift32.py
PYTHON_CLI_FILES := python/trecap_golden/cli/__init__.py python/trecap_golden/cli/_tool_adapter.py python/trecap_golden/cli/gen_coeffs.py python/trecap_golden/cli/gen_vectors.py python/trecap_golden/cli/run_suite.py python/trecap_golden/cli/artifact_check.py python/trecap_golden/cli/freeze_release.py
PYTHON_TEST_FILES := tests/python/test_schema_validation.py tests/python/test_vector_configs.py tests/python/test_hash_memh.py tests/python/test_generator_determinism.py tests/python/test_release_manifest.py
PYTHON_PACKAGE_FILES := python/trecap_golden/__init__.py python/trecap_golden/contracts/__init__.py python/trecap_golden/contracts/contract_paths.py python/trecap_golden/contracts/schema_loader.py python/trecap_golden/contracts/schema_validate.py python/trecap_golden/artifacts/__init__.py python/trecap_golden/artifacts/memh.py python/trecap_golden/artifacts/csv_io.py python/trecap_golden/artifacts/hashes.py python/trecap_golden/artifacts/manifests.py python/trecap_golden/artifacts/checker.py $(PYTHON_GENERATOR_FILES) $(PYTHON_CLI_FILES)
REQUIRED_DIRS := docs spec include src tools python configs artifacts tests scripts ci out runs legacy

.PHONY: help
help: ## Show available targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nT-RECAP golden-model targets:\n\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2} END {printf "\n"}' $(MAKEFILE_LIST)

.PHONY: check-layout
check-layout: ## Verify required root files and golden repository directories exist.
	@missing=0; \
	for f in $(ROOT_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING file: $$f"; missing=1; fi; \
	done; \
	for f in $(DOC_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING doc:  $$f"; missing=1; fi; \
	done; \
	for f in $(SCHEMA_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING schema: $$f"; missing=1; fi; \
	done; \
	for f in $(SUITE_CONFIG_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING suite config: $$f"; missing=1; fi; \
	done; \
	for f in $(VECTOR_CONFIG_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING vector config: $$f"; missing=1; fi; \
	done; \
	for f in $(RELEASE_CONFIG_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING release config: $$f"; missing=1; fi; \
	done; \
	for f in $(SELF_CHECK_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING selfcheck file: $$f"; missing=1; fi; \
	done; \
	for f in $(SCRIPT_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING script: $$f"; missing=1; fi; \
	done; \
	for f in $(CI_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING ci file: $$f"; missing=1; fi; \
	done; \
	for f in $(LOCAL_OUTPUT_KEEPERS); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING local output keeper: $$f"; missing=1; fi; \
	done; \
	for f in $(LEGACY_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING legacy file: $$f"; missing=1; fi; \
	done; \
	for f in $(HEADER_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING header: $$f"; missing=1; fi; \
	done; \
	for f in $(SOURCE_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING source: $$f"; missing=1; fi; \
	done; \
	for f in $(TOOL_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING tool: $$f"; missing=1; fi; \
	done; \
	for f in $(PYTHON_PACKAGE_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING python package file: $$f"; missing=1; fi; \
	done; \
	for f in $(PYTHON_TEST_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING python test file: $$f"; missing=1; fi; \
	done; \
	for d in $(REQUIRED_DIRS); do \
		if [[ ! -d "$$d" ]]; then echo "MISSING dir:  $$d"; missing=1; fi; \
	done; \
	if [[ $$missing -ne 0 ]]; then exit $$missing; fi; \
	echo "layout: OK"


.PHONY: check-schemas
check-schemas: ## Validate JSON Schema syntax and CSV schema documentation files.
	@$(PYTHON) -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator; [Draft202012Validator.check_schema(json.loads(p.read_text(encoding='utf-8'))) for p in sorted(Path('spec/schemas').glob('*.schema.json'))]; print('json schemas: OK')"
	@for f in $(CSV_SCHEMA_DOCS); do \
		grep -q '```csv' "$$f" || { echo "ERROR: missing csv block in $$f"; exit 2; }; \
		grep -q 'Validation checklist' "$$f" || { echo "ERROR: missing validation checklist in $$f"; exit 2; }; \
	done
	@echo "csv schema docs: OK"

.PHONY: check-python-contracts
check-python-contracts: ## Run schema-validation tests for Python contract helpers.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_schema_validation.py -q


.PHONY: check-python-artifacts
check-python-artifacts: ## Run canonical memh/hash tests without requiring generated artifacts.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_hash_memh.py -q


.PHONY: check-python-generators
check-python-generators: ## Run deterministic generator tests.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_generator_determinism.py -q

.PHONY: check-python-cli
check-python-cli: ## Check CLI wrapper files exist without requiring generated artifacts.
	@for f in $(PYTHON_CLI_FILES); do \
		if [[ ! -f "$$f" ]]; then echo "MISSING python cli file: $$f"; exit 1; fi; \
	done; \
	echo "python cli files: OK"

.PHONY: check-vector-configs
check-vector-configs: ## Validate reviewed vector-config bundles under configs/vectors/.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_vector_configs.py::test_required_vector_bundle_files_exist tests/python/test_vector_configs.py::test_vector_bundles_have_stable_signoff_fields tests/python/test_vector_configs.py::test_suite_references_are_not_dangling_and_preserve_order -q

.PHONY: check-suite-configs
check-suite-configs: ## Validate suite configs and their vector-config references.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_vector_configs.py -q

.PHONY: check-release-configs
check-release-configs: ## Validate manually reviewed release recipes and generated release manifests.
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -m pytest tests/python/test_release_manifest.py -q

.PHONY: check-headers
check-headers: ## Compile and run public C++ header contract self-tests.
	@$(CMAKE) -S . -B $(BUILD_DIR)/headers -DTRECAP_BUILD_TESTS=ON -DTRECAP_BUILD_TOOLS=OFF >/dev/null
	@$(CMAKE) --build $(BUILD_DIR)/headers --parallel >/dev/null
	@$(CTEST) --test-dir $(BUILD_DIR)/headers --output-on-failure
	@echo "headers: OK"

.PHONY: bootstrap-tree
bootstrap-tree: ## Create the standard empty golden-model directory tree.
	@mkdir -p \
		spec/normative spec/schemas spec/generated \
		include/trecap_golden src tools \
		python/trecap_golden/generated python/trecap_golden/contracts python/trecap_golden/artifacts python/trecap_golden/generators python/trecap_golden/cli \
		configs/suites configs/vectors configs/releases \
		artifacts/coefficients artifacts/test_vectors artifacts/golden artifacts/manifests artifacts/telemetry_captures \
		tests/cpp tests/python tests/golden_selfcheck \
		scripts ci/github ci/docker out runs legacy/phase1
	@find docs spec include src tools python configs artifacts tests scripts ci out runs legacy -type d -empty -exec sh -c 'touch "$$0/.gitkeep"' {} \;
	@echo "bootstrap tree: OK"

.PHONY: setup
setup: ## Install Python tooling from requirements.lock into the active environment.
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.lock

.PHONY: configure
configure: ## Configure the C++ golden-model build with CMake.
	@$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CMAKE_BUILD_TYPE) $(CMAKE_ARGS)

.PHONY: build
build: configure ## Build C++ library/tools.
	@$(CMAKE) --build $(BUILD_DIR) --parallel

.PHONY: test
test: build cpp-test python-test ## Run C++ and Python tests when present.

.PHONY: cpp-test
cpp-test: ## Run CTest tests from the CMake build tree.
	@if [[ -d "$(BUILD_DIR)" ]]; then \
		$(CTEST) --test-dir $(BUILD_DIR) --output-on-failure; \
	else \
		echo "ERROR: missing $(BUILD_DIR). Run make configure first."; exit 2; \
	fi

.PHONY: python-test
python-test: ## Run pytest on tests/python when Python tests exist.
	@if compgen -G "tests/python/test_*.py" >/dev/null; then \
		PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=python $(PYTHON) -c "import os, pytest; code = pytest.main(['tests/python']); os._exit(code)"; \
	else \
		echo "python tests: none present"; \
	fi

.PHONY: lint-basic
lint-basic: ## Run basic Python/C++/metadata lint checks.
	@command -v ruff >/dev/null || { echo "ERROR: ruff missing. Run make setup."; exit 2; }
	@ruff check python tools scripts tests/python || true
	@command -v black >/dev/null || { echo "ERROR: black missing. Run make setup."; exit 2; }
	@black --check python tools scripts tests/python || true
	@command -v cmake >/dev/null || { echo "ERROR: cmake missing."; exit 2; }
	@$(CMAKE) -S . -B $(BUILD_DIR)/lint -DTRECAP_BUILD_TESTS=OFF >/dev/null
	@echo "lint-basic: completed"

.PHONY: format
format: ## Format Python and C++ files where tools are available.
	@if command -v ruff >/dev/null; then ruff check --fix python tools scripts tests/python || true; fi
	@if command -v black >/dev/null; then black python tools scripts tests/python || true; fi
	@if command -v clang-format >/dev/null; then \
		find include src tools tests/cpp -type f \( -name '*.hpp' -o -name '*.cpp' -o -name '*.h' -o -name '*.cc' \) -print0 | xargs -0 -r clang-format -i; \
	fi
	@echo "format: completed"


.PHONY: script-bootstrap
script-bootstrap: ## Run scripts/bootstrap.sh.
	@scripts/bootstrap.sh

.PHONY: script-lint
script-lint: ## Run scripts/lint.sh quick checks.
	@scripts/lint.sh

.PHONY: script-format
script-format: ## Run scripts/format.sh --check.
	@scripts/format.sh --check

.PHONY: script-clean-outputs
script-clean-outputs: ## Run scripts/clean_outputs.sh.
	@scripts/clean_outputs.sh

.PHONY: script-reproducible
script-reproducible: ## Run scripts/check_reproducible.sh in quick mode.
	@scripts/check_reproducible.sh --quick

.PHONY: script-ci
script-ci: ## Run scripts/ci_entrypoint.sh quick mode.
	@scripts/ci_entrypoint.sh quick

.PHONY: gen-config
gen-config: ## Generate derived config files from spec schemas.
	@if [[ -f scripts/gen_config.py ]]; then \
		$(PYTHON) scripts/gen_config.py; \
	else \
		echo "ERROR: scripts/gen_config.py missing; populate generation layer first."; exit 2; \
	fi

.PHONY: coeffs
coeffs: ## Generate coefficient memh files and coeff_manifest.json.
	@if [[ -f tools/gen_coeffs.py ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.gen_coeffs --out artifacts/coefficients; \
	else \
		echo "ERROR: tools/gen_coeffs.py missing; coefficient generator not implemented yet."; exit 2; \
	fi

.PHONY: vectors
vectors: ## Generate or validate frozen input vectors.
	@if [[ -f tools/gen_vectors.py ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.gen_vectors --configs configs/vectors --out artifacts/test_vectors; \
	else \
		echo "ERROR: tools/gen_vectors.py missing; vector generator not implemented yet."; exit 2; \
	fi

.PHONY: vectors-suite
vectors-suite: ## Generate input vectors selected by SUITE=path, default smoke suite.
	@if [[ -f tools/gen_vectors.py ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.gen_vectors --configs configs/vectors --out artifacts/test_vectors --suite $(SUITE); \
	else \
		echo "ERROR: tools/gen_vectors.py missing; vector generator not implemented yet."; exit 2; \
	fi

.PHONY: golden
golden: build ## Run the C++ golden model through the suite orchestrator and emit output artifacts.
	@if [[ -f tools/run_suite.py && -x $(BUILD_DIR)/phase2_golden_model ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.run_suite --vectors artifacts/test_vectors --out artifacts/golden --golden-exe $(BUILD_DIR)/phase2_golden_model; \
	elif [[ -x $(BUILD_DIR)/phase2_golden_model ]]; then \
		$(BUILD_DIR)/phase2_golden_model --vectors artifacts/test_vectors --out artifacts/golden; \
	else \
		echo "ERROR: golden runner missing; run make build or implement tools/run_suite.py."; exit 2; \
	fi

.PHONY: golden-suite
golden-suite: build ## Run the C++ golden model for vectors selected by SUITE=path.
	@if [[ -f tools/run_suite.py && -x $(BUILD_DIR)/phase2_golden_model ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.run_suite --vectors artifacts/test_vectors --out artifacts/golden --golden-exe $(BUILD_DIR)/phase2_golden_model --suite $(SUITE); \
	else \
		echo "ERROR: golden runner missing; run make build or implement tools/run_suite.py."; exit 2; \
	fi

.PHONY: check-artifacts
check-artifacts: ## Check memh line counts, canonical hashes, CSV rows, and JSON schemas.
	@if [[ -f tools/artifact_check.py ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.artifact_check --artifacts artifacts; \
	else \
		echo "ERROR: tools/artifact_check.py missing; artifact checker not implemented yet."; exit 2; \
	fi

.PHONY: quality-bounds
quality-bounds: ## Generate no-suppression quality bounds from frozen golden artifacts.
	@if [[ -f tools/make_quality_bounds.py ]]; then \
		$(PYTHON) tools/make_quality_bounds.py --artifacts artifacts --out artifacts/manifests/quality_bounds.json; \
	else \
		echo "ERROR: tools/make_quality_bounds.py missing; quality-bound generator not implemented yet."; exit 2; \
	fi

.PHONY: freeze-release
freeze-release: check-artifacts ## Freeze artifact hashes into frozen_release_manifest.json.
	@if [[ -f tools/freeze_release.py ]]; then \
		PYTHONPATH=python $(PYTHON) -m trecap_golden.cli.freeze_release --release-config $(RELEASE_CONFIG) --artifacts artifacts --out artifacts/manifests/frozen_release_manifest.json; \
	else \
		echo "ERROR: tools/freeze_release.py missing; release freezer not implemented yet."; exit 2; \
	fi

.PHONY: reproduce-release
reproduce-release: ## Regenerate and verify a frozen release bit-for-bit.
	@if [[ -f tools/reproduce_release.py ]]; then \
		$(PYTHON) tools/reproduce_release.py --manifest artifacts/manifests/frozen_release_manifest.json; \
	else \
		echo "ERROR: tools/reproduce_release.py missing; release reproduction checker not implemented yet."; exit 2; \
	fi

.PHONY: hash-memh
hash-memh: ## Compute a canonical memh hash. Usage: make hash-memh MEMH=path [KIND=sample]
	@if [[ -z "$${MEMH:-}" ]]; then echo "ERROR: set MEMH=path"; exit 2; fi
	@$(PYTHON) tools/hash_memh.py "$${MEMH}" $${KIND:+--kind "$${KIND}"}

.PHONY: inspect-memh
inspect-memh: ## Inspect a memh file. Usage: make inspect-memh MEMH=path [KIND=sample]
	@if [[ -z "$${MEMH:-}" ]]; then echo "ERROR: set MEMH=path"; exit 2; fi
	@$(PYTHON) tools/inspect_memh.py "$${MEMH}" $${KIND:+--kind "$${KIND}"}

.PHONY: inspect-frame-stats
inspect-frame-stats: ## Inspect frame_stats.csv. Usage: make inspect-frame-stats FRAME_STATS=path [METRICS=path]
	@if [[ -z "$${FRAME_STATS:-}" ]]; then echo "ERROR: set FRAME_STATS=path"; exit 2; fi
	@$(PYTHON) tools/inspect_frame_stats.py "$${FRAME_STATS}" $${METRICS:+--metrics "$${METRICS}"}

.PHONY: compare-artifacts
compare-artifacts: ## Compare two artifact trees. Usage: make compare-artifacts LEFT=a RIGHT=b
	@if [[ -z "$${LEFT:-}" || -z "$${RIGHT:-}" ]]; then echo "ERROR: set LEFT=path RIGHT=path"; exit 2; fi
	@$(PYTHON) tools/compare_artifacts.py --left "$${LEFT}" --right "$${RIGHT}"

.PHONY: package-artifacts
package-artifacts: check-artifacts ## Package frozen artifacts under out/.
	@$(PYTHON) tools/package_artifacts.py --artifacts artifacts --out $(OUT_DIR)

.PHONY: clean-runs
clean-runs: ## Remove generated local run output.
	@rm -rf $(RUNS_DIR)/* $(OUT_DIR)/*
	@touch $(RUNS_DIR)/.gitkeep $(OUT_DIR)/.gitkeep
	@echo "clean-runs: OK"

.PHONY: clean
clean: clean-runs ## Remove build and local output directories.
	@rm -rf $(BUILD_DIR)
	@echo "clean: OK"

.PHONY: distclean
distclean: clean ## Remove all generated local state, including virtual environment.
	@rm -rf .venv .mypy_cache .pytest_cache .ruff_cache htmlcov .coverage
	@echo "distclean: OK"
