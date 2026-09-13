/* SPDX-License-Identifier: MIT
 * Deterministic host test for the Step-13 HPS transport implementation.
 * File class: [1] hand-written verification source.
 *
 * This test uses RAM-backed CSR/ring windows and linker-wrapped MMIO commit and
 * UDP send calls. It is host evidence only: it does not claim /dev/mem, active
 * device-tree, Ethernet, systemd, FPGA, or board execution.
 */

#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* White-box the config safety parser and orchestration seams while linking the
 * remaining HPS sources as normal translation units. Production code is unchanged. */
#include "../src/config.c"
#include "../src/trecap_udp_streamer.c"

#define TEST_RING_BYTES UINT32_C(1048576)
#define TEST_CSR_BYTES 4096u
#define TEST_MAX_SENDS 16u

typedef struct test_send_capture {
    size_t bytes;
    uint8_t data[TPKT_UDP_MAX_BYTES];
} test_send_capture_t;

static test_send_capture_t g_sends[TEST_MAX_SENDS];
static size_t g_send_count = 0u;
static int g_send_errno = 0;
static uint64_t g_commit_calls = 0u;
static uint64_t g_fail_commit_call = 0u;
static uint64_t g_control_level_calls = 0u;
static bool g_fail_control_levels = false;
static bool g_suppress_control_status_readback = false;
static uint64_t g_recvfrom_calls = 0u;
static bool g_recvfrom_flood = false;

trecap_csr_status_t __real_trecap_csr_commit_ring_rd(const trecap_csr_window_t *csr,
                                                     uint64_t rd);
trecap_csr_status_t __wrap_trecap_csr_commit_ring_rd(const trecap_csr_window_t *csr,
                                                     uint64_t rd);
trecap_csr_status_t __real_trecap_csr_set_control_levels(const trecap_csr_window_t *csr,
                                                        bool telemetry_enable,
                                                        bool ring_writer_enable);
trecap_csr_status_t __wrap_trecap_csr_set_control_levels(const trecap_csr_window_t *csr,
                                                        bool telemetry_enable,
                                                        bool ring_writer_enable);
ssize_t __wrap_sendmsg(int fd, const struct msghdr *msg, int flags);

trecap_csr_status_t __wrap_trecap_csr_commit_ring_rd(const trecap_csr_window_t *csr,
                                                     uint64_t rd)
{
    g_commit_calls += 1u;
    if (g_fail_commit_call != 0u && g_commit_calls == g_fail_commit_call) {
        return TRECAP_CSR_ERR_IO;
    }
    return __real_trecap_csr_commit_ring_rd(csr, rd);
}

trecap_csr_status_t __wrap_trecap_csr_set_control_levels(const trecap_csr_window_t *csr,
                                                        bool telemetry_enable,
                                                        bool ring_writer_enable)
{
    g_control_level_calls += 1u;
    if (g_fail_control_levels) {
        return TRECAP_CSR_ERR_IO;
    }
    const trecap_csr_status_t status =
        __real_trecap_csr_set_control_levels(csr, telemetry_enable, ring_writer_enable);
    if (status == TRECAP_CSR_OK && !g_suppress_control_status_readback) {
        uint32_t status_word = 0u;
        if (trecap_csr_read32(csr, TCSR_STATUS_OFFSET, &status_word) == TRECAP_CSR_OK) {
            status_word &= ~(TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                             TCSR_STATUS_RING_WRITER_ENABLED_MASK);
            if (telemetry_enable) {
                status_word |= TCSR_STATUS_TELEMETRY_ENABLED_MASK;
            }
            if (ring_writer_enable) {
                status_word |= TCSR_STATUS_RING_WRITER_ENABLED_MASK;
            }
            (void)trecap_csr_write32(csr, TCSR_STATUS_OFFSET, status_word);
        }
    }
    return status;
}

ssize_t __wrap_sendmsg(int fd, const struct msghdr *msg, int flags)
{
    (void)fd;
    (void)flags;
    if (g_send_errno != 0) {
        errno = g_send_errno;
        return -1;
    }
    if (msg == NULL || msg->msg_iov == NULL || msg->msg_iovlen == 0u ||
        g_send_count >= TEST_MAX_SENDS) {
        errno = EINVAL;
        return -1;
    }

    size_t total = 0u;
    for (size_t i = 0u; i < msg->msg_iovlen; ++i) {
        if (msg->msg_iov[i].iov_len > sizeof(g_sends[g_send_count].data) - total) {
            errno = EMSGSIZE;
            return -1;
        }
        memcpy(&g_sends[g_send_count].data[total],
               msg->msg_iov[i].iov_base,
               msg->msg_iov[i].iov_len);
        total += msg->msg_iov[i].iov_len;
    }
    g_sends[g_send_count].bytes = total;
    g_send_count += 1u;
    return (ssize_t)total;
}

