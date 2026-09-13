/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS runtime configuration implementation.
 * File class: [1] hand-written.
 *
 * This file owns parsing and validation for sw/hps/config/trecap_hps_config.json.
 * It intentionally does not define CSR offsets, packet IDs, payload offsets, payload
 * sizes, command IDs, or transport-version values. Those values come through the
 * generated headers included by trecap_hps_config.h.
 */

#include "trecap_hps_config.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define TRECAP_CONFIG_MAX_FILE_BYTES (64u * 1024u)
#define TRECAP_CONFIG_TOKEN_MAX 128u
#define TRECAP_CONFIG_MAX_TOP_LEVEL_KEYS 64u

static void trecap_config_set_error(char *err_buf, size_t err_buf_len, const char *fmt, ...)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }

    va_list ap;
    va_start(ap, fmt);
    (void)vsnprintf(err_buf, err_buf_len, fmt, ap);
    va_end(ap);
    err_buf[err_buf_len - 1u] = '\0';
}

static void trecap_config_copy_default(char *dst, size_t dst_len, const char *src)
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

static bool trecap_config_is_valid_ipv4_text(const char *text)
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }

    struct in_addr addr;
    return inet_pton(AF_INET, text, &addr) == 1;
}

static const char *trecap_config_skip_ws(const char *p)
{
    while (p != NULL && *p != '\0' && isspace((unsigned char)*p) != 0) {
        ++p;
    }
    return p;
}

static bool trecap_config_scan_json_string(const char **cursor,
                                           char *out,
                                           size_t out_len,
                                           char *err_buf,
                                           size_t err_buf_len)
{
    if (cursor == NULL || *cursor == NULL || **cursor != '"') {
        trecap_config_set_error(err_buf, err_buf_len, "expected JSON string token");
        return false;
    }

    const char *p = *cursor + 1;
    size_t used = 0u;
    while (*p != '\0' && *p != '"') {
        unsigned char ch = (unsigned char)*p;
        if (ch < UINT8_C(0x20)) {
            trecap_config_set_error(err_buf, err_buf_len, "control byte in JSON string");
            return false;
        }
        if (*p == '\\') {
            ++p;
            if (*p == '\0' || strchr("\"\\/bfnrt", *p) == NULL) {
                trecap_config_set_error(err_buf, err_buf_len, "unsupported JSON string escape");
                return false;
            }
            ch = (unsigned char)*p;
        }
        if (out != NULL) {
            if (used + 1u >= out_len) {
                trecap_config_set_error(err_buf, err_buf_len, "JSON string token is too long");
                return false;
            }
            out[used] = (char)ch;
        }
        ++used;
        ++p;
    }
    if (*p != '"') {
        trecap_config_set_error(err_buf, err_buf_len, "unterminated JSON string token");
        return false;
    }
    if (out != NULL) {
        out[used] = '\0';
    }
    *cursor = p + 1;
    return true;
}

static bool trecap_config_scan_json_scalar(const char **cursor,
                                           char *err_buf,
                                           size_t err_buf_len)
{
    if (cursor == NULL || *cursor == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null JSON scalar cursor");
        return false;
    }
    const char *p = trecap_config_skip_ws(*cursor);
    if (p == NULL || *p == '\0') {
        trecap_config_set_error(err_buf, err_buf_len, "missing JSON scalar value");
        return false;
    }
    if (*p == '"') {
        if (!trecap_config_scan_json_string(&p, NULL, 0u, err_buf, err_buf_len)) {
            return false;
        }
        *cursor = p;
        return true;
    }
    if (strncmp(p, "true", 4u) == 0) {
        *cursor = p + 4;
        return true;
    }
    if (strncmp(p, "false", 5u) == 0) {
        *cursor = p + 5;
        return true;
    }
    if (strncmp(p, "null", 4u) == 0) {
        *cursor = p + 4;
        return true;
    }

    if (*p == '-') {
        ++p;
    }
    if (*p == '0') {
        ++p;
        if (isdigit((unsigned char)*p) != 0) {
            trecap_config_set_error(err_buf, err_buf_len, "JSON number has a leading zero");
            return false;
        }
    } else if (*p >= '1' && *p <= '9') {
        do {
            ++p;
        } while (isdigit((unsigned char)*p) != 0);
    } else {
        trecap_config_set_error(err_buf, err_buf_len, "unsupported JSON value; flat scalars only");
        return false;
    }
    if (*p == '.' || *p == 'e' || *p == 'E') {
        trecap_config_set_error(err_buf, err_buf_len, "floating-point config values are forbidden");
        return false;
    }
    *cursor = p;
    return true;
}

