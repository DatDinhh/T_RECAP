/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS command-server implementation.
 * File class: [1] hand-written.
 *
 * This file owns the HPS userspace PC-command receive path. It validates the
 * Revision G command packet, enforces the trusted-peer rule, and translates
 * accepted commands into generated CSR API calls. It does not duplicate command
 * IDs, CSR offsets, packet offsets, payload sizes, or transport-version values.
 */

#include "command_server.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak))
#endif
ssize_t trecap_command_server_recvfrom(int fd,
                                       void *buf,
                                       size_t len,
                                       int flags,
                                       struct sockaddr *src_addr,
                                       socklen_t *addrlen)
{
    return recvfrom(fd, buf, len, flags, src_addr, addrlen);
}

#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak))
#endif
ssize_t trecap_command_server_sendto(int fd,
                                     const void *buf,
                                     size_t len,
                                     int flags,
                                     const struct sockaddr *dest_addr,
                                     socklen_t addrlen)
{
    return sendto(fd, buf, len, flags, dest_addr, addrlen);
}

static void trecap_cmd_set_error(char *err_buf, size_t err_buf_len, const char *message)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }
    if (message == NULL) {
        message = "";
    }
    (void)snprintf(err_buf, err_buf_len, "%s", message);
    err_buf[err_buf_len - 1u] = '\0';
}

static void trecap_cmd_copy_text(char *dst, size_t dst_len, const char *src)
{
    if (dst == NULL || dst_len == 0u) {
        return;
    }
    if (src == NULL) {
        src = "";
    }
    (void)snprintf(dst, dst_len, "%s", src);
    dst[dst_len - 1u] = '\0';
}

static bool trecap_cmd_sockaddr_same_ipv4(const struct sockaddr_in *a,
                                          const struct sockaddr_in *b,
                                          bool compare_port)
{
    if (a == NULL || b == NULL) {
        return false;
    }
    if (a->sin_family != AF_INET || b->sin_family != AF_INET) {
        return false;
    }
    if (a->sin_addr.s_addr != b->sin_addr.s_addr) {
        return false;
    }
    if (compare_port && a->sin_port != b->sin_port) {
        return false;
    }
    return true;
}

static void trecap_cmd_result_set_source(trecap_command_result_t *result,
                                         const struct sockaddr_in *source)
{
    if (result == NULL || source == NULL) {
        return;
    }
    const char *converted = inet_ntop(AF_INET,
                                      (const void *)&source->sin_addr,
                                      result->source_ip,
                                      (socklen_t)sizeof(result->source_ip));
    if (converted == NULL) {
        result->source_ip[0] = '\0';
    }
    result->source_port = ntohs(source->sin_port);
    result->source_addr = *source;
    result->source_addr_len = (socklen_t)sizeof(*source);
    result->source_addr_valid = source->sin_family == AF_INET && source->sin_port != 0u;
}

static void trecap_cmd_result_set_reject(trecap_command_result_t *result,
                                         trecap_cmd_reject_reason_t reason)
{
    if (result == NULL) {
        return;
    }
    result->status = TRECAP_CMD_REJECTED;
    result->reject_reason = reason;
    result->accepted = false;
    result->applied = false;
}

static trecap_cmd_status_t trecap_cmd_set_recv_timeout(trecap_command_server_t *server,
                                                       uint32_t timeout_ms)
{
    if (server == NULL || server->fd < 0) {
        return TRECAP_CMD_ERR_NULL;
    }
    struct timeval timeout;
    timeout.tv_sec = (time_t)(timeout_ms / 1000u);
    timeout.tv_usec = (suseconds_t)((timeout_ms % 1000u) * 1000u);
    if (setsockopt(server->fd,
                   SOL_SOCKET,
                   SO_RCVTIMEO,
                   &timeout,
                   (socklen_t)sizeof(timeout)) != 0) {
        server->last_errno_value = errno;
        return TRECAP_CMD_ERR_SOCKET;
    }
    server->cfg.recv_timeout_ms = timeout_ms;
    return TRECAP_CMD_OK;
}

static void trecap_command_server_count_accept(trecap_command_server_t *server,
                                               const trecap_command_packet_t *cmd)
{
    if (server == NULL || cmd == NULL) {
        return;
    }
    server->counters.commands_accepted += 1u;
    if (cmd->cmd_type == TCMD_TYPE_PING) {
        server->counters.ping_count += 1u;
    }
}