ssize_t trecap_command_server_recvfrom(int fd,
                                       void *buf,
                                       size_t len,
                                       int flags,
                                       struct sockaddr *src_addr,
                                       socklen_t *addrlen)
{
    (void)fd;
    (void)flags;
    if (!g_recvfrom_flood) {
        errno = EAGAIN;
        return -1;
    }
    if (buf == NULL || len == 0u) {
        errno = EINVAL;
        return -1;
    }
    ((uint8_t *)buf)[0] = 0u;
    if (src_addr != NULL && addrlen != NULL && *addrlen >= (socklen_t)sizeof(struct sockaddr_in)) {
        struct sockaddr_in *source = (struct sockaddr_in *)(void *)src_addr;
        memset(source, 0, sizeof(*source));
        source->sin_family = AF_INET;
        *addrlen = (socklen_t)sizeof(*source);
    }
    g_recvfrom_calls += 1u;
    return 1;
}

#define TEST_CHECK(condition)                                                                  \
    do {                                                                                       \
        if (!(condition)) {                                                                    \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition);             \
            return false;                                                                      \
        }                                                                                      \
    } while (0)

static void test_reset_wrappers(void)
{
    memset(g_sends, 0, sizeof(g_sends));
    g_send_count = 0u;
    g_send_errno = 0;
    g_commit_calls = 0u;
    g_fail_commit_call = 0u;
    g_control_level_calls = 0u;
    g_fail_control_levels = false;
    g_suppress_control_status_readback = false;
    g_recvfrom_calls = 0u;
    g_recvfrom_flood = false;
    g_stop_requested = 0;
}

static void test_store_le16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value & UINT16_C(0x00ff));
    p[1] = (uint8_t)(value >> 8u);
}

static void test_store_le32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)(value & UINT32_C(0x000000ff));
    p[1] = (uint8_t)((value >> 8u) & UINT32_C(0x000000ff));
    p[2] = (uint8_t)((value >> 16u) & UINT32_C(0x000000ff));
    p[3] = (uint8_t)(value >> 24u);
}

static void test_store_le64(uint8_t *p, uint64_t value)
{
    test_store_le32(p, (uint32_t)(value & UINT64_C(0xffffffff)));
    test_store_le32(&p[4], (uint32_t)(value >> 32u));
}

static uint16_t test_load_le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8u));
}

static uint32_t test_load_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static uint64_t test_load_le64(const uint8_t *p)
{
    return (uint64_t)test_load_le32(p) | ((uint64_t)test_load_le32(&p[4]) << 32u);
}

static uint32_t test_align64(uint32_t value)
{
    return (value + UINT32_C(63)) & ~UINT32_C(63);
}

