/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS DDR-ring reader API.
 * File class: [1] hand-written.
 *
 * This header owns the non-generated C API for consuming committed telemetry
 * records from the HPS-visible DDR ring. It intentionally does not define CSR
 * offsets, packet IDs, payload sizes, VERSION values, or wire-field offsets.
 * Those constants come from generated/trecap_csr.h and generated/trecap_packet.h.
 */

#ifndef TRECAP_HPS_RING_READER_H
#define TRECAP_HPS_RING_READER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "csr_map.h"
#include "generated/trecap_packet.h"
#include "trecap_hps_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum trecap_ring_status {
    TRECAP_RING_OK = 0,
    TRECAP_RING_EMPTY = 1,
    TRECAP_RING_WRAP_RECORD = 2,
    TRECAP_RING_ERR_NULL = -1,
    TRECAP_RING_ERR_RANGE = -2,
    TRECAP_RING_ERR_ALIGN = -3,
    TRECAP_RING_ERR_CONFIG = -4,
    TRECAP_RING_ERR_IO = -5,
    TRECAP_RING_ERR_MALFORMED = -6,
    TRECAP_RING_ERR_OVERSIZED = -7,
    TRECAP_RING_ERR_BOUNDARY = -8,
    TRECAP_RING_ERR_CSR = -9,
    TRECAP_RING_ERR_STALE = -10,
    TRECAP_RING_ERR_TIMEOUT = -11,
    TRECAP_RING_ERR_DISABLED = -12
} trecap_ring_status_t;

typedef enum trecap_ring_record_class {
    TRECAP_RING_RECORD_CLASS_NORMAL = 0,
    TRECAP_RING_RECORD_CLASS_WRAP = 1,
    TRECAP_RING_RECORD_CLASS_MALFORMED = 2,
    TRECAP_RING_RECORD_CLASS_OVERSIZED = 3
} trecap_ring_record_class_t;

typedef enum trecap_ring_reader_state {
    TRECAP_RING_READER_RESET_REQUIRED = 0,
    TRECAP_RING_READER_RECONFIG_REQUIRED = 1,
    TRECAP_RING_READER_RD0_REQUIRED = 2,
    TRECAP_RING_READER_ACTIVE = 3,
    TRECAP_RING_READER_MALFORMED_LATCHED = 4
} trecap_ring_reader_state_t;

typedef struct trecap_ring_mapping {
    uint8_t *base;
    size_t size_bytes;
    uint64_t hps_phys_base;
    uint64_t fpga_visible_base;
    bool cacheable_mapping;
    int fd;
} trecap_ring_mapping_t;

typedef struct trecap_ring_reader_config {
    uint32_t ring_size_bytes;
    uint32_t ring_guard_bytes;
    bool stop_on_malformed_record;
    bool commit_rd_after_each_record;
    bool reject_status_diagnostic_from_ring;
} trecap_ring_reader_config_t;

typedef struct trecap_ring_record_view {
    const uint8_t *record_bytes;
    const uint8_t *payload_bytes_ptr;
    uint64_t absolute_rd;
    uint64_t absolute_next_rd;
    uint32_t ring_offset;
    uint32_t physical_tail_bytes;
    uint32_t ddr_record_bytes;
    uint32_t udp_datagram_bytes;
    uint32_t payload_bytes;
    uint16_t packet_type;
    uint16_t flags;
    uint32_t seq;
    uint64_t timestamp;
    uint32_t header_crc;
    trecap_ring_record_class_t record_class;
} trecap_ring_record_view_t;

typedef struct trecap_ring_reader_counters {
    uint64_t records_seen;
    uint64_t records_forwardable;
    uint64_t wrap_records_seen;
    uint64_t malformed_record_count;
    uint64_t oversized_record_count;
    uint64_t boundary_error_count;
    uint64_t sequence_gap_count;
    uint64_t consumer_commit_count;
    uint64_t stale_snapshot_count;
} trecap_ring_reader_counters_t;

typedef struct trecap_ring_reader {
    trecap_ring_mapping_t ring;
    trecap_csr_window_t *csr;
    trecap_ring_reader_config_t cfg;
    trecap_ring_reader_counters_t counters;
    uint64_t rd;
    uint64_t wr_snapshot;
    uint32_t last_seq;
    bool have_last_seq;
    bool telemetry_disabled_by_reader;
    bool malformed_disable_commit_confirmed;
    trecap_ring_reader_state_t state;
} trecap_ring_reader_t;

static inline uint32_t trecap_ring_low32(uint64_t value)
{
    return (uint32_t)(value & UINT64_C(0xffffffff));
}

