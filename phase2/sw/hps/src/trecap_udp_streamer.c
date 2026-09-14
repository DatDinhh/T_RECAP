/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS UDP streamer orchestration.
 * File class: [1] hand-written.
 *
 * This file owns the top-level userspace control loop for the HPS transport
 * program. It deliberately delegates low-level CSR access, DDR-ring parsing,
 * UDP sending, PC command validation, and STATUS patching to the API layers in
 * the HPS public headers. It does not duplicate CSR offsets, packet IDs, wire-field
 * offsets, payload-size constants, or transport version constants.
 */

#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "command_server.h"
#include "command_bridge.h"
#include "csr_map.h"
#include "ring_reader.h"
#include "status_patch.h"
#include "trecap_hps_config.h"
#include "udp_sender.h"

#define TRECAP_STREAMER_ERRBUF_BYTES 256u
#define TRECAP_STREAMER_DEFAULT_POLL_US 1000u
#define TRECAP_STREAMER_DEFAULT_MAX_RECORDS 0u
#define TRECAP_STREAMER_DEFAULT_SAMPLE_RATE_HZ 0u
#define TRECAP_STREAMER_DUMMY_POLL_US 100000u
#define TRECAP_STREAMER_EXIT_MALFORMED_LATCHED 3
#define TRECAP_STREAMER_COMMIT_MAX_POLLS UINT32_C(1000000)
#define TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS UINT32_C(64)
#define TRECAP_STREAMER_RING_BUDGET_PER_PASS UINT32_C(64)

int trecap_udp_streamer_main(int argc, char **argv);

static volatile sig_atomic_t g_stop_requested = 0;

typedef struct trecap_streamer_cli {
    const char *config_path;
    bool dry_run;
    bool once;
    bool no_enable;
    bool no_commands;
    bool quiet;
    bool verbose;
    bool allow_any_command_source;
    bool stop_on_malformed;
    bool dummy_udp_counter;
    bool poll_sleep_us_overridden;
    uint64_t max_records;
    uint32_t poll_sleep_us;
    uint32_t packet_enable;
    uint32_t wave_decim;
    uint32_t spec_mode;
    uint32_t spec_shift;
    uint32_t source_mode;
    uint32_t sample_rate_hz;
    uint64_t thr2;
} trecap_streamer_cli_t;

typedef struct trecap_streamer_state {
    trecap_streamer_cli_t cli;
    trecap_hps_runtime_config_t cfg;
    trecap_csr_window_t csr;
    trecap_ring_mapping_t ring_mapping;
    trecap_ring_reader_t ring_reader;
    trecap_udp_sender_t udp_sender;
    trecap_command_server_t command_server;
    trecap_command_bridge_t command_bridge;
    bool csr_mapped;
    bool csr_identity_verified;
    bool ring_mapped;
    bool udp_open;
    bool command_open;
    bool command_bridge_initialized;
    bool transport_enabled;
    uint64_t active_thr2;
    uint32_t active_packet_enable;
    uint32_t active_wave_decim;
    uint32_t active_spec_mode;
    uint32_t active_spec_shift;
    uint32_t active_source_mode;
    uint64_t records_consumed;
    uint64_t records_sent_or_dropped;
} trecap_streamer_state_t;

static void trecap_streamer_signal_handler(int signum)
{
    (void)signum;
    g_stop_requested = 1;
}

static void trecap_streamer_install_signal_handlers(void)
{
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = trecap_streamer_signal_handler;
    (void)sigemptyset(&action.sa_mask);
    action.sa_flags = 0;
    (void)sigaction(SIGINT, &action, NULL);
    (void)sigaction(SIGTERM, &action, NULL);
}

static void trecap_streamer_sleep_us(uint32_t sleep_us)
{
    if (sleep_us == 0u) {
        return;
    }

    struct timespec req;
    req.tv_sec = (time_t)(sleep_us / 1000000u);
    req.tv_nsec = (long)((sleep_us % 1000000u) * 1000u);

    while (nanosleep(&req, &req) != 0) {
        if (errno != EINTR || g_stop_requested != 0) {
            break;
        }
    }
}

static void trecap_streamer_usage(FILE *out, const char *argv0)
{
    const char *prog = (argv0 != NULL) ? argv0 : "trecap_udp_streamer";
    fprintf(out,
            "Usage: %s [options]\n"
            "\n"
            "HPS userspace streamer for T-RECAP Phase 2 telemetry.\n"
            "\n"
            "Options:\n"
            "  --config <path>               Runtime config JSON.\n"
            "  --dry-run                     Load config and print planned setup only.\n"
            "  --once                        Exit after the first non-empty service pass.\n"
            "  --max-records <n>             Exit after consuming n normal records; 0 = unlimited.\n"
            "  --poll-us <n>                 Idle sleep between polls, default %u.\n"
            "  --no-enable                   Configure but leave telemetry writer disabled.\n"
            "  --no-commands                 Do not open the command UDP listener.\n"
            "  --allow-any-command-source    Lab mode: pin first fully valid PING endpoint.\n"
            "  --stop-on-malformed           Exit 3 after latching malformed transport (debug override).\n"
            "  --dummy-udp-counter           M0: send monotonic diagnostic STATUS without CSR/DDR.\n"
            "  --status-only                 Enable STATUS packets only. This is the default.\n"
            "  --full-demo                   Enable WAVE, SPEC, METRICS, and STATUS.\n"
            "  --packet-enable <mask>        Override PACKET_ENABLE mask.\n"
            "  --wave-decim <n>              Set WAVE_DECIM, valid 1..65535.\n"
            "  --spec-mode <0|1|2>           0 disabled, 1 SPEC64, 2 SPEC129.\n"
            "  --spec-shift <n>              Set SPEC_SHIFT, valid 0..55 baseline.\n"
            "  --source-mode <0..3>          Set source-mode shadow/commit.\n"
            "  --thr2 <n>                    Set 56-bit THR2 through shadow/commit.\n"
            "  --sample-rate-hz <n>          Diagnostic STATUS sample-rate field.\n"
            "  --verbose                     Print bring-up progress.\n"
            "  --quiet                       Print only errors.\n"
            "  --help                        Show this help.\n",
            prog,
            (unsigned)TRECAP_STREAMER_DEFAULT_POLL_US);
}

static bool trecap_streamer_parse_u64(const char *text, uint64_t max_value, uint64_t *out)
{
    if (text == NULL || text[0] == '\0' || text[0] == '-' || out == NULL) {
        return false;
    }

    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(text, &end, 0);
    if (errno != 0 || end == text || (end != NULL && *end != '\0')) {
        return false;
    }
    if ((uint64_t)parsed > max_value) {
        return false;
    }
    *out = (uint64_t)parsed;
    return true;
}