const char *trecap_cmd_status_string(trecap_cmd_status_t status)
{
    switch (status) {
    case TRECAP_CMD_OK:
        return "TRECAP_CMD_OK";
    case TRECAP_CMD_NO_PACKET:
        return "TRECAP_CMD_NO_PACKET";
    case TRECAP_CMD_PING:
        return "TRECAP_CMD_PING";
    case TRECAP_CMD_REJECTED:
        return "TRECAP_CMD_REJECTED";
    case TRECAP_CMD_ERR_NULL:
        return "TRECAP_CMD_ERR_NULL";
    case TRECAP_CMD_ERR_BAD_ARG:
        return "TRECAP_CMD_ERR_BAD_ARG";
    case TRECAP_CMD_ERR_ADDRESS:
        return "TRECAP_CMD_ERR_ADDRESS";
    case TRECAP_CMD_ERR_SOCKET:
        return "TRECAP_CMD_ERR_SOCKET";
    case TRECAP_CMD_ERR_BIND:
        return "TRECAP_CMD_ERR_BIND";
    case TRECAP_CMD_ERR_RECV:
        return "TRECAP_CMD_ERR_RECV";
    case TRECAP_CMD_ERR_WOULD_BLOCK:
        return "TRECAP_CMD_ERR_WOULD_BLOCK";
    case TRECAP_CMD_ERR_TIMEOUT:
        return "TRECAP_CMD_ERR_TIMEOUT";
    case TRECAP_CMD_ERR_CSR:
        return "TRECAP_CMD_ERR_CSR";
    case TRECAP_CMD_ERR_SEND:
        return "TRECAP_CMD_ERR_SEND";
    default:
        return "TRECAP_CMD_ERR_UNKNOWN";
    }
}

const char *trecap_cmd_reject_reason_string(trecap_cmd_reject_reason_t reason)
{
    switch (reason) {
    case TRECAP_CMD_REJECT_NONE:
        return "TRECAP_CMD_REJECT_NONE";
    case TRECAP_CMD_REJECT_BAD_SOURCE:
        return "TRECAP_CMD_REJECT_BAD_SOURCE";
    case TRECAP_CMD_REJECT_BAD_LENGTH:
        return "TRECAP_CMD_REJECT_BAD_LENGTH";
    case TRECAP_CMD_REJECT_BAD_MAGIC:
        return "TRECAP_CMD_REJECT_BAD_MAGIC";
    case TRECAP_CMD_REJECT_BAD_VERSION:
        return "TRECAP_CMD_REJECT_BAD_VERSION";
    case TRECAP_CMD_REJECT_BAD_CRC:
        return "TRECAP_CMD_REJECT_BAD_CRC";
    case TRECAP_CMD_REJECT_UNSUPPORTED_TYPE:
        return "TRECAP_CMD_REJECT_UNSUPPORTED_TYPE";
    case TRECAP_CMD_REJECT_RANGE:
        return "TRECAP_CMD_REJECT_RANGE";
    case TRECAP_CMD_REJECT_RESERVED_ARGUMENT:
        return "TRECAP_CMD_REJECT_RESERVED_ARGUMENT";
    case TRECAP_CMD_REJECT_CSR:
        return "TRECAP_CMD_REJECT_CSR";
    case TRECAP_CMD_REJECT_IO:
        return "TRECAP_CMD_REJECT_IO";
    case TRECAP_CMD_REJECT_UNSAFE_STATE:
        return "TRECAP_CMD_REJECT_UNSAFE_STATE";
    case TRECAP_CMD_REJECT_SEQUENCE_STALE:
        return "TRECAP_CMD_REJECT_SEQUENCE_STALE";
    case TRECAP_CMD_REJECT_SEQUENCE_CONFLICT:
        return "TRECAP_CMD_REJECT_SEQUENCE_CONFLICT";
    case TRECAP_CMD_REJECT_TIMEOUT:
        return "TRECAP_CMD_REJECT_TIMEOUT";
    case TRECAP_CMD_REJECT_RESET_REQUIRED:
        return "TRECAP_CMD_REJECT_RESET_REQUIRED";
    case TRECAP_CMD_REJECT_VERSION_MISMATCH:
        return "TRECAP_CMD_REJECT_VERSION_MISMATCH";
    default:
        return "TRECAP_CMD_REJECT_UNKNOWN";
    }
}

