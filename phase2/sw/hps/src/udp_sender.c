/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS UDP sender implementation.
 * File class: [1] hand-written.
 *
 * This file owns bounded UDP transmission for HPS telemetry datagrams. It sends
 * exactly the telemetry header plus payload bytes supplied by the ring reader;
 * DDR padding bytes are never transmitted by this layer.
 */

#include "udp_sender.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <unistd.h>

#define TRECAP_UDP_DEFAULT_TIMEOUT_MS 10u

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

static void trecap_udp_set_error(char *err_buf, size_t err_buf_len, const char *fmt, ...)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }

    va_list ap;
    va_start(ap, fmt);
    (void)vsnprintf(err_buf, err_buf_len, fmt, ap);
    va_end(ap);
}

static size_t trecap_udp_strnlen_local(const char *s, size_t max_len)
{
    if (s == NULL) {
        return 0u;
    }
    size_t n = 0u;
    while (n < max_len && s[n] != '\0') {
        ++n;
    }
    return n;
}

static void trecap_udp_copy_ip(char *dst, size_t dst_len, const char *src)
{
    if (dst == NULL || dst_len == 0u) {
        return;
    }
    dst[0] = '\0';
    if (src == NULL) {
        return;
    }
    const size_t n = trecap_udp_strnlen_local(src, dst_len - 1u);
    memcpy(dst, src, n);
    dst[n] = '\0';
}

static bool trecap_udp_should_treat_as_would_block(int errno_value)
{
    return errno_value == EAGAIN || errno_value == EWOULDBLOCK;
}

static trecap_udp_send_result_t trecap_udp_finish_send_error(trecap_udp_sender_t *sender,
                                                             size_t datagram_bytes,
                                                             trecap_udp_status_t status,
                                                             int errno_value,
                                                             bool consumed_record)
{
    trecap_udp_send_result_t result = trecap_udp_send_result_init();
    result.status = status;
    result.datagram_bytes = datagram_bytes;
    result.bytes_sent = -1;
    result.errno_value = errno_value;
    result.consumed_record = consumed_record;

    if (sender != NULL) {
        sender->last_errno_value = errno_value;
        sender->counters.datagrams_dropped += 1u;
        if (status == TRECAP_UDP_ERR_OVERSIZED) {
            sender->counters.oversized_count += 1u;
        } else if (status == TRECAP_UDP_ERR_WOULD_BLOCK ||
                   (status == TRECAP_UDP_DROPPED && trecap_udp_should_treat_as_would_block(errno_value))) {
            sender->counters.would_block_count += 1u;
            sender->counters.send_error_count += 1u;
        } else if (status == TRECAP_UDP_ERR_TIMEOUT) {
            sender->counters.timeout_count += 1u;
            sender->counters.send_error_count += 1u;
        } else if (status == TRECAP_UDP_DROPPED || status == TRECAP_UDP_ERR_SEND ||
                   status == TRECAP_UDP_ERR_SOCKET) {
            sender->counters.send_error_count += 1u;
        }
    }
    return result;
}

static trecap_udp_send_result_t trecap_udp_finish_send_success(trecap_udp_sender_t *sender,
                                                               size_t datagram_bytes,
                                                               ssize_t bytes_sent)
{
    trecap_udp_send_result_t result = trecap_udp_send_result_init();
    result.status = TRECAP_UDP_OK;
    result.datagram_bytes = datagram_bytes;
    result.bytes_sent = bytes_sent;
    result.errno_value = 0;
    result.consumed_record = true;

    if (sender != NULL) {
        sender->last_errno_value = 0;
        sender->counters.datagrams_sent += 1u;
        sender->counters.bytes_sent += (uint64_t)datagram_bytes;
    }
    return result;
}

