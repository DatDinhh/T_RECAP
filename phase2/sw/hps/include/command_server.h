/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS command-server API.
 * File class: [1] hand-written.
 *
 * This header owns the non-generated C API for receiving PC UDP commands,
 * validating them, enforcing the trusted-peer rule, and translating accepted
 * commands into CSR operations. It intentionally does not define command IDs,
 * packet wire offsets, CSR offsets, VERSION values, or packet-enable masks.
 * Those constants come from generated/trecap_packet.h and generated/trecap_csr.h.
 */

#ifndef TRECAP_HPS_COMMAND_SERVER_H
#define TRECAP_HPS_COMMAND_SERVER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>

#include "csr_map.h"
#include "generated/trecap_packet.h"
#include "trecap_hps_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum trecap_cmd_status {
    TRECAP_CMD_OK = 0,
    TRECAP_CMD_NO_PACKET = 1,
    TRECAP_CMD_PING = 2,
    TRECAP_CMD_REJECTED = 3,
    TRECAP_CMD_ERR_NULL = -1,
    TRECAP_CMD_ERR_BAD_ARG = -2,
    TRECAP_CMD_ERR_ADDRESS = -3,
    TRECAP_CMD_ERR_SOCKET = -4,
    TRECAP_CMD_ERR_BIND = -5,
    TRECAP_CMD_ERR_RECV = -6,
    TRECAP_CMD_ERR_WOULD_BLOCK = -7,
    TRECAP_CMD_ERR_TIMEOUT = -8,
    TRECAP_CMD_ERR_CSR = -9,
    TRECAP_CMD_ERR_SEND = -10
} trecap_cmd_status_t;

typedef enum trecap_cmd_reject_reason {
    TRECAP_CMD_REJECT_NONE = 0,
    TRECAP_CMD_REJECT_BAD_SOURCE = 1,
    TRECAP_CMD_REJECT_BAD_LENGTH = 2,
    TRECAP_CMD_REJECT_BAD_MAGIC = 3,
    TRECAP_CMD_REJECT_BAD_VERSION = 4,
    TRECAP_CMD_REJECT_BAD_CRC = 5,
    TRECAP_CMD_REJECT_UNSUPPORTED_TYPE = 6,
    TRECAP_CMD_REJECT_RANGE = 7,
    TRECAP_CMD_REJECT_RESERVED_ARGUMENT = 8,
    TRECAP_CMD_REJECT_CSR = 9,
    TRECAP_CMD_REJECT_IO = 10,
    TRECAP_CMD_REJECT_UNSAFE_STATE = 11,
    TRECAP_CMD_REJECT_SEQUENCE_STALE = 12,
    TRECAP_CMD_REJECT_SEQUENCE_CONFLICT = 13,
    TRECAP_CMD_REJECT_TIMEOUT = 14,
    TRECAP_CMD_REJECT_RESET_REQUIRED = 15,
    TRECAP_CMD_REJECT_VERSION_MISMATCH = 16
} trecap_cmd_reject_reason_t;

typedef enum trecap_cmd_disposition {
    TRECAP_CMD_DISPOSITION_APPLIED = 0,
    TRECAP_CMD_DISPOSITION_NOOP = 1,
    TRECAP_CMD_DISPOSITION_REJECTED = 2,
    TRECAP_CMD_DISPOSITION_FAILED = 3
} trecap_cmd_disposition_t;

typedef struct trecap_command_packet {
    uint32_t magic;
    uint16_t version;
    uint16_t cmd_type;
    uint32_t seq;
    uint32_t arg0;
    uint32_t arg1;
    uint32_t arg2;
    uint32_t crc32;
} trecap_command_packet_t;

typedef struct trecap_command_v2_result_packet {
    uint32_t magic;
    uint16_t version;
    uint16_t cmd_type;
    uint32_t seq;
    uint32_t disposition;
    uint32_t reject_reason;
    uint32_t fpga_status;
    uint32_t csr_version;
    uint32_t crc32;
} trecap_command_v2_result_packet_t;

/* Low-level receive seam. The production weak definition calls recvfrom(); the
 * deterministic host test supplies a strong in-memory flood source. */
ssize_t trecap_command_server_recvfrom(int fd,
                                       void *buf,
                                       size_t len,
                                       int flags,
                                       struct sockaddr *src_addr,
                                       socklen_t *addrlen);

/* Low-level response seam. Production calls sendto(); host tests replace this
 * weak symbol to assert byte-exact result routing without opening a socket. */
