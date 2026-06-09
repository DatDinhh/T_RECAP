// SPDX-License-Identifier: MIT
#include "trecap_golden/json_io.hpp"

#include "trecap_golden/memh.hpp"

#include <sstream>

namespace trecap::golden {
namespace {

static_assert(kTailPolicyFullTail.size() > 0U);

}  // namespace

std::string json_escape(const std::string_view text) {
    std::string out;
    out.reserve(text.size() + 2U);
    for (const char ch : text) {
        switch (ch) {
            case '\\':
                out += "\\\\";
                break;
            case '"':
                out += "\\\"";
                break;
            case '\b':
                out += "\\b";
                break;
            case '\f':
                out += "\\f";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\r':
                out += "\\r";
                break;
            case '\t':
                out += "\\t";
                break;
            default:
                if (static_cast<unsigned char>(ch) < 0x20U) {
                    std::ostringstream oss;
                    oss << "\\u" << std::hex << std::nouppercase;
                    const unsigned code = static_cast<unsigned char>(ch);
                    oss.width(4);
                    oss.fill('0');
                    oss << code;
                    out += oss.str();
                } else {
                    out.push_back(ch);
                }
                break;
        }
    }
    return out;
}

std::string json_quote(const std::string_view text) {
    return "\"" + json_escape(text) + "\"";
}

std::string json_bool(const bool value) {
    return value ? "true" : "false";
}

std::string indent(const unsigned level) {
    return std::string(static_cast<std::size_t>(2U * level), ' ');
}

std::string core_configuration_json(const CoreConfig& cfg,
                                    const StreamGeometry* geometry,
                                    const std::string_view thr2) {
    std::ostringstream os;
    os << "{\n";
    os << "    \"N\": " << cfg.N << ",\n";
    os << "    \"L\": " << cfg.L << ",\n";
    os << "    \"P\": " << cfg.P << ",\n";
    os << "    \"H\": " << cfg.H << ",\n";
    os << "    \"F\": " << cfg.F << ",\n";
    os << "    \"G\": " << cfg.G << ",\n";
    os << "    \"D\": " << cfg.D;
    if (geometry != nullptr) {
        os << ",\n";
        os << "    \"Ns\": " << geometry->Ns << ",\n";
        os << "    \"Ny\": " << geometry->Ny << ",\n";
        os << "    \"frames\": " << geometry->Nframes;
    }
    os << ",\n";
    os << "    \"THR2\": " << json_quote(thr2) << ",\n";
    os << "    \"PROTECT_DC\": " << (cfg.protect_dc ? 1 : 0) << ",\n";
    os << "    \"PROTECT_NYQ\": " << (cfg.protect_nyq ? 1 : 0) << "\n";
    os << "  }";
    return os.str();
}

std::string widths_json(const WidthConfig& widths) {
    std::ostringstream os;
    os << "{\n";
    os << "    \"W_Qw\": " << widths.W_Qw << ",\n";
    os << "    \"W_tw\": " << widths.W_tw << ",\n";
    os << "    \"W_u\": " << widths.W_u << ",\n";
    os << "    \"W_fft\": " << widths.W_fft << ",\n";
    os << "    \"W_fft_pre\": " << widths.W_fft_pre << ",\n";
    os << "    \"W_can_pre\": " << widths.W_can_pre << ",\n";
    os << "    \"W_can\": " << widths.W_can << ",\n";
    os << "    \"W_mag2\": " << widths.W_mag2 << ",\n";
    os << "    \"W_ifft\": " << widths.W_ifft << ",\n";
    os << "    \"W_z\": " << widths.W_z << ",\n";
    os << "    \"W_ola\": " << widths.W_ola << "\n";
    os << "  }";
    return os.str();
}

std::string contract_json(const bool include_memh_hash) {
    std::ostringstream os;
    os << "{\n";
    os << "    \"fft_mode\": " << json_quote(kFftMode) << ",\n";
    os << "    \"rounding_mode\": " << json_quote(kRoundingMode) << ",\n";
    os << "    \"tail_policy\": " << json_quote(kTailPolicyFullTail) << ",\n";
    os << "    \"threshold_mapping\": " << json_quote(kThresholdMappingRawThr2);
    if (include_memh_hash) {
        os << ",\n";
        os << "    \"memh_encoding\": " << json_quote(kMemhEncoding) << ",\n";
        os << "    \"hash_rule\": " << json_quote(kHashRule) << "\n";
    } else {
        os << "\n";
    }
    os << "  }";
    return os.str();
}

std::string coefficient_hashes_json(const std::string_view window_qw_sha256,
                                    const std::string_view twiddle_re_sha256,
                                    const std::string_view twiddle_im_sha256,
                                    const std::string_view twiddle_inv_re_sha256,
                                    const std::string_view twiddle_inv_im_sha256) {
    std::ostringstream os;
    os << "{\n";
    os << "    \"window_qw_sha256\": " << json_quote(window_qw_sha256) << ",\n";
    os << "    \"twiddle_re_sha256\": " << json_quote(twiddle_re_sha256) << ",\n";
    os << "    \"twiddle_im_sha256\": " << json_quote(twiddle_im_sha256) << ",\n";
    os << "    \"twiddle_inv_re_sha256\": " << json_quote(twiddle_inv_re_sha256) << ",\n";
    os << "    \"twiddle_inv_im_sha256\": " << json_quote(twiddle_inv_im_sha256) << "\n";
    os << "  }";
    return os.str();
}

std::string stream_hashes_json(const std::string_view x_in_sha256, const std::string_view y_out_sha256) {
    std::ostringstream os;
    os << "{\n";
    os << "    \"x_in_sha256\": " << json_quote(x_in_sha256) << ",\n";
    os << "    \"y_out_sha256\": " << json_quote(y_out_sha256) << "\n";
    os << "  }";
    return os.str();
}

void write_json_file(const std::filesystem::path& path, const std::string_view json_text) {
    write_text_file(path, std::string{json_text} + "\n");
}

}  // namespace trecap::golden
