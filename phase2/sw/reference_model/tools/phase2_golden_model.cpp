// SPDX-License-Identifier: MIT
#include "trecap_golden/artifact_checker.hpp"
#include "trecap_golden/artifact_writer.hpp"
#include "trecap_golden/memh.hpp"
#include "trecap_golden/metrics.hpp"
#include "trecap_golden/stft_wola_model.hpp"
#include "trecap_golden/version.hpp"
#include "trecap_golden/window.hpp"

#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace fs = std::filesystem;

namespace {

struct Options final {
    fs::path vectors_root{};
    fs::path out_root{"artifacts/golden"};
    fs::path input{};
    fs::path vector_dir{};
    fs::path golden_dir{};
    std::string vector_name{};
    std::optional<std::uint64_t> thr2{};
    bool collect_bin_stats{false};
    bool collect_bin_stats_set{false};
};

[[nodiscard]] std::string read_text_file(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw trecap::golden::contract_error("failed to open text file: " + path.string());
    }
    std::ostringstream os;
    os << in.rdbuf();
    return os.str();
}

[[nodiscard]] std::optional<std::string> extract_json_string(const std::string& text, const std::string_view key) {
    const std::regex pattern{"\"" + std::string(key) + "\"[[:space:]]*:[[:space:]]*\"([^\"]*)\""};
    std::smatch match;
    if (std::regex_search(text, match, pattern) && match.size() == 2U) {
        return match[1].str();
    }
    return std::nullopt;
}

[[nodiscard]] bool text_contains_true_field(const std::string& text, const std::string_view key) {
    const std::regex pattern{"\"" + std::string(key) + "\"[[:space:]]*:[[:space:]]*true"};
    return std::regex_search(text, pattern);
}

[[nodiscard]] std::uint64_t parse_u64_decimal(const std::string_view text, const std::string_view field_name) {
    if (text.empty()) {
        throw trecap::golden::contract_error(std::string(field_name) + " is empty");
    }
    if (text.size() > 1U && text.front() == '0') {
        throw trecap::golden::contract_error(std::string(field_name) + " is not canonical decimal");
    }
    for (const char ch : text) {
        if (ch < '0' || ch > '9') {
            throw trecap::golden::contract_error(std::string(field_name) + " is not unsigned decimal");
        }
    }
    std::size_t consumed = 0U;
    const auto value = static_cast<std::uint64_t>(std::stoull(std::string(text), &consumed, 10));
    if (consumed != text.size()) {
        throw trecap::golden::contract_error(std::string(field_name) + " has trailing characters");
    }
    return value;
}

[[nodiscard]] std::string maybe_config_text(const fs::path& vector_dir) {
    const fs::path config = vector_dir / "config.json";
    if (fs::exists(config)) {
        return read_text_file(config);
    }
    return {};
}

[[nodiscard]] std::uint64_t thr2_from_config_or_zero(const std::string& config_text) {
    if (const std::optional<std::string> value = extract_json_string(config_text, "THR2")) {
        return parse_u64_decimal(*value, "THR2");
    }
    return 0U;
}

[[nodiscard]] bool collect_bin_stats_from_config(const std::string& config_text) {
    return config_text.find("\"bin_stats_data_rows\"") != std::string::npos ||
           text_contains_true_field(config_text, "requires_bin_stats");
}

[[nodiscard]] std::string vector_name_from_config_or_path(const std::string& config_text, const fs::path& vector_dir) {
    if (const std::optional<std::string> value = extract_json_string(config_text, "vector_name")) {
        return *value;
    }
    if (const std::optional<std::string> value = extract_json_string(config_text, "name")) {
        return *value;
    }
    return vector_dir.filename().string();
}