static bool trecap_config_validate_flat_json(const char *json,
                                             char *err_buf,
                                             size_t err_buf_len)
{
    if (json == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null JSON document");
        return false;
    }

    char keys[TRECAP_CONFIG_MAX_TOP_LEVEL_KEYS][TRECAP_CONFIG_TOKEN_MAX];
    size_t key_count = 0u;
    const char *p = trecap_config_skip_ws(json);
    if (p == NULL || *p != '{') {
        trecap_config_set_error(err_buf, err_buf_len, "runtime config must be one JSON object");
        return false;
    }
    p = trecap_config_skip_ws(p + 1);
    if (p != NULL && *p == '}') {
        p = trecap_config_skip_ws(p + 1);
        return p != NULL && *p == '\0';
    }

    for (;;) {
        if (key_count >= (size_t)TRECAP_CONFIG_MAX_TOP_LEVEL_KEYS) {
            trecap_config_set_error(err_buf, err_buf_len, "too many top-level config keys");
            return false;
        }
        if (p == NULL || *p != '"' ||
            !trecap_config_scan_json_string(&p,
                                            keys[key_count],
                                            sizeof(keys[key_count]),
                                            err_buf,
                                            err_buf_len)) {
            return false;
        }
        for (size_t i = 0u; i < key_count; ++i) {
            if (strcmp(keys[i], keys[key_count]) == 0) {
                trecap_config_set_error(err_buf,
                                        err_buf_len,
                                        "duplicate top-level config key: %s",
                                        keys[key_count]);
                return false;
            }
        }
        ++key_count;

        p = trecap_config_skip_ws(p);
        if (p == NULL || *p != ':') {
            trecap_config_set_error(err_buf, err_buf_len, "missing colon after JSON key");
            return false;
        }
        p = trecap_config_skip_ws(p + 1);
        if (!trecap_config_scan_json_scalar(&p, err_buf, err_buf_len)) {
            return false;
        }
        p = trecap_config_skip_ws(p);
        if (p != NULL && *p == ',') {
            p = trecap_config_skip_ws(p + 1);
            if (p == NULL || *p == '}') {
                trecap_config_set_error(err_buf, err_buf_len, "trailing comma in JSON object");
                return false;
            }
            continue;
        }
        if (p == NULL || *p != '}') {
            trecap_config_set_error(err_buf, err_buf_len, "expected comma or object end");
            return false;
        }
        p = trecap_config_skip_ws(p + 1);
        if (p == NULL || *p != '\0') {
            trecap_config_set_error(err_buf, err_buf_len, "trailing bytes after JSON object");
            return false;
        }
        return true;
    }
}

static const char *trecap_config_find_value(const char *json, const char *key)
{
    if (json == NULL || key == NULL || key[0] == '\0') {
        return NULL;
    }

    char pattern[TRECAP_CONFIG_TOKEN_MAX];
    const int n = snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    if (n <= 0 || (size_t)n >= sizeof(pattern)) {
        return NULL;
    }

    const char *cursor = json;
    for (;;) {
        const char *found = strstr(cursor, pattern);
        if (found == NULL) {
            return NULL;
        }

        const char *after_key = found + (size_t)n;
        after_key = trecap_config_skip_ws(after_key);
        if (after_key != NULL && *after_key == ':') {
            return trecap_config_skip_ws(after_key + 1);
        }
        cursor = found + 1;
    }
}

static bool trecap_config_read_json_string(const char *value,
                                           char *out,
                                           size_t out_len,
                                           char *err_buf,
                                           size_t err_buf_len)
{
    if (value == NULL || out == NULL || out_len == 0u) {
        trecap_config_set_error(err_buf, err_buf_len, "null string parse argument");
        return false;
    }

    const char *p = trecap_config_skip_ws(value);
    if (p == NULL || *p != '"') {
        trecap_config_set_error(err_buf, err_buf_len, "expected JSON string");
        return false;
    }
    ++p;

    size_t used = 0u;
    while (*p != '\0' && *p != '"') {
        char ch = *p;
        if (ch == '\\') {
            ++p;
            if (*p == '\0') {
                trecap_config_set_error(err_buf, err_buf_len, "unterminated JSON escape");
                return false;
            }
            switch (*p) {
            case '"':
            case '\\':
            case '/':
                ch = *p;
                break;
            case 'b':
                ch = '\b';
                break;
            case 'f':
                ch = '\f';
                break;
            case 'n':
                ch = '\n';
                break;
            case 'r':
                ch = '\r';
                break;
            case 't':
                ch = '\t';
                break;
            default:
                trecap_config_set_error(err_buf,
                                        err_buf_len,
                                        "unsupported JSON escape in string field");
                return false;
            }
        }

        if (used + 1u >= out_len) {
            trecap_config_set_error(err_buf, err_buf_len, "string field exceeds destination size");
            return false;
        }
        out[used] = ch;
        ++used;
        ++p;
    }

    if (*p != '"') {
        trecap_config_set_error(err_buf, err_buf_len, "unterminated JSON string");
        return false;
    }
    out[used] = '\0';
    return true;
}