ssize_t trecap_command_server_sendto(int fd,
                                     const void *buf,
                                     size_t len,
                                     int flags,
                                     const struct sockaddr *dest_addr,
                                     socklen_t addrlen);

typedef struct trecap_command_peer {
    char ip[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t port;
    struct sockaddr_in addr;
    bool addr_valid;
} trecap_command_peer_t;

typedef struct trecap_command_server_config {
    uint16_t listen_port;
    char listen_ip[TRECAP_HPS_IPV4_TEXT_MAX];
    char trusted_peer_ip[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t trusted_peer_port;
    bool require_trusted_peer;
    bool learn_trusted_peer_on_valid_ping;
    /* Legacy knob retained for source compatibility; true is rejected. */
    bool accept_any_source_for_lab_debug;
    bool nonblocking;
    uint32_t recv_timeout_ms;
    uint32_t max_datagram_bytes;
} trecap_command_server_config_t;

typedef struct trecap_command_counters {
    uint64_t datagrams_received;
    uint64_t commands_accepted;
    uint64_t commands_applied;
    uint64_t ping_count;
    uint64_t hps_command_reject_count;
    uint64_t bad_source_count;
    uint64_t bad_length_count;
    uint64_t bad_magic_count;
    uint64_t bad_version_count;
    uint64_t bad_crc_count;
    uint64_t unsupported_type_count;
    uint64_t range_reject_count;
    uint64_t reserved_argument_count;
    uint64_t csr_reject_count;
    uint64_t recv_error_count;
    uint64_t unsafe_state_count;
    uint64_t stale_sequence_count;
    uint64_t sequence_conflict_count;
    uint64_t timeout_count;
    uint64_t reset_required_count;
    uint64_t version_mismatch_count;
} trecap_command_counters_t;

typedef struct trecap_command_result {
    trecap_cmd_status_t status;
    trecap_cmd_reject_reason_t reject_reason;
    uint16_t command_version;
    uint16_t cmd_type;
    uint32_t seq;
    bool accepted;
    bool applied;
    bool ping_requested;
    bool should_send_status;
    bool should_send_result;
    bool trusted_peer_learned;
    char source_ip[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t source_port;
    struct sockaddr_in source_addr;
    socklen_t source_addr_len;
    bool source_addr_valid;
    int errno_value;
    trecap_csr_status_t csr_status;
} trecap_command_result_t;

typedef struct trecap_command_server {
    int fd;
    trecap_command_server_config_t cfg;
    trecap_command_peer_t trusted_peer;
    trecap_command_counters_t counters;
    int last_errno_value;
    bool open;
    bool learned_peer;
} trecap_command_server_t;

static inline uint16_t trecap_cmd_load_le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8u));
}

static inline uint32_t trecap_cmd_load_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static inline void trecap_cmd_store_le16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value & UINT16_C(0x00ff));
    p[1] = (uint8_t)(value >> 8u);
}

static inline void trecap_cmd_store_le32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)(value & UINT32_C(0x000000ff));
    p[1] = (uint8_t)((value >> 8u) & UINT32_C(0x000000ff));
    p[2] = (uint8_t)((value >> 16u) & UINT32_C(0x000000ff));
    p[3] = (uint8_t)(value >> 24u);
}

static inline bool trecap_cmd_datagram_length_is_valid(size_t datagram_bytes)
{
    return datagram_bytes == (size_t)TCMD_PACKET_BYTES;
}

static inline bool trecap_cmd_type_is_known_v1(uint16_t cmd_type)
{
    return cmd_type == TCMD_TYPE_SET_THR2 || cmd_type == TCMD_TYPE_CLEAR_METRICS ||
           cmd_type == TCMD_TYPE_SET_SOURCE_MODE || cmd_type == TCMD_TYPE_SET_PACKET_ENABLE ||
           cmd_type == TCMD_TYPE_SET_WAVE_DECIM || cmd_type == TCMD_TYPE_SET_SPEC_SHIFT ||
           cmd_type == TCMD_TYPE_PING;
}

static inline bool trecap_cmd_type_is_known_v2(uint16_t cmd_type)
{
    return trecap_cmd_type_is_known_v1(cmd_type) || cmd_type == TCMD_TYPE_SET_SPEC_MODE ||
           cmd_type == TCMD_TYPE_SET_TELEMETRY_ENABLE ||
           cmd_type == TCMD_TYPE_CONFIGURE_DDR_RING ||
           cmd_type == TCMD_TYPE_RESET_TRANSPORT || cmd_type == TCMD_TYPE_CLEAR_COUNTERS ||
           cmd_type == TCMD_TYPE_START_BRAM_REPLAY ||
           cmd_type == TCMD_TYPE_READ_STATUS_VERSION;
}

