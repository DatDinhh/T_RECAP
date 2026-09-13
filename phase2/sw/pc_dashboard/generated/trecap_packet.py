# AUTO-GENERATED - DO NOT EDIT
# Generator: scripts/gen_headers.py
# Generator version: r1.2.0
# Source manifest: spec/generated/gen_manifest.json

from __future__ import annotations

import struct

# Transport constants
TELEMETRY_MAGIC = 1414677328
COMMAND_MAGIC = 1414677315
TELEMETRY_HEADER_VERSION = 1
COMMAND_VERSION_CURRENT = 2
TELEMETRY_HEADER_BYTES = 32
COMMAND_PACKET_BYTES = 28
UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES = 1200
DDR_RECORD_ALIGNMENT_BYTES = 64
TRANSPORT_VERSION_MAJOR = 1
TRANSPORT_VERSION_MINOR = 8
COMMAND_RESULT_MAGIC = 1414677330
COMMAND_RESULT_VERSION = 2
COMMAND_RESULT_BYTES = 32
COMMAND_VERSION_V1 = 1
COMMAND_VERSION_V2 = 2
COMMAND_VERSION = COMMAND_VERSION_CURRENT
COMMAND_VERSIONS_SUPPORTED = (1, 2)

TELEMETRY_HEADER_STRUCT = struct.Struct("<IHHHHIQII")
COMMAND_STRUCT = struct.Struct("<IHHIIIII")
COMMAND_RESULT_STRUCT = struct.Struct("<IHHIIIIII")

PACKET_TYPES = {
    'WAVE': 1,
    'SPEC64': 2,
    'SPEC129': 3,
    'METRICS': 4,
    'STATUS': 5,
    'PEAKS': 6,
    'DEBUG': 126,
    'WRAP': 127,
}
PACKET_TYPE_NAMES = {value: key for key, value in PACKET_TYPES.items()}
PACKET_PRIORITIES = {
    'WAVE': 0,
    'SPEC64': 1,
    'SPEC129': 1,
    'METRICS': 2,
    'STATUS': 3,
    'PEAKS': 1,
    'DEBUG': 0,
}

HEADER_OFFSETS = {
    'magic': 0,
    'version': 4,
    'header_bytes': 6,
    'packet_type': 8,
    'flags': 10,
    'seq': 12,
    'timestamp': 16,
    'payload_bytes': 24,
    'header_crc': 28,
}
COMMON_FLAG_BITS = {
    'payload_truncated': (0, 0),
    'payload_scaled': (1, 1),
    'aggregate_metrics': (2, 2),
    'per_frame_metrics': (3, 3),
    'crc_enabled': (4, 4),
    'status_diagnostic': (5, 5),
    'reserved_15_6': (6, 15),
}

PAYLOAD_RULES = {
    'WAVE': {"expression": "16 + 6 * nsamp", "kind": "variable", "max_bytes": 1168, "min_bytes": 22, "nsamp_max": 192, "nsamp_min": 1},
    'SPEC129': {"bytes": 287, "kind": "exact"},
    'SPEC64': {"bytes": 268, "kind": "exact"},
    'METRICS': {"bytes": 56, "kind": "exact"},
    'STATUS': {"bytes": 72, "kind": "exact"},
    'WRAP': {"bytes": 0, "kind": "exact"},
    'PEAKS': {"kind": "undefined_in_revision_g"},
    'DEBUG': {"kind": "undefined_in_revision_g"},
}
PAYLOAD_OFFSETS = {
    'WAVE': {
        'sample_base': 0,
        'nsamp': 8,
        'channels': 10,
        'stride': 12,
        'reserved': 14,
        'sample': 16,
    },
    'SPEC129': {
        'frame_idx': 0,
        'nbin': 8,
        'spec_shift': 10,
        'spec129': 12,
        'mask_bits': 270,
    },
    'SPEC64': {
        'frame_idx': 0,
        'nbin': 8,
        'spec_shift': 10,
        'spec64': 12,
        'suppressed_count': 140,
        'eligible_count': 204,
    },
    'METRICS': {
        'frame_idx': 0,
        'eligible_unique_bins': 8,
        'eligible_suppressed_bins': 12,
        'eligible_kept_mag2_lo': 16,
        'eligible_total_mag2_lo': 24,
        'sum_abs_err_lo': 32,
        'sum_sq_err_lo': 40,
        'max_abs_err': 48,
        'overflow_flags': 52,
    },
    'STATUS': {
        'sample_count': 0,
        'frame_count': 8,
        'source_mode': 16,
        'sample_rate': 20,
        'packet_enable': 24,
        'dma_drop_count': 28,
        'udp_send_error_count': 32,
        'malformed_record_count': 36,
        'oversized_record_count': 40,
        'command_reject_count': 44,
        'sequence_gap_count': 48,
        'overflow_flags': 52,
        'thr2_lo': 56,
        'thr2_hi': 60,
        'packet_fifo_drop_count': 64,
        'reserved': 68,
    },
    'WRAP': {
    },
    'PEAKS': {
    },
    'DEBUG': {
    },
}