void print_usage(std::ostream& os) {
    os << "phase2_golden_model - T-RECAP Phase 2 STFT/WOLA golden runner\n\n";
    os << "Suite mode:\n";
    os << "  phase2_golden_model --vectors artifacts/test_vectors --out artifacts/golden\n\n";
    os << "Single-vector mode:\n";
    os << "  phase2_golden_model --input artifacts/test_vectors/<name>/x_in.memh \\\n";
    os << "      --test-vector-dir artifacts/test_vectors/<name> \\\n";
    os << "      --golden-dir artifacts/golden/<name> --vector-name <name> --thr2 0\n\n";
    os << "Options:\n";
    os << "  --vectors DIR           Run every vector directory under DIR.\n";
    os << "  --out DIR               Golden output root for suite mode.\n";
    os << "  --vector-dir DIR        Single vector directory containing x_in.memh/config.json.\n";
    os << "  --input FILE            Single input x_in.memh.\n";
    os << "  --test-vector-dir DIR   Directory to receive/refresh config.json.\n";
    os << "  --golden-dir DIR        Directory to receive y_out.memh/frame_stats.csv/metrics.json.\n";
    os << "  --vector-name NAME      Vector name used in generated JSON.\n";
    os << "  --thr2 DECIMAL          Raw magnitude-squared threshold.\n";
    os << "  --collect-bin-stats     Emit bin_stats.csv.\n";
    os << "  --help                  Show this help.\n";
}

[[nodiscard]] Options parse_args(const int argc, char** argv) {
    Options opt{};
    for (int i = 1; i < argc; ++i) {
        const std::string arg{argv[i]};
        const auto require_value = [&i, argc, argv, &arg]() -> std::string {
            if ((i + 1) >= argc) {
                throw trecap::golden::contract_error("missing value after " + arg);
            }
            ++i;
            return std::string{argv[i]};
        };
        if (arg == "--help" || arg == "-h") {
            print_usage(std::cout);
            std::exit(0);
        } else if (arg == "--vectors") {
            opt.vectors_root = fs::path{require_value()};
        } else if (arg == "--out") {
            opt.out_root = fs::path{require_value()};
        } else if (arg == "--vector-dir") {
            opt.vector_dir = fs::path{require_value()};
        } else if (arg == "--input") {
            opt.input = fs::path{require_value()};
        } else if (arg == "--test-vector-dir") {
            opt.vector_dir = fs::path{require_value()};
        } else if (arg == "--golden-dir") {
            opt.golden_dir = fs::path{require_value()};
        } else if (arg == "--vector-name") {
            opt.vector_name = require_value();
        } else if (arg == "--thr2") {
            opt.thr2 = parse_u64_decimal(require_value(), "THR2");
        } else if (arg == "--collect-bin-stats") {
            opt.collect_bin_stats = true;
            opt.collect_bin_stats_set = true;
        } else {
            throw trecap::golden::contract_error("unknown argument: " + arg);
        }
    }
    return opt;
}