static bool trecap_config_parse_u64_text(const char *text, uint64_t *out)
{
    if (text == NULL || text[0] == '\0' || out == NULL || text[0] == '-') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(text, &end, 0);
    if (errno != 0 || end == text || end == NULL || *end != '\0') {
        return false;
    }
    *out = (uint64_t)parsed;
    return true;
}

static bool trecap_config_get_u64(const char *json,
                                  const char *key,
                                  bool required,
                                  uint64_t *out,
                                  char *err_buf,
                                  size_t err_buf_len)
{
    if (out == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null output for field %s", key);
        return false;
    }

    const char *value = trecap_config_find_value(json, key);
    if (value == NULL) {
        if (required) {
            trecap_config_set_error(err_buf, err_buf_len, "missing required field: %s", key);
            return false;
        }
        return true;
    }

    char token[TRECAP_CONFIG_TOKEN_MAX];
    token[0] = '\0';
    const char *p = trecap_config_skip_ws(value);
    if (p != NULL && *p == '"') {
        if (!trecap_config_read_json_string(p, token, sizeof(token), err_buf, err_buf_len)) {
            trecap_config_set_error(err_buf, err_buf_len, "invalid string value for field %s", key);
            return false;
        }
    } else {
        size_t used = 0u;
        while (p != NULL && *p != '\0' && *p != ',' && *p != '}' && isspace((unsigned char)*p) == 0) {
            if (used + 1u >= sizeof(token)) {
                trecap_config_set_error(err_buf, err_buf_len, "numeric field too long: %s", key);
                return false;
            }
            token[used] = *p;
            ++used;
            ++p;
        }
        token[used] = '\0';
    }

    if (!trecap_config_parse_u64_text(token, out)) {
        trecap_config_set_error(err_buf, err_buf_len, "invalid unsigned integer for field %s", key);
        return false;
    }
    return true;
}

static bool trecap_config_get_u32(const char *json,
                                  const char *key,
                                  bool required,
                                  uint32_t *out,
                                  char *err_buf,
                                  size_t err_buf_len)
{
    uint64_t value = 0u;
    if (!trecap_config_get_u64(json, key, required, &value, err_buf, err_buf_len)) {
        return false;
    }
    if (value > UINT32_MAX) {
        trecap_config_set_error(err_buf, err_buf_len, "field %s exceeds uint32 range", key);
        return false;
    }
    if (out != NULL && (required || trecap_config_find_value(json, key) != NULL)) {
        *out = (uint32_t)value;
    }
    return true;
}

static bool trecap_config_get_u16(const char *json,
                                  const char *key,
                                  bool required,
                                  uint16_t *out,
                                  char *err_buf,
                                  size_t err_buf_len)
{
    uint64_t value = 0u;
    if (!trecap_config_get_u64(json, key, required, &value, err_buf, err_buf_len)) {
        return false;
    }
    if (value > UINT16_MAX) {
        trecap_config_set_error(err_buf, err_buf_len, "field %s exceeds uint16 range", key);
        return false;
    }
    if (out != NULL && (required || trecap_config_find_value(json, key) != NULL)) {
        *out = (uint16_t)value;
    }
    return true;
}

static bool trecap_config_get_string(const char *json,
                                     const char *key,
                                     bool required,
                                     char *out,
                                     size_t out_len,
                                     char *err_buf,
                                     size_t err_buf_len)
{
    const char *value = trecap_config_find_value(json, key);
    if (value == NULL) {
        if (required) {
            trecap_config_set_error(err_buf, err_buf_len, "missing required field: %s", key);
            return false;
        }
        return true;
    }

    if (!trecap_config_read_json_string(value, out, out_len, err_buf, err_buf_len)) {
        trecap_config_set_error(err_buf, err_buf_len, "invalid string for field %s", key);
        return false;
    }
    return true;
}

