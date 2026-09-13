# AUTO-GENERATED - DO NOT EDIT
# Generator: scripts/gen_headers.py
# Generator version: r1.2.0
# Source manifest: spec/generated/gen_manifest.json

from __future__ import annotations

CONFIGURATION = {
  "D": 384,
  "F": 15,
  "G": 128,
  "H": 128,
  "L": 256,
  "N": 12,
  "P": 8,
  "PROTECT_DC": 1,
  "PROTECT_NYQ": 0,
  "THR2": 0
}

WIDTHS = {
  "W_Qw": 16,
  "W_can": 28,
  "W_can_pre": 29,
  "W_fft": 28,
  "W_fft_pre": 29,
  "W_ifft": 36,
  "W_mag2": 56,
  "W_ola": 37,
  "W_tw": 17,
  "W_u": 27,
  "W_z": 36
}

TRANSPORT = {
  "COMMAND_MAGIC": 1414677315,
  "TELEMETRY_MAGIC": 1414677328,
  "VERSION_MAJOR": 1,
  "VERSION_MINOR": 8
}

CSR_OFFSETS = {
  "CLEAR_STICKY_FLAGS": 128,
  "CONTROL": 8,
  "CORE_COUNT_SNAPSHOT": 104,
  "COUNTER_CLEAR": 140,
  "CSR_COMMAND_REJECT_COUNT": 132,
  "DMA_DROP_COUNT": 92,
  "DMA_PACKET_COUNT": 96,
  "DMA_STATUS": 100,
  "FRAME_COUNT_SNAP_HI": 112,
  "FRAME_COUNT_SNAP_LO": 108,
  "ID": 0,
  "OVERFLOW_FLAGS": 124,
  "PACKET_ENABLE": 28,
  "PACKET_FIFO_DROP_COUNT": 136,
  "REPLAY_CONTROL": 144,
  "REPLAY_STATUS": 148,
  "RING_BASE_HI": 56,
  "RING_BASE_LO": 52,
  "RING_CONFIG_COMMIT": 64,
  "RING_RD_COMMIT": 88,
  "RING_RD_HI_SHADOW": 84,
  "RING_RD_LO_SHADOW": 80,
  "RING_SIZE_BYTES": 60,
  "RING_WR_HI_SNAP": 76,
  "RING_WR_LO_SNAP": 72,
  "RING_WR_SNAPSHOT": 68,
  "SAMPLE_COUNT_SNAP_HI": 120,
  "SAMPLE_COUNT_SNAP_LO": 116,
  "SOURCE_MODE_COMMIT": 48,
  "SOURCE_MODE_SHADOW": 44,
  "SPEC_MODE": 36,
  "SPEC_SHIFT": 40,
  "STATUS": 12,
  "THR2_COMMIT": 24,
  "THR2_HI": 20,
  "THR2_LO": 16,
  "VERSION": 4,
  "WAVE_DECIM": 32
}

PACKET_TYPES = {
  "DEBUG": 126,
  "METRICS": 4,
  "PEAKS": 6,
  "SPEC129": 3,
  "SPEC64": 2,
  "STATUS": 5,
  "WAVE": 1,
  "WRAP": 127
}