static bool trecap_streamer_parse_u32(const char *text, uint32_t max_value, uint32_t *out)
{
    uint64_t tmp = 0u;
    if (!trecap_streamer_parse_u64(text, (uint64_t)max_value, &tmp) || out == NULL) {
        return false;
    }
    *out = (uint32_t)tmp;
    return true;
}

static const char *trecap_streamer_need_value(int argc, char **argv, int *index)
{
    if (index == NULL || argv == NULL || *index + 1 >= argc) {
        return NULL;
    }
    *index += 1;
    return argv[*index];
}

static void trecap_streamer_cli_set_defaults(trecap_streamer_cli_t *cli)
{
    if (cli == NULL) {
        return;
    }
    memset(cli, 0, sizeof(*cli));
    cli->config_path = TRECAP_HPS_DEFAULT_CONFIG;
    cli->max_records = TRECAP_STREAMER_DEFAULT_MAX_RECORDS;
    cli->poll_sleep_us = TRECAP_STREAMER_DEFAULT_POLL_US;
    cli->packet_enable = TCSR_PACKET_ENABLE_STATUS_EN_MASK;
    cli->wave_decim = TCSR_WAVE_DECIM_MIN;
    cli->spec_mode = TCSR_SPEC_MODE_SPEC_DISABLED;
    cli->spec_shift = 0u;
    cli->source_mode = TCSR_SOURCE_MODE_BRAM_REPLAY;
    cli->sample_rate_hz = TRECAP_STREAMER_DEFAULT_SAMPLE_RATE_HZ;
    cli->thr2 = 0u;
}

static int trecap_streamer_parse_args(int argc, char **argv, trecap_streamer_cli_t *cli)
{
    if (cli == NULL) {
        return 2;
    }
    trecap_streamer_cli_set_defaults(cli);

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        const char *value = NULL;
        if (arg == NULL) {
            return 2;
        }

        if (strcmp(arg, "--help") == 0 || strcmp(arg, "-h") == 0) {
            trecap_streamer_usage(stdout, argv[0]);
            return 1;
        } else if (strcmp(arg, "--config") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL) {
                fprintf(stderr, "ERROR: --config requires a path\n");
                return 2;
            }
            cli->config_path = value;
        } else if (strcmp(arg, "--dry-run") == 0) {
            cli->dry_run = true;
        } else if (strcmp(arg, "--once") == 0) {
            cli->once = true;
        } else if (strcmp(arg, "--no-enable") == 0) {
            cli->no_enable = true;
        } else if (strcmp(arg, "--no-commands") == 0) {
            cli->no_commands = true;
        } else if (strcmp(arg, "--allow-any-command-source") == 0) {
            cli->allow_any_command_source = true;
        } else if (strcmp(arg, "--stop-on-malformed") == 0) {
            cli->stop_on_malformed = true;
        } else if (strcmp(arg, "--dummy-udp-counter") == 0) {
            cli->dummy_udp_counter = true;
        } else if (strcmp(arg, "--status-only") == 0) {
            cli->packet_enable = TCSR_PACKET_ENABLE_STATUS_EN_MASK;
            cli->spec_mode = TCSR_SPEC_MODE_SPEC_DISABLED;
        } else if (strcmp(arg, "--full-demo") == 0) {
            cli->packet_enable = TCSR_PACKET_ENABLE_WAVE_EN_MASK |
                                 TCSR_PACKET_ENABLE_SPEC_EN_MASK |
                                 TCSR_PACKET_ENABLE_METRICS_EN_MASK |
                                 TCSR_PACKET_ENABLE_STATUS_EN_MASK;
            cli->spec_mode = TCSR_SPEC_MODE_SPEC64;
        } else if (strcmp(arg, "--verbose") == 0) {
            cli->verbose = true;
        } else if (strcmp(arg, "--quiet") == 0) {
            cli->quiet = true;
        } else if (strcmp(arg, "--max-records") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u64(value, UINT64_MAX, &cli->max_records)) {
                fprintf(stderr, "ERROR: --max-records requires an unsigned integer\n");
                return 2;
            }
        } else if (strcmp(arg, "--poll-us") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->poll_sleep_us)) {
                fprintf(stderr, "ERROR: --poll-us requires a uint32 value\n");
                return 2;
            }
            cli->poll_sleep_us_overridden = true;
        } else if (strcmp(arg, "--packet-enable") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->packet_enable) ||
                !trecap_csr_packet_enable_is_valid(cli->packet_enable)) {
                fprintf(stderr, "ERROR: --packet-enable contains reserved or invalid bits\n");
                return 2;
            }
        } else if (strcmp(arg, "--wave-decim") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->wave_decim) ||
                !trecap_csr_wave_decim_is_valid(cli->wave_decim)) {
                fprintf(stderr, "ERROR: --wave-decim is outside valid range\n");
                return 2;
            }
        } else if (strcmp(arg, "--spec-mode") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->spec_mode) ||
                !trecap_csr_spec_mode_is_valid(cli->spec_mode)) {
                fprintf(stderr, "ERROR: --spec-mode must be 0, 1, or 2\n");
                return 2;
            }
        } else if (strcmp(arg, "--spec-shift") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->spec_shift) ||
                !trecap_csr_spec_shift_is_valid(cli->spec_shift)) {
                fprintf(stderr, "ERROR: --spec-shift is outside valid range\n");
                return 2;
            }
        } else if (strcmp(arg, "--source-mode") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->source_mode) ||
                !trecap_csr_source_mode_is_valid(cli->source_mode)) {
                fprintf(stderr, "ERROR: --source-mode must be 0, 1, 2, or 3\n");
                return 2;
            }
        } else if (strcmp(arg, "--sample-rate-hz") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u32(value, UINT32_MAX, &cli->sample_rate_hz)) {
                fprintf(stderr, "ERROR: --sample-rate-hz requires a uint32 value\n");
                return 2;
            }
        } else if (strcmp(arg, "--thr2") == 0) {
            value = trecap_streamer_need_value(argc, argv, &i);
            if (value == NULL || !trecap_streamer_parse_u64(value, UINT64_MAX, &cli->thr2) ||
                !trecap_csr_thr2_is_valid(cli->thr2)) {
                fprintf(stderr, "ERROR: --thr2 is outside the generated threshold range\n");
                return 2;
            }
        } else {
            fprintf(stderr, "ERROR: unknown option: %s\n", arg);
            trecap_streamer_usage(stderr, argv[0]);
            return 2;
        }
    }

    if (cli->quiet && cli->verbose) {
        cli->verbose = false;
    }
    if (cli->dummy_udp_counter && !cli->poll_sleep_us_overridden) {
        cli->poll_sleep_us = TRECAP_STREAMER_DUMMY_POLL_US;
    }
    return 0;
}

