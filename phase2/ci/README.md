# Build automation

The active GitHub Actions workflow is
[`.github/workflows/source.yml`](../.github/workflows/source.yml). It checks source
hygiene and builds the reference software on Linux and Windows. Linux also builds
the HPS transport. These builds have tests disabled and do not establish RTL,
numerical, timing, or board correctness.

`ci/github/` and `sw/reference_model/ci/github/` retain historical workflow examples
used by the existing release tools. GitHub does not execute workflows from those
paths. They are not the current CI configuration. `ci/docker/` retains the optional
container environment.

The active workflow follows the official
[checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python) action interfaces.