void trecap_command_server_config_set_defaults(trecap_command_server_config_t *cfg,
                                               const trecap_hps_runtime_config_t *runtime_cfg)
{
    if (cfg == NULL) {
        return;
    }
    memset(cfg, 0, sizeof(*cfg));
    cfg->listen_port = 5006u;
    trecap_cmd_copy_text(cfg->listen_ip, sizeof(cfg->listen_ip), "192.168.10.2");
    trecap_cmd_copy_text(cfg->trusted_peer_ip,
                         sizeof(cfg->trusted_peer_ip),
                         "192.168.10.1");
    cfg->trusted_peer_port = 5007u;
    cfg->require_trusted_peer = true;
    cfg->learn_trusted_peer_on_valid_ping = false;
    cfg->accept_any_source_for_lab_debug = false;
    cfg->nonblocking = true;
    cfg->recv_timeout_ms = 0u;
    cfg->max_datagram_bytes = (uint32_t)TCMD_PACKET_BYTES;

    if (runtime_cfg != NULL) {
        cfg->listen_port = runtime_cfg->command_listen_port;
        trecap_cmd_copy_text(cfg->listen_ip,
                             sizeof(cfg->listen_ip),
                             runtime_cfg->hps_static_ip);
        cfg->require_trusted_peer = runtime_cfg->require_trusted_peer;
        cfg->nonblocking = runtime_cfg->use_nonblocking_udp;
        trecap_cmd_copy_text(cfg->trusted_peer_ip,
                             sizeof(cfg->trusted_peer_ip),
                             runtime_cfg->trusted_command_peer);
        cfg->trusted_peer_port = runtime_cfg->trusted_command_peer_port;
        cfg->learn_trusted_peer_on_valid_ping = false;
    }
}

void trecap_command_counters_reset(trecap_command_counters_t *counters)
{
    if (counters != NULL) {
        memset(counters, 0, sizeof(*counters));
    }
}

trecap_cmd_status_t trecap_command_peer_from_ipv4(const char *ip,
                                                  uint16_t port,
                                                  trecap_command_peer_t *peer,
                                                  char *err_buf,
                                                  size_t err_buf_len)
{
    if (ip == NULL || peer == NULL || ip[0] == '\0') {
        trecap_cmd_set_error(err_buf, err_buf_len, "null or empty command peer IPv4 address");
        return TRECAP_CMD_ERR_BAD_ARG;
    }
    memset(peer, 0, sizeof(*peer));
    trecap_cmd_copy_text(peer->ip, sizeof(peer->ip), ip);
    peer->port = port;
    memset(&peer->addr, 0, sizeof(peer->addr));
    peer->addr.sin_family = AF_INET;
    peer->addr.sin_port = htons(port);
    if (inet_pton(AF_INET, peer->ip, &peer->addr.sin_addr) != 1) {
        trecap_cmd_set_error(err_buf, err_buf_len, "invalid command peer IPv4 address");
        return TRECAP_CMD_ERR_ADDRESS;
    }
    peer->addr_valid = true;
    return TRECAP_CMD_OK;
}

trecap_cmd_status_t trecap_command_server_set_nonblocking(trecap_command_server_t *server,
                                                          bool nonblocking)
{
    if (server == NULL || server->fd < 0) {
        return TRECAP_CMD_ERR_NULL;
    }
    int flags = fcntl(server->fd, F_GETFL, 0);
    if (flags < 0) {
        server->last_errno_value = errno;
        return TRECAP_CMD_ERR_SOCKET;
    }
    if (nonblocking) {
        flags |= O_NONBLOCK;
    } else {
        flags &= ~O_NONBLOCK;
    }
    if (fcntl(server->fd, F_SETFL, flags) != 0) {
        server->last_errno_value = errno;
        return TRECAP_CMD_ERR_SOCKET;
    }
    server->cfg.nonblocking = nonblocking;
    return TRECAP_CMD_OK;
}

