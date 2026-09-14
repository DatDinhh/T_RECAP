// SPDX-License-Identifier: MIT
#include "json_config.hpp"
#include "trecap_golden/artifact_writer.hpp"
#include "trecap_golden/memh.hpp"
#include "trecap_golden/metrics.hpp"
#include "trecap_golden/stft_wola_model.hpp"
#include "trecap_golden/version.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <regex>
#include <set>
#include <sstream>

namespace fs = std::filesystem;
namespace model = trecap::golden;
using trecap::reference_cli::Json;

namespace {

struct Options final {
    fs::path vectors_root{};
    fs::path out_root{"runs/reference_outputs"};
    fs::path input{};
    fs::path vector_dir{};
    fs::path output_dir{};
    fs::path coeff_dir{"artifacts/coefficients"};
    std::string vector_name{};
    std::optional<std::uint64_t> thr2{};
    bool collect_bin_stats{false};
};

std::string read_text(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw model::contract_error("cannot open " + path.string());
    std::ostringstream text; text << in.rdbuf();
    if (in.bad()) throw model::contract_error("I/O error reading " + path.string());
    return text.str();
}

Json read_json(const fs::path& path) {
    const auto text = read_text(path);
    return trecap::reference_cli::JsonReader(text).parse();
}

std::uint64_t decimal(std::string_view text) {
    if (text.empty() || (text.size() > 1U && text.front() == '0') ||
        !std::all_of(text.begin(), text.end(), [](char c) { return c >= '0' && c <= '9'; }))
        throw model::contract_error("THR2 must be a canonical unsigned decimal string");
    std::uint64_t result{};
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), result);
    if (error != std::errc{} || end != text.data() + text.size() ||
        !model::threshold_is_legal(result, model::kBaselineWidths.W_mag2))
        throw model::contract_error("THR2 is outside the baseline magnitude-squared domain");
    return result;
}

std::string vector_name(const Json& config) {
    const auto name = config.at("vector_name").string();
    if (!std::regex_match(name, std::regex("[A-Za-z0-9][A-Za-z0-9_-]{0,95}")))
        throw model::contract_error("invalid vector_name");
    return name;
}

void require_uint(const Json& object, std::string_view field, std::uint64_t expected) {
    if (object.at(field).uint() != expected)
        throw model::contract_error("baseline config mismatch: " + std::string(field));
}

void require_text(const Json& object, std::string_view field, std::string_view expected) {
    if (object.at(field).string() != expected)
        throw model::contract_error("baseline config mismatch: " + std::string(field));
}

void validate_config(const Json& config, const model::StreamGeometry* geometry = nullptr) {
    require_text(config, "schema", model::kVectorConfigSchema);
    static_cast<void>(vector_name(config));
    const auto& c = config.at("configuration");
    const auto cfg = model::CoreConfig::baseline();
    require_uint(c, "N", cfg.N); require_uint(c, "L", cfg.L); require_uint(c, "P", cfg.P);
    require_uint(c, "H", cfg.H); require_uint(c, "F", cfg.F); require_uint(c, "G", cfg.G);
    require_uint(c, "D", cfg.D); require_uint(c, "PROTECT_DC", cfg.protect_dc ? 1U : 0U);
    require_uint(c, "PROTECT_NYQ", cfg.protect_nyq ? 1U : 0U);
    static_cast<void>(decimal(c.at("THR2").string()));
    const auto& widths = config.at("widths");
    const auto w = model::WidthConfig::baseline();
    require_uint(widths, "W_Qw", w.W_Qw); require_uint(widths, "W_tw", w.W_tw);
    require_uint(widths, "W_u", w.W_u); require_uint(widths, "W_fft", w.W_fft);
    require_uint(widths, "W_fft_pre", w.W_fft_pre); require_uint(widths, "W_can_pre", w.W_can_pre);
    require_uint(widths, "W_can", w.W_can); require_uint(widths, "W_mag2", w.W_mag2);
    require_uint(widths, "W_ifft", w.W_ifft); require_uint(widths, "W_z", w.W_z);
    require_uint(widths, "W_ola", w.W_ola);
    const auto& contract = config.at("contract");
    require_text(contract, "fft_mode", model::kFftMode);
    require_text(contract, "rounding_mode", model::kRoundingMode);
    require_text(contract, "tail_policy", model::kTailPolicyFullTail);
    require_text(contract, "threshold_mapping", model::kThresholdMappingRawThr2);
    require_text(contract, "memh_encoding", model::kMemhEncoding);
    require_text(contract, "hash_rule", model::kHashRule);
    const auto& rows = config.at("artifact_rows");
    for (const auto key : {"window_qw", "twiddle_re", "twiddle_im", "twiddle_inv_re", "twiddle_inv_im"})
        require_uint(rows, key, cfg.L);
    if (geometry) {
        require_uint(c, "Ns", geometry->Ns); require_uint(c, "Ny", geometry->Ny);
        require_uint(c, "frames", geometry->Nframes);
        require_uint(rows, "x_in", geometry->Ns); require_uint(rows, "y_out", geometry->Ny);
        require_uint(rows, "frame_stats_data_rows", geometry->Nframes);
        if (rows.has("bin_stats_data_rows"))
            require_uint(rows, "bin_stats_data_rows", geometry->Nframes * cfg.unique_bins());
    }
}