static void trecap_streamer_log(const trecap_streamer_state_t *state, const char *message)
{
    if (state != NULL && !state->cli.quiet && message != NULL) {
        fprintf(stderr, "%s\n", message);
    }
}

static void trecap_streamer_log_error(const char *prefix, const char *detail)
{
    if (prefix == NULL) {
        prefix = "ERROR";
    }
    if (detail == NULL || detail[0] == '\0') {
        fprintf(stderr, "%s\n", prefix);
    } else {
        fprintf(stderr, "%s: %s\n", prefix, detail);
    }
}

static void trecap_streamer_print_config(const trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return;
    }
    fprintf(stdout, "T-RECAP HPS streamer configuration\n");
    fprintf(stdout, "  config_path             %s\n", state->cli.config_path);
    fprintf(stdout, "  csr_base_phys           0x%016" PRIx64 "\n", state->cfg.csr_base_phys);
    fprintf(stdout, "  csr_span_bytes          %" PRIu32 "\n", state->cfg.csr_span_bytes);
    fprintf(stdout, "  ring_base_hps_phys      0x%016" PRIx64 "\n", state->cfg.ring_base_hps_phys);
    fprintf(stdout, "  ring_base_fpga          0x%016" PRIx64 "\n", state->cfg.ring_base_fpga);
    fprintf(stdout, "  ring_size_bytes         %" PRIu32 "\n", state->cfg.ring_size_bytes);
    fprintf(stdout, "  ring_guard_bytes        %" PRIu32 "\n", state->cfg.ring_guard_bytes);
    fprintf(stdout, "  telemetry_dst           %s:%" PRIu16 "\n",
            state->cfg.telemetry_dst_ip,
            state->cfg.telemetry_dst_port);
    fprintf(stdout, "  command_listen_port     %" PRIu16 "\n", state->cfg.command_listen_port);
    fprintf(stdout, "  trusted_command_peer    %s\n", state->cfg.trusted_command_peer);
    fprintf(stdout, "  trusted_command_port    %" PRIu16 "\n",
            state->cfg.trusted_command_peer_port);
    fprintf(stdout, "  transport_version       %" PRIu16 ".%" PRIu16 "\n",
            state->cfg.transport_version_major,
            state->cfg.transport_version_minor);
    fprintf(stdout, "  packet_enable           0x%08" PRIx32 "\n", state->cli.packet_enable);
    fprintf(stdout, "  wave_decim              %" PRIu32 "\n", state->cli.wave_decim);
    fprintf(stdout, "  spec_mode               %" PRIu32 "\n", state->cli.spec_mode);
    fprintf(stdout, "  spec_shift              %" PRIu32 "\n", state->cli.spec_shift);
    fprintf(stdout, "  source_mode             %" PRIu32 "\n", state->cli.source_mode);
    fprintf(stdout, "  thr2                    0x%014" PRIx64 "\n", state->cli.thr2);
    fprintf(stdout, "  dry_run                 %s\n", state->cli.dry_run ? "yes" : "no");
    fprintf(stdout, "  no_enable               %s\n", state->cli.no_enable ? "yes" : "no");
    fprintf(stdout, "  no_commands             %s\n", state->cli.no_commands ? "yes" : "no");
    fprintf(stdout, "  dummy_udp_counter       %s\n",
            state->cli.dummy_udp_counter ? "yes" : "no");
}

static int trecap_streamer_load_config(trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return 2;
    }

    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';
    trecap_hps_config_set_defaults(&state->cfg);

    trecap_hps_config_status_t cfg_status = trecap_hps_config_load_file(
        state->cli.config_path,
        &state->cfg,
        err_buf,
        sizeof(err_buf));
    if (cfg_status != TRECAP_HPS_CONFIG_OK) {
        trecap_streamer_log_error(trecap_hps_config_status_string(cfg_status), err_buf);
        return 2;
    }

    cfg_status = trecap_hps_config_validate(&state->cfg, err_buf, sizeof(err_buf));
    if (cfg_status != TRECAP_HPS_CONFIG_OK) {
        trecap_streamer_log_error(trecap_hps_config_status_string(cfg_status), err_buf);
        return 2;
    }

    if (state->cli.stop_on_malformed) {
        state->cfg.stop_on_malformed_record = true;
    }
    return 0;
}