trecap_cmd_status_t trecap_command_server_open(const trecap_command_server_config_t *cfg,
                                               trecap_command_server_t *server,
                                               char *err_buf,
                                               size_t err_buf_len)
{
    if (cfg == NULL || server == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null command-server config");
        return TRECAP_CMD_ERR_NULL;
    }
    const bool configured_exact_peer = cfg->trusted_peer_ip[0] != '\0' &&
                                       cfg->trusted_peer_port != 0u &&
                                       !cfg->learn_trusted_peer_on_valid_ping;
    const bool explicit_unbound_learning = cfg->trusted_peer_ip[0] == '\0' &&
                                           cfg->trusted_peer_port == 0u &&
                                           cfg->learn_trusted_peer_on_valid_ping;
    if (cfg->listen_port == 0u || cfg->listen_ip[0] == '\0' ||
        cfg->max_datagram_bytes < (uint32_t)TCMD_PACKET_BYTES ||
        !cfg->require_trusted_peer || cfg->accept_any_source_for_lab_debug ||
        (!configured_exact_peer && !explicit_unbound_learning)) {
        trecap_cmd_set_error(err_buf, err_buf_len, "invalid command-server config");
        return TRECAP_CMD_ERR_BAD_ARG;
    }

    memset(server, 0, sizeof(*server));
    server->fd = -1;
    server->cfg = *cfg;
    trecap_command_counters_reset(&server->counters);

    if (cfg->trusted_peer_ip[0] != '\0') {
        trecap_cmd_status_t peer_status = trecap_command_peer_from_ipv4(cfg->trusted_peer_ip,
                                                                        cfg->trusted_peer_port,
                                                                        &server->trusted_peer,
                                                                        err_buf,
                                                                        err_buf_len);
        if (peer_status != TRECAP_CMD_OK) {
            return peer_status;
        }
    }

    const int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        server->last_errno_value = errno;
        trecap_cmd_set_error(err_buf, err_buf_len, "socket(AF_INET, SOCK_DGRAM) failed");
        return TRECAP_CMD_ERR_SOCKET;
    }
    server->fd = fd;

    const int reuse = 1;
    (void)setsockopt(server->fd, SOL_SOCKET, SO_REUSEADDR, &reuse, (socklen_t)sizeof(reuse));

    struct sockaddr_in bind_addr;
    memset(&bind_addr, 0, sizeof(bind_addr));
    bind_addr.sin_family = AF_INET;
    bind_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    if (cfg->listen_ip[0] != '\0' &&
        inet_pton(AF_INET, cfg->listen_ip, &bind_addr.sin_addr) != 1) {
        trecap_cmd_set_error(err_buf, err_buf_len, "invalid command listen IPv4 address");
        trecap_command_server_close(server);
        return TRECAP_CMD_ERR_ADDRESS;
    }
    bind_addr.sin_port = htons(cfg->listen_port);
    if (bind(server->fd,
             (const struct sockaddr *)(const void *)&bind_addr,
             (socklen_t)sizeof(bind_addr)) != 0) {
        server->last_errno_value = errno;
        trecap_cmd_set_error(err_buf, err_buf_len, "bind(command UDP socket) failed");
        trecap_command_server_close(server);
        return TRECAP_CMD_ERR_BIND;
    }

    trecap_cmd_status_t status = trecap_command_server_set_nonblocking(server, cfg->nonblocking);
    if (status != TRECAP_CMD_OK) {
        trecap_cmd_set_error(err_buf, err_buf_len, "failed to set command socket nonblocking mode");
        trecap_command_server_close(server);
        return status;
    }
    status = trecap_cmd_set_recv_timeout(server, cfg->recv_timeout_ms);
    if (status != TRECAP_CMD_OK) {
        trecap_cmd_set_error(err_buf, err_buf_len, "failed to set command socket receive timeout");
        trecap_command_server_close(server);
        return status;
    }

    server->open = true;
    server->learned_peer = false;
    return TRECAP_CMD_OK;
}

void trecap_command_server_close(trecap_command_server_t *server)
{
    if (server == NULL) {
        return;
    }
    if (server->fd >= 0) {
        (void)close(server->fd);
    }
    server->fd = -1;
    server->open = false;
}

bool trecap_command_server_source_allowed(trecap_command_server_t *server,
                                          const struct sockaddr_in *source,
                                          const trecap_command_packet_t *cmd,
                                          trecap_command_result_t *result)
{
    if (server == NULL || source == NULL || source->sin_family != AF_INET ||
        source->sin_port == 0u) {
        trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
        return false;
    }
    trecap_cmd_result_set_source(result, source);

    if (server->trusted_peer.addr_valid) {
        const bool same_ip = trecap_cmd_sockaddr_same_ipv4(source,
                                                          &server->trusted_peer.addr,
                                                          false);
        if (!same_ip) {
            trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
            return false;
        }
        if (server->trusted_peer.port != 0u) {
            const bool same_endpoint = trecap_cmd_sockaddr_same_ipv4(source,
                                                                    &server->trusted_peer.addr,
                                                                    true);
            if (!same_endpoint) {
                trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
            }
            return same_endpoint;
        }
        if (!server->cfg.learn_trusted_peer_on_valid_ping || cmd == NULL ||
            cmd->cmd_type != TCMD_TYPE_PING) {
            trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
            return false;
        }
        server->trusted_peer.port = ntohs(source->sin_port);
        server->trusted_peer.addr.sin_port = source->sin_port;
        server->learned_peer = true;
        if (result != NULL) {
            result->trusted_peer_learned = true;
        }
        return true;
    }
    if (server->cfg.learn_trusted_peer_on_valid_ping && cmd != NULL &&
        cmd->cmd_type == TCMD_TYPE_PING) {
        char source_ip[TRECAP_HPS_IPV4_TEXT_MAX];
        source_ip[0] = '\0';
        const char *converted = inet_ntop(AF_INET,
                                          (const void *)&source->sin_addr,
                                          source_ip,
                                          (socklen_t)sizeof(source_ip));
        if (converted == NULL) {
            trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
            return false;
        }
        trecap_cmd_status_t peer_status = trecap_command_peer_from_ipv4(source_ip,
                                                                        ntohs(source->sin_port),
                                                                        &server->trusted_peer,
                                                                        NULL,
                                                                        0u);
        if (peer_status != TRECAP_CMD_OK) {
            trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
            return false;
        }
        server->learned_peer = true;
        if (result != NULL) {
            result->trusted_peer_learned = true;
        }
        return true;
    }
    trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_SOURCE);
    return false;
}