bool within(const fs::path& child, const fs::path& parent) {
    // weakly_canonical resolves aliases through existing parent directories.
    const auto c = fs::weakly_canonical(child);
    const auto p = fs::weakly_canonical(parent);
    for (auto current = c; !current.empty(); current = current.parent_path()) {
        if (current == p || (fs::exists(current) && fs::exists(p) && fs::equivalent(current, p))) return true;
        if (current == current.root_path()) break;
    }
    return false;
}

void run_one(const Options& opt, const fs::path& vector_dir, const fs::path& input,
             const fs::path& explicit_output = {}) {
    const auto config_path = vector_dir / "config.json";
    const auto config_text = read_text(config_path);
    const auto config = trecap::reference_cli::JsonReader(config_text).parse();
    validate_config(config);
    const auto name = vector_name(config);
    if (!opt.vector_name.empty() && opt.vector_name != name)
        throw model::contract_error("--vector-name must agree with config.json");
    const auto output = explicit_output.empty() ? opt.out_root / name : explicit_output;
    if (within(output, vector_dir) || within(vector_dir, output) ||
        within(output, input.parent_path()) ||
        within(output, opt.coeff_dir) || within(opt.coeff_dir, output))
        throw model::contract_error("output directory must be separate from input and coefficient directories");
    if (fs::exists(output) && (!fs::is_directory(output) || !fs::is_empty(output)))
        throw model::contract_error("output directory must be new or empty: " + output.string());

    const auto cfg = model::CoreConfig::baseline();
    const auto w = model::WidthConfig::baseline();
    const auto x = model::read_memh(input, model::signed_memh_spec(cfg.N, 0U, "x_in"));
    const auto geometry = model::full_tail_geometry(x.size(), cfg);
    validate_config(config, &geometry);
    require_text(config.at("stream_hashes"), "x_in_sha256", model::sha256_memh_signed(x, cfg.N));

    // Frozen coefficient files are read, never regenerated during an ordinary run.
    model::WindowTable window{};
    window.cfg = cfg;
    for (const auto value : model::read_memh(opt.coeff_dir / "window_qw.memh",
                                            model::unsigned_memh_spec(w.W_Qw, cfg.L, "window_qw")))
        window.q.push_back(static_cast<std::uint64_t>(value));
    model::TwiddleTables twiddles{};
    twiddles.cfg = cfg;
    const auto re = model::read_memh(opt.coeff_dir / "twiddle_re.memh", model::signed_memh_spec(w.W_tw, cfg.L));
    const auto im = model::read_memh(opt.coeff_dir / "twiddle_im.memh", model::signed_memh_spec(w.W_tw, cfg.L));
    const auto ir = model::read_memh(opt.coeff_dir / "twiddle_inv_re.memh", model::signed_memh_spec(w.W_tw, cfg.L));
    const auto ii = model::read_memh(opt.coeff_dir / "twiddle_inv_im.memh", model::signed_memh_spec(w.W_tw, cfg.L));
    for (unsigned i = 0; i < cfg.L; ++i) {
        twiddles.forward.push_back({re[i], im[i]});
        twiddles.inverse.push_back({ir[i], ii[i]});
    }
    const auto hashes = model::compute_coefficient_hashes(window, twiddles);
    const auto& declared_hashes = config.at("hashes");
    require_text(declared_hashes, "window_qw_sha256", hashes.window_qw_sha256);
    require_text(declared_hashes, "twiddle_re_sha256", hashes.twiddle_re_sha256);
    require_text(declared_hashes, "twiddle_im_sha256", hashes.twiddle_im_sha256);
    require_text(declared_hashes, "twiddle_inv_re_sha256", hashes.twiddle_inv_re_sha256);
    require_text(declared_hashes, "twiddle_inv_im_sha256", hashes.twiddle_inv_im_sha256);

    model::StftWolaRunConfig run_cfg{};
    run_cfg.core = cfg;
    run_cfg.thr2 = opt.thr2.value_or(decimal(config.at("configuration").at("THR2").string()));
    run_cfg.collect_bin_stats = opt.collect_bin_stats || config.at("artifact_rows").has("bin_stats_data_rows");
    const auto result = model::run_stft_wola_model(x, run_cfg, window, twiddles);
    model::write_reference_outputs(output, name, x, run_cfg, result, hashes);
    model::write_text_file(output / "source_config.json", config_text);
    model::write_json_file(output / "run.json",
        "{\n  \"schema\": \"trecap_reference_run_v1\",\n  \"status\": \"reference_output\",\n"
        "  \"input\": " + model::json_quote(fs::absolute(input).generic_string()) +
        ",\n  \"source_config_sha256\": " + model::json_quote(model::sha256_bytes(config_text)) +
        ",\n  \"coefficient_directory\": " + model::json_quote(fs::absolute(opt.coeff_dir).generic_string()) +
        ",\n  \"threshold_override\": " + model::json_bool(opt.thr2.has_value()) + "\n}");
    std::cout << "reference: " << name << " Ns=" << geometry.Ns << " Ny=" << geometry.Ny
              << " frames=" << geometry.Nframes << " THR2=" << run_cfg.thr2 << '\n';
}