static uint32_t test_write_record(uint8_t *ring,
                                  uint32_t offset,
                                  uint16_t packet_type,
                                  uint16_t flags,
                                  uint32_t seq,
                                  uint64_t timestamp,
                                  uint32_t payload_bytes)
{
    const uint32_t ddr_bytes = test_align64((uint32_t)TPKT_HEADER_BYTES + payload_bytes);
    uint8_t *header = &ring[offset];
    memset(header, 0, ddr_bytes);
    test_store_le32(&header[TPKT_HDR_MAGIC_OFFSET], TPKT_TELEMETRY_MAGIC);
    test_store_le16(&header[TPKT_HDR_VERSION_OFFSET], (uint16_t)TPKT_HEADER_VERSION);
    test_store_le16(&header[TPKT_HDR_HEADER_BYTES_OFFSET], (uint16_t)TPKT_HEADER_BYTES);
    test_store_le16(&header[TPKT_HDR_PACKET_TYPE_OFFSET], packet_type);
    test_store_le16(&header[TPKT_HDR_FLAGS_OFFSET], flags);
    test_store_le32(&header[TPKT_HDR_SEQ_OFFSET], seq);
    test_store_le64(&header[TPKT_HDR_TIMESTAMP_OFFSET], timestamp);
    test_store_le32(&header[TPKT_HDR_PAYLOAD_BYTES_OFFSET], payload_bytes);
    test_store_le32(&header[TPKT_HDR_HEADER_CRC_OFFSET], 0u);

    uint8_t *payload = &header[TPKT_HEADER_BYTES];
    switch (packet_type) {
    case TPKT_TYPE_WAVE:
        if (payload_bytes >= (uint32_t)TPKT_PAYLOAD_WAVE_MIN_BYTES) {
            const uint16_t nsamp = (uint16_t)((payload_bytes - 16u) / 6u);
            test_store_le64(&payload[TPKT_WAVE_SAMPLE_BASE_OFFSET], timestamp);
            test_store_le16(&payload[TPKT_WAVE_NSAMP_OFFSET], nsamp);
            test_store_le16(&payload[TPKT_WAVE_CHANNELS_OFFSET], 3u);
            test_store_le16(&payload[TPKT_WAVE_STRIDE_OFFSET], 1u);
            test_store_le16(&payload[TPKT_WAVE_RESERVED_OFFSET], 0u);
        }
        break;
    case TPKT_TYPE_SPEC64:
        test_store_le64(&payload[TPKT_SPEC64_FRAME_IDX_OFFSET], timestamp);
        test_store_le16(&payload[TPKT_SPEC64_NBIN_OFFSET], 64u);
        test_store_le16(&payload[TPKT_SPEC64_SPEC_SHIFT_OFFSET], 0u);
        break;
    case TPKT_TYPE_SPEC129:
        test_store_le64(&payload[TPKT_SPEC129_FRAME_IDX_OFFSET], timestamp);
        test_store_le16(&payload[TPKT_SPEC129_NBIN_OFFSET], 129u);
        test_store_le16(&payload[TPKT_SPEC129_SPEC_SHIFT_OFFSET], 0u);
        break;
    case TPKT_TYPE_METRICS:
        test_store_le64(&payload[TPKT_METRICS_FRAME_IDX_OFFSET], timestamp);
        break;
    case TPKT_TYPE_STATUS:
        test_store_le64(&payload[TPKT_STATUS_SAMPLE_COUNT_OFFSET], timestamp);
        test_store_le32(&payload[TPKT_STATUS_RESERVED_OFFSET], 0u);
        break;
    default:
        break;
    }
    return ddr_bytes;
}

static void test_set_wr(uint8_t *csr_bytes, uint64_t wr)
{
    test_store_le32(&csr_bytes[TCSR_RING_WR_LO_SNAP_OFFSET], (uint32_t)wr);
    test_store_le32(&csr_bytes[TCSR_RING_WR_HI_SNAP_OFFSET], (uint32_t)(wr >> 32u));
}

static void test_init_state(trecap_streamer_state_t *state,
                            uint8_t *csr_bytes,
                            uint8_t *ring_bytes)
{
    memset(state, 0, sizeof(*state));
    memset(csr_bytes, 0, TEST_CSR_BYTES);
    memset(ring_bytes, 0, TEST_RING_BYTES);
    state->cli.quiet = true;
    state->cfg.stop_on_malformed_record = false;
    state->csr.base = csr_bytes;
    state->csr.span_bytes = TEST_CSR_BYTES;
    state->csr_mapped = true;

    trecap_ring_mapping_t mapping;
    memset(&mapping, 0, sizeof(mapping));
    mapping.base = ring_bytes;
    mapping.size_bytes = TEST_RING_BYTES;
    mapping.fd = -1;

    trecap_ring_reader_config_t ring_cfg;
    trecap_ring_reader_config_set_defaults(&ring_cfg, NULL);
    ring_cfg.ring_size_bytes = TEST_RING_BYTES;
    ring_cfg.ring_guard_bytes = (uint32_t)TCSR_RING_GUARD_BYTES_MIN;
    trecap_ring_reader_init(&state->ring_reader, &state->csr, &mapping, &ring_cfg);
    state->ring_reader.state = TRECAP_RING_READER_ACTIVE;
    state->ring_reader.telemetry_disabled_by_reader = false;

    state->udp_sender.fd = 7;
    state->udp_sender.open = true;
    state->udp_sender.cfg.destination.addr_valid = true;
    state->udp_sender.cfg.nonblocking = true;
    state->udp_sender.cfg.drop_on_would_block = true;
    state->udp_sender.cfg.max_datagram_bytes = (uint32_t)TPKT_UDP_MAX_BYTES;
    state->udp_open = true;
}