static trecap_udp_send_result_t trecap_udp_sendmsg_common(trecap_udp_sender_t *sender,
                                                          struct msghdr *msg,
                                                          size_t datagram_bytes)
{
    if (sender == NULL || msg == NULL) {
        return trecap_udp_finish_send_error(sender, datagram_bytes, TRECAP_UDP_ERR_NULL, 0, false);
    }
    if (!sender->open || sender->fd < 0 || !sender->cfg.destination.addr_valid) {
        return trecap_udp_finish_send_error(sender,
                                            datagram_bytes,
                                            TRECAP_UDP_ERR_CONFIG,
                                            0,
                                            false);
    }
    if (!trecap_udp_datagram_bytes_can_send(datagram_bytes) ||
        datagram_bytes > (size_t)sender->cfg.max_datagram_bytes) {
        return trecap_udp_finish_send_error(sender,
                                            datagram_bytes,
                                            TRECAP_UDP_ERR_OVERSIZED,
                                            0,
                                            true);
    }

    sender->counters.datagrams_attempted += 1u;
    errno = 0;
    const ssize_t sent = sendmsg(sender->fd, msg, MSG_NOSIGNAL);
    const int saved_errno = errno;
    if (sent < 0) {
        if (trecap_udp_should_treat_as_would_block(saved_errno)) {
            const bool timeout_style = !sender->cfg.nonblocking && sender->cfg.send_timeout_ms != 0u;
            const trecap_udp_status_t status = timeout_style
                                                   ? TRECAP_UDP_ERR_TIMEOUT
                                                   : (sender->cfg.drop_on_would_block
                                                          ? TRECAP_UDP_DROPPED
                                                          : TRECAP_UDP_ERR_WOULD_BLOCK);
            return trecap_udp_finish_send_error(sender, datagram_bytes, status, saved_errno, true);
        }
        return trecap_udp_finish_send_error(sender,
                                            datagram_bytes,
                                            TRECAP_UDP_DROPPED,
                                            saved_errno,
                                            true);
    }

    const size_t sent_size = (size_t)sent;
    if (sent_size != datagram_bytes) {
        return trecap_udp_finish_send_error(sender,
                                            datagram_bytes,
                                            TRECAP_UDP_ERR_SEND,
                                            0,
                                            true);
    }
    return trecap_udp_finish_send_success(sender, datagram_bytes, sent);
}

const char *trecap_udp_status_string(trecap_udp_status_t status)
{
    switch (status) {
    case TRECAP_UDP_OK:
        return "TRECAP_UDP_OK";
    case TRECAP_UDP_DROPPED:
        return "TRECAP_UDP_DROPPED";
    case TRECAP_UDP_ERR_NULL:
        return "TRECAP_UDP_ERR_NULL";
    case TRECAP_UDP_ERR_BAD_ARG:
        return "TRECAP_UDP_ERR_BAD_ARG";
    case TRECAP_UDP_ERR_ADDRESS:
        return "TRECAP_UDP_ERR_ADDRESS";
    case TRECAP_UDP_ERR_SOCKET:
        return "TRECAP_UDP_ERR_SOCKET";
    case TRECAP_UDP_ERR_CONFIG:
        return "TRECAP_UDP_ERR_CONFIG";
    case TRECAP_UDP_ERR_OVERSIZED:
        return "TRECAP_UDP_ERR_OVERSIZED";
    case TRECAP_UDP_ERR_WOULD_BLOCK:
        return "TRECAP_UDP_ERR_WOULD_BLOCK";
    case TRECAP_UDP_ERR_TIMEOUT:
        return "TRECAP_UDP_ERR_TIMEOUT";
    case TRECAP_UDP_ERR_SEND:
        return "TRECAP_UDP_ERR_SEND";
    default:
        return "TRECAP_UDP_ERR_UNKNOWN";
    }
}

void trecap_udp_sender_config_set_defaults(trecap_udp_sender_config_t *cfg,
                                           const trecap_hps_runtime_config_t *runtime_cfg)
{
    if (cfg == NULL) {
        return;
    }
    memset(cfg, 0, sizeof(*cfg));
    cfg->nonblocking = runtime_cfg == NULL ? true : runtime_cfg->use_nonblocking_udp;
    cfg->send_timeout_ms = TRECAP_UDP_DEFAULT_TIMEOUT_MS;
    cfg->max_datagram_bytes = (uint32_t)TPKT_UDP_MAX_BYTES;
    cfg->drop_on_would_block = true;

    if (runtime_cfg != NULL) {
        char err_buf[1];
        err_buf[0] = '\0';
        (void)trecap_udp_endpoint_from_ipv4(runtime_cfg->telemetry_dst_ip,
                                            runtime_cfg->telemetry_dst_port,
                                            &cfg->destination,
                                            err_buf,
                                            sizeof(err_buf));
    }
}

void trecap_udp_sender_counters_reset(trecap_udp_sender_counters_t *counters)
{
    if (counters != NULL) {
        memset(counters, 0, sizeof(*counters));
    }
}

