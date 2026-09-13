/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS CSR access API.
 * File class: [1] hand-written.
 *
 * This header wraps the generated CSR contract with typed HPS access helpers.
 * It does not duplicate CSR offsets, bit masks, VERSION values, or packet constants.
 */

#ifndef TRECAP_HPS_CSR_MAP_H
#define TRECAP_HPS_CSR_MAP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "generated/trecap_csr.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum trecap_csr_status {
    TRECAP_CSR_OK = 0,
    TRECAP_CSR_ERR_NULL = -1,
    TRECAP_CSR_ERR_RANGE = -2,
    TRECAP_CSR_ERR_ALIGN = -3,
    TRECAP_CSR_ERR_VERSION = -4,
    TRECAP_CSR_ERR_BAD_VALUE = -5,
    TRECAP_CSR_ERR_IO = -6,
    TRECAP_CSR_ERR_TIMEOUT = -7
} trecap_csr_status_t;

typedef struct trecap_csr_window {
    volatile uint8_t *base;
    size_t span_bytes;
} trecap_csr_window_t;

typedef struct trecap_csr_ring_config {
    uint64_t base_fpga;
    uint32_t size_bytes;
    uint32_t guard_bytes;
} trecap_csr_ring_config_t;

typedef struct trecap_csr_core_counts {
    uint64_t frame_count;
    uint64_t sample_count;
} trecap_csr_core_counts_t;

typedef struct trecap_csr_counters {
    uint32_t dma_drop_count;
    uint32_t dma_packet_count;
    uint32_t csr_command_reject_count;
    uint32_t packet_fifo_drop_count;
} trecap_csr_counters_t;

typedef struct trecap_csr_replay_status {
    uint32_t raw;
    uint16_t result_epoch;
    bool pending;
    bool last_accept;
    bool last_reject;
    bool start_ready;
    bool replay_active;
    bool replay_path_busy;
    bool replay_path_done;
    bool e2e_busy;
    bool e2e_done;
    bool error;
    bool rearm_required;
} trecap_csr_replay_status_t;

static inline bool trecap_csr_offset_is_aligned(uint32_t offset)
{
    return (offset & UINT32_C(3)) == 0u;
}

static inline bool trecap_csr_offset_in_range(const trecap_csr_window_t *csr, uint32_t offset)
{
    return csr != NULL && csr->base != NULL && trecap_csr_offset_is_aligned(offset) &&
           ((size_t)offset + sizeof(uint32_t)) <= csr->span_bytes;
}

static inline uint32_t trecap_csr_read32_raw(const trecap_csr_window_t *csr, uint32_t offset)
{
    return *(const volatile uint32_t *)(const volatile void *)(csr->base + offset);
}

static inline void trecap_csr_write32_raw(const trecap_csr_window_t *csr,
                                          uint32_t offset,
                                          uint32_t value)
{
    *(volatile uint32_t *)(volatile void *)(csr->base + offset) = value;
}

static inline uint32_t trecap_csr_make_control_word(bool telemetry_enable,
                                                    bool ring_writer_enable)
{
    uint32_t value = 0u;
    if (telemetry_enable) {
        value |= TCSR_CONTROL_TELEMETRY_ENABLE_MASK;
    }
    if (ring_writer_enable) {
        value |= TCSR_CONTROL_RING_WRITER_ENABLE_MASK;
    }
    return value;
}

static inline bool trecap_csr_version_supported(uint32_t csr_version)
{
    return ((csr_version >> 16u) & UINT32_C(0xffff)) == TCSR_VERSION_MAJOR;
}

static inline uint64_t trecap_csr_join_u64(uint32_t lo, uint32_t hi)
{
    return ((uint64_t)hi << 32u) | (uint64_t)lo;
}

static inline uint32_t trecap_csr_lo32(uint64_t value)
{
    return (uint32_t)(value & UINT64_C(0xffffffff));
}

static inline uint32_t trecap_csr_hi32(uint64_t value)
{
    return (uint32_t)(value >> 32u);
}

static inline bool trecap_csr_thr2_is_valid(uint64_t thr2)
{
    return (thr2 >> TCSR_THR2_WIDTH_BITS) == 0u;
}

static inline bool trecap_csr_source_mode_is_valid(uint32_t source_mode)
{
    return source_mode == TCSR_SOURCE_MODE_BRAM_REPLAY ||
           source_mode == TCSR_SOURCE_MODE_ADC_LIVE ||
           source_mode == TCSR_SOURCE_MODE_AUDIO_WRAPPER ||
           source_mode == TCSR_SOURCE_MODE_DIAGNOSTIC;
}

static inline bool trecap_csr_spec_mode_is_valid(uint32_t spec_mode)
{
    return spec_mode == TCSR_SPEC_MODE_SPEC_DISABLED ||
           spec_mode == TCSR_SPEC_MODE_SPEC64 ||
           spec_mode == TCSR_SPEC_MODE_SPEC129;
}

static inline bool trecap_csr_spec_shift_is_valid(uint32_t spec_shift)
{
    return spec_shift <= TCSR_SPEC_SHIFT_MAX;
}