static trecap_hps_config_status_t test_validate_iomem_text(
    const trecap_hps_runtime_config_t *cfg,
    const char *text)
{
    FILE *fp = tmpfile();
    if (fp == NULL) {
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    const size_t bytes = strlen(text);
    if (fwrite(text, 1u, bytes, fp) != bytes || fflush(fp) != 0 || fseek(fp, 0L, SEEK_SET) != 0) {
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';
    const trecap_hps_config_status_t status =
        trecap_config_validate_iomem_stream(fp, cfg, err_buf, sizeof(err_buf));
    (void)fclose(fp);
    return status;
}

static bool test_iomem_fail_closed(void)
{
    trecap_hps_runtime_config_t cfg;
    trecap_hps_config_set_defaults(&cfg);

    TEST_CHECK(test_validate_iomem_text(
                   &cfg,
                   "00000000-3dffffff : System RAM\n"
                   "ff200000-ff200fff : trecap-csr\n") == TRECAP_HPS_CONFIG_OK);
    TEST_CHECK(test_validate_iomem_text(
                   &cfg,
                   "00000000-00000000 : System RAM\n"
                   "ff200000-ff200fff : trecap-csr\n") == TRECAP_HPS_CONFIG_ERR_IO);
    TEST_CHECK(test_validate_iomem_text(
                   &cfg,
                   "00000000-3effffff : System RAM\n") == TRECAP_HPS_CONFIG_ERR_BAD_VALUE);

    const char embedded_nul[] = {'{', '}', '\0', 'x'};
    TEST_CHECK(trecap_config_buffer_has_embedded_nul(embedded_nul, sizeof(embedded_nul)));
    cfg.use_nonblocking_udp = false;
    TEST_CHECK(trecap_hps_config_validate(&cfg, NULL, 0u) == TRECAP_HPS_CONFIG_ERR_BAD_VALUE);
    cfg.use_nonblocking_udp = true;
    cfg.require_trusted_peer = false;
    TEST_CHECK(trecap_hps_config_validate(&cfg, NULL, 0u) == TRECAP_HPS_CONFIG_ERR_BAD_VALUE);
    return true;
}

static bool test_embedded_nul_config_rejected(void)
{
    FILE *source = fopen(TRECAP_HPS_DEFAULT_CONFIG, "rb");
    TEST_CHECK(source != NULL);
    TEST_CHECK(fseek(source, 0L, SEEK_END) == 0);
    const long end_pos = ftell(source);
    TEST_CHECK(end_pos > 0L);
    TEST_CHECK(fseek(source, 0L, SEEK_SET) == 0);
    const size_t bytes = (size_t)end_pos;
    uint8_t *data = (uint8_t *)malloc(bytes);
    TEST_CHECK(data != NULL);
    TEST_CHECK(fread(data, 1u, bytes, source) == bytes);
    TEST_CHECK(fclose(source) == 0);

    char path[] = "/tmp/trecap-step13-config.XXXXXX";
    const int fd = mkstemp(path);
    TEST_CHECK(fd >= 0);
    FILE *output = fdopen(fd, "wb");
    TEST_CHECK(output != NULL);
    const uint8_t suffix[2] = {0u, (uint8_t)'x'};
    TEST_CHECK(fwrite(data, 1u, bytes, output) == bytes);
    TEST_CHECK(fwrite(suffix, 1u, sizeof(suffix), output) == sizeof(suffix));
    TEST_CHECK(fclose(output) == 0);
    free(data);

    trecap_hps_runtime_config_t cfg;
    trecap_hps_config_set_defaults(&cfg);
    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';
    const trecap_hps_config_status_t status =
        trecap_hps_config_load_file(path, &cfg, err_buf, sizeof(err_buf));
    TEST_CHECK(unlink(path) == 0);
    TEST_CHECK(status == TRECAP_HPS_CONFIG_ERR_PARSE);
    return true;
}

static bool test_fail_closed_reset_and_identity_cleanup(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    g_fail_control_levels = true;
    TEST_CHECK(trecap_ring_reader_reset_transport(&state.ring_reader) == TRECAP_RING_ERR_CSR);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_RESET_REQUIRED);
    TEST_CHECK(state.ring_reader.telemetry_disabled_by_reader);

    test_reset_wrappers();
    test_init_state(&state, csr, ring);
    test_store_le32(&csr[TCSR_STATUS_OFFSET],
                    TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                        TCSR_STATUS_RING_WRITER_ENABLED_MASK);
    g_suppress_control_status_readback = true;
    TEST_CHECK(trecap_ring_reader_reset_transport(&state.ring_reader) == TRECAP_RING_ERR_CSR);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_RESET_REQUIRED);
    TEST_CHECK(state.ring_reader.telemetry_disabled_by_reader);

    test_reset_wrappers();
    test_init_state(&state, csr, ring);
    state.ring_reader.state = TRECAP_RING_READER_RECONFIG_REQUIRED;
    state.ring_reader.telemetry_disabled_by_reader = true;
    TEST_CHECK(trecap_ring_reader_configure_fpga_ring(&state.ring_reader,
                                                     TRECAP_HPS_DE1SOC_RING_FPGA_BASE,
                                                     TEST_RING_BYTES,
                                                     (uint32_t)TCSR_RING_GUARD_BYTES_MIN) ==
               TRECAP_RING_ERR_CSR);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_RECONFIG_REQUIRED);

    test_reset_wrappers();
    memset(&state, 0, sizeof(state));
    state.csr_mapped = true;
    state.csr_identity_verified = false;
    trecap_streamer_close_resources(&state);
    TEST_CHECK(g_control_level_calls == 0u);
    free(ring);
    return true;
}