trecap_udp_status_t trecap_udp_endpoint_from_ipv4(const char *ip,
                                                  uint16_t port,
                                                  trecap_udp_endpoint_t *endpoint,
                                                  char *err_buf,
                                                  size_t err_buf_len)
{
    if (ip == NULL || endpoint == NULL) {
        trecap_udp_set_error(err_buf, err_buf_len, "null endpoint argument");
        return TRECAP_UDP_ERR_NULL;
    }
    if (!trecap_hps_udp_port_is_valid(port)) {
        trecap_udp_set_error(err_buf, err_buf_len, "invalid UDP port: %u", (unsigned)port);
        return TRECAP_UDP_ERR_BAD_ARG;
    }

    memset(endpoint, 0, sizeof(*endpoint));
    endpoint->port = port;
    endpoint->addr.sin_family = AF_INET;
    endpoint->addr.sin_port = htons(port);
    const int ok = inet_pton(AF_INET, ip, &endpoint->addr.sin_addr);
    if (ok != 1) {
        trecap_udp_set_error(err_buf, err_buf_len, "invalid IPv4 address: %s", ip);
        return TRECAP_UDP_ERR_ADDRESS;
    }
    trecap_udp_copy_ip(endpoint->ip, sizeof(endpoint->ip), ip);
    endpoint->addr_valid = true;
    return TRECAP_UDP_OK;
}

trecap_udp_status_t trecap_udp_sender_set_nonblocking(trecap_udp_sender_t *sender,
                                                      bool nonblocking)
{
    if (sender == NULL || sender->fd < 0) {
        return TRECAP_UDP_ERR_NULL;
    }

    const int flags = fcntl(sender->fd, F_GETFL, 0);
    if (flags < 0) {
        sender->last_errno_value = errno;
        return TRECAP_UDP_ERR_SOCKET;
    }

    const int new_flags = nonblocking ? (flags | O_NONBLOCK) : (flags & ~O_NONBLOCK);
    if (fcntl(sender->fd, F_SETFL, new_flags) != 0) {
        sender->last_errno_value = errno;
        return TRECAP_UDP_ERR_SOCKET;
    }
    sender->cfg.nonblocking = nonblocking;
    return TRECAP_UDP_OK;
}

trecap_udp_status_t trecap_udp_sender_set_timeout(trecap_udp_sender_t *sender,
                                                  uint32_t send_timeout_ms)
{
    if (sender == NULL || sender->fd < 0) {
        return TRECAP_UDP_ERR_NULL;
    }

    struct timeval tv;
    tv.tv_sec = (time_t)(send_timeout_ms / 1000u);
    tv.tv_usec = (suseconds_t)((send_timeout_ms % 1000u) * 1000u);
    if (setsockopt(sender->fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)) != 0) {
        sender->last_errno_value = errno;
        return TRECAP_UDP_ERR_SOCKET;
    }
    sender->cfg.send_timeout_ms = send_timeout_ms;
    return TRECAP_UDP_OK;
}

trecap_udp_status_t trecap_udp_sender_open(const trecap_udp_sender_config_t *cfg,
                                           trecap_udp_sender_t *sender,
                                           char *err_buf,
                                           size_t err_buf_len)
{
    if (cfg == NULL || sender == NULL) {
        trecap_udp_set_error(err_buf, err_buf_len, "null sender argument");
        return TRECAP_UDP_ERR_NULL;
    }
    if (!cfg->destination.addr_valid || cfg->max_datagram_bytes < (uint32_t)TPKT_HEADER_BYTES ||
        cfg->max_datagram_bytes > (uint32_t)TPKT_UDP_MAX_BYTES) {
        trecap_udp_set_error(err_buf, err_buf_len, "invalid UDP sender config");
        return TRECAP_UDP_ERR_CONFIG;
    }

    memset(sender, 0, sizeof(*sender));
    sender->fd = -1;
    sender->cfg = *cfg;

    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        sender->last_errno_value = errno;
        trecap_udp_set_error(err_buf, err_buf_len, "socket() failed: %s", strerror(errno));
        return TRECAP_UDP_ERR_SOCKET;
    }

    const int fd_flags = fcntl(fd, F_GETFD, 0);
    if (fd_flags >= 0) {
        (void)fcntl(fd, F_SETFD, fd_flags | FD_CLOEXEC);
    }

    sender->fd = fd;
    sender->open = true;

    trecap_udp_status_t status = trecap_udp_sender_set_destination(sender, &cfg->destination);
    if (status != TRECAP_UDP_OK) {
        trecap_udp_sender_close(sender);
        trecap_udp_set_error(err_buf, err_buf_len, "failed to set UDP destination");
        return status;
    }
    status = trecap_udp_sender_set_timeout(sender, cfg->send_timeout_ms);
    if (status != TRECAP_UDP_OK) {
        trecap_udp_sender_close(sender);
        trecap_udp_set_error(err_buf, err_buf_len, "failed to set UDP send timeout");
        return status;
    }
    status = trecap_udp_sender_set_nonblocking(sender, cfg->nonblocking);
    if (status != TRECAP_UDP_OK) {
        trecap_udp_sender_close(sender);
        trecap_udp_set_error(err_buf, err_buf_len, "failed to set nonblocking mode");
        return status;
    }

    return TRECAP_UDP_OK;
}