void run_one_vector(const fs::path& input_path,
                    const fs::path& vector_dir,
                    const fs::path& golden_dir,
                    const std::string& vector_name_arg,
                    const std::optional<std::uint64_t> thr2_arg,
                    const bool collect_arg,
                    const bool collect_arg_is_set) {
    const trecap::golden::CoreConfig cfg = trecap::golden::CoreConfig::baseline();
    const std::string config_text = maybe_config_text(vector_dir);
    const std::uint64_t thr2 = thr2_arg.value_or(thr2_from_config_or_zero(config_text));
    const bool collect_bin_stats = collect_arg_is_set ? collect_arg : collect_bin_stats_from_config(config_text);
    const std::string vector_name = vector_name_arg.empty() ? vector_name_from_config_or_path(config_text, vector_dir)
                                                           : vector_name_arg;

    const std::vector<std::int64_t> x = trecap::golden::read_memh(input_path,
                                                                  trecap::golden::signed_memh_spec(cfg.N, 0U, "x_in"));
    if (x.empty()) {
        throw trecap::golden::contract_error("x_in.memh has zero samples; Revision J requires Ns > 0");
    }

    const trecap::golden::WindowTable window = trecap::golden::WindowTable::generated(cfg);
    const trecap::golden::TwiddleTables twiddles = trecap::golden::TwiddleTables::generated(cfg);
    const trecap::golden::CoefficientHashes coeff_hashes = trecap::golden::compute_coefficient_hashes(window, twiddles);

    trecap::golden::StftWolaRunConfig run_cfg{};
    run_cfg.core = cfg;
    run_cfg.thr2 = thr2;
    run_cfg.collect_bin_stats = collect_bin_stats;

    const trecap::golden::StftWolaResult result = trecap::golden::run_stft_wola_model(x, run_cfg, window, twiddles);
    if (thr2 == 0U && !trecap::golden::no_suppression_invariant_holds(result.metrics)) {
        throw trecap::golden::contract_error("THR2=0 invariant failed: at least one eligible bin was suppressed");
    }

    trecap::golden::write_vector_artifacts(vector_dir, golden_dir, vector_name, x, run_cfg, result, coeff_hashes);
    const trecap::golden::ArtifactCheckResult rows = trecap::golden::check_vector_artifact_rows(vector_dir,
                                                                                                  golden_dir,
                                                                                                  result.geometry,
                                                                                                  collect_bin_stats,
                                                                                                  cfg);
    trecap::golden::throw_if_failed(rows);

    std::cout << "golden: " << vector_name << " Ns=" << result.geometry.Ns << " Ny=" << result.geometry.Ny
              << " frames=" << result.geometry.Nframes << " THR2=" << thr2 << " bin_stats="
              << (collect_bin_stats ? "yes" : "no") << '\n';
}

void run_suite(const Options& opt) {
    if (!fs::exists(opt.vectors_root)) {
        throw trecap::golden::contract_error("vector root does not exist: " + opt.vectors_root.string());
    }
    std::uint64_t count = 0U;
    for (const fs::directory_entry& entry : fs::directory_iterator(opt.vectors_root)) {
        if (!entry.is_directory()) {
            continue;
        }
        const fs::path vector_dir = entry.path();
        const fs::path input = vector_dir / "x_in.memh";
        if (!fs::exists(input)) {
            continue;
        }
        const std::string config_text = maybe_config_text(vector_dir);
        const std::string name = vector_name_from_config_or_path(config_text, vector_dir);
        const fs::path golden_dir = opt.out_root / name;
        run_one_vector(input, vector_dir, golden_dir, name, opt.thr2, opt.collect_bin_stats, opt.collect_bin_stats_set);
        ++count;
    }
    if (count == 0U) {
        throw trecap::golden::contract_error("no vector directories containing x_in.memh under " + opt.vectors_root.string());
    }
}

}  // namespace

int main(const int argc, char** argv) {
    try {
        const Options opt = parse_args(argc, argv);
        if (!opt.vectors_root.empty()) {
            run_suite(opt);
            return 0;
        }

        fs::path vector_dir = opt.vector_dir;
        if (!opt.input.empty() && vector_dir.empty()) {
            vector_dir = opt.input.parent_path();
        }
        fs::path input = opt.input;
        if (input.empty() && !vector_dir.empty()) {
            input = vector_dir / "x_in.memh";
        }
        if (input.empty() || vector_dir.empty()) {
            print_usage(std::cerr);
            throw trecap::golden::contract_error("single-vector mode requires --input/--vector-dir");
        }
        fs::path golden_dir = opt.golden_dir;
        if (golden_dir.empty()) {
            const std::string config_text = maybe_config_text(vector_dir);
            const std::string name = opt.vector_name.empty() ? vector_name_from_config_or_path(config_text, vector_dir)
                                                            : opt.vector_name;
            golden_dir = opt.out_root / name;
        }
        run_one_vector(input,
                       vector_dir,
                       golden_dir,
                       opt.vector_name,
                       opt.thr2,
                       opt.collect_bin_stats,
                       opt.collect_bin_stats_set);
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << '\n';
        return 2;
    }
}