static inline uint32_t trecap_ring_high32(uint64_t value)
{
    return (uint32_t)(value >> 32u);
}

static inline uint64_t trecap_ring_join64(uint32_t lo, uint32_t hi)
{
    return ((uint64_t)hi << 32u) | (uint64_t)lo;
}

static inline bool trecap_ring_is_power_of_two_u32(uint32_t value)
{
    return value != 0u && (value & (value - 1u)) == 0u;
}

static inline bool trecap_ring_size_is_valid(uint32_t size_bytes)
{
    return trecap_hps_ring_size_is_valid(size_bytes);
}

static inline bool trecap_ring_base_is_valid(uint64_t base)
{
    return trecap_hps_ring_base_is_valid(base);
}

static inline uint32_t trecap_ring_align64_u32(uint32_t value)
{
    const uint32_t mask = (uint32_t)TPKT_DDR_ALIGN_BYTES - 1u;
    return (value + mask) & ~mask;
}

static inline size_t trecap_ring_align64_size(size_t value)
{
    const size_t mask = (size_t)TPKT_DDR_ALIGN_BYTES - (size_t)1;
    return (value + mask) & ~mask;
}

static inline uint32_t trecap_ring_offset(uint64_t absolute_pointer, uint32_t ring_size_bytes)
{
    return (uint32_t)(absolute_pointer & (uint64_t)(ring_size_bytes - 1u));
}

static inline uint64_t trecap_ring_used_bytes(uint64_t wr, uint64_t rd)
{
    return wr - rd;
}

static inline uint32_t trecap_ring_payload_to_udp_bytes(uint32_t payload_bytes)
{
    return (uint32_t)TPKT_HEADER_BYTES + payload_bytes;
}

static inline uint32_t trecap_ring_payload_to_ddr_bytes(uint32_t payload_bytes)
{
    return trecap_ring_align64_u32((uint32_t)TPKT_HEADER_BYTES + payload_bytes);
}

static inline bool trecap_ring_udp_datagram_size_is_valid(uint32_t payload_bytes)
{
    return trecap_ring_payload_to_udp_bytes(payload_bytes) <= (uint32_t)TPKT_UDP_MAX_BYTES;
}

static inline bool trecap_ring_wave_payload_size_is_valid(uint32_t payload_bytes)
{
    if (payload_bytes < (uint32_t)TPKT_PAYLOAD_WAVE_MIN_BYTES ||
        payload_bytes > (uint32_t)TPKT_PAYLOAD_WAVE_MAX_BYTES || payload_bytes < 16u) {
        return false;
    }
    const uint32_t sample_bytes = payload_bytes - 16u;
    if ((sample_bytes % 6u) != 0u) {
        return false;
    }
    const uint32_t nsamp = sample_bytes / 6u;
    return nsamp >= (uint32_t)TPKT_PAYLOAD_WAVE_NSAMP_MIN &&
           nsamp <= (uint32_t)TPKT_PAYLOAD_WAVE_NSAMP_MAX;
}

static inline bool trecap_ring_payload_size_is_valid(uint16_t packet_type, uint32_t payload_bytes)
{
    switch (packet_type) {
    case TPKT_TYPE_WAVE:
        return trecap_ring_wave_payload_size_is_valid(payload_bytes);
    case TPKT_TYPE_SPEC64:
        return payload_bytes == (uint32_t)TPKT_PAYLOAD_SPEC64_BYTES;
    case TPKT_TYPE_SPEC129:
        return payload_bytes == (uint32_t)TPKT_PAYLOAD_SPEC129_BYTES;
    case TPKT_TYPE_METRICS:
        return payload_bytes == (uint32_t)TPKT_PAYLOAD_METRICS_BYTES;
    case TPKT_TYPE_STATUS:
        return payload_bytes == (uint32_t)TPKT_PAYLOAD_STATUS_BYTES;
    case TPKT_TYPE_WRAP:
        return payload_bytes == (uint32_t)TPKT_PAYLOAD_WRAP_BYTES;
    default:
        return false;
    }
}

static inline bool trecap_ring_packet_type_is_forwardable(uint16_t packet_type)
{
    return packet_type == TPKT_TYPE_WAVE || packet_type == TPKT_TYPE_SPEC64 ||
           packet_type == TPKT_TYPE_SPEC129 || packet_type == TPKT_TYPE_METRICS ||
           packet_type == TPKT_TYPE_STATUS;
}

static inline bool trecap_ring_packet_type_is_wrap(uint16_t packet_type)
{
    return packet_type == TPKT_TYPE_WRAP;
}