void trecap_udp_sender_close(trecap_udp_sender_t *sender)
{
    if (sender == NULL) {
        return;
    }
    if (sender->fd >= 0) {
        (void)close(sender->fd);
    }
    sender->fd = -1;
    sender->open = false;
}

trecap_udp_status_t trecap_udp_sender_set_destination(trecap_udp_sender_t *sender,
                                                      const trecap_udp_endpoint_t *endpoint)
{
    if (sender == NULL || endpoint == NULL) {
        return TRECAP_UDP_ERR_NULL;
    }
    if (!endpoint->addr_valid || !trecap_hps_udp_port_is_valid(endpoint->port)) {
        return TRECAP_UDP_ERR_ADDRESS;
    }
    sender->cfg.destination = *endpoint;
    return TRECAP_UDP_OK;
}

trecap_udp_send_result_t trecap_udp_sender_send_datagram(trecap_udp_sender_t *sender,
                                                         const void *datagram,
                                                         size_t datagram_bytes)
{
    if (sender == NULL || datagram == NULL) {
        return trecap_udp_finish_send_error(sender, datagram_bytes, TRECAP_UDP_ERR_NULL, 0, false);
    }

    struct iovec iov;
    iov.iov_base = (void *)(uintptr_t)datagram;
    iov.iov_len = datagram_bytes;

    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));
    msg.msg_name = &sender->cfg.destination.addr;
    msg.msg_namelen = sizeof(sender->cfg.destination.addr);
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1u;
    return trecap_udp_sendmsg_common(sender, &msg, datagram_bytes);
}

trecap_udp_send_result_t trecap_udp_sender_send_header_payload(trecap_udp_sender_t *sender,
                                                               const void *header,
                                                               const void *payload,
                                                               uint32_t payload_bytes)
{
    if (sender == NULL || header == NULL || (payload == NULL && payload_bytes != 0u)) {
        return trecap_udp_finish_send_error(sender,
                                            trecap_udp_record_bytes_from_payload(payload_bytes),
                                            TRECAP_UDP_ERR_NULL,
                                            0,
                                            false);
    }

    const size_t datagram_bytes = (size_t)trecap_udp_record_bytes_from_payload(payload_bytes);
    struct iovec iov[2];
    iov[0].iov_base = (void *)(uintptr_t)header;
    iov[0].iov_len = (size_t)TPKT_HEADER_BYTES;
    iov[1].iov_base = (void *)(uintptr_t)payload;
    iov[1].iov_len = (size_t)payload_bytes;

    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));
    msg.msg_name = &sender->cfg.destination.addr;
    msg.msg_namelen = sizeof(sender->cfg.destination.addr);
    msg.msg_iov = iov;
    msg.msg_iovlen = payload_bytes == 0u ? 1u : 2u;
    return trecap_udp_sendmsg_common(sender, &msg, datagram_bytes);
}

trecap_udp_send_result_t trecap_udp_sender_send_record_bytes(trecap_udp_sender_t *sender,
                                                             const void *record_bytes,
                                                             uint32_t payload_bytes)
{
    if (record_bytes == NULL) {
        return trecap_udp_finish_send_error(sender,
                                            trecap_udp_record_bytes_from_payload(payload_bytes),
                                            TRECAP_UDP_ERR_NULL,
                                            0,
                                            false);
    }
    const size_t datagram_bytes = (size_t)trecap_udp_record_bytes_from_payload(payload_bytes);
    return trecap_udp_sender_send_datagram(sender, record_bytes, datagram_bytes);
}