static bool trecap_config_get_bool(const char *json,
                                   const char *key,
                                   bool required,
                                   bool *out,
                                   char *err_buf,
                                   size_t err_buf_len)
{
    if (out == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null bool output for field %s", key);
        return false;
    }

    const char *value = trecap_config_find_value(json, key);
    if (value == NULL) {
        if (required) {
            trecap_config_set_error(err_buf, err_buf_len, "missing required field: %s", key);
            return false;
        }
        return true;
    }

    value = trecap_config_skip_ws(value);
    if (value != NULL && strncmp(value, "true", 4u) == 0) {
        *out = true;
        return true;
    }
    if (value != NULL && strncmp(value, "false", 5u) == 0) {
        *out = false;
        return true;
    }

    trecap_config_set_error(err_buf, err_buf_len, "invalid boolean for field %s", key);
    return false;
}

static trecap_hps_config_status_t trecap_config_validate_identity(const char *json,
                                                                  char *err_buf,
                                                                  size_t err_buf_len)
{
    char text[TRECAP_CONFIG_TOKEN_MAX];

    text[0] = '\0';
    if (!trecap_config_get_string(json, "schema", true, text, sizeof(text), err_buf, err_buf_len)) {
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }
    if (strcmp(text, TRECAP_HPS_CONFIG_SCHEMA) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "unsupported schema: %s", text);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    text[0] = '\0';
    if (!trecap_config_get_string(json, "project", true, text, sizeof(text), err_buf, err_buf_len)) {
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }
    if (strcmp(text, TRECAP_HPS_PROJECT_NAME) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "unexpected project: %s", text);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    text[0] = '\0';
    if (!trecap_config_get_string(json, "board", true, text, sizeof(text), err_buf, err_buf_len)) {
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }
    if (strcmp(text, TRECAP_HPS_BOARD_DE1SOC) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "unsupported board: %s", text);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }
    return TRECAP_HPS_CONFIG_OK;
}

static trecap_hps_config_status_t trecap_config_read_file(const char *path,
                                                          char **text_out,
                                                          size_t *size_out,
                                                          char *err_buf,
                                                          size_t err_buf_len)
{
    if (path == NULL || text_out == NULL || size_out == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null file-read argument");
        return TRECAP_HPS_CONFIG_ERR_NULL;
    }

    FILE *fp = fopen(path, "rb");
    if (fp == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: %s", path, strerror(errno));
        return TRECAP_HPS_CONFIG_ERR_IO;
    }

    if (fseek(fp, 0L, SEEK_END) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: seek failed", path);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }

    const long end_pos = ftell(fp);
    if (end_pos < 0) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: tell failed", path);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    if ((unsigned long)end_pos > (unsigned long)TRECAP_CONFIG_MAX_FILE_BYTES) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: config file too large", path);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_TRUNCATED;
    }
    if (fseek(fp, 0L, SEEK_SET) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: rewind failed", path);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }

    const size_t bytes = (size_t)end_pos;
    char *text = (char *)calloc(bytes + 1u, 1u);
    if (text == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "out of memory reading %s", path);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }

    const size_t nread = fread(text, 1u, bytes, fp);
    if (nread != bytes || ferror(fp) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "%s: short read", path);
        free(text);
        (void)fclose(fp);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    (void)fclose(fp);

    text[bytes] = '\0';
    *text_out = text;
    *size_out = bytes;
    return TRECAP_HPS_CONFIG_OK;
}

static bool trecap_config_buffer_has_embedded_nul(const char *text, size_t size)
{
    return text != NULL && memchr(text, '\0', size) != NULL;
}