static inline bool trecap_cmd_type_is_known_for_version(uint16_t version, uint16_t cmd_type)
{
    if (version == (uint16_t)TCMD_VERSION_V1) {
        return trecap_cmd_type_is_known_v1(cmd_type);
    }
    if (version == (uint16_t)TCMD_VERSION_V2) {
        return trecap_cmd_type_is_known_v2(cmd_type);
    }
    return false;
}

/* Backward-compatible helper: Revision-G v1 owns exactly seven command IDs. */
static inline bool trecap_cmd_type_is_known(uint16_t cmd_type)
{
    return trecap_cmd_type_is_known_v1(cmd_type);
}

static inline uint64_t trecap_cmd_thr2_from_args(uint32_t arg0, uint32_t arg1)
{
    return ((uint64_t)arg1 << 32u) | (uint64_t)arg0;
}

static inline bool trecap_cmd_args_reserved_zero(uint32_t arg1, uint32_t arg2)
{
    return arg1 == 0u && arg2 == 0u;
}

static inline bool trecap_cmd_thr2_args_are_valid(uint32_t arg0, uint32_t arg1, uint32_t arg2)
{
    (void)arg0;
    return arg2 == 0u && ((arg1 >> 24u) == 0u);
}

static inline bool trecap_cmd_clear_metrics_args_are_valid(uint32_t arg0,
                                                           uint32_t arg1,
                                                           uint32_t arg2)
{
    return arg0 == 0u && arg1 == 0u && arg2 == 0u;
}

