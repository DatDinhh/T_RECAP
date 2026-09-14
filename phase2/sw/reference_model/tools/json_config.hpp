// SPDX-License-Identifier: MIT
#pragma once

#include "trecap_golden/signed_int.hpp"

#include <charconv>
#include <cstdint>
#include <map>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace trecap::reference_cli {

// Small dependency-free JSON reader for runtime configuration. Numbers remain
// exact lexical tokens; configuration integers never pass through floating point.
struct Json final {
    enum class Kind { null_value, boolean, number, string, array, object };
    Kind kind{Kind::null_value};
    std::string text{};
    std::vector<Json> items{};
    std::map<std::string, Json, std::less<>> fields{};

    [[nodiscard]] const Json& at(std::string_view key) const {
        if (kind != Kind::object) throw golden::contract_error("JSON object required");
        const auto it = fields.find(key);
        if (it == fields.end()) throw golden::contract_error("missing JSON field: " + std::string(key));
        return it->second;
    }
    [[nodiscard]] bool has(std::string_view key) const {
        return kind == Kind::object && fields.contains(key);
    }
    [[nodiscard]] const std::string& string() const {
        if (kind != Kind::string) throw golden::contract_error("JSON string required");
        return text;
    }
    [[nodiscard]] std::uint64_t uint() const {
        if (kind != Kind::number) throw golden::contract_error("JSON unsigned integer required");
        std::uint64_t value{};
        const auto [end, err] = std::from_chars(text.data(), text.data() + text.size(), value);
        if (err != std::errc{} || end != text.data() + text.size())
            throw golden::contract_error("JSON unsigned integer required");
        return value;
    }
};