void trecap_command_server_note_reject(trecap_command_server_t *server,
                                       trecap_cmd_reject_reason_t reason)
{
    if (server == NULL || reason == TRECAP_CMD_REJECT_NONE) {
        return;
    }
    server->counters.hps_command_reject_count += 1u;
    switch (reason) {
    case TRECAP_CMD_REJECT_BAD_SOURCE:
        server->counters.bad_source_count += 1u;
        break;
    case TRECAP_CMD_REJECT_BAD_LENGTH:
        server->counters.bad_length_count += 1u;
        break;
    case TRECAP_CMD_REJECT_BAD_MAGIC:
        server->counters.bad_magic_count += 1u;
        break;
    case TRECAP_CMD_REJECT_BAD_VERSION:
        server->counters.bad_version_count += 1u;
        break;
    case TRECAP_CMD_REJECT_BAD_CRC:
        server->counters.bad_crc_count += 1u;
        break;
    case TRECAP_CMD_REJECT_UNSUPPORTED_TYPE:
        server->counters.unsupported_type_count += 1u;
        break;
    case TRECAP_CMD_REJECT_RANGE:
        server->counters.range_reject_count += 1u;
        break;
    case TRECAP_CMD_REJECT_RESERVED_ARGUMENT:
        server->counters.reserved_argument_count += 1u;
        break;
    case TRECAP_CMD_REJECT_CSR:
        server->counters.csr_reject_count += 1u;
        break;
    case TRECAP_CMD_REJECT_IO:
        server->counters.recv_error_count += 1u;
        break;
    case TRECAP_CMD_REJECT_UNSAFE_STATE:
        server->counters.unsafe_state_count += 1u;
        break;
    case TRECAP_CMD_REJECT_SEQUENCE_STALE:
        server->counters.stale_sequence_count += 1u;
        break;
    case TRECAP_CMD_REJECT_SEQUENCE_CONFLICT:
        server->counters.sequence_conflict_count += 1u;
        break;
    case TRECAP_CMD_REJECT_TIMEOUT:
        server->counters.timeout_count += 1u;
        break;
    case TRECAP_CMD_REJECT_RESET_REQUIRED:
        server->counters.reset_required_count += 1u;
        break;
    case TRECAP_CMD_REJECT_VERSION_MISMATCH:
        server->counters.version_mismatch_count += 1u;
        break;
    case TRECAP_CMD_REJECT_NONE:
    default:
        break;
    }
}