void usage() {
    std::cout << "T-RECAP Phase 2 reference runner (legacy executable name retained)\n"
                 "  --vector-dir DIR        Input x_in.memh and config.json (read-only)\n"
                 "  --vectors DIR           Run each vector subdirectory, sorted by name\n"
                 "  --input FILE            Input file; defaults to vector-dir/x_in.memh\n"
                 "  --test-vector-dir DIR   Alias of --vector-dir\n"
                 "  --coeff-dir DIR         Frozen coefficient files (default artifacts/coefficients)\n"
                 "  --out DIR               Output root (default runs/reference_outputs)\n"
                 "  --output-dir DIR        Exact output directory for a single vector\n"
                 "  --golden-dir DIR        Legacy alias of --output-dir\n"
                 "  --vector-name NAME      Must match config.json\n"
                 "  --thr2 DECIMAL          Explicit threshold override, recorded in output only\n"
                 "  --collect-bin-stats     Include canonical bin statistics\n"
                 "Input config is required; baseline mismatches and nonempty outputs are rejected.\n";
}

Options parse_args(int argc, char** argv) {
    Options opt;
    std::set<std::string> seen;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") { usage(); std::exit(0); }
        if (arg == "--test-vector-dir") arg = "--vector-dir";
        if (arg == "--golden-dir") arg = "--output-dir";
        if (!seen.insert(arg).second) throw model::contract_error("duplicate option: " + arg);
        auto value = [&]() -> std::string {
            if (++i >= argc) throw model::contract_error("missing value after " + arg);
            return argv[i];
        };
        if (arg == "--vectors") opt.vectors_root = value();
        else if (arg == "--out") opt.out_root = value();
        else if (arg == "--vector-dir") opt.vector_dir = value();
        else if (arg == "--input") opt.input = value();
        else if (arg == "--output-dir") opt.output_dir = value();
        else if (arg == "--coeff-dir") opt.coeff_dir = value();
        else if (arg == "--vector-name") opt.vector_name = value();
        else if (arg == "--thr2") opt.thr2 = decimal(value());
        else if (arg == "--collect-bin-stats") opt.collect_bin_stats = true;
        else throw model::contract_error("unknown option: " + arg);
    }
    if (!opt.vectors_root.empty() &&
        (!opt.input.empty() || !opt.vector_dir.empty() || !opt.output_dir.empty() || !opt.vector_name.empty()))
        throw model::contract_error("suite mode cannot use single-vector options");
    return opt;
}
}  // namespace

int main(int argc, char** argv) {
    try {
        const auto opt = parse_args(argc, argv);
        if (!opt.vectors_root.empty()) {
            std::vector<fs::path> dirs;
            std::set<std::string> names;
            for (const auto& entry : fs::directory_iterator(opt.vectors_root)) {
                if (entry.is_directory() && fs::exists(entry.path() / "x_in.memh")) {
                    const auto config = read_json(entry.path() / "config.json");
                    validate_config(config);
                    if (!names.insert(vector_name(config)).second)
                        throw model::contract_error("duplicate vector_name in suite");
                    dirs.push_back(entry.path());
                }
            }
            if (dirs.empty()) throw model::contract_error("no vector inputs found");
            std::sort(dirs.begin(), dirs.end());
            for (const auto& dir : dirs) run_one(opt, dir, dir / "x_in.memh");
        } else {
            const auto dir = opt.vector_dir.empty() ? opt.input.parent_path() : opt.vector_dir;
            if (dir.empty()) throw model::contract_error("--vector-dir or --input is required");
            run_one(opt, dir, opt.input.empty() ? dir / "x_in.memh" : opt.input, opt.output_dir);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 2;
    }
}