static trecap_csr_status_t trecap_streamer_wait_commit_clear(trecap_streamer_state_t *state,
                                                             uint32_t pending_mask)
{
    if (state == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    if (pending_mask == 0u) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    for (uint32_t poll = 0u; poll < TRECAP_STREAMER_COMMIT_MAX_POLLS; ++poll) {
        uint32_t status_word = 0u;
        const trecap_csr_status_t status =
            trecap_csr_read32(&state->csr, TCSR_STATUS_OFFSET, &status_word);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        if ((status_word & pending_mask) == 0u) {
            return TRECAP_CSR_OK;
        }
    }
    return TRECAP_CSR_ERR_TIMEOUT;
}

static trecap_csr_status_t trecap_streamer_configure_initial_csr(trecap_streamer_state_t *state,
                                                                 char *err_buf,
                                                                 size_t err_buf_len)
{
    if (state == NULL) {
        if (err_buf != NULL && err_buf_len > 0u) {
            (void)snprintf(err_buf, err_buf_len, "null streamer state");
        }
        return TRECAP_CSR_ERR_NULL;
    }

    trecap_ring_status_t ring_status = trecap_ring_reader_reset_transport(&state->ring_reader);
    if (ring_status != TRECAP_RING_OK) {
        if (err_buf != NULL && err_buf_len > 0u) {
            (void)snprintf(err_buf, err_buf_len, "ring reset failed: %s",
                           trecap_ring_status_string(ring_status));
        }
        return TRECAP_CSR_ERR_IO;
    }

    ring_status = trecap_ring_reader_configure_fpga_ring(&state->ring_reader,
                                                         state->cfg.ring_base_fpga,
                                                         state->cfg.ring_size_bytes,
                                                         state->cfg.ring_guard_bytes);
    if (ring_status != TRECAP_RING_OK) {
        if (err_buf != NULL && err_buf_len > 0u) {
            (void)snprintf(err_buf, err_buf_len, "ring configure failed: %s",
                           trecap_ring_status_string(ring_status));
        }
        return TRECAP_CSR_ERR_IO;
    }

    ring_status = trecap_ring_reader_commit_rd(&state->ring_reader, 0u);
    if (ring_status != TRECAP_RING_OK) {
        if (err_buf != NULL && err_buf_len > 0u) {
            (void)snprintf(err_buf, err_buf_len, "initial Rd commit failed: %s",
                           trecap_ring_status_string(ring_status));
        }
        return TRECAP_CSR_ERR_IO;
    }

    uint64_t producer_ptr = UINT64_MAX;
    ring_status = trecap_ring_reader_snapshot_wr(&state->ring_reader, &producer_ptr);
    if ((ring_status != TRECAP_RING_EMPTY && ring_status != TRECAP_RING_OK) || producer_ptr != 0u) {
        if (err_buf != NULL && err_buf_len > 0u) {
            (void)snprintf(err_buf,
                           err_buf_len,
                           "initial W verification failed: status=%s W=0x%016" PRIx64,
                           trecap_ring_status_string(ring_status),
                           producer_ptr);
        }
        return TRECAP_CSR_ERR_IO;
    }

    trecap_csr_status_t csr_status = trecap_csr_set_thr2(&state->csr, state->cli.thr2);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }
    csr_status = trecap_csr_set_source_mode(&state->csr, state->cli.source_mode);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }
    csr_status = trecap_csr_set_wave_decim(&state->csr, state->cli.wave_decim);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }
    csr_status = trecap_csr_set_spec_mode_shift(&state->csr,
                                                state->cli.spec_mode,
                                                state->cli.spec_shift);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }
    csr_status = trecap_csr_set_packet_enable(&state->csr, state->cli.packet_enable);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }

    csr_status = trecap_streamer_wait_commit_clear(
        state,
        TCSR_STATUS_THR2_COMMIT_PENDING_MASK | TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK);
    if (csr_status != TRECAP_CSR_OK) {
        return csr_status;
    }

    state->active_thr2 = state->cli.thr2;
    state->active_packet_enable = state->cli.packet_enable;
    state->active_wave_decim = state->cli.wave_decim;
    state->active_spec_mode = state->cli.spec_mode;
    state->active_spec_shift = state->cli.spec_shift;
    state->active_source_mode = state->cli.source_mode;

    if (!state->cli.no_enable) {
        /* Step 12 bring-up order: arm the DDR writer only after Rd/W are
         * verified, then enable telemetry as the final admission gate. */
        csr_status = trecap_csr_set_control_levels(&state->csr, false, true);
        if (csr_status != TRECAP_CSR_OK) {
            return csr_status;
        }
        csr_status = trecap_csr_require_control_levels(&state->csr, false, true);
        if (csr_status != TRECAP_CSR_OK) {
            (void)trecap_csr_set_control_levels(&state->csr, false, false);
            return csr_status;
        }
        csr_status = trecap_csr_set_control_levels(&state->csr, true, true);
        if (csr_status != TRECAP_CSR_OK) {
            (void)trecap_csr_set_control_levels(&state->csr, false, false);
            return csr_status;
        }
        csr_status = trecap_csr_require_control_levels(&state->csr, true, true);
        if (csr_status != TRECAP_CSR_OK) {
            (void)trecap_csr_set_control_levels(&state->csr, false, false);
            return csr_status;
        }
        state->transport_enabled = true;
    }
    return TRECAP_CSR_OK;
}

static int trecap_streamer_open_resources(trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return 2;
    }

    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';

    trecap_hps_config_status_t reservation_status =
        trecap_hps_config_validate_live_ddr_reservation(&state->cfg,
                                                        err_buf,
                                                        sizeof(err_buf));
    if (reservation_status != TRECAP_HPS_CONFIG_OK) {
        trecap_streamer_log_error(trecap_hps_config_status_string(reservation_status), err_buf);
        return 2;
    }

    trecap_csr_status_t csr_status = trecap_csr_map_physical(state->cfg.csr_base_phys,
                                                             state->cfg.csr_span_bytes,
                                                             &state->csr);
    if (csr_status != TRECAP_CSR_OK) {
        trecap_streamer_log_error(trecap_csr_status_string(csr_status), "CSR mmap failed");
        return 2;
    }
    state->csr_mapped = true;

    uint32_t id_value = 0u;
    uint32_t version_value = 0u;
    csr_status = trecap_csr_require_id_version(&state->csr, &id_value, &version_value);
    if (csr_status != TRECAP_CSR_OK) {
        (void)snprintf(err_buf,
                       sizeof(err_buf),
                       "ID=0x%08" PRIx32 " VERSION=0x%08" PRIx32,
                       id_value,
                       version_value);
        trecap_streamer_log_error(trecap_csr_status_string(csr_status), err_buf);
        return 2;
    }
    state->csr_identity_verified = true;

    trecap_ring_status_t ring_status = trecap_ring_map_physical(state->cfg.ring_base_hps_phys,
                                                                state->cfg.ring_size_bytes,
                                                                state->cfg.allow_cached_ring_mapping,
                                                                &state->ring_mapping);
    if (ring_status != TRECAP_RING_OK) {
        trecap_streamer_log_error(trecap_ring_status_string(ring_status), "DDR ring mmap failed");
        return 2;
    }
    state->ring_mapped = true;

    trecap_ring_reader_config_t ring_cfg;
    trecap_ring_reader_config_set_defaults(&ring_cfg, &state->cfg);
    ring_cfg.stop_on_malformed_record = state->cfg.stop_on_malformed_record;
    trecap_ring_reader_init(&state->ring_reader, &state->csr, &state->ring_mapping, &ring_cfg);

    trecap_udp_sender_config_t udp_cfg;
    trecap_udp_sender_config_set_defaults(&udp_cfg, &state->cfg);
    trecap_udp_status_t udp_status = trecap_udp_sender_open(&udp_cfg,
                                                            &state->udp_sender,
                                                            err_buf,
                                                            sizeof(err_buf));
    if (udp_status != TRECAP_UDP_OK) {
        trecap_streamer_log_error(trecap_udp_status_string(udp_status), err_buf);
        return 2;
    }
    state->udp_open = true;

    if (!state->cli.no_commands) {
        trecap_command_server_config_t cmd_cfg;
        trecap_command_server_config_set_defaults(&cmd_cfg, &state->cfg);
        if (state->cli.allow_any_command_source) {
            cmd_cfg.accept_any_source_for_lab_debug = false;
            cmd_cfg.require_trusted_peer = true;
            cmd_cfg.learn_trusted_peer_on_valid_ping = true;
            (void)snprintf(cmd_cfg.listen_ip, sizeof(cmd_cfg.listen_ip), "%s", "0.0.0.0");
            cmd_cfg.trusted_peer_ip[0] = '\0';
            cmd_cfg.trusted_peer_port = 0u;
        }
        trecap_cmd_status_t cmd_status = trecap_command_server_open(&cmd_cfg,
                                                                    &state->command_server,
                                                                    err_buf,
                                                                    sizeof(err_buf));
        if (cmd_status != TRECAP_CMD_OK) {
            trecap_streamer_log_error(trecap_cmd_status_string(cmd_status), err_buf);
            return 2;
        }
        state->command_open = true;
    }

    csr_status = trecap_streamer_configure_initial_csr(state, err_buf, sizeof(err_buf));
    if (csr_status != TRECAP_CSR_OK) {
        trecap_streamer_log_error(trecap_csr_status_string(csr_status), err_buf);
        return 2;
    }

    trecap_command_bridge_bindings_t bridge_bindings;
    memset(&bridge_bindings, 0, sizeof(bridge_bindings));
    bridge_bindings.csr = &state->csr;
    bridge_bindings.ring_reader = &state->ring_reader;
    bridge_bindings.runtime_config = &state->cfg;
    bridge_bindings.command_counters = &state->command_server.counters;
    bridge_bindings.udp_counters = &state->udp_sender.counters;
    bridge_bindings.transport_enabled = &state->transport_enabled;
    bridge_bindings.active_thr2 = &state->active_thr2;
    bridge_bindings.active_packet_enable = &state->active_packet_enable;
    bridge_bindings.active_wave_decim = &state->active_wave_decim;
    bridge_bindings.active_spec_mode = &state->active_spec_mode;
    bridge_bindings.active_spec_shift = &state->active_spec_shift;
    bridge_bindings.active_source_mode = &state->active_source_mode;
    bridge_bindings.records_consumed = &state->records_consumed;
    bridge_bindings.records_sent_or_dropped = &state->records_sent_or_dropped;
    const trecap_command_bridge_status_t bridge_status =
        trecap_command_bridge_init(&state->command_bridge,
                                   &bridge_bindings,
                                   NULL,
                                   NULL);
    if (bridge_status != TRECAP_COMMAND_BRIDGE_OK) {
        trecap_streamer_log_error("TRECAP_COMMAND_BRIDGE_ERR",
                                  "failed to initialize transactional command bridge");
        return 2;
    }
    state->command_bridge_initialized = true;

    if (state->cli.verbose) {
        trecap_streamer_log(state, "HPS streamer resources opened and transport configured");
    }
    return 0;
}