COMMAND_TYPES = {
    'SET_THR2': 1,
    'CLEAR_METRICS': 2,
    'SET_SOURCE_MODE': 3,
    'SET_PACKET_ENABLE': 4,
    'SET_WAVE_DECIM': 5,
    'SET_SPEC_SHIFT': 6,
    'PING': 7,
    'SET_SPEC_MODE': 8,
    'SET_TELEMETRY_ENABLE': 9,
    'CONFIGURE_DDR_RING': 10,
    'RESET_TRANSPORT': 11,
    'CLEAR_COUNTERS': 12,
    'START_BRAM_REPLAY': 13,
    'READ_STATUS_VERSION': 14,
}
COMMAND_TYPE_NAMES = {value: key for key, value in COMMAND_TYPES.items()}
COMMAND_TYPE_MIN_VERSION = {
    1: 1,
    2: 1,
    3: 1,
    4: 1,
    5: 1,
    6: 1,
    7: 1,
    8: 2,
    9: 2,
    10: 2,
    11: 2,
    12: 2,
    13: 2,
    14: 2,
}
COMMAND_V1_TYPES = frozenset(value for value, version in COMMAND_TYPE_MIN_VERSION.items() if version <= 1)
COMMAND_V2_TYPES = frozenset(value for value, version in COMMAND_TYPE_MIN_VERSION.items() if version <= 2)
COMMAND_OFFSETS = {
    'magic': 0,
    'version': 4,
    'cmd_type': 6,
    'seq': 8,
    'arg0': 12,
    'arg1': 16,
    'arg2': 20,
    'crc32': 24,
}
COMMAND_RESULT_OFFSETS = {
    'magic': 0,
    'version': 4,
    'cmd_type': 6,
    'seq': 8,
    'disposition': 12,
    'reject_reason': 16,
    'fpga_status': 20,
    'csr_version': 24,
    'crc32': 28,
}
COMMAND_DISPOSITIONS = {
    'APPLIED': 0,
    'NOOP': 1,
    'REJECTED': 2,
    'FAILED': 3,
}
COMMAND_DISPOSITION_NAMES = {value: key for key, value in COMMAND_DISPOSITIONS.items()}
COMMAND_REJECT_REASONS = {
    'NONE': 0,
    'BAD_SOURCE': 1,
    'BAD_LENGTH': 2,
    'BAD_MAGIC': 3,
    'BAD_VERSION': 4,
    'BAD_CRC': 5,
    'UNSUPPORTED_TYPE': 6,
    'RANGE': 7,
    'RESERVED_ARGUMENT': 8,
    'CSR': 9,
    'IO': 10,
    'UNSAFE_STATE': 11,
    'SEQUENCE_STALE': 12,
    'SEQUENCE_CONFLICT': 13,
    'TIMEOUT': 14,
    'RESET_REQUIRED': 15,
    'VERSION_MISMATCH': 16,
}
COMMAND_REJECT_REASON_NAMES = {value: key for key, value in COMMAND_REJECT_REASONS.items()}