static bool test_command_budget(void)
{
    test_reset_wrappers();
    trecap_streamer_state_t state;
    memset(&state, 0, sizeof(state));
    state.command_open = true;
    state.command_server.open = true;
    state.command_server.fd = 7;
    state.command_server.cfg.nonblocking = true;
    g_recvfrom_flood = true;
    TEST_CHECK(trecap_streamer_service_commands(&state) == 0);
    TEST_CHECK(g_recvfrom_calls == TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS);
    TEST_CHECK(state.command_server.counters.hps_command_reject_count ==
               TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS);
    state.command_open = false;
    state.command_server.open = false;
    state.command_server.fd = -1;
    return true;
}

static bool test_valid_packet_types(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);

    const uint16_t types[5] = {
        TPKT_TYPE_WAVE, TPKT_TYPE_SPEC64, TPKT_TYPE_SPEC129,
        TPKT_TYPE_METRICS, TPKT_TYPE_STATUS};
    const uint32_t payloads[5] = {
        TPKT_PAYLOAD_WAVE_MIN_BYTES, TPKT_PAYLOAD_SPEC64_BYTES,
        TPKT_PAYLOAD_SPEC129_BYTES, TPKT_PAYLOAD_METRICS_BYTES,
        TPKT_PAYLOAD_STATUS_BYTES};
    uint32_t offset = 0u;
    for (size_t i = 0u; i < 5u; ++i) {
        const uint16_t flags = types[i] == TPKT_TYPE_METRICS
                                   ? TPKT_FLAG_PER_FRAME_METRICS_MASK
                                   : 0u;
        offset += test_write_record(ring,
                                    offset,
                                    types[i],
                                    flags,
                                    (uint32_t)(10u + i),
                                    UINT64_C(1000) + (uint64_t)i,
                                    payloads[i]);
    }
    test_set_wr(csr, offset);

    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(made_progress);
    TEST_CHECK(g_send_count == 5u);
    TEST_CHECK(state.ring_reader.rd == (uint64_t)offset);
    TEST_CHECK(state.ring_reader.counters.records_seen == 5u);
    TEST_CHECK(state.ring_reader.counters.records_forwardable == 5u);
    TEST_CHECK(state.ring_reader.counters.consumer_commit_count == 5u);
    TEST_CHECK(state.records_consumed == 5u);
    for (size_t i = 0u; i < 5u; ++i) {
        TEST_CHECK(g_sends[i].bytes == (size_t)TPKT_HEADER_BYTES + (size_t)payloads[i]);
        TEST_CHECK(test_load_le16(&g_sends[i].data[TPKT_HDR_PACKET_TYPE_OFFSET]) == types[i]);
    }
    free(ring);
    return true;
}