trecap_cmd_status_t trecap_command_server_recv(trecap_command_server_t *server,
                                               trecap_command_packet_t *cmd,
                                               trecap_command_result_t *result,
                                               char *err_buf,
                                               size_t err_buf_len)
{
    if (server == NULL || cmd == NULL || result == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null command receive argument");
        return TRECAP_CMD_ERR_NULL;
    }
    trecap_command_result_init(result);
    memset(cmd, 0, sizeof(*cmd));

    if (!server->open || server->fd < 0) {
        trecap_cmd_set_error(err_buf, err_buf_len, "command socket is not open");
        return TRECAP_CMD_ERR_SOCKET;
    }

    uint8_t datagram[2048];
    struct sockaddr_in source;
    memset(&source, 0, sizeof(source));
    socklen_t source_len = (socklen_t)sizeof(source);

    ssize_t received = 0;
    do {
        received = trecap_command_server_recvfrom(server->fd,
                                                  datagram,
                                                  sizeof(datagram),
                                                  0,
                                                  (struct sockaddr *)(void *)&source,
                                                  &source_len);
    } while (received < 0 && errno == EINTR);

    if (received < 0) {
        const int saved_errno = errno;
        server->last_errno_value = saved_errno;
        result->errno_value = saved_errno;
        if (saved_errno == EAGAIN || saved_errno == EWOULDBLOCK) {
            return server->cfg.nonblocking ? TRECAP_CMD_ERR_WOULD_BLOCK : TRECAP_CMD_ERR_TIMEOUT;
        }
        server->counters.recv_error_count += 1u;
        trecap_cmd_set_error(err_buf, err_buf_len, "recvfrom(command socket) failed");
        return TRECAP_CMD_ERR_RECV;
    }

    server->counters.datagrams_received += 1u;
    trecap_cmd_result_set_source(result, &source);

    const size_t received_bytes = (size_t)received;
    if (!trecap_cmd_datagram_length_is_valid(received_bytes)) {
        trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_LENGTH);
        trecap_command_server_note_reject(server, result->reject_reason);
        trecap_cmd_set_error(err_buf, err_buf_len, "command packet length is not 28 bytes");
        return TRECAP_CMD_REJECTED;
    }
    if (!trecap_command_packet_parse(datagram, received_bytes, cmd)) {
        trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_BAD_LENGTH);
        trecap_command_server_note_reject(server, result->reject_reason);
        trecap_cmd_set_error(err_buf, err_buf_len, "command packet parse failed");
        return TRECAP_CMD_REJECTED;
    }
    result->cmd_type = cmd->cmd_type;
    result->seq = cmd->seq;
    result->command_version = cmd->version;

    const trecap_cmd_reject_reason_t envelope_reason =
        trecap_command_packet_validate_envelope(cmd);
    if (envelope_reason != TRECAP_CMD_REJECT_NONE) {
        trecap_cmd_result_set_reject(result, envelope_reason);
        trecap_command_server_note_reject(server, envelope_reason);
        trecap_cmd_set_error(err_buf,
                            err_buf_len,
                            trecap_cmd_reject_reason_string(envelope_reason));
        return TRECAP_CMD_REJECTED;
    }
    if (!trecap_command_server_source_allowed(server, &source, cmd, result)) {
        trecap_command_server_note_reject(server, result->reject_reason);
        trecap_cmd_set_error(err_buf, err_buf_len, "command source is not trusted");
        return TRECAP_CMD_REJECTED;
    }

    /* Version-1 argument rejection remains exactly on the receive side. Every
     * trusted, envelope-valid v2 non-PING transaction instead reaches the
     * bridge, where argument rejection participates in the sequence/cache
     * ledger and therefore has byte-identical retry behavior. */
    if (cmd->version == (uint16_t)TCMD_VERSION_V1) {
        const trecap_cmd_reject_reason_t args_reason =
            trecap_command_packet_validate_args(cmd);
        if (args_reason != TRECAP_CMD_REJECT_NONE) {
            trecap_cmd_result_set_reject(result, args_reason);
            trecap_command_server_note_reject(server, args_reason);
            trecap_cmd_set_error(err_buf,
                                err_buf_len,
                                trecap_cmd_reject_reason_string(args_reason));
            return TRECAP_CMD_REJECTED;
        }
    }

    trecap_command_server_count_accept(server, cmd);
    result->status = cmd->cmd_type == TCMD_TYPE_PING ? TRECAP_CMD_PING : TRECAP_CMD_OK;
    result->reject_reason = TRECAP_CMD_REJECT_NONE;
    result->accepted = true;
    result->applied = false;
    result->ping_requested = cmd->cmd_type == TCMD_TYPE_PING;
    result->should_send_status = cmd->cmd_type == TCMD_TYPE_PING;
    result->should_send_result = cmd->version == (uint16_t)TCMD_VERSION_V2 &&
                                 cmd->cmd_type != TCMD_TYPE_PING;
    return result->ping_requested ? TRECAP_CMD_PING : TRECAP_CMD_OK;
}

void trecap_command_v2_result_init(trecap_command_v2_result_packet_t *packet,
                                   uint16_t cmd_type,
                                   uint32_t seq,
                                   trecap_cmd_disposition_t disposition,
                                   trecap_cmd_reject_reason_t reject_reason,
                                   uint32_t fpga_status,
                                   uint32_t csr_version)
{
    if (packet == NULL) {
        return;
    }
    packet->magic = TCMD_RESULT_MAGIC;
    packet->version = (uint16_t)TCMD_RESULT_VERSION;
    packet->cmd_type = cmd_type;
    packet->seq = seq;
    packet->disposition = (uint32_t)disposition;
    packet->reject_reason = (uint32_t)reject_reason;
    packet->fpga_status = fpga_status;
    packet->csr_version = csr_version;
    packet->crc32 = 0u;
}