void trecap_hps_config_set_defaults(trecap_hps_runtime_config_t *cfg)
{
    if (cfg == NULL) {
        return;
    }

    memset(cfg, 0, sizeof(*cfg));
    /* Keep the frozen literals visible to the cross-layer address-map checker. */
    cfg->csr_base_phys = UINT64_C(0x00000000ff200000);
    cfg->csr_span_bytes = UINT32_C(4096);
    cfg->ring_base_hps_phys = UINT64_C(0x000000003e000000);
    cfg->ring_base_fpga = UINT64_C(0x000000003e000000);
    cfg->ring_size_bytes = UINT32_C(33554432);
    cfg->ring_guard_bytes = TCSR_RING_GUARD_BYTES_MIN;
    trecap_config_copy_default(cfg->telemetry_dst_ip, sizeof(cfg->telemetry_dst_ip), "192.168.10.1");
    cfg->telemetry_dst_port = UINT16_C(5005);
    cfg->command_listen_port = UINT16_C(5006);
    trecap_config_copy_default(cfg->trusted_command_peer,
                               sizeof(cfg->trusted_command_peer),
                               "192.168.10.1");
    cfg->trusted_command_peer_port = UINT16_C(5007);
    trecap_config_copy_default(cfg->hps_static_ip, sizeof(cfg->hps_static_ip), "192.168.10.2");
    trecap_config_copy_default(cfg->netmask, sizeof(cfg->netmask), "255.255.255.0");
    cfg->transport_version_major = (uint16_t)TPKT_TRANSPORT_VERSION_MAJOR;
    cfg->transport_version_minor = (uint16_t)TPKT_TRANSPORT_VERSION_MINOR;
    cfg->require_trusted_peer = true;
    cfg->use_nonblocking_udp = true;
    cfg->allow_cached_ring_mapping = false;
    cfg->stop_on_malformed_record = false;
}