static bool test_wrap_record(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    const uint32_t offset = TEST_RING_BYTES - (uint32_t)TPKT_DDR_ALIGN_BYTES;
    (void)test_write_record(ring, offset, TPKT_TYPE_WRAP, 0u, 0u, 0u, 0u);
    state.ring_reader.rd = offset;
    test_set_wr(csr, TEST_RING_BYTES);

    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(made_progress);
    TEST_CHECK(state.ring_reader.rd == TEST_RING_BYTES);
    TEST_CHECK(state.ring_reader.counters.wrap_records_seen == 1u);
    TEST_CHECK(!state.ring_reader.have_last_seq);
    TEST_CHECK(g_send_count == 0u);
    free(ring);
    return true;
}

static bool test_oversized_and_hostile_length(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    const uint32_t oversized_payload = (uint32_t)TPKT_UDP_MAX_BYTES -
                                       (uint32_t)TPKT_HEADER_BYTES + 1u;
    const uint32_t oversized_ddr = test_write_record(ring,
                                                     0u,
                                                     TPKT_TYPE_WAVE,
                                                     0u,
                                                     1u,
                                                     1u,
                                                     oversized_payload);
    test_set_wr(csr, oversized_ddr);
    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(made_progress);
    TEST_CHECK(state.ring_reader.counters.oversized_record_count == 1u);
    TEST_CHECK(state.ring_reader.rd == oversized_ddr);
    TEST_CHECK(g_send_count == 0u);

    test_reset_wrappers();
    test_init_state(&state, csr, ring);
    memset(ring, 0, TEST_RING_BYTES);
    test_store_le32(&ring[TPKT_HDR_MAGIC_OFFSET], TPKT_TELEMETRY_MAGIC);
    test_store_le16(&ring[TPKT_HDR_VERSION_OFFSET], (uint16_t)TPKT_HEADER_VERSION);
    test_store_le16(&ring[TPKT_HDR_HEADER_BYTES_OFFSET], (uint16_t)TPKT_HEADER_BYTES);
    test_store_le16(&ring[TPKT_HDR_PACKET_TYPE_OFFSET], TPKT_TYPE_WAVE);
    test_store_le32(&ring[TPKT_HDR_PAYLOAD_BYTES_OFFSET], UINT32_MAX);
    test_set_wr(csr, TPKT_DDR_ALIGN_BYTES);
    made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    TEST_CHECK(state.ring_reader.rd == 0u);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_MALFORMED_LATCHED);
    free(ring);
    return true;
}

static bool test_malformed_latch_and_rearm(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    (void)test_write_record(ring,
                            0u,
                            TPKT_TYPE_STATUS,
                            0u,
                            1u,
                            1u,
                            TPKT_PAYLOAD_STATUS_BYTES);
    test_store_le32(&ring[TPKT_HDR_MAGIC_OFFSET], 0u);
    test_set_wr(csr, 128u);

    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    TEST_CHECK(state.ring_reader.counters.consumer_commit_count == 1u);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_MALFORMED_LATCHED);
    TEST_CHECK(state.ring_reader.telemetry_disabled_by_reader);
    TEST_CHECK(state.ring_reader.malformed_disable_commit_confirmed);
    TEST_CHECK(g_commit_calls == 1u);
    TEST_CHECK(test_load_le32(&csr[TCSR_CONTROL_OFFSET]) == 0u);

    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    TEST_CHECK(g_commit_calls == 1u);

    test_store_le32(&csr[TCSR_DMA_STATUS_OFFSET], TCSR_DMA_STATUS_WRITER_IDLE_MASK);
    TEST_CHECK(trecap_ring_reader_reset_transport(&state.ring_reader) == TRECAP_RING_OK);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_RECONFIG_REQUIRED);
    TEST_CHECK(state.ring_reader.telemetry_disabled_by_reader);
    test_store_le32(&csr[TCSR_STATUS_OFFSET], TCSR_STATUS_RING_CONFIGURED_MASK);
    TEST_CHECK(trecap_ring_reader_configure_fpga_ring(&state.ring_reader,
                                                     TRECAP_HPS_DE1SOC_RING_FPGA_BASE,
                                                     TEST_RING_BYTES,
                                                     (uint32_t)TCSR_RING_GUARD_BYTES_MIN) ==
               TRECAP_RING_OK);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_RD0_REQUIRED);
    TEST_CHECK(trecap_ring_reader_commit_rd(&state.ring_reader, 0u) == TRECAP_RING_OK);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_ACTIVE);
    TEST_CHECK(!state.ring_reader.telemetry_disabled_by_reader);

    memset(ring, 0, TEST_RING_BYTES);
    (void)test_write_record(ring,
                            0u,
                            TPKT_TYPE_STATUS,
                            0u,
                            2u,
                            2u,
                            TPKT_PAYLOAD_STATUS_BYTES);
    test_set_wr(csr, 128u);
    made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(made_progress);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    TEST_CHECK(g_send_count == 1u);
    free(ring);
    return true;
}