static int trecap_streamer_open_dummy_udp(trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return 2;
    }
    trecap_udp_sender_config_t udp_cfg;
    trecap_udp_sender_config_set_defaults(&udp_cfg, &state->cfg);
    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';
    const trecap_udp_status_t udp_status =
        trecap_udp_sender_open(&udp_cfg, &state->udp_sender, err_buf, sizeof(err_buf));
    if (udp_status != TRECAP_UDP_OK) {
        trecap_streamer_log_error(trecap_udp_status_string(udp_status), err_buf);
        return 2;
    }
    state->udp_open = true;
    return 0;
}

static void trecap_streamer_close_resources(trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return;
    }
    if (state->csr_mapped && state->csr_identity_verified) {
        (void)trecap_csr_set_control_levels(&state->csr, false, false);
    }
    if (state->command_open) {
        trecap_command_server_close(&state->command_server);
        state->command_open = false;
    }
    if (state->udp_open) {
        trecap_udp_sender_close(&state->udp_sender);
        state->udp_open = false;
    }
    if (state->ring_mapped) {
        trecap_ring_unmap(&state->ring_mapping);
        state->ring_mapped = false;
    }
    if (state->csr_mapped) {
        trecap_csr_unmap(&state->csr);
        state->csr_mapped = false;
        state->csr_identity_verified = false;
    }
}

static void trecap_streamer_make_hps_counters(trecap_streamer_state_t *state,
                                              trecap_status_hps_counters_t *out)
{
    if (state == NULL || out == NULL) {
        return;
    }

    trecap_csr_counters_t csr_counters;
    memset(&csr_counters, 0, sizeof(csr_counters));
    if (state->csr_mapped) {
        (void)trecap_csr_read_counters(&state->csr, &csr_counters);
    }

    trecap_status_hps_counters_from_runtime(&state->udp_sender.counters,
                                            &state->ring_reader.counters,
                                            state->command_server.counters.hps_command_reject_count,
                                            (uint64_t)csr_counters.csr_command_reject_count,
                                            out);
}

static void trecap_streamer_make_status_inputs(trecap_streamer_state_t *state,
                                               bool diagnostic,
                                               trecap_status_patch_inputs_t *inputs)
{
    if (state == NULL || inputs == NULL) {
        return;
    }
    memset(inputs, 0, sizeof(*inputs));

    trecap_csr_core_counts_t core_counts;
    memset(&core_counts, 0, sizeof(core_counts));
    trecap_csr_counters_t csr_counters;
    memset(&csr_counters, 0, sizeof(csr_counters));

    uint32_t overflow_flags = 0u;
    if (state->csr_mapped) {
        uint32_t frame_lo = 0u;
        uint32_t frame_hi = 0u;
        uint32_t sample_lo = 0u;
        uint32_t sample_hi = 0u;
        /* PING is architecturally read-only. Read the most recent retained
         * snapshot words without pulsing CORE_COUNT_SNAPSHOT. */
        if (trecap_csr_read32(&state->csr, TCSR_FRAME_COUNT_SNAP_LO_OFFSET, &frame_lo) ==
                TRECAP_CSR_OK &&
            trecap_csr_read32(&state->csr, TCSR_FRAME_COUNT_SNAP_HI_OFFSET, &frame_hi) ==
                TRECAP_CSR_OK &&
            trecap_csr_read32(&state->csr, TCSR_SAMPLE_COUNT_SNAP_LO_OFFSET, &sample_lo) ==
                TRECAP_CSR_OK &&
            trecap_csr_read32(&state->csr, TCSR_SAMPLE_COUNT_SNAP_HI_OFFSET, &sample_hi) ==
                TRECAP_CSR_OK) {
            core_counts.frame_count = trecap_csr_join_u64(frame_lo, frame_hi);
            core_counts.sample_count = trecap_csr_join_u64(sample_lo, sample_hi);
        }
        (void)trecap_csr_read_counters(&state->csr, &csr_counters);
        (void)trecap_csr_read32(&state->csr, TCSR_OVERFLOW_FLAGS_OFFSET, &overflow_flags);
    }

    inputs->fpga.sample_count = core_counts.sample_count;
    inputs->fpga.frame_count = core_counts.frame_count;
    inputs->fpga.source_mode = state->active_source_mode;
    /* Synthesized HPS STATUS cannot infer physical cadence or ADC manual mode from
     * the current CSR ABI. Zero means rate unavailable; normal FPGA STATUS owns
     * the actual cadence. The separate dummy-UDP generator retains its CLI rate. */
    inputs->fpga.sample_rate_hz = 0u;
    inputs->fpga.packet_enable = state->active_packet_enable;
    inputs->fpga.dma_drop_count = csr_counters.dma_drop_count;
    inputs->fpga.overflow_flags = overflow_flags;
    inputs->fpga.active_thr2 = state->active_thr2;
    inputs->fpga.packet_fifo_drop_count = csr_counters.packet_fifo_drop_count;
    inputs->fpga.valid = true;
    inputs->diagnostic = diagnostic;
    trecap_streamer_make_hps_counters(state, &inputs->hps);
}

