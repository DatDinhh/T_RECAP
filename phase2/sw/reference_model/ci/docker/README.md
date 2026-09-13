# Docker CI environment

This directory defines the container used for repeatable local CI checks of the
T-RECAP golden-model repository.

Build from the repository root, not from this subdirectory:

```bash
docker build -f ci/docker/Dockerfile -t trecap-golden-ci .
```

Run quick hygiene checks:

```bash
docker run --rm -it -v "$PWD:/workspace" -w /workspace trecap-golden-ci \
  scripts/ci_entrypoint.sh quick
```

Run the C++ build/test gate:

```bash
docker run --rm -it -v "$PWD:/workspace" -w /workspace trecap-golden-ci \
  scripts/ci_entrypoint.sh cpp
```

Run the generated-artifact smoke flow:

```bash
docker run --rm -it -v "$PWD:/workspace" -w /workspace trecap-golden-ci \
  scripts/ci_entrypoint.sh artifacts --clean-first
```

The image intentionally does not install Quartus, ModelSim, board drivers, or
HPS cross-compilers. Those are outside the golden-model CI layer. The container
is for repository hygiene, CMake builds, Python tests, deterministic artifact
regeneration, and packaging.
