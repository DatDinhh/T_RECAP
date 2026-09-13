/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS UDP sender API.
 * File class: [1] hand-written.
 *
 * This header owns the non-generated C API for the HPS telemetry UDP transmit
 * path. It intentionally does not define packet IDs, packet payload sizes,
 * command IDs, or header offsets. Those values come from generated/trecap_packet.h.
 */

#ifndef TRECAP_HPS_UDP_SENDER_H
#define TRECAP_HPS_UDP_SENDER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>

#include "generated/trecap_packet.h"
#include "trecap_hps_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum trecap_udp_status {
    TRECAP_UDP_OK = 0,
    TRECAP_UDP_DROPPED = 1,
    TRECAP_UDP_ERR_NULL = -1,
    TRECAP_UDP_ERR_BAD_ARG = -2,
    TRECAP_UDP_ERR_ADDRESS = -3,
    TRECAP_UDP_ERR_SOCKET = -4,
    TRECAP_UDP_ERR_CONFIG = -5,
    TRECAP_UDP_ERR_OVERSIZED = -6,
    TRECAP_UDP_ERR_WOULD_BLOCK = -7,
    TRECAP_UDP_ERR_TIMEOUT = -8,
    TRECAP_UDP_ERR_SEND = -9
} trecap_udp_status_t;

typedef struct trecap_udp_endpoint {
    char ip[TRECAP_HPS_IPV4_TEXT_MAX];
    uint16_t port;
    struct sockaddr_in addr;
    bool addr_valid;
} trecap_udp_endpoint_t;

typedef struct trecap_udp_sender_config {
    trecap_udp_endpoint_t destination;
    bool nonblocking;
    uint32_t send_timeout_ms;
    uint32_t max_datagram_bytes;
    bool drop_on_would_block;
} trecap_udp_sender_config_t;

typedef struct trecap_udp_sender_counters {
    uint64_t datagrams_attempted;
    uint64_t datagrams_sent;
    uint64_t datagrams_dropped;
    uint64_t send_error_count;
    uint64_t would_block_count;
    uint64_t timeout_count;
    uint64_t oversized_count;
    uint64_t bytes_sent;
} trecap_udp_sender_counters_t;

typedef struct trecap_udp_sender {
    int fd;
    trecap_udp_sender_config_t cfg;
    trecap_udp_sender_counters_t counters;
    int last_errno_value;
    bool open;
} trecap_udp_sender_t;

typedef struct trecap_udp_send_result {
    trecap_udp_status_t status;
    size_t datagram_bytes;
    ssize_t bytes_sent;
    int errno_value;
    bool consumed_record;
} trecap_udp_send_result_t;

static inline uint32_t trecap_udp_record_bytes_from_payload(uint32_t payload_bytes)
{
    return (uint32_t)TPKT_HEADER_BYTES + payload_bytes;
}

static inline bool trecap_udp_payload_bytes_can_send(uint32_t payload_bytes)
{
    return trecap_udp_record_bytes_from_payload(payload_bytes) <= (uint32_t)TPKT_UDP_MAX_BYTES;
}

static inline bool trecap_udp_datagram_bytes_can_send(size_t datagram_bytes)
{
    return datagram_bytes >= (size_t)TPKT_HEADER_BYTES &&
           datagram_bytes <= (size_t)TPKT_UDP_MAX_BYTES;
}

static inline trecap_udp_send_result_t trecap_udp_send_result_init(void)
{
    trecap_udp_send_result_t result;
    result.status = TRECAP_UDP_OK;
    result.datagram_bytes = 0u;
    result.bytes_sent = 0;
    result.errno_value = 0;
    result.consumed_record = false;
    return result;
}

const char *trecap_udp_status_string(trecap_udp_status_t status);

void trecap_udp_sender_config_set_defaults(trecap_udp_sender_config_t *cfg,
                                           const trecap_hps_runtime_config_t *runtime_cfg);

void trecap_udp_sender_counters_reset(trecap_udp_sender_counters_t *counters);

trecap_udp_status_t trecap_udp_endpoint_from_ipv4(const char *ip,
                                                  uint16_t port,
                                                  trecap_udp_endpoint_t *endpoint,
                                                  char *err_buf,
                                                  size_t err_buf_len);

trecap_udp_status_t trecap_udp_sender_open(const trecap_udp_sender_config_t *cfg,
                                           trecap_udp_sender_t *sender,
                                           char *err_buf,
                                           size_t err_buf_len);

void trecap_udp_sender_close(trecap_udp_sender_t *sender);

trecap_udp_status_t trecap_udp_sender_set_destination(trecap_udp_sender_t *sender,
                                                      const trecap_udp_endpoint_t *endpoint);

trecap_udp_status_t trecap_udp_sender_set_nonblocking(trecap_udp_sender_t *sender,
                                                      bool nonblocking);

trecap_udp_status_t trecap_udp_sender_set_timeout(trecap_udp_sender_t *sender,
                                                  uint32_t send_timeout_ms);

trecap_udp_send_result_t trecap_udp_sender_send_datagram(trecap_udp_sender_t *sender,
                                                         const void *datagram,
                                                         size_t datagram_bytes);

trecap_udp_send_result_t trecap_udp_sender_send_header_payload(trecap_udp_sender_t *sender,
                                                               const void *header,
                                                               const void *payload,
                                                               uint32_t payload_bytes);

trecap_udp_send_result_t trecap_udp_sender_send_record_bytes(trecap_udp_sender_t *sender,
                                                             const void *record_bytes,
                                                             uint32_t payload_bytes);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_UDP_SENDER_H */