static bool test_invalid_atomic_pointer_latches(void)
{
    const uint64_t invalid_wr[2] = {
        UINT64_C(1),
        (uint64_t)TEST_RING_BYTES + (uint64_t)TPKT_DDR_ALIGN_BYTES,
    };
    for (size_t i = 0u; i < 2u; ++i) {
        test_reset_wrappers();
        uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
        TEST_CHECK(ring != NULL);
        uint8_t csr[TEST_CSR_BYTES];
        trecap_streamer_state_t state;
        test_init_state(&state, csr, ring);
        test_set_wr(csr, invalid_wr[i]);
        bool made_progress = false;
        TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
        TEST_CHECK(!made_progress);
        TEST_CHECK(state.ring_reader.counters.stale_snapshot_count == 1u);
        TEST_CHECK(state.ring_reader.counters.boundary_error_count == 1u);
        TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
        TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_MALFORMED_LATCHED);
        TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
        TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
        free(ring);
    }
    return true;
}

static bool test_malformed_mmio_failure_stays_latched(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    (void)test_write_record(ring,
                            0u,
                            TPKT_TYPE_STATUS,
                            0u,
                            1u,
                            1u,
                            TPKT_PAYLOAD_STATUS_BYTES);
    test_store_le32(&ring[TPKT_HDR_MAGIC_OFFSET], 0u);
    test_set_wr(csr, 128u);
    g_fail_commit_call = 1u;

    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 2);
    TEST_CHECK(state.ring_reader.state == TRECAP_RING_READER_MALFORMED_LATCHED);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    TEST_CHECK(!state.ring_reader.malformed_disable_commit_confirmed);
    TEST_CHECK(state.ring_reader.rd == 0u);
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.ring_reader.counters.malformed_record_count == 1u);
    free(ring);
    return true;
}

static bool test_commit_and_send_failures(void)
{
    test_reset_wrappers();
    uint8_t *ring = (uint8_t *)calloc(TEST_RING_BYTES, 1u);
    TEST_CHECK(ring != NULL);
    uint8_t csr[TEST_CSR_BYTES];
    trecap_streamer_state_t state;
    test_init_state(&state, csr, ring);
    const uint32_t ddr_bytes = test_write_record(ring,
                                                0u,
                                                TPKT_TYPE_WAVE,
                                                0u,
                                                1u,
                                                1u,
                                                TPKT_PAYLOAD_WAVE_MIN_BYTES);
    test_set_wr(csr, ddr_bytes);
    g_fail_commit_call = 1u;
    bool made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 2);
    TEST_CHECK(g_send_count == 1u);
    TEST_CHECK(state.ring_reader.rd == 0u);
    TEST_CHECK(state.ring_reader.counters.consumer_commit_count == 0u);
    TEST_CHECK(state.ring_reader.counters.records_seen == 0u);
    TEST_CHECK(state.ring_reader.counters.records_forwardable == 0u);
    TEST_CHECK(!state.ring_reader.have_last_seq);
    TEST_CHECK(state.records_consumed == 0u);

    test_reset_wrappers();
    test_init_state(&state, csr, ring);
    memset(ring, 0, TEST_RING_BYTES);
    const uint32_t metrics_ddr = test_write_record(ring,
                                                  0u,
                                                  TPKT_TYPE_METRICS,
                                                  TPKT_FLAG_PER_FRAME_METRICS_MASK,
                                                  1u,
                                                  1u,
                                                  TPKT_PAYLOAD_METRICS_BYTES);
    test_set_wr(csr, metrics_ddr);
    g_send_errno = EIO;
    made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.udp_sender.counters.send_error_count == 1u);
    TEST_CHECK(state.udp_sender.counters.datagrams_dropped == 1u);
    TEST_CHECK(state.ring_reader.rd == metrics_ddr);
    TEST_CHECK(state.records_consumed == 1u);

    test_reset_wrappers();
    test_init_state(&state, csr, ring);
    memset(ring, 0, TEST_RING_BYTES);
    (void)test_write_record(ring,
                            0u,
                            TPKT_TYPE_METRICS,
                            TPKT_FLAG_PER_FRAME_METRICS_MASK,
                            1u,
                            1u,
                            TPKT_PAYLOAD_METRICS_BYTES);
    test_set_wr(csr, metrics_ddr);
    state.udp_sender.cfg.nonblocking = false;
    state.udp_sender.cfg.send_timeout_ms = 10u;
    g_send_errno = EAGAIN;
    made_progress = false;
    TEST_CHECK(trecap_streamer_service_ring(&state, &made_progress) == 0);
    TEST_CHECK(state.udp_sender.counters.timeout_count == 1u);
    TEST_CHECK(state.udp_sender.counters.send_error_count == 1u);
    TEST_CHECK(state.ring_reader.rd == metrics_ddr);
    free(ring);
    return true;
}