bool trecap_command_v2_result_encode(const trecap_command_v2_result_packet_t *packet,
                                     uint8_t *out,
                                     size_t out_bytes)
{
    if (packet == NULL || out == NULL || out_bytes != (size_t)TCMD_RESULT_BYTES ||
        packet->magic != TCMD_RESULT_MAGIC ||
        packet->version != (uint16_t)TCMD_RESULT_VERSION || packet->crc32 != 0u) {
        return false;
    }
    memset(out, 0, out_bytes);
    trecap_cmd_store_le32(&out[TCMD_RESULT_MAGIC_OFFSET], packet->magic);
    trecap_cmd_store_le16(&out[TCMD_RESULT_VERSION_OFFSET], packet->version);
    trecap_cmd_store_le16(&out[TCMD_RESULT_CMD_TYPE_OFFSET], packet->cmd_type);
    trecap_cmd_store_le32(&out[TCMD_RESULT_SEQ_OFFSET], packet->seq);
    trecap_cmd_store_le32(&out[TCMD_RESULT_DISPOSITION_OFFSET], packet->disposition);
    trecap_cmd_store_le32(&out[TCMD_RESULT_REJECT_REASON_OFFSET], packet->reject_reason);
    trecap_cmd_store_le32(&out[TCMD_RESULT_FPGA_STATUS_OFFSET], packet->fpga_status);
    trecap_cmd_store_le32(&out[TCMD_RESULT_CSR_VERSION_OFFSET], packet->csr_version);
    trecap_cmd_store_le32(&out[TCMD_RESULT_CRC32_OFFSET], packet->crc32);
    return true;
}

trecap_cmd_status_t trecap_command_server_send_v2_result(
    trecap_command_server_t *server,
    const trecap_command_v2_result_packet_t *packet,
    const struct sockaddr_in *destination,
    char *err_buf,
    size_t err_buf_len)
{
    if (server == NULL || packet == NULL || destination == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null command-result send argument");
        return TRECAP_CMD_ERR_NULL;
    }
    uint8_t wire[TCMD_RESULT_BYTES];
    if (!trecap_command_v2_result_encode(packet, wire, sizeof(wire))) {
        trecap_cmd_set_error(err_buf, err_buf_len, "invalid command-result packet");
        return TRECAP_CMD_ERR_BAD_ARG;
    }

    return trecap_command_server_send_peer_datagram(server,
                                                    wire,
                                                    sizeof(wire),
                                                    destination,
                                                    err_buf,
                                                    err_buf_len);
}

trecap_cmd_status_t trecap_command_server_send_peer_datagram(
    trecap_command_server_t *server,
    const void *datagram,
    size_t datagram_bytes,
    const struct sockaddr_in *destination,
    char *err_buf,
    size_t err_buf_len)
{
    if (server == NULL || datagram == NULL || destination == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null command-peer send argument");
        return TRECAP_CMD_ERR_NULL;
    }
    if (!server->open || server->fd < 0 || destination->sin_family != AF_INET ||
        destination->sin_port == 0u || datagram_bytes == 0u || datagram_bytes > 2048u) {
        trecap_cmd_set_error(err_buf, err_buf_len, "command-peer socket, destination, or size invalid");
        return TRECAP_CMD_ERR_SEND;
    }
    if (!server->trusted_peer.addr_valid || server->trusted_peer.port == 0u ||
        !trecap_cmd_sockaddr_same_ipv4(destination,
                                       &server->trusted_peer.addr,
                                       true)) {
        trecap_cmd_set_error(err_buf,
                            err_buf_len,
                            "command response destination is not the pinned peer");
        return TRECAP_CMD_ERR_SEND;
    }

    ssize_t sent = 0;
    do {
        sent = trecap_command_server_sendto(server->fd,
                                            datagram,
                                            datagram_bytes,
                                            MSG_NOSIGNAL,
                                            (const struct sockaddr *)(const void *)destination,
                                            (socklen_t)sizeof(*destination));
    } while (sent < 0 && errno == EINTR);
    if (sent != (ssize_t)datagram_bytes) {
        server->last_errno_value = sent < 0 ? errno : EIO;
        trecap_cmd_set_error(err_buf, err_buf_len, "sendto(command peer) failed");
        return TRECAP_CMD_ERR_SEND;
    }
    server->last_errno_value = 0;
    return TRECAP_CMD_OK;
}