static inline bool trecap_cmd_source_mode_args_are_valid(uint32_t arg0,
                                                         uint32_t arg1,
                                                         uint32_t arg2)
{
    return trecap_csr_source_mode_is_valid(arg0) && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_packet_enable_args_are_valid(uint32_t arg0,
                                                           uint32_t arg1,
                                                           uint32_t arg2)
{
    return trecap_csr_packet_enable_is_valid(arg0) && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_wave_decim_args_are_valid(uint32_t arg0,
                                                        uint32_t arg1,
                                                        uint32_t arg2)
{
    return trecap_csr_wave_decim_is_valid(arg0) && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_spec_shift_args_are_valid(uint32_t arg0,
                                                        uint32_t arg1,
                                                        uint32_t arg2)
{
    return trecap_csr_spec_shift_is_valid(arg0) && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_spec_mode_args_are_valid(uint32_t arg0,
                                                       uint32_t arg1,
                                                       uint32_t arg2)
{
    return trecap_csr_spec_mode_is_valid(arg0) && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_telemetry_enable_args_are_valid(uint32_t arg0,
                                                              uint32_t arg1,
                                                              uint32_t arg2)
{
    return arg0 <= 1u && trecap_cmd_args_reserved_zero(arg1, arg2);
}

static inline bool trecap_cmd_all_args_zero(uint32_t arg0, uint32_t arg1, uint32_t arg2)
{
    return arg0 == 0u && arg1 == 0u && arg2 == 0u;
}

static inline bool trecap_command_packet_equal(const trecap_command_packet_t *a,
                                               const trecap_command_packet_t *b)
{
    return a != NULL && b != NULL && a->magic == b->magic && a->version == b->version &&
           a->cmd_type == b->cmd_type && a->seq == b->seq && a->arg0 == b->arg0 &&
           a->arg1 == b->arg1 && a->arg2 == b->arg2 && a->crc32 == b->crc32;
}

static inline void trecap_command_result_init(trecap_command_result_t *result)
{
    if (result != NULL) {
        result->status = TRECAP_CMD_OK;
        result->reject_reason = TRECAP_CMD_REJECT_NONE;
        result->command_version = 0u;
        result->cmd_type = 0u;
        result->seq = 0u;
        result->accepted = false;
        result->applied = false;
        result->ping_requested = false;
        result->should_send_status = false;
        result->should_send_result = false;
        result->trusted_peer_learned = false;
        result->source_ip[0] = '\0';
        result->source_port = 0u;
        result->source_addr_len = 0u;
        result->source_addr_valid = false;
        result->source_addr.sin_family = AF_UNSPEC;
        result->errno_value = 0;
        result->csr_status = TRECAP_CSR_OK;
    }
}

static inline bool trecap_command_packet_parse(const void *datagram,
                                               size_t datagram_bytes,
                                               trecap_command_packet_t *cmd)
{
    if (datagram == NULL || cmd == NULL || !trecap_cmd_datagram_length_is_valid(datagram_bytes)) {
        return false;
    }
    const uint8_t *bytes = (const uint8_t *)datagram;
    cmd->magic = trecap_cmd_load_le32(&bytes[TCMD_MAGIC_OFFSET]);
    cmd->version = trecap_cmd_load_le16(&bytes[TCMD_VERSION_OFFSET]);
    cmd->cmd_type = trecap_cmd_load_le16(&bytes[TCMD_CMD_TYPE_OFFSET]);
    cmd->seq = trecap_cmd_load_le32(&bytes[TCMD_SEQ_OFFSET]);
    cmd->arg0 = trecap_cmd_load_le32(&bytes[TCMD_ARG0_OFFSET]);
    cmd->arg1 = trecap_cmd_load_le32(&bytes[TCMD_ARG1_OFFSET]);
    cmd->arg2 = trecap_cmd_load_le32(&bytes[TCMD_ARG2_OFFSET]);
    cmd->crc32 = trecap_cmd_load_le32(&bytes[TCMD_CRC32_OFFSET]);
    return true;
}

static inline trecap_cmd_reject_reason_t trecap_command_packet_validate_envelope(
    const trecap_command_packet_t *cmd)
{
    if (cmd == NULL) {
        return TRECAP_CMD_REJECT_IO;
    }
    if (cmd->magic != TCMD_COMMAND_MAGIC) {
        return TRECAP_CMD_REJECT_BAD_MAGIC;
    }
    if (cmd->version != (uint16_t)TCMD_VERSION_V1 &&
        cmd->version != (uint16_t)TCMD_VERSION_V2) {
        return TRECAP_CMD_REJECT_BAD_VERSION;
    }
    if (cmd->crc32 != 0u) {
        return TRECAP_CMD_REJECT_BAD_CRC;
    }
    if (!trecap_cmd_type_is_known_for_version(cmd->version, cmd->cmd_type)) {
        return TRECAP_CMD_REJECT_UNSUPPORTED_TYPE;
    }
    return TRECAP_CMD_REJECT_NONE;
}

static inline trecap_cmd_reject_reason_t trecap_command_packet_validate_args(
    const trecap_command_packet_t *cmd)
{
    if (cmd == NULL) {
        return TRECAP_CMD_REJECT_IO;
    }
    switch (cmd->cmd_type) {
    case TCMD_TYPE_SET_THR2:
        if (cmd->arg2 != 0u) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return ((cmd->arg1 >> 24u) == 0u) ? TRECAP_CMD_REJECT_NONE
                                          : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_CLEAR_METRICS:
        return trecap_cmd_clear_metrics_args_are_valid(cmd->arg0, cmd->arg1, cmd->arg2)
                   ? TRECAP_CMD_REJECT_NONE
                   : TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
    case TCMD_TYPE_SET_SOURCE_MODE:
        if (!trecap_cmd_args_reserved_zero(cmd->arg1, cmd->arg2)) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return trecap_csr_source_mode_is_valid(cmd->arg0) ? TRECAP_CMD_REJECT_NONE
                                                          : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_SET_PACKET_ENABLE:
        if (!trecap_cmd_args_reserved_zero(cmd->arg1, cmd->arg2)) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return trecap_csr_packet_enable_is_valid(cmd->arg0) ? TRECAP_CMD_REJECT_NONE
                                                            : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_SET_WAVE_DECIM:
        if (!trecap_cmd_args_reserved_zero(cmd->arg1, cmd->arg2)) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return trecap_csr_wave_decim_is_valid(cmd->arg0) ? TRECAP_CMD_REJECT_NONE
                                                         : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_SET_SPEC_SHIFT:
        if (!trecap_cmd_args_reserved_zero(cmd->arg1, cmd->arg2)) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return trecap_csr_spec_shift_is_valid(cmd->arg0) ? TRECAP_CMD_REJECT_NONE
                                                         : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_PING:
        return TRECAP_CMD_REJECT_NONE;
    case TCMD_TYPE_SET_SPEC_MODE:
        if (cmd->arg1 != 0u || cmd->arg2 != 0u) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return trecap_csr_spec_mode_is_valid(cmd->arg0) ? TRECAP_CMD_REJECT_NONE
                                                        : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_SET_TELEMETRY_ENABLE:
        if (cmd->arg1 != 0u || cmd->arg2 != 0u) {
            return TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
        }
        return cmd->arg0 <= 1u ? TRECAP_CMD_REJECT_NONE : TRECAP_CMD_REJECT_RANGE;
    case TCMD_TYPE_CONFIGURE_DDR_RING:
    case TCMD_TYPE_RESET_TRANSPORT:
    case TCMD_TYPE_CLEAR_COUNTERS:
    case TCMD_TYPE_START_BRAM_REPLAY:
    case TCMD_TYPE_READ_STATUS_VERSION:
        return trecap_cmd_all_args_zero(cmd->arg0, cmd->arg1, cmd->arg2)
                   ? TRECAP_CMD_REJECT_NONE
                   : TRECAP_CMD_REJECT_RESERVED_ARGUMENT;
    default:
        return TRECAP_CMD_REJECT_UNSUPPORTED_TYPE;
    }
}

static inline trecap_cmd_reject_reason_t trecap_command_packet_validate_fields(
    const trecap_command_packet_t *cmd)
{
    const trecap_cmd_reject_reason_t envelope_reason =
        trecap_command_packet_validate_envelope(cmd);
    return envelope_reason == TRECAP_CMD_REJECT_NONE
               ? trecap_command_packet_validate_args(cmd)
               : envelope_reason;
}

const char *trecap_cmd_status_string(trecap_cmd_status_t status);

const char *trecap_cmd_reject_reason_string(trecap_cmd_reject_reason_t reason);

void trecap_command_server_config_set_defaults(trecap_command_server_config_t *cfg,
                                               const trecap_hps_runtime_config_t *runtime_cfg);

void trecap_command_counters_reset(trecap_command_counters_t *counters);

trecap_cmd_status_t trecap_command_peer_from_ipv4(const char *ip,
                                                  uint16_t port,
                                                  trecap_command_peer_t *peer,
                                                  char *err_buf,
                                                  size_t err_buf_len);

trecap_cmd_status_t trecap_command_server_open(const trecap_command_server_config_t *cfg,
                                               trecap_command_server_t *server,
                                               char *err_buf,
                                               size_t err_buf_len);

void trecap_command_server_close(trecap_command_server_t *server);

trecap_cmd_status_t trecap_command_server_set_nonblocking(trecap_command_server_t *server,
                                                          bool nonblocking);

bool trecap_command_server_source_allowed(trecap_command_server_t *server,
                                          const struct sockaddr_in *source,
                                          const trecap_command_packet_t *cmd,
                                          trecap_command_result_t *result);

trecap_cmd_status_t trecap_command_server_recv(trecap_command_server_t *server,
                                               trecap_command_packet_t *cmd,
                                               trecap_command_result_t *result,
                                               char *err_buf,
                                               size_t err_buf_len);

trecap_cmd_status_t trecap_command_apply_to_csr(const trecap_command_packet_t *cmd,
                                                const trecap_csr_window_t *csr,
                                                trecap_command_result_t *result,
                                                char *err_buf,
                                                size_t err_buf_len);

trecap_cmd_status_t trecap_command_server_poll_apply(trecap_command_server_t *server,
                                                     const trecap_csr_window_t *csr,
                                                     trecap_command_result_t *result,
                                                     char *err_buf,
                                                     size_t err_buf_len);

void trecap_command_server_note_reject(trecap_command_server_t *server,
                                       trecap_cmd_reject_reason_t reason);

void trecap_command_v2_result_init(trecap_command_v2_result_packet_t *packet,
                                   uint16_t cmd_type,
                                   uint32_t seq,
                                   trecap_cmd_disposition_t disposition,
                                   trecap_cmd_reject_reason_t reject_reason,
                                   uint32_t fpga_status,
                                   uint32_t csr_version);

bool trecap_command_v2_result_encode(const trecap_command_v2_result_packet_t *packet,
                                     uint8_t *out,
                                     size_t out_bytes);

trecap_cmd_status_t trecap_command_server_send_v2_result(
    trecap_command_server_t *server,
    const trecap_command_v2_result_packet_t *packet,
    const struct sockaddr_in *destination,
    char *err_buf,
    size_t err_buf_len);

trecap_cmd_status_t trecap_command_server_send_peer_datagram(
    trecap_command_server_t *server,
    const void *datagram,
    size_t datagram_bytes,
    const struct sockaddr_in *destination,
    char *err_buf,
    size_t err_buf_len);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_COMMAND_SERVER_H */