CSR_OFFSETS = {
    'ID': 0,
    'VERSION': 4,
    'CONTROL': 8,
    'STATUS': 12,
    'THR2_LO': 16,
    'THR2_HI': 20,
    'THR2_COMMIT': 24,
    'PACKET_ENABLE': 28,
    'WAVE_DECIM': 32,
    'SPEC_MODE': 36,
    'SPEC_SHIFT': 40,
    'SOURCE_MODE_SHADOW': 44,
    'SOURCE_MODE_COMMIT': 48,
    'RING_BASE_LO': 52,
    'RING_BASE_HI': 56,
    'RING_SIZE_BYTES': 60,
    'RING_CONFIG_COMMIT': 64,
    'RING_WR_SNAPSHOT': 68,
    'RING_WR_LO_SNAP': 72,
    'RING_WR_HI_SNAP': 76,
    'RING_RD_LO_SHADOW': 80,
    'RING_RD_HI_SHADOW': 84,
    'RING_RD_COMMIT': 88,
    'DMA_DROP_COUNT': 92,
    'DMA_PACKET_COUNT': 96,
    'DMA_STATUS': 100,
    'CORE_COUNT_SNAPSHOT': 104,
    'FRAME_COUNT_SNAP_LO': 108,
    'FRAME_COUNT_SNAP_HI': 112,
    'SAMPLE_COUNT_SNAP_LO': 116,
    'SAMPLE_COUNT_SNAP_HI': 120,
    'OVERFLOW_FLAGS': 124,
    'CLEAR_STICKY_FLAGS': 128,
    'CSR_COMMAND_REJECT_COUNT': 132,
    'PACKET_FIFO_DROP_COUNT': 136,
    'COUNTER_CLEAR': 140,
    'REPLAY_CONTROL': 144,
    'REPLAY_STATUS': 148,
}
CSR_BITS = {
    'CONTROL': {
        'telemetry_enable': (0, 0),
        'telemetry_soft_reset': (1, 1),
        'clear_metrics': (2, 2),
        'reserved_3': (3, 3),
        'ring_writer_enable': (4, 4),
        'reserved_31_5': (5, 31),
    },
    'STATUS': {
        'telemetry_enabled': (0, 0),
        'ring_writer_enabled': (1, 1),
        'ring_configured': (2, 2),
        'writer_busy': (3, 3),
        'core_alive': (4, 4),
        'malformed_config': (5, 5),
        'ring_full': (6, 6),
        'packet_fifo_full': (7, 7),
        'thr2_commit_pending': (8, 8),
        'source_commit_pending': (9, 9),
        'actual_source_mode': (10, 11),
        'transport_epoch_idle': (12, 12),
        'source_transition_busy': (13, 13),
        'reserved_31_14': (14, 31),
    },
    'PACKET_ENABLE': {
        'WAVE_EN': (0, 0),
        'SPEC_EN': (1, 1),
        'METRICS_EN': (2, 2),
        'STATUS_EN': (3, 3),
        'PEAKS_EN': (4, 4),
        'DEBUG_EN': (5, 5),
        'reserved_31_6': (6, 31),
    },
    'DMA_STATUS': {
        'writer_idle': (0, 0),
        'writer_busy': (1, 1),
        'no_space': (2, 2),
        'malformed_config': (3, 3),
        'ring_full': (4, 4),
        'packet_fifo_full': (5, 5),
        'ddr_wait': (6, 6),
        'drop_active': (7, 7),
        'reserved_31_8': (8, 31),
    },
    'OVERFLOW_FLAGS': {
        'arithmetic_overflow': (0, 0),
        'ola_overflow': (1, 1),
        'ring_overflow': (2, 2),
        'packet_fifo_overflow': (3, 3),
        'malformed_packet': (4, 4),
        'illegal_command': (5, 5),
        'cdc_error': (6, 6),
        'threshold_range_error': (7, 7),
        'source_mode_error': (8, 8),
        'oversized_record': (9, 9),
        'reserved_31_10': (10, 31),
    },
    'CLEAR_STICKY_FLAGS': {
        'arithmetic_overflow': (0, 0),
        'ola_overflow': (1, 1),
        'ring_overflow': (2, 2),
        'packet_fifo_overflow': (3, 3),
        'malformed_packet': (4, 4),
        'illegal_command': (5, 5),
        'cdc_error': (6, 6),
        'threshold_range_error': (7, 7),
        'source_mode_error': (8, 8),
        'oversized_record': (9, 9),
        'reserved_31_10': (10, 31),
    },
    'COUNTER_CLEAR': {
        'transport_counters': (0, 0),
        'reserved_31_1': (1, 31),
    },
    'REPLAY_CONTROL': {
        'start': (0, 0),
        'rearm': (1, 1),
        'reserved_31_2': (2, 31),
    },
    'REPLAY_STATUS': {
        'pending': (0, 0),
        'last_accept': (1, 1),
        'last_reject': (2, 2),
        'start_ready': (3, 3),
        'replay_active': (4, 4),
        'replay_path_busy': (5, 5),
        'replay_path_done': (6, 6),
        'e2e_busy': (7, 7),
        'e2e_done': (8, 8),
        'error': (9, 9),
        'rearm_required': (10, 10),
        'reserved_15_11': (11, 15),
        'result_epoch': (16, 31),
    },
}

def align64(n: int) -> int:
    return (int(n) + 63) & ~63

def expected_payload_bytes(packet_type_name: str, *, nsamp: int | None = None) -> int:
    rule = PAYLOAD_RULES[packet_type_name]
    if rule.get('kind') == 'exact':
        return int(rule['bytes'])
    if rule.get('kind') == 'variable' and packet_type_name == 'WAVE':
        if nsamp is None:
            raise ValueError('WAVE requires nsamp')
        if not (int(rule['nsamp_min']) <= nsamp <= int(rule['nsamp_max'])):
            raise ValueError(f'WAVE nsamp out of range: {nsamp}')
        return 16 + 6 * nsamp
    raise ValueError(f'no fixed payload rule for {packet_type_name}')