static bool trecap_streamer_build_diagnostic_status(trecap_streamer_state_t *state,
                                                    uint8_t *datagram,
                                                    size_t datagram_capacity,
                                                    size_t *datagram_bytes_out)
{
    if (state == NULL || datagram == NULL || datagram_bytes_out == NULL) {
        return false;
    }
    *datagram_bytes_out = 0u;
    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';

    trecap_status_patch_inputs_t inputs;
    trecap_streamer_make_status_inputs(state, true, &inputs);

    trecap_status_patch_status_t patch_status = trecap_status_build_diagnostic(datagram,
                                                                                datagram_capacity,
                                                                                &inputs,
                                                                                datagram_bytes_out,
                                                                                err_buf,
                                                                                sizeof(err_buf));
    if (patch_status != TRECAP_STATUS_PATCH_OK) {
        if (!state->cli.quiet) {
            trecap_streamer_log_error(trecap_status_patch_status_string(patch_status), err_buf);
        }
        return false;
    }
    return true;
}

static int trecap_streamer_run_dummy_udp_counter(trecap_streamer_state_t *state)
{
    if (state == NULL || !state->udp_open) {
        return 2;
    }

    uint64_t counter = 0u;
    while (g_stop_requested == 0) {
        ++counter;
        trecap_status_patch_inputs_t inputs;
        memset(&inputs, 0, sizeof(inputs));
        inputs.fpga.sample_count = counter;
        inputs.fpga.frame_count = counter;
        inputs.fpga.source_mode = TCSR_SOURCE_MODE_DIAGNOSTIC;
        inputs.fpga.sample_rate_hz = state->cli.sample_rate_hz;
        inputs.fpga.packet_enable = TCSR_PACKET_ENABLE_STATUS_EN_MASK;
        inputs.fpga.valid = true;
        inputs.diagnostic = true;
        trecap_status_hps_counters_from_runtime(&state->udp_sender.counters,
                                                &state->ring_reader.counters,
                                                0u,
                                                0u,
                                                &inputs.hps);

        uint8_t datagram[TPKT_HEADER_BYTES + TPKT_PAYLOAD_STATUS_BYTES];
        size_t datagram_bytes = 0u;
        char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
        err_buf[0] = '\0';
        const trecap_status_patch_status_t patch_status =
            trecap_status_build_diagnostic(datagram,
                                           sizeof(datagram),
                                           &inputs,
                                           &datagram_bytes,
                                           err_buf,
                                           sizeof(err_buf));
        if (patch_status != TRECAP_STATUS_PATCH_OK) {
            trecap_streamer_log_error(trecap_status_patch_status_string(patch_status), err_buf);
            return 2;
        }

        const trecap_udp_send_result_t send_result =
            trecap_udp_sender_send_datagram(&state->udp_sender, datagram, datagram_bytes);
        if (send_result.status != TRECAP_UDP_OK && send_result.status != TRECAP_UDP_DROPPED) {
            trecap_streamer_log_error(trecap_udp_status_string(send_result.status),
                                      "dummy diagnostic STATUS send failed");
            return 2;
        }
        state->records_sent_or_dropped += 1u;

        if (state->cli.once ||
            (state->cli.max_records != 0u && counter >= state->cli.max_records)) {
            break;
        }
        trecap_streamer_sleep_us(state->cli.poll_sleep_us);
    }
    return 0;
}

static trecap_udp_send_result_t trecap_streamer_send_record_view(trecap_streamer_state_t *state,
                                                                 const trecap_ring_record_view_t *view)
{
    if (state == NULL || view == NULL) {
        trecap_udp_send_result_t result = trecap_udp_send_result_init();
        result.status = TRECAP_UDP_ERR_NULL;
        return result;
    }

    if (view->packet_type != TPKT_TYPE_STATUS) {
        return trecap_udp_sender_send_record_bytes(&state->udp_sender,
                                                   view->record_bytes,
                                                   view->payload_bytes);
    }

    uint8_t datagram[TPKT_HEADER_BYTES + TPKT_PAYLOAD_STATUS_BYTES];
    if (view->udp_datagram_bytes != (uint32_t)sizeof(datagram)) {
        trecap_udp_send_result_t result = trecap_udp_send_result_init();
        result.status = TRECAP_UDP_ERR_OVERSIZED;
        result.datagram_bytes = (size_t)view->udp_datagram_bytes;
        result.consumed_record = true;
        state->udp_sender.counters.oversized_count += 1u;
        state->udp_sender.counters.datagrams_dropped += 1u;
        return result;
    }

    memcpy(datagram, view->record_bytes, sizeof(datagram));
    trecap_status_hps_counters_t hps_counters;
    trecap_streamer_make_hps_counters(state, &hps_counters);

    char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
    err_buf[0] = '\0';
    trecap_status_patch_status_t patch_status = trecap_status_patch_udp_copy(datagram,
                                                                              sizeof(datagram),
                                                                              &hps_counters,
                                                                              err_buf,
                                                                              sizeof(err_buf));
    if (patch_status != TRECAP_STATUS_PATCH_OK) {
        trecap_udp_send_result_t result = trecap_udp_send_result_init();
        result.status = TRECAP_UDP_DROPPED;
        result.datagram_bytes = sizeof(datagram);
        result.consumed_record = true;
        state->udp_sender.counters.datagrams_dropped += 1u;
        if (!state->cli.quiet) {
            trecap_streamer_log_error(trecap_status_patch_status_string(patch_status), err_buf);
        }
        return result;
    }

    return trecap_udp_sender_send_datagram(&state->udp_sender, datagram, sizeof(datagram));
}