trecap_hps_config_status_t trecap_hps_config_load_file(const char *path,
                                                       trecap_hps_runtime_config_t *cfg,
                                                       char *err_buf,
                                                       size_t err_buf_len)
{
    if (path == NULL || cfg == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null config path or output");
        return TRECAP_HPS_CONFIG_ERR_NULL;
    }

    char *json = NULL;
    size_t json_size = 0u;
    trecap_hps_config_status_t status = trecap_config_read_file(path,
                                                                &json,
                                                                &json_size,
                                                                err_buf,
                                                                err_buf_len);
    if (status != TRECAP_HPS_CONFIG_OK) {
        return status;
    }
    if (trecap_config_buffer_has_embedded_nul(json, json_size)) {
        trecap_config_set_error(err_buf, err_buf_len, "config contains an embedded NUL byte");
        free(json);
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }

    if (!trecap_config_validate_flat_json(json, err_buf, err_buf_len)) {
        free(json);
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }

    status = trecap_config_validate_identity(json, err_buf, err_buf_len);
    if (status != TRECAP_HPS_CONFIG_OK) {
        free(json);
        return status;
    }

    bool ok = true;
    ok = ok && trecap_config_get_u64(json, "csr_base_phys", true, &cfg->csr_base_phys, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u32(json, "csr_span_bytes", true, &cfg->csr_span_bytes, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u64(json, "ring_base_hps_phys", true, &cfg->ring_base_hps_phys, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u64(json, "ring_base_fpga", true, &cfg->ring_base_fpga, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u32(json, "ring_size_bytes", true, &cfg->ring_size_bytes, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u32(json, "ring_guard_bytes", false, &cfg->ring_guard_bytes, err_buf, err_buf_len);
    ok = ok && trecap_config_get_string(json,
                                        "telemetry_dst_ip",
                                        true,
                                        cfg->telemetry_dst_ip,
                                        sizeof(cfg->telemetry_dst_ip),
                                        err_buf,
                                        err_buf_len);
    ok = ok && trecap_config_get_u16(json, "telemetry_dst_port", true, &cfg->telemetry_dst_port, err_buf, err_buf_len);
    ok = ok && trecap_config_get_u16(json, "command_listen_port", true, &cfg->command_listen_port, err_buf, err_buf_len);
    ok = ok && trecap_config_get_string(json,
                                        "trusted_command_peer",
                                        true,
                                        cfg->trusted_command_peer,
                                        sizeof(cfg->trusted_command_peer),
                                        err_buf,
                                        err_buf_len);
    ok = ok && trecap_config_get_u16(json,
                                     "trusted_command_peer_port",
                                     true,
                                     &cfg->trusted_command_peer_port,
                                     err_buf,
                                     err_buf_len);
    ok = ok && trecap_config_get_string(json,
                                        "hps_static_ip",
                                        false,
                                        cfg->hps_static_ip,
                                        sizeof(cfg->hps_static_ip),
                                        err_buf,
                                        err_buf_len);
    ok = ok && trecap_config_get_string(json,
                                        "netmask",
                                        false,
                                        cfg->netmask,
                                        sizeof(cfg->netmask),
                                        err_buf,
                                        err_buf_len);
    ok = ok && trecap_config_get_u16(json,
                                     "transport_version_major",
                                     true,
                                     &cfg->transport_version_major,
                                     err_buf,
                                     err_buf_len);
    ok = ok && trecap_config_get_u16(json,
                                     "transport_version_minor",
                                     true,
                                     &cfg->transport_version_minor,
                                     err_buf,
                                     err_buf_len);
    ok = ok && trecap_config_get_bool(json,
                                      "require_trusted_peer",
                                      true,
                                      &cfg->require_trusted_peer,
                                      err_buf,
                                      err_buf_len);
    ok = ok && trecap_config_get_bool(json,
                                      "use_nonblocking_udp",
                                      true,
                                      &cfg->use_nonblocking_udp,
                                      err_buf,
                                      err_buf_len);
    ok = ok && trecap_config_get_bool(json,
                                      "allow_cached_ring_mapping",
                                      true,
                                      &cfg->allow_cached_ring_mapping,
                                      err_buf,
                                      err_buf_len);
    ok = ok && trecap_config_get_bool(json,
                                      "stop_on_malformed_record",
                                      true,
                                      &cfg->stop_on_malformed_record,
                                      err_buf,
                                      err_buf_len);

    free(json);
    if (!ok) {
        return TRECAP_HPS_CONFIG_ERR_PARSE;
    }
    return trecap_hps_config_validate(cfg, err_buf, err_buf_len);
}

trecap_hps_config_status_t trecap_hps_config_validate(const trecap_hps_runtime_config_t *cfg,
                                                      char *err_buf,
                                                      size_t err_buf_len)
{
    if (cfg == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null HPS runtime config");
        return TRECAP_HPS_CONFIG_ERR_NULL;
    }

    if (!trecap_hps_versions_match(cfg->transport_version_major, cfg->transport_version_minor)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "transport version %" PRIu16 ".%" PRIu16 " does not match generated %u.%u",
                                cfg->transport_version_major,
                                cfg->transport_version_minor,
                                (unsigned)TPKT_TRANSPORT_VERSION_MAJOR,
                                (unsigned)TPKT_TRANSPORT_VERSION_MINOR);
        return TRECAP_HPS_CONFIG_ERR_VERSION;
    }

    if (cfg->csr_base_phys != TRECAP_HPS_DE1SOC_CSR_BASE ||
        cfg->csr_span_bytes != TRECAP_HPS_DE1SOC_CSR_SPAN_BYTES) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "CSR window must match frozen DE1-SoC base=0x%016" PRIx64
                                " span=%" PRIu32,
                                TRECAP_HPS_DE1SOC_CSR_BASE,
                                TRECAP_HPS_DE1SOC_CSR_SPAN_BYTES);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->ring_base_hps_phys != TRECAP_HPS_DE1SOC_RING_HPS_BASE ||
        cfg->ring_base_fpga != TRECAP_HPS_DE1SOC_RING_FPGA_BASE ||
        cfg->ring_size_bytes != TRECAP_HPS_DE1SOC_RING_SIZE_BYTES) {
        trecap_config_set_error(
            err_buf,
            err_buf_len,
            "ring geometry must match the Step-12 reserved-memory carveout "
            "HPS=0x%016" PRIx64 " FPGA=0x%016" PRIx64 " size=%" PRIu32,
            TRECAP_HPS_DE1SOC_RING_HPS_BASE,
            TRECAP_HPS_DE1SOC_RING_FPGA_BASE,
            TRECAP_HPS_DE1SOC_RING_SIZE_BYTES);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!cfg->require_trusted_peer) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "require_trusted_peer must be true in the canonical runtime config");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!cfg->use_nonblocking_udp) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "use_nonblocking_udp must be true to keep ring service bounded");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->allow_cached_ring_mapping) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "allow_cached_ring_mapping is forbidden by the Step-12 ownership contract");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    const uint32_t min_csr_span = TCSR_REPLAY_STATUS_OFFSET + (uint32_t)sizeof(uint32_t);
    if (cfg->csr_span_bytes < min_csr_span || (cfg->csr_span_bytes % (uint32_t)sizeof(uint32_t)) != 0u) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "invalid csr_span_bytes=%" PRIu32 " minimum=%" PRIu32,
                                cfg->csr_span_bytes,
                                min_csr_span);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!trecap_hps_ring_base_is_valid(cfg->ring_base_hps_phys)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "ring_base_hps_phys is not %u-byte aligned",
                                (unsigned)TCSR_RING_ALIGNMENT_BYTES);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!trecap_hps_ring_base_is_valid(cfg->ring_base_fpga)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "ring_base_fpga is not %u-byte aligned",
                                (unsigned)TCSR_RING_ALIGNMENT_BYTES);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!trecap_hps_ring_size_is_valid(cfg->ring_size_bytes)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "invalid ring_size_bytes=%" PRIu32,
                                cfg->ring_size_bytes);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->ring_guard_bytes != TCSR_RING_GUARD_BYTES_MIN) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "ring_guard_bytes=%" PRIu32 " must equal fixed RTL guard=%u",
                                cfg->ring_guard_bytes,
                                (unsigned)TCSR_RING_GUARD_BYTES_MIN);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!trecap_hps_udp_port_is_valid(cfg->telemetry_dst_port) ||
        !trecap_hps_udp_port_is_valid(cfg->command_listen_port) ||
        !trecap_hps_udp_port_is_valid(cfg->trusted_command_peer_port)) {
        trecap_config_set_error(err_buf, err_buf_len, "UDP ports must be nonzero");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->telemetry_dst_port == cfg->command_listen_port) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "telemetry and command UDP ports must differ");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->trusted_command_peer_port != UINT16_C(5007)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "trusted_command_peer_port must equal canonical PC source port 5007");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (strcmp(cfg->trusted_command_peer, "192.168.10.1") != 0 ||
        strcmp(cfg->hps_static_ip, "192.168.10.2") != 0) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "canonical command endpoint must be HPS 192.168.10.2 and PC 192.168.10.1");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (!trecap_config_is_valid_ipv4_text(cfg->telemetry_dst_ip)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "invalid telemetry_dst_ip: %s",
                                cfg->telemetry_dst_ip);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->require_trusted_peer && !trecap_config_is_valid_ipv4_text(cfg->trusted_command_peer)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "invalid trusted_command_peer: %s",
                                cfg->trusted_command_peer);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->hps_static_ip[0] != '\0' && !trecap_config_is_valid_ipv4_text(cfg->hps_static_ip)) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "invalid hps_static_ip: %s",
                                cfg->hps_static_ip);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    if (cfg->netmask[0] != '\0' && !trecap_config_is_valid_ipv4_text(cfg->netmask)) {
        trecap_config_set_error(err_buf, err_buf_len, "invalid netmask: %s", cfg->netmask);
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    return TRECAP_HPS_CONFIG_OK;
}

