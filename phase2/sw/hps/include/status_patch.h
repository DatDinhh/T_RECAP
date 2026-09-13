/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS STATUS patch API.
 * File class: [1] hand-written.
 *
 * This header owns the non-generated C API for patching the HPS-owned fields in
 * an outgoing STATUS UDP copy and for building HPS diagnostic STATUS replies.
 * It intentionally does not define packet IDs, STATUS payload offsets, command
 * IDs, or VERSION values. Those constants come from generated/trecap_packet.h
 * and generated/trecap_csr.h.
 */

#ifndef TRECAP_HPS_STATUS_PATCH_H
#define TRECAP_HPS_STATUS_PATCH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "csr_map.h"
#include "generated/trecap_packet.h"
#include "ring_reader.h"
#include "trecap_hps_config.h"
#include "udp_sender.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum trecap_status_patch_status {
    TRECAP_STATUS_PATCH_OK = 0,
    TRECAP_STATUS_PATCH_NOT_STATUS = 1,
    TRECAP_STATUS_PATCH_DIAGNOSTIC = 2,
    TRECAP_STATUS_PATCH_ERR_NULL = -1,
    TRECAP_STATUS_PATCH_ERR_RANGE = -2,
    TRECAP_STATUS_PATCH_ERR_MAGIC = -3,
    TRECAP_STATUS_PATCH_ERR_VERSION = -4,
    TRECAP_STATUS_PATCH_ERR_HEADER = -5,
    TRECAP_STATUS_PATCH_ERR_PACKET_TYPE = -6,
    TRECAP_STATUS_PATCH_ERR_FLAGS = -7,
    TRECAP_STATUS_PATCH_ERR_PAYLOAD = -8,
    TRECAP_STATUS_PATCH_ERR_CRC = -9,
    TRECAP_STATUS_PATCH_ERR_CAPACITY = -10
} trecap_status_patch_status_t;

typedef struct trecap_status_fpga_snapshot {
    uint64_t sample_count;
    uint64_t frame_count;
    uint32_t source_mode;
    uint32_t sample_rate_hz;
    uint32_t packet_enable;
    uint32_t dma_drop_count;
    uint32_t overflow_flags;
    uint64_t active_thr2;
    uint32_t packet_fifo_drop_count;
    bool valid;
} trecap_status_fpga_snapshot_t;

typedef struct trecap_status_hps_counters {
    uint64_t udp_send_error_count;
    uint64_t malformed_record_count;
    uint64_t oversized_record_count;
    uint64_t hps_command_reject_count;
    uint64_t csr_command_reject_count;
    uint64_t sequence_gap_count;
} trecap_status_hps_counters_t;

typedef struct trecap_status_patch_inputs {
    trecap_status_fpga_snapshot_t fpga;
    trecap_status_hps_counters_t hps;
    bool diagnostic;
} trecap_status_patch_inputs_t;

static inline uint16_t trecap_status_load_le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8u));
}

static inline uint32_t trecap_status_load_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static inline uint64_t trecap_status_load_le64(const uint8_t *p)
{
    return (uint64_t)trecap_status_load_le32(p) |
           ((uint64_t)trecap_status_load_le32(&p[4]) << 32u);
}

static inline void trecap_status_store_le16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value & UINT16_C(0x00ff));
    p[1] = (uint8_t)((value >> 8u) & UINT16_C(0x00ff));
}

static inline void trecap_status_store_le32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)(value & UINT32_C(0x000000ff));
    p[1] = (uint8_t)((value >> 8u) & UINT32_C(0x000000ff));
    p[2] = (uint8_t)((value >> 16u) & UINT32_C(0x000000ff));
    p[3] = (uint8_t)((value >> 24u) & UINT32_C(0x000000ff));
}

static inline void trecap_status_store_le64(uint8_t *p, uint64_t value)
{
    trecap_status_store_le32(p, (uint32_t)(value & UINT64_C(0xffffffff)));
    trecap_status_store_le32(&p[4], (uint32_t)(value >> 32u));
}

static inline uint32_t trecap_status_low32(uint64_t value)
{
    return (uint32_t)(value & UINT64_C(0xffffffff));
}