static int trecap_streamer_service_one_record(trecap_streamer_state_t *state,
                                              const trecap_ring_record_view_t *view)
{
    if (state == NULL || view == NULL) {
        return 2;
    }

    if (view->record_class == TRECAP_RING_RECORD_CLASS_WRAP) {
        trecap_ring_status_t advance_status = trecap_ring_reader_advance(&state->ring_reader, view);
        if (advance_status != TRECAP_RING_OK) {
            trecap_streamer_log_error(trecap_ring_status_string(advance_status), "WRAP advance failed");
            return 2;
        }
        return 0;
    }

    if (view->record_class == TRECAP_RING_RECORD_CLASS_OVERSIZED) {
        state->ring_reader.counters.oversized_record_count += 1u;
        trecap_ring_status_t advance_status = trecap_ring_reader_advance(&state->ring_reader, view);
        if (advance_status != TRECAP_RING_OK) {
            trecap_streamer_log_error(trecap_ring_status_string(advance_status), "oversized advance failed");
            return 2;
        }
        state->records_consumed += 1u;
        state->records_sent_or_dropped += 1u;
        return 0;
    }

    if (!trecap_ring_record_view_is_forwardable(view)) {
        trecap_ring_status_t malformed_status = trecap_ring_reader_handle_malformed(
            &state->ring_reader,
            view,
            NULL,
            0u);
        trecap_streamer_log_error(trecap_ring_status_string(malformed_status),
                                  "record was not forwardable");
        state->transport_enabled = false;
        if (malformed_status == TRECAP_RING_ERR_CSR) {
            return 2;
        }
        return state->cfg.stop_on_malformed_record ? TRECAP_STREAMER_EXIT_MALFORMED_LATCHED : 0;
    }

    trecap_udp_send_result_t send_result = trecap_streamer_send_record_view(state, view);
    if (send_result.status != TRECAP_UDP_OK && send_result.status != TRECAP_UDP_DROPPED) {
        if (!state->cli.quiet) {
            trecap_streamer_log_error(trecap_udp_status_string(send_result.status),
                                      "UDP send did not complete normally");
        }
    }

    trecap_ring_status_t advance_status = trecap_ring_reader_advance(&state->ring_reader, view);
    if (advance_status != TRECAP_RING_OK) {
        trecap_streamer_log_error(trecap_ring_status_string(advance_status), "record advance failed");
        return 2;
    }
    trecap_ring_status_t note_status =
        trecap_ring_reader_note_forwarded(&state->ring_reader, view);
    if (note_status != TRECAP_RING_OK) {
        trecap_streamer_log_error(trecap_ring_status_string(note_status),
                                  "record accounting failed after Rd commit");
        return 2;
    }

    state->records_consumed += 1u;
    state->records_sent_or_dropped += 1u;
    return 0;
}

static int trecap_streamer_service_ring(trecap_streamer_state_t *state, bool *made_progress)
{
    if (state == NULL || made_progress == NULL) {
        return 2;
    }
    *made_progress = false;

    if (state->ring_reader.state == TRECAP_RING_READER_MALFORMED_LATCHED ||
        state->ring_reader.telemetry_disabled_by_reader) {
        return 0;
    }

    uint64_t wr = 0u;
    trecap_ring_status_t ring_status = trecap_ring_reader_snapshot_wr(&state->ring_reader, &wr);
    if (ring_status != TRECAP_RING_OK) {
        if (ring_status == TRECAP_RING_EMPTY) {
            return 0;
        }
        if (ring_status == TRECAP_RING_ERR_STALE) {
            state->ring_reader.counters.boundary_error_count += 1u;
            trecap_ring_record_view_t invalid_view;
            char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
            memset(&invalid_view, 0, sizeof(invalid_view));
            err_buf[0] = '\0';
            const trecap_ring_status_t malformed_status =
                trecap_ring_reader_handle_malformed(&state->ring_reader,
                                                    &invalid_view,
                                                    err_buf,
                                                    sizeof(err_buf));
            trecap_streamer_log_error(trecap_ring_status_string(malformed_status),
                                      "invalid atomic producer/consumer pointer state");
            state->transport_enabled = false;
            if (state->command_bridge_initialized) {
                state->command_bridge.reset_required = true;
            }
            if (malformed_status == TRECAP_RING_ERR_CSR) {
                return 2;
            }
            return state->cfg.stop_on_malformed_record
                       ? TRECAP_STREAMER_EXIT_MALFORMED_LATCHED
                       : 0;
        }
        trecap_streamer_log_error(trecap_ring_status_string(ring_status), "producer snapshot failed");
        return 2;
    }

    uint32_t serviced = 0u;
    while (state->ring_reader.rd != wr && g_stop_requested == 0 &&
           serviced < TRECAP_STREAMER_RING_BUDGET_PER_PASS) {
        trecap_ring_record_view_t view;
        char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
        err_buf[0] = '\0';
        ring_status = trecap_ring_reader_peek(&state->ring_reader, &view, err_buf, sizeof(err_buf));

        if (ring_status == TRECAP_RING_EMPTY) {
            break;
        }
        if (ring_status == TRECAP_RING_WRAP_RECORD || ring_status == TRECAP_RING_OK) {
            int rc = trecap_streamer_service_one_record(state, &view);
            if (rc != 0) {
                return rc;
            }
            *made_progress = true;
            serviced += 1u;
        } else if (ring_status == TRECAP_RING_ERR_MALFORMED ||
                   ring_status == TRECAP_RING_ERR_BOUNDARY) {
            if (ring_status == TRECAP_RING_ERR_BOUNDARY) {
                state->ring_reader.counters.boundary_error_count += 1u;
            }
            trecap_ring_status_t malformed_status = trecap_ring_reader_handle_malformed(
                &state->ring_reader,
                &view,
                err_buf,
                sizeof(err_buf));
            trecap_streamer_log_error(trecap_ring_status_string(malformed_status), err_buf);
            state->transport_enabled = false;
            if (state->command_bridge_initialized) {
                state->command_bridge.reset_required = true;
            }
            if (malformed_status == TRECAP_RING_ERR_CSR) {
                return 2;
            }
            return state->cfg.stop_on_malformed_record
                       ? TRECAP_STREAMER_EXIT_MALFORMED_LATCHED
                       : 0;
        } else if (ring_status == TRECAP_RING_ERR_OVERSIZED) {
            int rc = trecap_streamer_service_one_record(state, &view);
            if (rc != 0) {
                return rc;
            }
            *made_progress = true;
            serviced += 1u;
        } else {
            trecap_streamer_log_error(trecap_ring_status_string(ring_status), err_buf);
            return 2;
        }

        if (state->cli.max_records != 0u && state->records_consumed >= state->cli.max_records) {
            g_stop_requested = 1;
            break;
        }
    }
    return 0;
}

