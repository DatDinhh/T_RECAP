# syntax=docker/dockerfile:1.7
# SPDX-License-Identifier: MIT
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=trecap
ARG UID=1000
ARG GID=1000

LABEL org.opencontainers.image.title="trecap-golden-ci"
LABEL org.opencontainers.image.description="Build and CI environment for the T-RECAP Phase 2 golden-model repository"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    clang-format \
    cmake \
    g++ \
    gcc \
    git \
    make \
    ninja-build \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    shellcheck \
    unzip \
    zip \
  && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/trecap-venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python3 -m venv "${VIRTUAL_ENV}" \
  && python -m pip install --upgrade pip setuptools wheel

WORKDIR /workspace
COPY requirements.lock /tmp/trecap-requirements.lock
RUN python -m pip install -r /tmp/trecap-requirements.lock \
  && rm -f /tmp/trecap-requirements.lock

RUN groupadd --gid "${GID}" "${USERNAME}" \
  && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /bin/bash "${USERNAME}" \
  && chown -R "${USERNAME}:${USERNAME}" /workspace

USER "${USERNAME}"

ENV PYTHONPATH=/workspace/python
ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
ENV CMAKE_BUILD_PARALLEL_LEVEL=2

CMD ["/bin/bash"]