trecap_cmd_status_t trecap_command_apply_to_csr(const trecap_command_packet_t *cmd,
                                                const trecap_csr_window_t *csr,
                                                trecap_command_result_t *result,
                                                char *err_buf,
                                                size_t err_buf_len)
{
    if (cmd == NULL || csr == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null command apply argument");
        return TRECAP_CMD_ERR_NULL;
    }
    if (result != NULL) {
        result->cmd_type = cmd->cmd_type;
        result->seq = cmd->seq;
        result->accepted = true;
    }

    const trecap_cmd_reject_reason_t reason = trecap_command_packet_validate_fields(cmd);
    if (reason != TRECAP_CMD_REJECT_NONE) {
        trecap_cmd_result_set_reject(result, reason);
        trecap_cmd_set_error(err_buf, err_buf_len, trecap_cmd_reject_reason_string(reason));
        return TRECAP_CMD_REJECTED;
    }

    trecap_csr_status_t csr_status = TRECAP_CSR_OK;
    switch (cmd->cmd_type) {
    case TCMD_TYPE_SET_THR2:
        csr_status = trecap_csr_set_thr2(csr, trecap_cmd_thr2_from_args(cmd->arg0, cmd->arg1));
        break;
    case TCMD_TYPE_CLEAR_METRICS:
        csr_status = trecap_csr_pulse_control(csr, TCSR_CONTROL_CLEAR_METRICS_MASK);
        break;
    case TCMD_TYPE_SET_SOURCE_MODE:
        csr_status = trecap_csr_set_source_mode(csr, cmd->arg0);
        break;
    case TCMD_TYPE_SET_PACKET_ENABLE:
        csr_status = trecap_csr_set_packet_enable(csr, cmd->arg0);
        break;
    case TCMD_TYPE_SET_WAVE_DECIM:
        csr_status = trecap_csr_set_wave_decim(csr, cmd->arg0);
        break;
    case TCMD_TYPE_SET_SPEC_SHIFT:
        csr_status = trecap_csr_set_spec_shift(csr, cmd->arg0);
        break;
    case TCMD_TYPE_SET_SPEC_MODE:
        csr_status = trecap_csr_set_spec_mode(csr, cmd->arg0);
        break;
    case TCMD_TYPE_PING:
        if (result != NULL) {
            result->status = TRECAP_CMD_PING;
            result->ping_requested = true;
            result->should_send_status = true;
        }
        return TRECAP_CMD_PING;
    default:
        trecap_cmd_result_set_reject(result, TRECAP_CMD_REJECT_UNSUPPORTED_TYPE);
        trecap_cmd_set_error(err_buf, err_buf_len, "unsupported command type");
        return TRECAP_CMD_REJECTED;
    }

    if (csr_status != TRECAP_CSR_OK) {
        if (result != NULL) {
            result->status = TRECAP_CMD_ERR_CSR;
            result->reject_reason = TRECAP_CMD_REJECT_CSR;
            result->csr_status = csr_status;
            result->applied = false;
        }
        trecap_cmd_set_error(err_buf, err_buf_len, trecap_csr_status_string(csr_status));
        return csr_status == TRECAP_CSR_ERR_BAD_VALUE || csr_status == TRECAP_CSR_ERR_RANGE
                   ? TRECAP_CMD_REJECTED
                   : TRECAP_CMD_ERR_CSR;
    }

    if (result != NULL) {
        result->status = TRECAP_CMD_OK;
        result->reject_reason = TRECAP_CMD_REJECT_NONE;
        result->csr_status = TRECAP_CSR_OK;
        result->applied = true;
        result->should_send_status = false;
    }
    return TRECAP_CMD_OK;
}

trecap_cmd_status_t trecap_command_server_poll_apply(trecap_command_server_t *server,
                                                     const trecap_csr_window_t *csr,
                                                     trecap_command_result_t *result,
                                                     char *err_buf,
                                                     size_t err_buf_len)
{
    if (server == NULL || csr == NULL || result == NULL) {
        trecap_cmd_set_error(err_buf, err_buf_len, "null poll/apply argument");
        return TRECAP_CMD_ERR_NULL;
    }

    trecap_command_packet_t cmd;
    memset(&cmd, 0, sizeof(cmd));
    trecap_cmd_status_t status = trecap_command_server_recv(server,
                                                            &cmd,
                                                            result,
                                                            err_buf,
                                                            err_buf_len);
    if (status == TRECAP_CMD_NO_PACKET || status == TRECAP_CMD_ERR_WOULD_BLOCK ||
        status == TRECAP_CMD_ERR_TIMEOUT || status == TRECAP_CMD_REJECTED) {
        return status;
    }
    if (status == TRECAP_CMD_PING) {
        return status;
    }
    if (status != TRECAP_CMD_OK) {
        return status;
    }

    status = trecap_command_apply_to_csr(&cmd, csr, result, err_buf, err_buf_len);
    if (status == TRECAP_CMD_OK) {
        server->counters.commands_applied += 1u;
    } else if (status == TRECAP_CMD_REJECTED || status == TRECAP_CMD_ERR_CSR) {
        trecap_command_server_note_reject(server, TRECAP_CMD_REJECT_CSR);
    }
    return status;
}