static int trecap_streamer_service_commands(trecap_streamer_state_t *state)
{
    if (state == NULL || !state->command_open) {
        return 0;
    }

    for (uint32_t serviced = 0u;
         serviced < TRECAP_STREAMER_COMMAND_BUDGET_PER_PASS;
         ++serviced) {
        trecap_command_packet_t cmd;
        memset(&cmd, 0, sizeof(cmd));
        trecap_command_result_t result;
        trecap_command_result_init(&result);
        char err_buf[TRECAP_STREAMER_ERRBUF_BYTES];
        err_buf[0] = '\0';

        trecap_cmd_status_t cmd_status = trecap_command_server_recv(&state->command_server,
                                                                    &cmd,
                                                                    &result,
                                                                    err_buf,
                                                                    sizeof(err_buf));
        if (cmd_status == TRECAP_CMD_NO_PACKET || cmd_status == TRECAP_CMD_ERR_WOULD_BLOCK ||
            cmd_status == TRECAP_CMD_ERR_TIMEOUT) {
            return 0;
        }
        if (cmd_status == TRECAP_CMD_REJECTED) {
            if (state->cli.verbose) {
                trecap_streamer_log_error(trecap_cmd_reject_reason_string(result.reject_reason),
                                          err_buf);
            }
            continue;
        }
        if (cmd_status != TRECAP_CMD_OK && cmd_status != TRECAP_CMD_PING) {
            trecap_streamer_log_error(trecap_cmd_status_string(cmd_status), err_buf);
            return 2;
        }

        if (result.trusted_peer_learned) {
            trecap_command_bridge_reset_peer_session(&state->command_bridge);
        }

        if (cmd.cmd_type == TCMD_TYPE_PING || cmd_status == TRECAP_CMD_PING) {
            uint8_t diagnostic[TPKT_HEADER_BYTES + TPKT_PAYLOAD_STATUS_BYTES];
            size_t diagnostic_bytes = 0u;
            if (result.source_addr_valid &&
                trecap_streamer_build_diagnostic_status(state,
                                                        diagnostic,
                                                        sizeof(diagnostic),
                                                        &diagnostic_bytes)) {
                const trecap_cmd_status_t send_status =
                    trecap_command_server_send_peer_datagram(&state->command_server,
                                                             diagnostic,
                                                             diagnostic_bytes,
                                                             &result.source_addr,
                                                             err_buf,
                                                             sizeof(err_buf));
                if (send_status != TRECAP_CMD_OK && state->cli.verbose) {
                    trecap_streamer_log_error(trecap_cmd_status_string(send_status), err_buf);
                }
            }
            continue;
        }

        /* Startup initializes the bridge before entering the production loop.
         * Keep receive/reject draining independent so malformed-datagram flood
         * fairness remains testable and fail closed if that invariant is ever
         * violated. */
        if (!state->command_bridge_initialized) {
            trecap_streamer_log_error("TRECAP_COMMAND_BRIDGE_ERR",
                                      "command bridge is not initialized");
            continue;
        }

        trecap_command_bridge_outcome_t bridge_outcome;
        trecap_command_bridge_status_t bridge_status;
        if (cmd.version == (uint16_t)TCMD_VERSION_V2) {
            bridge_status = trecap_command_bridge_handle_v2(&state->command_bridge,
                                                            &cmd,
                                                            &bridge_outcome,
                                                            err_buf,
                                                            sizeof(err_buf));
            if (bridge_outcome.has_result && result.source_addr_valid) {
                const trecap_cmd_status_t send_status =
                    trecap_command_server_send_v2_result(&state->command_server,
                                                         &bridge_outcome.result_packet,
                                                         &result.source_addr,
                                                         err_buf,
                                                         sizeof(err_buf));
                if (send_status != TRECAP_CMD_OK && state->cli.verbose) {
                    trecap_streamer_log_error(trecap_cmd_status_string(send_status), err_buf);
                }
            }
        } else {
            bridge_status = trecap_command_bridge_apply_v1(&state->command_bridge,
                                                           &cmd,
                                                           &bridge_outcome,
                                                           err_buf,
                                                           sizeof(err_buf));
        }
        if (bridge_status < 0) {
            trecap_streamer_log_error("TRECAP_COMMAND_BRIDGE_ERR", err_buf);
            continue;
        }
        if ((bridge_status == TRECAP_COMMAND_BRIDGE_REJECTED ||
             bridge_status == TRECAP_COMMAND_BRIDGE_FAILED) && state->cli.verbose) {
            trecap_streamer_log_error(
                trecap_cmd_reject_reason_string(bridge_outcome.reject_reason),
                err_buf);
        }
    }
    return 0;
}

static int trecap_streamer_run_loop(trecap_streamer_state_t *state)
{
    if (state == NULL) {
        return 2;
    }

    bool made_progress_since_start = false;
    while (g_stop_requested == 0) {
        bool made_progress = false;
        int rc = trecap_streamer_service_ring(state, &made_progress);
        if (rc != 0) {
            return rc;
        }
        if (made_progress) {
            made_progress_since_start = true;
        }

        rc = trecap_streamer_service_commands(state);
        if (rc != 0) {
            return rc;
        }

        if (state->cli.once && made_progress_since_start) {
            break;
        }
        if (state->cli.max_records != 0u && state->records_consumed >= state->cli.max_records) {
            break;
        }
        if (!made_progress) {
            trecap_streamer_sleep_us(state->cli.poll_sleep_us);
        }
    }
    return 0;
}

int trecap_udp_streamer_main(int argc, char **argv)
{
    trecap_streamer_state_t state;
    memset(&state, 0, sizeof(state));
    g_stop_requested = 0;

    int parse_rc = trecap_streamer_parse_args(argc, argv, &state.cli);
    if (parse_rc != 0) {
        return (parse_rc == 1) ? 0 : parse_rc;
    }

    int rc = trecap_streamer_load_config(&state);
    if (rc != 0) {
        return rc;
    }

    if (state.cli.dry_run || state.cli.verbose) {
        trecap_streamer_print_config(&state);
    }
    if (state.cli.dry_run) {
        return 0;
    }

    trecap_streamer_install_signal_handlers();

    if (state.cli.dummy_udp_counter) {
        rc = trecap_streamer_open_dummy_udp(&state);
        if (rc == 0) {
            rc = trecap_streamer_run_dummy_udp_counter(&state);
        }
    } else {
        rc = trecap_streamer_open_resources(&state);
        if (rc == 0) {
            rc = trecap_streamer_run_loop(&state);
        }
    }

    if (!state.cli.quiet) {
        fprintf(stderr,
                "HPS streamer exit: rc=%d records=%" PRIu64 " datagrams_sent=%" PRIu64
                " udp_errors=%" PRIu64 " malformed=%" PRIu64 " oversized=%" PRIu64 "\n",
                rc,
                state.records_consumed,
                state.udp_sender.counters.datagrams_sent,
                state.udp_sender.counters.send_error_count,
                state.ring_reader.counters.malformed_record_count,
                state.ring_reader.counters.oversized_record_count);
    }

    trecap_streamer_close_resources(&state);
    return rc;
}