static uint32_t trecap_config_load_be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24u) | ((uint32_t)p[1] << 16u) |
           ((uint32_t)p[2] << 8u) | (uint32_t)p[3];
}

static trecap_hps_config_status_t trecap_config_validate_iomem_stream(
    FILE *fp,
    const trecap_hps_runtime_config_t *cfg,
    char *err_buf,
    size_t err_buf_len)
{
    if (fp == NULL || cfg == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "null /proc/iomem validation input");
        return TRECAP_HPS_CONFIG_ERR_NULL;
    }

    const uint64_t ring_start = cfg->ring_base_hps_phys;
    const uint64_t ring_end = ring_start + (uint64_t)cfg->ring_size_bytes;
    bool saw_unmasked_system_ram = false;
    bool overlaps_system_ram = false;
    char *line = NULL;
    size_t line_capacity = 0u;
    while (getline(&line, &line_capacity, fp) >= 0) {
        unsigned long long lo_raw = 0u;
        unsigned long long hi_raw = 0u;
        char label[256];
        label[0] = '\0';
        if (sscanf(line, " %llx-%llx : %255[^\n]", &lo_raw, &hi_raw, label) != 3) {
            continue;
        }
        const uint64_t lo = (uint64_t)lo_raw;
        const uint64_t hi = (uint64_t)hi_raw;
        if (strstr(label, "System RAM") != NULL) {
            if (lo != 0u || hi != 0u) {
                saw_unmasked_system_ram = true;
            }
            if (lo < ring_end && hi >= ring_start) {
                overlaps_system_ram = true;
            }
        }
    }
    const int iomem_error = ferror(fp);
    free(line);
    if (iomem_error != 0 || !saw_unmasked_system_ram) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "/proc/iomem is missing, unreadable, or address-masked");
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    if (overlaps_system_ram) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "reserved DDR ring overlaps /proc/iomem System RAM");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }
    return TRECAP_HPS_CONFIG_OK;
}