static bool test_dummy_counter(void)
{
    test_reset_wrappers();
    trecap_streamer_state_t state;
    memset(&state, 0, sizeof(state));
    state.cli.quiet = true;
    state.cli.max_records = 3u;
    state.cli.poll_sleep_us = 0u;
    state.udp_sender.fd = 7;
    state.udp_sender.open = true;
    state.udp_sender.cfg.destination.addr_valid = true;
    state.udp_sender.cfg.nonblocking = true;
    state.udp_sender.cfg.drop_on_would_block = true;
    state.udp_sender.cfg.max_datagram_bytes = (uint32_t)TPKT_UDP_MAX_BYTES;
    state.udp_open = true;

    TEST_CHECK(trecap_streamer_run_dummy_udp_counter(&state) == 0);
    TEST_CHECK(g_send_count == 3u);
    for (size_t i = 0u; i < 3u; ++i) {
        const uint8_t *packet = g_sends[i].data;
        TEST_CHECK(g_sends[i].bytes ==
                   (size_t)TPKT_HEADER_BYTES + (size_t)TPKT_PAYLOAD_STATUS_BYTES);
        TEST_CHECK(test_load_le16(&packet[TPKT_HDR_PACKET_TYPE_OFFSET]) == TPKT_TYPE_STATUS);
        TEST_CHECK(test_load_le16(&packet[TPKT_HDR_FLAGS_OFFSET]) ==
                   TPKT_FLAG_STATUS_DIAGNOSTIC_MASK);
        TEST_CHECK(test_load_le32(&packet[TPKT_HDR_SEQ_OFFSET]) == 0u);
        TEST_CHECK(test_load_le64(&packet[TPKT_HDR_TIMESTAMP_OFFSET]) == (uint64_t)(i + 1u));
        TEST_CHECK(test_load_le64(&packet[TPKT_HEADER_BYTES + TPKT_STATUS_SAMPLE_COUNT_OFFSET]) ==
                   (uint64_t)(i + 1u));
    }
    return true;
}

static bool test_unsigned_cli_parser(void)
{
    uint64_t parsed = 0u;
    TEST_CHECK(!trecap_streamer_parse_u64("-1", UINT64_MAX, &parsed));
    TEST_CHECK(trecap_streamer_parse_u64("18446744073709551615", UINT64_MAX, &parsed));
    TEST_CHECK(parsed == UINT64_MAX);
    return true;
}

int main(void)
{
    const bool ok = test_iomem_fail_closed() && test_embedded_nul_config_rejected() &&
                    test_fail_closed_reset_and_identity_cleanup() && test_command_budget() &&
                    test_valid_packet_types() && test_wrap_record() &&
                    test_oversized_and_hostile_length() &&
                    test_malformed_latch_and_rearm() && test_invalid_atomic_pointer_latches() &&
                    test_malformed_mmio_failure_stays_latched() &&
                    test_commit_and_send_failures() && test_dummy_counter() &&
                    test_unsigned_cli_parser();
    if (!ok) {
        return 1;
    }
    printf("STEP13_HPS_TRANSPORT_PASS iomem_fail_closed=3 embedded_nul=1 reset_fail_closed=1 "
           "identity_read_only=1 command_budget=64 valid_types=5 wrap=1 oversized=1 "
           "malformed_once=1 malformed_mmio_fail=1 invalid_wr=2 commit_failure=1 "
           "send_failure=2 dummy_status=3 unsigned_cli=1\n");
    return 0;
}
