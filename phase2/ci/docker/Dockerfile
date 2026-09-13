# syntax=docker/dockerfile:1
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 CI/development image.
# File class: [1] hand-written CI infrastructure.
#
# This image intentionally does not include Intel Quartus, ModelSim, hardware
# drivers, or board-specific licensed tools. Use a self-hosted runner for real
# FPGA builds.

FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG TRECAP_UID=1000
ARG TRECAP_GID=1000

LABEL org.opencontainers.image.title="T-RECAP Phase 2 CI image"
LABEL org.opencontainers.image.description="Host-side lint, generated-contract, reference-model, HPS, and PC-dashboard smoke environment."
LABEL org.opencontainers.image.licenses="MIT"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/trecap-venv \
    PATH=/opt/trecap-venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        clang-format \
        cmake \
        curl \
        file \
        g++ \
        gcc \
        git \
        iproute2 \
        jq \
        make \
        ninja-build \
        pkg-config \
        python3 \
        python3-pip \
        python3-venv \
        shellcheck \
        shfmt \
        tcl \
        unzip \
        xz-utils \
        zip \
    && python3 -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/python" -m pip install --upgrade pip setuptools wheel \
    && "$VIRTUAL_ENV/bin/python" -m pip install \
        black \
        jsonschema \
        mypy \
        pytest \
        ruff \
    && groupadd --gid "$TRECAP_GID" trecap \
    && useradd --uid "$TRECAP_UID" --gid "$TRECAP_GID" --create-home --shell /bin/bash trecap \
    && mkdir -p /workspace \
    && chown trecap:trecap /workspace \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER trecap
WORKDIR /workspace

CMD ["bash"]