class JsonReader final {
public:
    explicit JsonReader(std::string_view source) : source_(source) {}
    [[nodiscard]] Json parse() {
        auto value = parse_value(0);
        space();
        if (pos_ != source_.size()) fail("trailing content");
        return value;
    }
private:
    std::string_view source_;
    std::size_t pos_{};
    [[noreturn]] void fail(std::string_view message) const {
        throw golden::contract_error("invalid JSON at byte " + std::to_string(pos_) + ": " + std::string(message));
    }
    char peek() const { return pos_ < source_.size() ? source_[pos_] : '\0'; }
    void space() {
        while (peek() == ' ' || peek() == '\t' || peek() == '\r' || peek() == '\n') ++pos_;
    }
    bool take(char ch) {
        if (peek() != ch) return false;
        ++pos_; return true;
    }
    void expect(char ch) { if (!take(ch)) fail("unexpected token"); }
    static bool digit(char ch) { return ch >= '0' && ch <= '9'; }
    void literal(std::string_view token) {
        if (source_.substr(pos_, token.size()) != token) fail("invalid literal");
        pos_ += token.size();
    }
    unsigned hex4() {
        unsigned value{};
        for (unsigned i = 0; i < 4; ++i) {
            const char ch = peek();
            unsigned nibble{};
            if (ch >= '0' && ch <= '9') nibble = static_cast<unsigned>(ch - '0');
            else if (ch >= 'a' && ch <= 'f') nibble = static_cast<unsigned>(ch - 'a') + 10U;
            else if (ch >= 'A' && ch <= 'F') nibble = static_cast<unsigned>(ch - 'A') + 10U;
            else fail("invalid Unicode escape");
            ++pos_; value = (value << 4U) | nibble;
        }
        return value;
    }
    static void utf8(std::string& out, unsigned code) {
        if (code < 0x80U) out.push_back(static_cast<char>(code));
        else if (code < 0x800U) {
            out.push_back(static_cast<char>(0xc0U | (code >> 6U)));
            out.push_back(static_cast<char>(0x80U | (code & 0x3fU)));
        } else if (code < 0x10000U) {
            out.push_back(static_cast<char>(0xe0U | (code >> 12U)));
            out.push_back(static_cast<char>(0x80U | ((code >> 6U) & 0x3fU)));
            out.push_back(static_cast<char>(0x80U | (code & 0x3fU)));
        } else {
            out.push_back(static_cast<char>(0xf0U | (code >> 18U)));
            out.push_back(static_cast<char>(0x80U | ((code >> 12U) & 0x3fU)));
            out.push_back(static_cast<char>(0x80U | ((code >> 6U) & 0x3fU)));
            out.push_back(static_cast<char>(0x80U | (code & 0x3fU)));
        }
    }
    std::string string() {
        expect('"');
        std::string out;
        while (!take('"')) {
            const auto ch = static_cast<unsigned char>(peek());
            if (ch < 0x20U) fail("control character or unterminated string");
            ++pos_;
            if (ch == '\\') {
                const char escape = peek(); ++pos_;
                switch (escape) {
                    case '"': out += '"'; break;
                    case '\\': out += '\\'; break;
                    case '/': out += '/'; break;
                    case 'b': out += '\b'; break;
                    case 'f': out += '\f'; break;
                    case 'n': out += '\n'; break;
                    case 'r': out += '\r'; break;
                    case 't': out += '\t'; break;
                    case 'u': {
                        unsigned code = hex4();
                        if (code >= 0xd800U && code <= 0xdbffU) {
                            expect('\\'); expect('u');
                            const unsigned low = hex4();
                            if (low < 0xdc00U || low > 0xdfffU) fail("invalid surrogate pair");
                            code = 0x10000U + ((code - 0xd800U) << 10U) + low - 0xdc00U;
                        } else if (code >= 0xdc00U && code <= 0xdfffU) fail("unpaired surrogate");
                        utf8(out, code); break;
                    }
                    default: fail("invalid string escape");
                }
            } else if (ch < 0x80U) out.push_back(static_cast<char>(ch));
            else {
                unsigned remaining{};
                unsigned code{};
                unsigned minimum{};
                if (ch >= 0xc2U && ch <= 0xdfU) { remaining = 1; code = ch & 0x1fU; minimum = 0x80U; }
                else if (ch >= 0xe0U && ch <= 0xefU) { remaining = 2; code = ch & 0x0fU; minimum = 0x800U; }
                else if (ch >= 0xf0U && ch <= 0xf4U) { remaining = 3; code = ch & 7U; minimum = 0x10000U; }
                else fail("invalid UTF-8");
                for (unsigned i = 0; i < remaining; ++i) {
                    const auto next = static_cast<unsigned char>(peek());
                    if ((next & 0xc0U) != 0x80U) fail("invalid UTF-8 continuation");
                    ++pos_; code = (code << 6U) | (next & 0x3fU);
                }
                if (code < minimum || code > 0x10ffffU || (code >= 0xd800U && code <= 0xdfffU))
                    fail("invalid UTF-8 scalar");
                utf8(out, code);
            }
        }
        return out;
    }
    Json parse_value(unsigned depth) {
        if (depth > 128U) fail("nesting exceeds 128 levels");
        space();
        Json out;
        if (peek() == '"') { out.kind = Json::Kind::string; out.text = string(); return out; }
        if (take('{')) {
            out.kind = Json::Kind::object; space();
            if (take('}')) return out;
            do {
                space(); const auto key = string(); space(); expect(':');
                auto value = parse_value(depth + 1U);
                if (!out.fields.emplace(key, std::move(value)).second) fail("duplicate object key");
                space();
                if (take('}')) return out;
                expect(',');
            } while (true);
        }
        if (take('[')) {
            out.kind = Json::Kind::array; space();
            if (take(']')) return out;
            do {
                out.items.push_back(parse_value(depth + 1U)); space();
                if (take(']')) return out;
                expect(',');
            } while (true);
        }
        if (peek() == 't') { literal("true"); out.kind = Json::Kind::boolean; out.text = "true"; return out; }
        if (peek() == 'f') { literal("false"); out.kind = Json::Kind::boolean; out.text = "false"; return out; }
        if (peek() == 'n') { literal("null"); return out; }
        const auto start = pos_;
        take('-');
        if (!take('0')) {
            if (peek() < '1' || peek() > '9') fail("value expected");
            while (digit(peek())) ++pos_;
        }
        if (take('.')) {
            if (!digit(peek())) fail("fraction requires digits");
            while (digit(peek())) ++pos_;
        }
        if (take('e') || take('E')) {
            if (!take('+')) take('-');
            if (!digit(peek())) fail("exponent requires digits");
            while (digit(peek())) ++pos_;
        }
        out.kind = Json::Kind::number;
        out.text = source_.substr(start, pos_ - start);
        return out;
    }
};

}  // namespace trecap::reference_cli