static inline bool trecap_ring_flags_have_common_illegal_bits(uint16_t flags)
{
    const uint16_t illegal = TPKT_FLAG_RESERVED_15_6_MASK | TPKT_FLAG_CRC_ENABLED_MASK;
    return (flags & illegal) != 0u;
}

static inline bool trecap_ring_metrics_flags_are_valid(uint16_t flags)
{
    const bool aggregate = (flags & TPKT_FLAG_AGGREGATE_METRICS_MASK) != 0u;
    const bool per_frame = (flags & TPKT_FLAG_PER_FRAME_METRICS_MASK) != 0u;
    const bool scaled = (flags & TPKT_FLAG_PAYLOAD_SCALED_MASK) != 0u;
    return aggregate != per_frame && !scaled;
}

static inline bool trecap_ring_flags_are_valid_for_ddr(uint16_t packet_type, uint16_t flags)
{
    if (trecap_ring_flags_have_common_illegal_bits(flags)) {
        return false;
    }
    if ((flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 0u) {
        return false;
    }
    if (packet_type == TPKT_TYPE_METRICS) {
        return trecap_ring_metrics_flags_are_valid(flags);
    }
    if ((flags & (TPKT_FLAG_AGGREGATE_METRICS_MASK | TPKT_FLAG_PER_FRAME_METRICS_MASK)) != 0u) {
        return false;
    }
    if (packet_type == TPKT_TYPE_STATUS || packet_type == TPKT_TYPE_WRAP) {
        return flags == 0u;
    }
    return true;
}

static inline bool trecap_ring_record_view_is_forwardable(const trecap_ring_record_view_t *view)
{
    return view != NULL && view->record_class == TRECAP_RING_RECORD_CLASS_NORMAL &&
           trecap_ring_packet_type_is_forwardable(view->packet_type) &&
           view->udp_datagram_bytes <= (uint32_t)TPKT_UDP_MAX_BYTES;
}

const char *trecap_ring_status_string(trecap_ring_status_t status);

void trecap_ring_reader_config_set_defaults(trecap_ring_reader_config_t *cfg,
                                            const trecap_hps_runtime_config_t *runtime_cfg);

void trecap_ring_reader_counters_reset(trecap_ring_reader_counters_t *counters);

void trecap_ring_reader_init(trecap_ring_reader_t *reader,
                             trecap_csr_window_t *csr,
                             const trecap_ring_mapping_t *ring,
                             const trecap_ring_reader_config_t *cfg);

trecap_ring_status_t trecap_ring_map_physical(uint64_t ring_base_hps_phys,
                                              size_t ring_size_bytes,
                                              bool cacheable_mapping,
                                              trecap_ring_mapping_t *ring);

void trecap_ring_unmap(trecap_ring_mapping_t *ring);

trecap_ring_status_t trecap_ring_reader_reset_transport(trecap_ring_reader_t *reader);

trecap_ring_status_t trecap_ring_reader_configure_fpga_ring(trecap_ring_reader_t *reader,
                                                            uint64_t ring_base_fpga,
                                                            uint32_t ring_size_bytes,
                                                            uint32_t ring_guard_bytes);

trecap_ring_status_t trecap_ring_reader_commit_rd(trecap_ring_reader_t *reader, uint64_t rd);

trecap_ring_status_t trecap_ring_reader_snapshot_wr(trecap_ring_reader_t *reader,
                                                    uint64_t *wr_out);

trecap_ring_status_t trecap_ring_reader_peek(const trecap_ring_reader_t *reader,
                                             trecap_ring_record_view_t *view,
                                             char *err_buf,
                                             size_t err_buf_len);

trecap_ring_status_t trecap_ring_reader_advance(trecap_ring_reader_t *reader,
                                                const trecap_ring_record_view_t *view);

trecap_ring_status_t trecap_ring_reader_note_forwarded(trecap_ring_reader_t *reader,
                                                       const trecap_ring_record_view_t *view);

trecap_ring_status_t trecap_ring_reader_handle_malformed(trecap_ring_reader_t *reader,
                                                         const trecap_ring_record_view_t *view,
                                                         char *err_buf,
                                                         size_t err_buf_len);

trecap_ring_status_t trecap_ring_validate_record_header(const trecap_ring_mapping_t *ring,
                                                        uint64_t rd,
                                                        uint64_t wr,
                                                        trecap_ring_record_view_t *view,
                                                        char *err_buf,
                                                        size_t err_buf_len);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_RING_READER_H */