static inline uint32_t trecap_status_thr2_lo(uint64_t thr2)
{
    return (uint32_t)(thr2 & UINT64_C(0xffffffff));
}

static inline uint32_t trecap_status_thr2_hi(uint64_t thr2)
{
    return (uint32_t)((thr2 >> 32u) & UINT64_C(0x00ffffff));
}

static inline uint32_t trecap_status_combined_command_reject_low32(
    const trecap_status_hps_counters_t *hps)
{
    if (hps == NULL) {
        return 0u;
    }
    return trecap_status_low32(hps->hps_command_reject_count + hps->csr_command_reject_count);
}

static inline size_t trecap_status_datagram_bytes(void)
{
    return (size_t)TPKT_HEADER_BYTES + (size_t)TPKT_PAYLOAD_STATUS_BYTES;
}

static inline bool trecap_status_datagram_size_is_valid(size_t datagram_bytes)
{
    return datagram_bytes == trecap_status_datagram_bytes();
}

static inline bool trecap_status_header_basic_is_valid(const uint8_t *datagram,
                                                       size_t datagram_bytes)
{
    if (datagram == NULL || !trecap_status_datagram_size_is_valid(datagram_bytes)) {
        return false;
    }
    return trecap_status_load_le32(&datagram[TPKT_HDR_MAGIC_OFFSET]) == TPKT_TELEMETRY_MAGIC &&
           trecap_status_load_le16(&datagram[TPKT_HDR_VERSION_OFFSET]) ==
               (uint16_t)TPKT_HEADER_VERSION &&
           trecap_status_load_le16(&datagram[TPKT_HDR_HEADER_BYTES_OFFSET]) ==
               (uint16_t)TPKT_HEADER_BYTES &&
           trecap_status_load_le16(&datagram[TPKT_HDR_PACKET_TYPE_OFFSET]) == TPKT_TYPE_STATUS &&
           trecap_status_load_le32(&datagram[TPKT_HDR_PAYLOAD_BYTES_OFFSET]) ==
               (uint32_t)TPKT_PAYLOAD_STATUS_BYTES &&
           trecap_status_load_le32(&datagram[TPKT_HDR_HEADER_CRC_OFFSET]) == 0u;
}

