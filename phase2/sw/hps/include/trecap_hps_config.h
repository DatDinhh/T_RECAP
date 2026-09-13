/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS runtime configuration API.
 * File class: [1] hand-written.
 *
 * This header owns the non-generated C view of sw/hps/config/trecap_hps_config.json.
 * It intentionally does not define CSR offsets, packet IDs, packet payload sizes, or
 * transport version constants. Those values come from generated/trecap_csr.h and
 * generated/trecap_packet.h.
 */

#ifndef TRECAP_HPS_CONFIG_H
#define TRECAP_HPS_CONFIG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "generated/trecap_csr.h"
#include "generated/trecap_packet.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef TRECAP_HPS_DEFAULT_CONFIG
#define TRECAP_HPS_DEFAULT_CONFIG "sw/hps/config/trecap_hps_config.json"
#endif

#define TRECAP_HPS_CONFIG_SCHEMA "trecap_phase2_hps_runtime_config_v1"
#define TRECAP_HPS_PROJECT_NAME "T_RECAP_Phase2"
#define TRECAP_HPS_BOARD_DE1SOC "de1soc"
#define TRECAP_HPS_IPV4_TEXT_MAX 48u
#define TRECAP_HPS_PATH_TEXT_MAX 256u
#define TRECAP_HPS_DE1SOC_RING_HPS_BASE UINT64_C(0x000000003e000000)
#define TRECAP_HPS_DE1SOC_RING_FPGA_BASE UINT64_C(0x000000003e000000)
#define TRECAP_HPS_DE1SOC_RING_SIZE_BYTES UINT32_C(0x02000000)
#define TRECAP_HPS_DE1SOC_CSR_BASE UINT64_C(0x00000000ff200000)
#define TRECAP_HPS_DE1SOC_CSR_SPAN_BYTES UINT32_C(4096)
#define TRECAP_HPS_DE1SOC_LIVE_DT_NODE \
    "/sys/firmware/devicetree/base/reserved-memory/trecap-ring@3e000000"

typedef enum trecap_hps_config_status {
    TRECAP_HPS_CONFIG_OK = 0,
    TRECAP_HPS_CONFIG_ERR_NULL = -1,
    TRECAP_HPS_CONFIG_ERR_IO = -2,
    TRECAP_HPS_CONFIG_ERR_PARSE = -3,
    TRECAP_HPS_CONFIG_ERR_MISSING_FIELD = -4,
    TRECAP_HPS_CONFIG_ERR_BAD_VALUE = -5,
    TRECAP_HPS_CONFIG_ERR_VERSION = -6,
    TRECAP_HPS_CONFIG_ERR_TRUNCATED = -7
} trecap_hps_config_status_t;

typedef struct trecap_hps_runtime_config {
    uint64_t csr_base_phys;
    uint32_t csr_span_bytes;

    uint64_t ring_base_hps_phys;
    uint64_t ring_base_fpga;
    uint32_t ring_size_bytes;
    uint32_t ring_guard_bytes;

    char telemetry_dst_ip[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t telemetry_dst_port;
    uint16_t command_listen_port;
    char trusted_command_peer[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t trusted_command_peer_port;
    char hps_static_ip[TRECAP_HPS_IPV4_TEXT_MAX];
    char netmask[TRECAP_HPS_IPV4_TEXT_MAX];

    uint16_t transport_version_major;
    uint16_t transport_version_minor;

    bool require_trusted_peer;
    bool use_nonblocking_udp;
    /* Legacy config field retained only so true can be rejected explicitly. */
    bool allow_cached_ring_mapping;
    bool stop_on_malformed_record;
} trecap_hps_runtime_config_t;

static inline uint32_t trecap_hps_expected_transport_version(void)
{
    return TCSR_VERSION_VALUE;
}

static inline bool trecap_hps_versions_match(uint16_t major, uint16_t minor)
{
    return major == (uint16_t)TPKT_TRANSPORT_VERSION_MAJOR &&
           minor == (uint16_t)TPKT_TRANSPORT_VERSION_MINOR &&
           major == (uint16_t)TCSR_VERSION_MAJOR &&
           minor == (uint16_t)TCSR_VERSION_MINOR;
}

static inline bool trecap_hps_is_power_of_two_u32(uint32_t value)
{
    return value != 0u && (value & (value - 1u)) == 0u;
}

static inline bool trecap_hps_is_aligned_u64(uint64_t value, uint64_t alignment)
{
    return alignment != 0u && (value % alignment) == 0u;
}

static inline bool trecap_hps_ring_size_is_valid(uint32_t ring_size_bytes)
{
    return ring_size_bytes >= UINT32_C(1048576) &&
           trecap_hps_is_power_of_two_u32(ring_size_bytes) &&
           (ring_size_bytes % TCSR_RING_ALIGNMENT_BYTES) == 0u;
}

static inline bool trecap_hps_ring_base_is_valid(uint64_t ring_base)
{
    return trecap_hps_is_aligned_u64(ring_base, (uint64_t)TCSR_RING_ALIGNMENT_BYTES);
}

static inline bool trecap_hps_udp_port_is_valid(uint16_t port)
{
    return port != 0u;
}

void trecap_hps_config_set_defaults(trecap_hps_runtime_config_t *cfg);

trecap_hps_config_status_t trecap_hps_config_load_file(
    const char *path,
    trecap_hps_runtime_config_t *cfg,
    char *err_buf,
    size_t err_buf_len);

trecap_hps_config_status_t trecap_hps_config_validate(
    const trecap_hps_runtime_config_t *cfg,
    char *err_buf,
    size_t err_buf_len);

trecap_hps_config_status_t trecap_hps_config_validate_live_ddr_reservation(
    const trecap_hps_runtime_config_t *cfg,
    char *err_buf,
    size_t err_buf_len);

const char *trecap_hps_config_status_string(trecap_hps_config_status_t status);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_CONFIG_H */
