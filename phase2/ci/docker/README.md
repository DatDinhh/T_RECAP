# T-RECAP Phase 2 Docker image

File class: `[1]` hand-written CI/development documentation.

This directory contains the host-side Docker image used for repeatable T-RECAP
Phase 2 repository checks. The image is intentionally limited to open host-side
tools. It does **not** contain Intel Quartus, ModelSim, board drivers, USB-Blaster
access, `/dev/mem` hardware access, or any DE1-SoC runtime services.

## What this image is for

Use it for checks that do not need FPGA vendor tools or board hardware:

```sh
docker build -t trecap-phase2-ci -f ci/docker/Dockerfile .

docker run --rm -it \
  -v "$PWD:/workspace" \
  -w /workspace \
  trecap-phase2-ci \
  bash -lc 'make check-layout && make lint-basic && make check-generated'
```

Useful smoke commands inside the container:

```sh
make check-layout
make lint-basic
make check-generated
make -C sw/hps build
python sw/pc_dashboard/scripts/run_dashboard.py --preflight-only --text-only --quiet
python scripts/package_artifacts.py --manifest-only --include-tools
scripts/quartus/build_de1soc.sh --dry-run --skip-contract-checks --allow-missing-constraints
```

## What this image is not for

This image is not the FPGA signoff environment. It cannot prove timing closure,
Quartus synthesis, Platform Designer generation, USB-Blaster programming, HPS
`/dev/mem` access, or live Ethernet streaming. Real Quartus smoke builds belong
on a self-hosted runner with Intel FPGA tools installed. Real board bring-up
belongs on the DE1-SoC using the scripts under `sw/hps/scripts/`.

The image also does not make the imported reference model a final golden
authority. The current package under `sw/reference_model/` remains the reference
model until artifacts and hashes are frozen by the project process.

## Generated-contract policy

Generated outputs must not be hand-edited. The container can regenerate and
check them:

```sh
python scripts/gen_headers.py
python scripts/gen_filelists.py
python scripts/check_generated.py --quiet
```

If this reports a drift, fix the source contract under `spec/generated/` or the
corresponding generator script, regenerate, and commit the generated outputs and
manifest together.

## HPS and PC-dashboard policy

The HPS streamer built in this image is a host-side build smoke. It does not
access real CSR or DDR unless run on the board with the right runtime config,
reserved DDR region, and privileges.

The PC dashboard checks are parser/config/import checks. They do not replace
BRAM replay correctness signoff and they do not run FFT/IFFT/STFT/WOLA/mask or
reconstruction algorithms on the PC.

## Quartus policy

`quartus_smoke.yml` has two paths:

1. A hosted dry-run job that validates generated contracts, Platform Designer Tcl
   entry points, and the Quartus wrapper command construction.
2. A manual self-hosted job for real Quartus builds on a runner labeled
   `self-hosted`, `linux`, and `quartus`.

Do not add Quartus installers, license files, or vendor tool output to this
Docker image or repository.