trecap_hps_config_status_t trecap_hps_config_validate_live_ddr_reservation(
    const trecap_hps_runtime_config_t *cfg,
    char *err_buf,
    size_t err_buf_len)
{
    trecap_hps_config_status_t cfg_status =
        trecap_hps_config_validate(cfg, err_buf, err_buf_len);
    if (cfg_status != TRECAP_HPS_CONFIG_OK) {
        return cfg_status;
    }

    char path[TRECAP_HPS_PATH_TEXT_MAX];
    int path_len = snprintf(path,
                            sizeof(path),
                            "%s/reg",
                            TRECAP_HPS_DE1SOC_LIVE_DT_NODE);
    if (path_len <= 0 || (size_t)path_len >= sizeof(path)) {
        trecap_config_set_error(err_buf, err_buf_len, "live device-tree path is too long");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    FILE *fp = fopen(path, "rb");
    if (fp == NULL) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "live reserved-memory reg is unreadable: %s",
                                path);
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    uint8_t reg_bytes[8];
    const size_t reg_read = fread(reg_bytes, 1u, sizeof(reg_bytes), fp);
    const int extra_byte = fgetc(fp);
    const int reg_error = ferror(fp);
    (void)fclose(fp);
    if (reg_read != sizeof(reg_bytes) || extra_byte != EOF || reg_error != 0) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "live reserved-memory reg must contain exactly two 32-bit cells");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }
    if ((uint64_t)trecap_config_load_be32(&reg_bytes[0]) != cfg->ring_base_hps_phys ||
        trecap_config_load_be32(&reg_bytes[4]) != cfg->ring_size_bytes) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "live reserved-memory reg does not match configured ring");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    path_len = snprintf(path,
                        sizeof(path),
                        "%s/no-map",
                        TRECAP_HPS_DE1SOC_LIVE_DT_NODE);
    if (path_len <= 0 || (size_t)path_len >= sizeof(path)) {
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }
    struct stat st;
    if (stat(path, &st) != 0) {
        trecap_config_set_error(err_buf, err_buf_len, "live reserved-memory node lacks no-map");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    path_len = snprintf(path,
                        sizeof(path),
                        "%s/reusable",
                        TRECAP_HPS_DE1SOC_LIVE_DT_NODE);
    if (path_len <= 0 || (size_t)path_len >= sizeof(path)) {
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }
    errno = 0;
    if (stat(path, &st) == 0 || errno != ENOENT) {
        trecap_config_set_error(err_buf,
                                err_buf_len,
                                "live reserved-memory node must not contain reusable");
        return TRECAP_HPS_CONFIG_ERR_BAD_VALUE;
    }

    fp = fopen("/proc/iomem", "r");
    if (fp == NULL) {
        trecap_config_set_error(err_buf, err_buf_len, "/proc/iomem is unreadable");
        return TRECAP_HPS_CONFIG_ERR_IO;
    }
    cfg_status = trecap_config_validate_iomem_stream(fp, cfg, err_buf, err_buf_len);
    (void)fclose(fp);
    return cfg_status;
}

const char *trecap_hps_config_status_string(trecap_hps_config_status_t status)
{
    switch (status) {
    case TRECAP_HPS_CONFIG_OK:
        return "TRECAP_HPS_CONFIG_OK";
    case TRECAP_HPS_CONFIG_ERR_NULL:
        return "TRECAP_HPS_CONFIG_ERR_NULL";
    case TRECAP_HPS_CONFIG_ERR_IO:
        return "TRECAP_HPS_CONFIG_ERR_IO";
    case TRECAP_HPS_CONFIG_ERR_PARSE:
        return "TRECAP_HPS_CONFIG_ERR_PARSE";
    case TRECAP_HPS_CONFIG_ERR_MISSING_FIELD:
        return "TRECAP_HPS_CONFIG_ERR_MISSING_FIELD";
    case TRECAP_HPS_CONFIG_ERR_BAD_VALUE:
        return "TRECAP_HPS_CONFIG_ERR_BAD_VALUE";
    case TRECAP_HPS_CONFIG_ERR_VERSION:
        return "TRECAP_HPS_CONFIG_ERR_VERSION";
    case TRECAP_HPS_CONFIG_ERR_TRUNCATED:
        return "TRECAP_HPS_CONFIG_ERR_TRUNCATED";
    default:
        return "TRECAP_HPS_CONFIG_ERR_UNKNOWN";
    }
}