static inline bool trecap_csr_wave_decim_is_valid(uint32_t wave_decim)
{
    return wave_decim >= TCSR_WAVE_DECIM_MIN && wave_decim <= TCSR_WAVE_DECIM_MAX;
}

static inline bool trecap_csr_packet_enable_is_valid(uint32_t packet_enable)
{
    const uint32_t reserved_disabled = TCSR_PACKET_ENABLE_PEAKS_EN_MASK |
                                       TCSR_PACKET_ENABLE_DEBUG_EN_MASK |
                                       TCSR_PACKET_ENABLE_RESERVED_31_6_MASK;
    return (packet_enable & reserved_disabled) == 0u;
}

static inline bool trecap_csr_ring_size_is_valid(uint32_t ring_size_bytes)
{
    return ring_size_bytes >= UINT32_C(1048576) &&
           (ring_size_bytes & (ring_size_bytes - 1u)) == 0u &&
           (ring_size_bytes % TCSR_RING_ALIGNMENT_BYTES) == 0u;
}

static inline bool trecap_csr_ring_base_is_valid(uint64_t base_fpga)
{
    return (base_fpga % TCSR_RING_ALIGNMENT_BYTES) == 0u;
}

const char *trecap_csr_status_string(trecap_csr_status_t status);

trecap_csr_status_t trecap_csr_map_physical(uint64_t csr_base_phys,
                                            size_t span_bytes,
                                            trecap_csr_window_t *csr);

void trecap_csr_unmap(trecap_csr_window_t *csr);

trecap_csr_status_t trecap_csr_read32(const trecap_csr_window_t *csr,
                                      uint32_t offset,
                                      uint32_t *value);

trecap_csr_status_t trecap_csr_write32(const trecap_csr_window_t *csr,
                                       uint32_t offset,
                                       uint32_t value);

trecap_csr_status_t trecap_csr_require_id_version(const trecap_csr_window_t *csr,
                                                  uint32_t *id_out,
                                                  uint32_t *version_out);

trecap_csr_status_t trecap_csr_require_control_levels(const trecap_csr_window_t *csr,
                                                      bool telemetry_enable,
                                                      bool ring_writer_enable);

trecap_csr_status_t trecap_csr_require_ring_configured(const trecap_csr_window_t *csr);

trecap_csr_status_t trecap_csr_set_control_levels(const trecap_csr_window_t *csr,
                                                  bool telemetry_enable,
                                                  bool ring_writer_enable);

trecap_csr_status_t trecap_csr_pulse_control(const trecap_csr_window_t *csr,
                                             uint32_t w1p_mask);

trecap_csr_status_t trecap_csr_set_thr2(const trecap_csr_window_t *csr, uint64_t thr2);

trecap_csr_status_t trecap_csr_set_source_mode(const trecap_csr_window_t *csr,
                                               uint32_t source_mode);

trecap_csr_status_t trecap_csr_set_packet_enable(const trecap_csr_window_t *csr,
                                                 uint32_t packet_enable);

trecap_csr_status_t trecap_csr_set_wave_decim(const trecap_csr_window_t *csr,
                                              uint32_t wave_decim);

trecap_csr_status_t trecap_csr_set_spec_mode_shift(const trecap_csr_window_t *csr,
                                                   uint32_t spec_mode,
                                                   uint32_t spec_shift);

trecap_csr_status_t trecap_csr_set_spec_mode(const trecap_csr_window_t *csr,
                                             uint32_t spec_mode);

trecap_csr_status_t trecap_csr_set_spec_shift(const trecap_csr_window_t *csr,
                                              uint32_t spec_shift);

trecap_csr_status_t trecap_csr_configure_ring(const trecap_csr_window_t *csr,
                                              const trecap_csr_ring_config_t *ring);

trecap_csr_status_t trecap_csr_commit_ring_rd(const trecap_csr_window_t *csr, uint64_t rd);

trecap_csr_status_t trecap_csr_snapshot_ring_wr(const trecap_csr_window_t *csr,
                                                uint64_t *wr_out);

trecap_csr_status_t trecap_csr_snapshot_core_counts(const trecap_csr_window_t *csr,
                                                    trecap_csr_core_counts_t *counts_out);

trecap_csr_status_t trecap_csr_read_counters(const trecap_csr_window_t *csr,
                                             trecap_csr_counters_t *counters_out);

trecap_csr_status_t trecap_csr_clear_sticky_flags(const trecap_csr_window_t *csr,
                                                  uint32_t clear_mask);

trecap_csr_status_t trecap_csr_clear_transport_counters(const trecap_csr_window_t *csr);

trecap_csr_status_t trecap_csr_pulse_replay_control(const trecap_csr_window_t *csr,
                                                    uint32_t pulse_mask);

trecap_csr_status_t trecap_csr_read_replay_status(const trecap_csr_window_t *csr,
                                                  trecap_csr_replay_status_t *status_out);

trecap_csr_status_t trecap_csr_read_status_version(const trecap_csr_window_t *csr,
                                                   uint32_t *status_out,
                                                   uint32_t *version_out);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_CSR_MAP_H */