static inline bool trecap_status_flags_are_valid(uint16_t flags, bool diagnostic_allowed)
{
    const uint16_t common_illegal = TPKT_FLAG_RESERVED_15_6_MASK | TPKT_FLAG_CRC_ENABLED_MASK |
                                    TPKT_FLAG_PAYLOAD_TRUNCATED_MASK |
                                    TPKT_FLAG_PAYLOAD_SCALED_MASK |
                                    TPKT_FLAG_AGGREGATE_METRICS_MASK |
                                    TPKT_FLAG_PER_FRAME_METRICS_MASK;
    if ((flags & common_illegal) != 0u) {
        return false;
    }
    if ((flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 0u) {
        return diagnostic_allowed;
    }
    return true;
}

static inline uint8_t *trecap_status_payload_mut(uint8_t *datagram)
{
    return datagram + (size_t)TPKT_HEADER_BYTES;
}

static inline const uint8_t *trecap_status_payload_const(const uint8_t *datagram)
{
    return datagram + (size_t)TPKT_HEADER_BYTES;
}

static inline trecap_status_patch_status_t trecap_status_patch_hps_fields_in_payload(
    uint8_t *payload,
    const trecap_status_hps_counters_t *hps)
{
    if (payload == NULL || hps == NULL) {
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    trecap_status_store_le32(&payload[TPKT_STATUS_UDP_SEND_ERROR_COUNT_OFFSET],
                             trecap_status_low32(hps->udp_send_error_count));
    trecap_status_store_le32(&payload[TPKT_STATUS_MALFORMED_RECORD_COUNT_OFFSET],
                             trecap_status_low32(hps->malformed_record_count));
    trecap_status_store_le32(&payload[TPKT_STATUS_OVERSIZED_RECORD_COUNT_OFFSET],
                             trecap_status_low32(hps->oversized_record_count));
    trecap_status_store_le32(&payload[TPKT_STATUS_COMMAND_REJECT_COUNT_OFFSET],
                             trecap_status_combined_command_reject_low32(hps));
    trecap_status_store_le32(&payload[TPKT_STATUS_SEQUENCE_GAP_COUNT_OFFSET],
                             trecap_status_low32(hps->sequence_gap_count));
    trecap_status_store_le32(&payload[TPKT_STATUS_RESERVED_OFFSET], 0u);
    return TRECAP_STATUS_PATCH_OK;
}

static inline trecap_status_patch_status_t trecap_status_write_payload_from_snapshot(
    uint8_t *payload,
    const trecap_status_patch_inputs_t *inputs)
{
    if (payload == NULL || inputs == NULL) {
        return TRECAP_STATUS_PATCH_ERR_NULL;
    }
    trecap_status_store_le64(&payload[TPKT_STATUS_SAMPLE_COUNT_OFFSET], inputs->fpga.sample_count);
    trecap_status_store_le64(&payload[TPKT_STATUS_FRAME_COUNT_OFFSET], inputs->fpga.frame_count);
    trecap_status_store_le32(&payload[TPKT_STATUS_SOURCE_MODE_OFFSET], inputs->fpga.source_mode);
    trecap_status_store_le32(&payload[TPKT_STATUS_SAMPLE_RATE_OFFSET], inputs->fpga.sample_rate_hz);
    trecap_status_store_le32(&payload[TPKT_STATUS_PACKET_ENABLE_OFFSET], inputs->fpga.packet_enable);
    trecap_status_store_le32(&payload[TPKT_STATUS_DMA_DROP_COUNT_OFFSET],
                             inputs->fpga.dma_drop_count);
    trecap_status_store_le32(&payload[TPKT_STATUS_OVERFLOW_FLAGS_OFFSET],
                             inputs->fpga.overflow_flags);
    trecap_status_store_le32(&payload[TPKT_STATUS_THR2_LO_OFFSET],
                             trecap_status_thr2_lo(inputs->fpga.active_thr2));
    trecap_status_store_le32(&payload[TPKT_STATUS_THR2_HI_OFFSET],
                             trecap_status_thr2_hi(inputs->fpga.active_thr2));
    trecap_status_store_le32(&payload[TPKT_STATUS_PACKET_FIFO_DROP_COUNT_OFFSET],
                             inputs->fpga.packet_fifo_drop_count);
    return trecap_status_patch_hps_fields_in_payload(payload, &inputs->hps);
}

const char *trecap_status_patch_status_string(trecap_status_patch_status_t status);

void trecap_status_hps_counters_clear(trecap_status_hps_counters_t *counters);

void trecap_status_hps_counters_from_runtime(const trecap_udp_sender_counters_t *udp,
                                             const trecap_ring_reader_counters_t *ring,
                                             uint64_t hps_command_reject_count,
                                             uint64_t csr_command_reject_count,
                                             trecap_status_hps_counters_t *out);

trecap_status_patch_status_t trecap_status_patch_validate_status_datagram(
    const void *datagram,
    size_t datagram_bytes,
    bool diagnostic_allowed);

trecap_status_patch_status_t trecap_status_patch_udp_copy(void *datagram,
                                                          size_t datagram_bytes,
                                                          const trecap_status_hps_counters_t *hps,
                                                          char *err_buf,
                                                          size_t err_buf_len);

trecap_status_patch_status_t trecap_status_patch_from_ring_view(
    void *udp_datagram,
    size_t udp_datagram_bytes,
    const trecap_ring_record_view_t *view,
    const trecap_status_hps_counters_t *hps,
    char *err_buf,
    size_t err_buf_len);

trecap_status_patch_status_t trecap_status_build_diagnostic(void *out_datagram,
                                                            size_t out_capacity_bytes,
                                                            const trecap_status_patch_inputs_t *inputs,
                                                            size_t *out_datagram_bytes,
                                                            char *err_buf,
                                                            size_t err_buf_len);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_STATUS_PATCH_H */
