// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jaeson
// Phase 2 Golden Model

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <filesystem>

namespace fs = std::filesystem;

namespace {

constexpr double PI = 3.141592653589793238462643383279502884;

using u128 = unsigned __int128;

struct Config {
  int N = 12;
  int L = 256;
  int H = 128;
  int F = 15;
  int G = 128;
  uint64_t THR2 = 0;
  int PROTECT_DC = 1;
  int PROTECT_NYQ = 0;

  std::string input_mode = "memh"; // memh | zero | tone | multitone | lfsr
  std::string input_path;
  int Ns = -1;

  int amp = 1024;
  double phase = 0.0;
  int tone_bin = -1;
  double tone_bin_frac = std::numeric_limits<double>::quiet_NaN();
  std::string tones_spec; // e.g. "10:800,25.5:300,40:200"

  uint32_t seed = 0xACE1u;
  int SHIFT = 3; // for lfsr source only

  std::string outdir = ".";
  std::string x_out = "x_in.memh";
  std::string y_out = "y_out.memh";
  std::string frame_csv = "frame_stats.csv";
  std::string metrics_json = "metrics.json";

  std::string load_window_rom;   // exact shared window artifact
  std::string emit_window_rom;   // dump used window artifact

  std::string debug_dir;
  std::set<int> debug_frames;

  bool quiet = false;
  bool strict = true;
};

struct Widths {
  int W_Qw = 0;
  int W_u = 0;
  int W_fft = 0;
  int W_can_pre = 0;
  int W_can = 0;
  int W_mag2 = 0;
  int W_ifft = 0;
  int W_z = 0;
  int W_ola = 0;
  int P = 0;
};

struct Cx {
  int64_t re = 0;
  int64_t im = 0;
};

struct FrameStats {
  uint64_t frame_idx = 0;
  uint64_t raw_unique_bins = 0;
  uint64_t raw_suppressed_bins = 0;
  uint64_t eligible_unique_bins = 0;
  uint64_t eligible_suppressed_bins = 0;
  u128 kept_mag2 = 0;
  u128 total_mag2 = 0;
};

struct OverflowFlags {
  bool window_input = false;
  bool fft = false;
  bool canon_pre = false;
  bool canon = false;
  bool mag2 = false;
  bool ifft = false;
  bool z = false;
  bool ola = false;

  int64_t max_ifft_imag_abs = 0;
};

struct Metrics {
  u128 raw_unique_bins = 0;
  u128 raw_suppressed_bins = 0;
  u128 eligible_unique_bins = 0;
  u128 eligible_suppressed_bins = 0;
  u128 total_kept_mag2 = 0;
  u128 total_mag2 = 0;

  u128 sum_abs_err = 0;
  u128 sum_sq_err = 0;
  u128 max_abs_err = 0;
  u128 error_sample_count = 0;

  uint64_t frames = 0;
};

static std::string u128_to_string(u128 v) {
  if (v == 0) return "0";
  std::string s;
  while (v > 0) {
    int digit = static_cast<int>(v % 10);
    s.push_back(static_cast<char>('0' + digit));
    v /= 10;
  }
  std::reverse(s.begin(), s.end());
  return s;
}

static int64_t i64_abs(int64_t v) {
  return (v < 0) ? -v : v;
}

static bool fits_signed(int64_t v, int bits) {
  if (bits <= 0) return false;
  if (bits >= 63) {
    const long long lo = std::numeric_limits<long long>::min();
    const long long hi = std::numeric_limits<long long>::max();
    return (v >= lo && v <= hi);
  }
  const int64_t lo = -(int64_t(1) << (bits - 1));
  const int64_t hi = (int64_t(1) << (bits - 1)) - 1;
  return (v >= lo && v <= hi);
}

static bool fits_unsigned_u64(uint64_t v, int bits) {
  if (bits <= 0) return false;
  if (bits >= 64) return true;
  const uint64_t hi = (uint64_t(1) << bits) - 1ull;
  return v <= hi;
}

static int32_t satN(int64_t v, int N) {
  const int64_t lo = -(int64_t(1) << (N - 1));
  const int64_t hi = (int64_t(1) << (N - 1)) - 1;
  if (v < lo) return static_cast<int32_t>(lo);
  if (v > hi) return static_cast<int32_t>(hi);
  return static_cast<int32_t>(v);
}

static int64_t asr_i64(int64_t v, unsigned sh) {
  if (sh == 0) return v;
  if (v >= 0) return (v >> sh);
  const int64_t av = -v;
  const int64_t bias = (int64_t(1) << sh) - 1;
  return -((av + bias) >> sh);
}

static int64_t rnd_shr(int64_t v, unsigned sh) {
  if (sh == 0) return v;
  const int64_t bias = int64_t(1) << (sh - 1);
  if (v >= 0) return (v + bias) >> sh;
  return -(((-v) + bias) >> sh);
}

static int64_t rnd2(int64_t v) {
  return rnd_shr(v, 1);
}

static int32_t qcoef(double x, int F) {
  const double mag = std::floor(std::fabs(x) * double(uint64_t(1) << F) + 0.5);
  const int64_t q = static_cast<int64_t>(mag);
  if (x < 0.0) return static_cast<int32_t>(-q);
  return static_cast<int32_t>(q);
}

static uint32_t to_twosN(int32_t v, int N) {
  uint64_t mask = (N >= 32) ? 0xFFFFFFFFull : ((uint64_t(1) << N) - 1ull);
  uint64_t uv = static_cast<uint32_t>(v);
  return static_cast<uint32_t>(uv & mask);
}

static void dump_memh_samples(const std::string &path, const std::vector<int32_t> &samps, int N) {
  std::ofstream f(path);
  if (!f) throw std::runtime_error("Failed to open " + path);
  const int hexw = (N + 3) / 4;
  for (auto v : samps) {
    uint32_t u = to_twosN(v, N);
    f << std::uppercase << std::hex << std::setw(hexw) << std::setfill('0') << u << "\n";
  }
}

static void dump_memh_u16(const std::string &path, const std::vector<uint16_t> &vals) {
  std::ofstream f(path);
  if (!f) throw std::runtime_error("Failed to open " + path);
  for (auto v : vals) {
    f << std::uppercase << std::hex << std::setw(4) << std::setfill('0')
      << static_cast<unsigned>(v) << "\n";
  }
}

static std::vector<int32_t> load_memh_signed(const std::string &path, int N) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("Failed to open input memh: " + path);
  std::vector<int32_t> out;
  std::string line;
  while (std::getline(f, line)) {
    std::string s;
    for (char c : line) {
      if (!std::isspace(static_cast<unsigned char>(c))) s.push_back(c);
    }
    if (s.empty()) continue;
    uint32_t u = static_cast<uint32_t>(std::stoul(s, nullptr, 16));
    const uint32_t sign_bit = 1u << (N - 1);
    const uint32_t full = (N == 32) ? 0u : (1u << N);
    if (N < 32 && (u & sign_bit)) {
      out.push_back(static_cast<int32_t>(u) - static_cast<int32_t>(full));
    } else {
      out.push_back(static_cast<int32_t>(u));
    }
  }
  return out;
}

static std::vector<uint16_t> load_window_rom(const std::string &path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("Failed to open window ROM: " + path);
  std::vector<uint16_t> out;
  std::string line;
  while (std::getline(f, line)) {
    std::string s;
    for (char c : line) {
      if (!std::isspace(static_cast<unsigned char>(c))) s.push_back(c);
    }
    if (s.empty()) continue;
    uint32_t u = static_cast<uint32_t>(std::stoul(s, nullptr, 16));
    if (u > 0xFFFFu) throw std::runtime_error("Window ROM entry exceeds 16 bits");
    out.push_back(static_cast<uint16_t>(u));
  }
  return out;
}

static uint32_t lfsr_step16(uint32_t s) {
  uint32_t b = ((s >> 0) ^ (s >> 2) ^ (s >> 3) ^ (s >> 5)) & 1u;
  s = (s >> 1) | (b << 15);
  return (s & 0xFFFFu);
}

static int32_t map_lfsr_to_signedN(uint32_t lfsr, int N) {
  uint32_t mask = (N == 32) ? 0xFFFFFFFFu : ((1u << N) - 1u);
  uint32_t u = lfsr & mask;
  return static_cast<int32_t>(u) - (1 << (N - 1));
}

static int32_t noise_shaper_step(int32_t &state, int32_t u, int SHIFT, int N) {
  int64_t diff = int64_t(u) - int64_t(state);
  int32_t delta = static_cast<int32_t>(asr_i64(diff, static_cast<unsigned>(SHIFT)));
  state = static_cast<int32_t>(state + delta);
  return satN(state, N);
}

static std::vector<std::string> split(const std::string &s, char delim) {
  std::vector<std::string> parts;
  std::stringstream ss(s);
  std::string tok;
  while (std::getline(ss, tok, delim)) {
    if (!tok.empty()) parts.push_back(tok);
  }
  return parts;
}

static std::set<int> parse_int_set(const std::string &spec) {
  std::set<int> out;
  if (spec.empty()) return out;
  for (const auto &p : split(spec, ',')) {
    out.insert(std::stoi(p, nullptr, 0));
  }
  return out;
}

static std::string join_path(const std::string &dir, const std::string &base) {
  fs::path p(dir);
  p /= base;
  return p.string();
}

static int bit_reverse(unsigned x, int bits) {
  unsigned r = 0;
  for (int i = 0; i < bits; ++i) {
    r = (r << 1u) | (x & 1u);
    x >>= 1u;
  }
  return static_cast<int>(r);
}

static std::vector<Cx> bit_reverse_copy(const std::vector<Cx> &in, int bits) {
  std::vector<Cx> out(in.size());
  for (size_t i = 0; i < in.size(); ++i) {
    out[bit_reverse(static_cast<unsigned>(i), bits)] = in[i];
  }
  return out;
}

static std::vector<Cx> build_stage_twiddles(int m, int F, bool inverse) {
  std::vector<Cx> tw(m / 2);
  for (int j = 0; j < m / 2; ++j) {
    double ang = 2.0 * PI * double(j) / double(m);
    int32_t wr = qcoef(std::cos(ang), F);
    int32_t wi = inverse ? qcoef(std::sin(ang), F) : qcoef(-std::sin(ang), F);
    tw[j] = Cx{wr, wi};
  }
  return tw;
}

static Cx cmulF(const Cx &b, const Cx &w, int F) {
  const int64_t br = b.re;
  const int64_t bi = b.im;
  const int64_t wr = w.re;
  const int64_t wi = w.im;
  const int64_t twr = rnd_shr(br * wr - bi * wi, static_cast<unsigned>(F));
  const int64_t twi = rnd_shr(br * wi + bi * wr, static_cast<unsigned>(F));
  return Cx{twr, twi};
}

struct FftResult {
  std::vector<Cx> bins;
};

static FftResult fft_norm_custom(const std::vector<Cx> &time, const Widths &wd, OverflowFlags &ovf, int F) {
  const int L = static_cast<int>(time.size());
  std::vector<Cx> a = bit_reverse_copy(time, wd.P);
  for (int stage = 1; stage <= wd.P; ++stage) {
    const int m = 1 << stage;
    const int half = m >> 1;
    const auto tw = build_stage_twiddles(m, F, false);
    for (int k = 0; k < L; k += m) {
      for (int j = 0; j < half; ++j) {
        const Cx u = a[k + j];
        const Cx t = cmulF(a[k + j + half], tw[j], F);
        const Cx ap{rnd2(u.re + t.re), rnd2(u.im + t.im)};
        const Cx bp{rnd2(u.re - t.re), rnd2(u.im - t.im)};
        if (!fits_signed(ap.re, wd.W_fft) || !fits_signed(ap.im, wd.W_fft) ||
            !fits_signed(bp.re, wd.W_fft) || !fits_signed(bp.im, wd.W_fft)) {
          ovf.fft = true;
        }
        a[k + j] = ap;
        a[k + j + half] = bp;
      }
    }
  }
  return FftResult{a};
}

static FftResult ifft_unscaled_custom(const std::vector<Cx> &freq, const Widths &wd, OverflowFlags &ovf, int F) {
  const int L = static_cast<int>(freq.size());
  std::vector<Cx> a = bit_reverse_copy(freq, wd.P);
  for (int stage = 1; stage <= wd.P; ++stage) {
    const int m = 1 << stage;
    const int half = m >> 1;
    const auto tw = build_stage_twiddles(m, F, true);
    const int stage_bits = wd.W_can + stage;
    for (int k = 0; k < L; k += m) {
      for (int j = 0; j < half; ++j) {
        const Cx u = a[k + j];
        const Cx t = cmulF(a[k + j + half], tw[j], F);
        const Cx ap{u.re + t.re, u.im + t.im};
        const Cx bp{u.re - t.re, u.im - t.im};
        if (!fits_signed(ap.re, stage_bits) || !fits_signed(ap.im, stage_bits) ||
            !fits_signed(bp.re, stage_bits) || !fits_signed(bp.im, stage_bits) ||
            !fits_signed(ap.re, wd.W_ifft) || !fits_signed(ap.im, wd.W_ifft) ||
            !fits_signed(bp.re, wd.W_ifft) || !fits_signed(bp.im, wd.W_ifft)) {
          ovf.ifft = true;
        }
        a[k + j] = ap;
        a[k + j + half] = bp;
      }
    }
  }
  return FftResult{a};
}

class Phase2GoldenModel {
 public:
  explicit Phase2GoldenModel(Config cfg) : cfg_(std::move(cfg)) {
    derive_and_validate();
  }

  int run() {
    try {
      prepare_outdir();
      init_window();
      load_or_generate_input();
      streaming_run();
      compute_error_metrics();
      write_artifacts();
      const bool ok = self_consistency_checks();
      if (!cfg_.quiet) {
        print_summary(ok);
      }
      if (cfg_.strict && (!ok || any_overflow())) {
        return 2;
      }
      return 0;
    } catch (const std::exception &e) {
      std::cerr << "ERROR: " << e.what() << "\n";
      return 1;
    }
  }

 private:
  Config cfg_;
  Widths wd_;
  int D_ = 0;

  std::vector<uint16_t> window_q_;
  std::vector<int32_t> x_in_;
  std::vector<int32_t> y_out_;
  std::vector<int32_t> xring_;
  std::vector<int64_t> ola_;
  std::vector<FrameStats> frames_;

  Metrics metrics_;
  OverflowFlags ovf_;

  int wr_ = 0;
  int rd_ = 0;
  uint64_t sample_count_ = 0;
  uint64_t frame_count_ = 0;

  void derive_and_validate() {
    if (cfg_.L <= 0 || (cfg_.L & (cfg_.L - 1)) != 0) {
      throw std::runtime_error("L must be a positive power of two");
    }
    wd_.P = 0;
    while ((1 << wd_.P) < cfg_.L) ++wd_.P;

    if (cfg_.H <= 0) cfg_.H = cfg_.L / 2;
    if (cfg_.G < 0) cfg_.G = cfg_.H;
    if (cfg_.H != cfg_.L / 2) {
      throw std::runtime_error("This baseline model freezes H = L/2");
    }
    if (cfg_.N < 2 || cfg_.N > 30) {
      throw std::runtime_error("N out of supported range (2..30)");
    }
    if (cfg_.F <= 0 || cfg_.F > 30) {
      throw std::runtime_error("F out of supported range (1..30)");
    }
    if (cfg_.PROTECT_DC != 0 && cfg_.PROTECT_DC != 1) {
      throw std::runtime_error("PROTECT_DC must be 0 or 1");
    }
    if (cfg_.PROTECT_NYQ != 0 && cfg_.PROTECT_NYQ != 1) {
      throw std::runtime_error("PROTECT_NYQ must be 0 or 1");
    }
    D_ = cfg_.L + cfg_.G;

    wd_.W_Qw = cfg_.F + 1;
    wd_.W_u = cfg_.N + cfg_.F;
    wd_.W_fft = wd_.W_u + 1;
    wd_.W_can_pre = wd_.W_fft + 1;
    wd_.W_can = wd_.W_fft;
    wd_.W_mag2 = 2 * wd_.W_can;
    wd_.W_ifft = wd_.W_can + wd_.P;
    wd_.W_z = wd_.W_ifft;
    wd_.W_ola = wd_.W_z + 1;

    if (!std::isnan(cfg_.tone_bin_frac) && cfg_.tone_bin_frac < 0.0) {
      throw std::runtime_error("tone-bin-frac must be nonnegative");
    }
  }

  void prepare_outdir() const {
    fs::create_directories(cfg_.outdir);
    if (!cfg_.debug_dir.empty()) {
      fs::create_directories(cfg_.debug_dir);
    }
  }

  void init_window() {
    if (!cfg_.load_window_rom.empty()) {
      window_q_ = load_window_rom(cfg_.load_window_rom);
      if (static_cast<int>(window_q_.size()) != cfg_.L) {
        throw std::runtime_error("Loaded window ROM length does not equal L");
      }
    } else {
      window_q_.resize(cfg_.L);
      for (int n = 0; n < cfg_.L; ++n) {
        const double hp = 0.5 - 0.5 * std::cos(2.0 * PI * double(n) / double(cfg_.L));
        const double w = std::sqrt(std::max(0.0, hp));
        const int32_t q = qcoef(w, cfg_.F);
        if (q < 0 || q > (1 << cfg_.F)) {
          throw std::runtime_error("Generated window coefficient out of unsigned range");
        }
        window_q_[n] = static_cast<uint16_t>(q);
      }
    }

    if (!cfg_.emit_window_rom.empty()) {
      dump_memh_u16(cfg_.emit_window_rom, window_q_);
    }
  }

  void load_or_generate_input() {
    if (cfg_.input_mode == "memh") {
      if (cfg_.input_path.empty()) throw std::runtime_error("--input-path is required for input-mode memh");
      x_in_ = load_memh_signed(cfg_.input_path, cfg_.N);
      if (cfg_.Ns >= 0 && cfg_.Ns != static_cast<int>(x_in_.size())) {
        throw std::runtime_error("Ns does not match loaded memh length");
      }
      cfg_.Ns = static_cast<int>(x_in_.size());
    } else {
      if (cfg_.Ns <= 0) throw std::runtime_error("Ns must be positive for generated inputs");
      if (cfg_.input_mode == "zero") {
        x_in_.assign(cfg_.Ns, 0);
      } else if (cfg_.input_mode == "tone") {
        x_in_ = generate_tone();
      } else if (cfg_.input_mode == "multitone") {
        x_in_ = generate_multitone();
      } else if (cfg_.input_mode == "lfsr") {
        x_in_ = generate_lfsr();
      } else {
        throw std::runtime_error("Unsupported input-mode: " + cfg_.input_mode);
      }
    }
    if (cfg_.Ns != static_cast<int>(x_in_.size())) {
      throw std::runtime_error("Internal error: Ns mismatch after input preparation");
    }
  }

  std::vector<int32_t> generate_tone() const {
    double bin = 0.0;
    if (cfg_.tone_bin >= 0) {
      bin = static_cast<double>(cfg_.tone_bin);
    } else if (!std::isnan(cfg_.tone_bin_frac)) {
      bin = cfg_.tone_bin_frac;
    } else {
      throw std::runtime_error("tone mode requires --tone-bin or --tone-bin-frac");
    }
    std::vector<int32_t> x(cfg_.Ns);
    const double freq_norm = bin / double(cfg_.L);
    for (int n = 0; n < cfg_.Ns; ++n) {
      double v = double(cfg_.amp) * std::sin(2.0 * PI * freq_norm * double(n) + cfg_.phase);
      x[n] = satN(static_cast<int64_t>(std::llround(v)), cfg_.N);
    }
    return x;
  }

  std::vector<int32_t> generate_multitone() const {
    if (cfg_.tones_spec.empty()) throw std::runtime_error("multitone mode requires --tones");
    struct Tone { double bin; double amp; double phase; };
    std::vector<Tone> tones;
    for (const auto &tok : split(cfg_.tones_spec, ',')) {
      const auto parts = split(tok, ':');
      if (parts.size() < 2 || parts.size() > 3) {
        throw std::runtime_error("Each tones entry must be bin:amp or bin:amp:phase");
      }
      Tone t{};
      t.bin = std::stod(parts[0]);
      t.amp = std::stod(parts[1]);
      t.phase = (parts.size() == 3) ? std::stod(parts[2]) : 0.0;
      tones.push_back(t);
    }
    std::vector<int32_t> x(cfg_.Ns);
    for (int n = 0; n < cfg_.Ns; ++n) {
      double sum = 0.0;
      for (const auto &t : tones) {
        const double freq_norm = t.bin / double(cfg_.L);
        sum += t.amp * std::sin(2.0 * PI * freq_norm * double(n) + t.phase);
      }
      x[n] = satN(static_cast<int64_t>(std::llround(sum)), cfg_.N);
    }
    return x;
  }

  std::vector<int32_t> generate_lfsr() const {
    if (cfg_.seed == 0) throw std::runtime_error("LFSR seed must be non-zero");
    std::vector<int32_t> x(cfg_.Ns);
    uint32_t lfsr = cfg_.seed & 0xFFFFu;
    int32_t shaper_state = 0;
    for (int n = 0; n < cfg_.Ns; ++n) {
      lfsr = lfsr_step16(lfsr);
      int32_t u = map_lfsr_to_signedN(lfsr, cfg_.N);
      x[n] = noise_shaper_step(shaper_state, u, cfg_.SHIFT, cfg_.N);
    }
    return x;
  }

  void streaming_run() {
    xring_.assign(cfg_.L, 0);
    ola_.assign(D_, 0);
    y_out_.clear();
    y_out_.reserve(static_cast<size_t>(cfg_.Ns + D_));
    frames_.clear();
    frames_.reserve(static_cast<size_t>((cfg_.Ns + D_ + cfg_.H - 1) / cfg_.H));

    wr_ = 0;
    rd_ = 0;
    sample_count_ = 0;
    frame_count_ = 0;

    for (int n = 0; n < cfg_.Ns + D_; ++n) {
      const int32_t xin = (n < cfg_.Ns) ? x_in_[n] : 0;
      xring_[wr_] = xin;
      wr_ = (wr_ + 1) % cfg_.L;

      const int32_t y = satN(rnd_shr(ola_[rd_], static_cast<unsigned>(cfg_.F)), cfg_.N);
      y_out_.push_back(y);
      ola_[rd_] = 0;
      rd_ = (rd_ + 1) % D_;

      sample_count_ += 1;
      if ((sample_count_ % static_cast<uint64_t>(cfg_.H)) == 0u) {
        process_frame(frame_count_);
        frame_count_ += 1;
      }
    }
    metrics_.frames = frame_count_;
  }

  void process_frame(uint64_t frame_idx) {
    std::vector<int32_t> xf(cfg_.L);
    std::vector<Cx> u(cfg_.L);
    for (int i = 0; i < cfg_.L; ++i) {
      xf[i] = xring_[(wr_ + i) % cfg_.L];
      const int64_t prod = int64_t(xf[i]) * int64_t(window_q_[i]);
      if (!fits_signed(prod, wd_.W_u)) ovf_.window_input = true;
      u[i] = Cx{prod, 0};
    }

    const auto fft = fft_norm_custom(u, wd_, ovf_, cfg_.F).bins;

    std::vector<Cx> xcan(cfg_.L);
    xcan[0] = Cx{fft[0].re, 0};
    xcan[cfg_.L / 2] = Cx{fft[cfg_.L / 2].re, 0};
    if (!fits_signed(fft[0].re, wd_.W_can) || !fits_signed(fft[cfg_.L / 2].re, wd_.W_can)) {
      ovf_.canon = true;
    }

    for (int k = 1; k <= cfg_.L / 2 - 1; ++k) {
      const int64_t re_sum = fft[k].re + fft[cfg_.L - k].re;
      const int64_t im_dif = fft[k].im - fft[cfg_.L - k].im;
      if (!fits_signed(re_sum, wd_.W_can_pre) || !fits_signed(im_dif, wd_.W_can_pre)) {
        ovf_.canon_pre = true;
      }
      const int64_t R = rnd2(re_sum);
      const int64_t I = rnd2(im_dif);
      if (!fits_signed(R, wd_.W_can) || !fits_signed(I, wd_.W_can)) {
        ovf_.canon = true;
      }
      xcan[k] = Cx{R, I};
      xcan[cfg_.L - k] = Cx{R, -I};
    }

    std::vector<uint64_t> mag2(cfg_.L / 2 + 1, 0);
    std::vector<uint8_t> m(cfg_.L / 2 + 1, 0);
    std::vector<uint8_t> eligible(cfg_.L / 2 + 1, 1);
    std::vector<uint8_t> weight(cfg_.L / 2 + 1, 2);

    for (int k = 0; k <= cfg_.L / 2; ++k) {
      const int64_t re = xcan[k].re;
      const int64_t im = xcan[k].im;
      const uint64_t val = static_cast<uint64_t>(re * re + im * im);
      if (!fits_unsigned_u64(val, wd_.W_mag2)) ovf_.mag2 = true;
      mag2[k] = val;
      m[k] = (val < cfg_.THR2) ? 1u : 0u;
    }

    if (cfg_.PROTECT_DC) m[0] = 0;
    if (cfg_.PROTECT_NYQ) m[cfg_.L / 2] = 0;

    for (int k = 0; k <= cfg_.L / 2; ++k) {
      eligible[k] = 1;
      if (cfg_.PROTECT_DC && k == 0) eligible[k] = 0;
      if (cfg_.PROTECT_NYQ && k == cfg_.L / 2) eligible[k] = 0;
      weight[k] = (k == 0 || k == cfg_.L / 2) ? 1u : 2u;
    }

    FrameStats fs{};
    fs.frame_idx = frame_idx;
    fs.raw_unique_bins = static_cast<uint64_t>(cfg_.L / 2 + 1);
    for (int k = 0; k <= cfg_.L / 2; ++k) {
      fs.raw_suppressed_bins += static_cast<uint64_t>(m[k]);
      fs.eligible_unique_bins += static_cast<uint64_t>(eligible[k]);
      fs.eligible_suppressed_bins += static_cast<uint64_t>(eligible[k]) * static_cast<uint64_t>(m[k]);
      fs.total_mag2 += static_cast<u128>(eligible[k]) * static_cast<u128>(weight[k]) * static_cast<u128>(mag2[k]);
      fs.kept_mag2 += static_cast<u128>(eligible[k]) * static_cast<u128>(1u - m[k]) *
                      static_cast<u128>(weight[k]) * static_cast<u128>(mag2[k]);
    }

    std::vector<Cx> xhat(cfg_.L, Cx{0, 0});
    for (int k = 1; k <= cfg_.L / 2 - 1; ++k) {
      if (m[k] == 0u) {
        xhat[k] = xcan[k];
        xhat[cfg_.L - k] = xcan[cfg_.L - k];
      }
    }
    xhat[0] = (m[0] == 0u) ? xcan[0] : Cx{0, 0};
    xhat[cfg_.L / 2] = (m[cfg_.L / 2] == 0u) ? xcan[cfg_.L / 2] : Cx{0, 0};

    dump_debug_if_requested(frame_idx, fft, xcan, xhat);

    const auto ifft = ifft_unscaled_custom(xhat, wd_, ovf_, cfg_.F).bins;
    for (int i = 0; i < cfg_.L; ++i) {
      ovf_.max_ifft_imag_abs = std::max<int64_t>(ovf_.max_ifft_imag_abs, i64_abs(ifft[i].im));
      const int64_t z = rnd_shr(ifft[i].re * int64_t(window_q_[i]), static_cast<unsigned>(cfg_.F));
      if (!fits_signed(z, wd_.W_z)) ovf_.z = true;
      const int idx = (rd_ + cfg_.G + i) % D_;
      const int64_t sum = ola_[idx] + z;
      if (!fits_signed(sum, wd_.W_ola)) ovf_.ola = true;
      ola_[idx] = sum;
    }

    metrics_.raw_unique_bins += fs.raw_unique_bins;
    metrics_.raw_suppressed_bins += fs.raw_suppressed_bins;
    metrics_.eligible_unique_bins += fs.eligible_unique_bins;
    metrics_.eligible_suppressed_bins += fs.eligible_suppressed_bins;
    metrics_.total_kept_mag2 += fs.kept_mag2;
    metrics_.total_mag2 += fs.total_mag2;

    frames_.push_back(fs);
  }

  void dump_debug_if_requested(uint64_t frame_idx,
                               const std::vector<Cx> &raw,
                               const std::vector<Cx> &xcan,
                               const std::vector<Cx> &xhat) const {
    if (cfg_.debug_dir.empty()) return;
    if (cfg_.debug_frames.find(static_cast<int>(frame_idx)) == cfg_.debug_frames.end()) return;
    dump_complex_csv(join_path(cfg_.debug_dir, frame_name(frame_idx, "fft_raw.csv")), raw);
    dump_complex_csv(join_path(cfg_.debug_dir, frame_name(frame_idx, "fft_can.csv")), xcan);
    dump_complex_csv(join_path(cfg_.debug_dir, frame_name(frame_idx, "fft_masked.csv")), xhat);
  }

  static std::string frame_name(uint64_t idx, const std::string &suffix) {
    std::ostringstream oss;
    oss << "frame_" << std::setw(6) << std::setfill('0') << idx << "_" << suffix;
    return oss.str();
  }

  static void dump_complex_csv(const std::string &path, const std::vector<Cx> &v) {
    std::ofstream f(path);
    if (!f) throw std::runtime_error("Failed to open debug CSV: " + path);
    f << "bin,re,im\n";
    for (size_t i = 0; i < v.size(); ++i) {
      f << i << "," << v[i].re << "," << v[i].im << "\n";
    }
  }

  void compute_error_metrics() {
    metrics_.sum_abs_err = 0;
    metrics_.sum_sq_err = 0;
    metrics_.max_abs_err = 0;
    metrics_.error_sample_count = y_out_.size();
    for (size_t n = 0; n < y_out_.size(); ++n) {
      int32_t ref = 0;
      if (static_cast<int64_t>(n) >= D_ && static_cast<int64_t>(n) - D_ < cfg_.Ns) {
        ref = x_in_[static_cast<size_t>(static_cast<int64_t>(n) - D_)];
      }
      const int64_t err = int64_t(ref) - int64_t(y_out_[n]);
      const u128 abs_err = static_cast<u128>(i64_abs(err));
      const u128 sq_err = static_cast<u128>(err * err);
      metrics_.sum_abs_err += abs_err;
      metrics_.sum_sq_err += sq_err;
      metrics_.max_abs_err = std::max(metrics_.max_abs_err, abs_err);
    }
  }

  void write_artifacts() const {
    dump_memh_samples(join_path(cfg_.outdir, cfg_.x_out), x_in_, cfg_.N);
    dump_memh_samples(join_path(cfg_.outdir, cfg_.y_out), y_out_, cfg_.N);
    write_frame_stats_csv();
    write_metrics_json();
  }

  void write_frame_stats_csv() const {
    std::ofstream f(join_path(cfg_.outdir, cfg_.frame_csv));
    if (!f) throw std::runtime_error("Failed to open frame_stats.csv for writing");
    f << "frame_idx,raw_unique_bins,raw_suppressed_bins,eligible_unique_bins,eligible_suppressed_bins,kept_mag2,total_mag2\n";
    for (const auto &fr : frames_) {
      f << fr.frame_idx << ","
        << fr.raw_unique_bins << ","
        << fr.raw_suppressed_bins << ","
        << fr.eligible_unique_bins << ","
        << fr.eligible_suppressed_bins << ","
        << u128_to_string(fr.kept_mag2) << ","
        << u128_to_string(fr.total_mag2) << "\n";
    }
  }

  void write_metrics_json() const {
    const double raw_ratio = (metrics_.raw_unique_bins == 0)
                                 ? 0.0
                                 : static_cast<double>(to_long_double(metrics_.raw_suppressed_bins) /
                                                       to_long_double(metrics_.raw_unique_bins));
    const double elig_ratio = (metrics_.eligible_unique_bins == 0)
                                  ? 0.0
                                  : static_cast<double>(to_long_double(metrics_.eligible_suppressed_bins) /
                                                        to_long_double(metrics_.eligible_unique_bins));
    const double keep_ratio = (metrics_.total_mag2 == 0)
                                  ? 1.0
                                  : static_cast<double>(to_long_double(metrics_.total_kept_mag2) /
                                                        to_long_double(metrics_.total_mag2));
    const double rmse = (metrics_.error_sample_count == 0)
                            ? 0.0
                            : std::sqrt(static_cast<double>(to_long_double(metrics_.sum_sq_err) /
                                                            to_long_double(metrics_.error_sample_count)));

    std::ofstream f(join_path(cfg_.outdir, cfg_.metrics_json));
    if (!f) throw std::runtime_error("Failed to open metrics.json for writing");
    f << "{\n";
    f << "  \"N\": " << cfg_.N << ",\n";
    f << "  \"L\": " << cfg_.L << ",\n";
    f << "  \"H\": " << cfg_.H << ",\n";
    f << "  \"F\": " << cfg_.F << ",\n";
    f << "  \"G\": " << cfg_.G << ",\n";
    f << "  \"D\": " << D_ << ",\n";
    f << "  \"Ns\": " << cfg_.Ns << ",\n";
    f << "  \"frames\": " << metrics_.frames << ",\n";
    f << "  \"thr2\": " << cfg_.THR2 << ",\n";
    f << "  \"protect_dc\": " << cfg_.PROTECT_DC << ",\n";
    f << "  \"protect_nyq\": " << cfg_.PROTECT_NYQ << ",\n";
    f << "  \"raw_unique_bins\": " << u128_to_string(metrics_.raw_unique_bins) << ",\n";
    f << "  \"raw_suppressed_bins\": " << u128_to_string(metrics_.raw_suppressed_bins) << ",\n";
    f << "  \"eligible_unique_bins\": " << u128_to_string(metrics_.eligible_unique_bins) << ",\n";
    f << "  \"eligible_suppressed_bins\": " << u128_to_string(metrics_.eligible_suppressed_bins) << ",\n";
    f << "  \"total_kept_mag2\": " << u128_to_string(metrics_.total_kept_mag2) << ",\n";
    f << "  \"total_mag2\": " << u128_to_string(metrics_.total_mag2) << ",\n";
    f << "  \"sum_abs_err\": " << u128_to_string(metrics_.sum_abs_err) << ",\n";
    f << "  \"sum_sq_err\": " << u128_to_string(metrics_.sum_sq_err) << ",\n";
    f << "  \"max_abs_err\": " << u128_to_string(metrics_.max_abs_err) << ",\n";
    f << "  \"error_sample_count\": " << u128_to_string(metrics_.error_sample_count) << ",\n";
    f << std::fixed << std::setprecision(12);
    f << "  \"raw_suppression_ratio\": " << raw_ratio << ",\n";
    f << "  \"eligible_suppression_ratio\": " << elig_ratio << ",\n";
    f << "  \"kept_energy_ratio\": " << keep_ratio << ",\n";
    f << "  \"rmse\": " << rmse << ",\n";
    f << "  \"overflow_window_input\": " << bool_to_json(ovf_.window_input) << ",\n";
    f << "  \"overflow_fft\": " << bool_to_json(ovf_.fft) << ",\n";
    f << "  \"overflow_canon_pre\": " << bool_to_json(ovf_.canon_pre) << ",\n";
    f << "  \"overflow_canon\": " << bool_to_json(ovf_.canon) << ",\n";
    f << "  \"overflow_mag2\": " << bool_to_json(ovf_.mag2) << ",\n";
    f << "  \"overflow_ifft\": " << bool_to_json(ovf_.ifft) << ",\n";
    f << "  \"overflow_z\": " << bool_to_json(ovf_.z) << ",\n";
    f << "  \"overflow_ola\": " << bool_to_json(ovf_.ola) << ",\n";
    f << "  \"max_ifft_imag_abs\": " << ovf_.max_ifft_imag_abs << "\n";
    f << "}\n";
  }

  static long double to_long_double(u128 v) {
    long double out = 0.0L;
    long double base = 1.0L;
    while (v > 0) {
      out += base * static_cast<unsigned>(v & 0xFFFFu);
      v >>= 16;
      base *= 65536.0L;
    }
    return out;
  }

  static const char *bool_to_json(bool b) {
    return b ? "true" : "false";
  }

  bool self_consistency_checks() const {
    bool ok = true;
    if (static_cast<int>(y_out_.size()) != cfg_.Ns + D_) {
      ok = false;
    }
    if (cfg_.THR2 == 0) {
      if (metrics_.eligible_suppressed_bins != 0) ok = false;
    }
    bool all_zero_input = true;
    for (auto v : x_in_) {
      if (v != 0) { all_zero_input = false; break; }
    }
    if (all_zero_input) {
      for (auto y : y_out_) {
        if (y != 0) { ok = false; break; }
      }
    }
    return ok;
  }

  bool any_overflow() const {
    return ovf_.window_input || ovf_.fft || ovf_.canon_pre || ovf_.canon ||
           ovf_.mag2 || ovf_.ifft || ovf_.z || ovf_.ola;
  }

  void print_summary(bool ok) const {
    std::cout << "Phase 2 golden model summary\n";
    std::cout << "  input-mode              : " << cfg_.input_mode << "\n";
    if (cfg_.input_mode == "memh") {
      std::cout << "  input-path              : " << cfg_.input_path << "\n";
    }
    std::cout << "  N,L,H,F,G,D            : " << cfg_.N << ", " << cfg_.L << ", " << cfg_.H
              << ", " << cfg_.F << ", " << cfg_.G << ", " << D_ << "\n";
    std::cout << "  Ns / output samples     : " << cfg_.Ns << " / " << y_out_.size() << "\n";
    std::cout << "  frames                  : " << metrics_.frames << "\n";
    std::cout << "  eligible suppressed     : " << u128_to_string(metrics_.eligible_suppressed_bins)
              << " / " << u128_to_string(metrics_.eligible_unique_bins) << "\n";
    std::cout << "  kept energy / total     : " << u128_to_string(metrics_.total_kept_mag2)
              << " / " << u128_to_string(metrics_.total_mag2) << "\n";
    std::cout << "  sum_abs_err             : " << u128_to_string(metrics_.sum_abs_err) << "\n";
    std::cout << "  sum_sq_err              : " << u128_to_string(metrics_.sum_sq_err) << "\n";
    std::cout << "  max_abs_err             : " << u128_to_string(metrics_.max_abs_err) << "\n";
    std::cout << "  max_ifft_imag_abs       : " << ovf_.max_ifft_imag_abs << "\n";
    std::cout << "  overflow flags          : "
              << "window=" << ovf_.window_input
              << " fft=" << ovf_.fft
              << " canon_pre=" << ovf_.canon_pre
              << " canon=" << ovf_.canon
              << " mag2=" << ovf_.mag2
              << " ifft=" << ovf_.ifft
              << " z=" << ovf_.z
              << " ola=" << ovf_.ola << "\n";
    std::cout << "  self-consistency        : " << (ok ? "PASS" : "FAIL") << "\n";
    std::cout << "  outdir                  : " << cfg_.outdir << "\n";
  }
};

static bool take_arg(int &i, int argc, char **argv, const char *name, std::string &out) {
  if (std::strcmp(argv[i], name) == 0 && i + 1 < argc) {
    out = argv[++i];
    return true;
  }
  return false;
}

static bool take_arg_int(int &i, int argc, char **argv, const char *name, int &out) {
  std::string s;
  if (take_arg(i, argc, argv, name, s)) {
    out = std::stoi(s, nullptr, 0);
    return true;
  }
  return false;
}

static bool take_arg_u32(int &i, int argc, char **argv, const char *name, uint32_t &out) {
  std::string s;
  if (take_arg(i, argc, argv, name, s)) {
    out = static_cast<uint32_t>(std::stoul(s, nullptr, 0));
    return true;
  }
  return false;
}

static bool take_arg_u64(int &i, int argc, char **argv, const char *name, uint64_t &out) {
  std::string s;
  if (take_arg(i, argc, argv, name, s)) {
    out = static_cast<uint64_t>(std::stoull(s, nullptr, 0));
    return true;
  }
  return false;
}

static bool take_flag(int &i, int argc, char **argv, const char *name) {
  (void)argc;
  if (std::strcmp(argv[i], name) == 0) return true;
  return false;
}

static void print_usage(const char *argv0) {
  std::cerr
      << "Usage: " << argv0 << " [options]\n\n"
      << "Core options:\n"
      << "  --n <int>                 Sample width N (default 12)\n"
      << "  --l <int>                 FFT length L, power of two (default 256)\n"
      << "  --h <int>                 Hop size H (default 128; baseline requires L/2)\n"
      << "  --f <int>                 Fractional width F (default 15)\n"
      << "  --g <int>                 Scheduling cushion G (default 128)\n"
      << "  --thr2 <uint64>           Internal threshold-squared in mag2 domain\n"
      << "  --protect-dc <0|1>        Protect DC unique bin (default 1)\n"
      << "  --protect-nyq <0|1>       Protect Nyquist unique bin (default 0)\n\n"
      << "Input options:\n"
      << "  --input-mode <mode>       memh | zero | tone | multitone | lfsr\n"
      << "  --input-path <file>       Signed N-bit memh for input-mode memh\n"
      << "  --ns <int>                Input sample count for generated sources\n"
      << "  --amp <int>               Amplitude for tone source (default 1024)\n"
      << "  --phase <float>           Phase radians for tone source (default 0)\n"
      << "  --tone-bin <int>          Exact FFT-bin tone index for tone source\n"
      << "  --tone-bin-frac <float>   Fractional bin for off-bin tone source\n"
      << "  --tones <spec>            Multitone spec: bin:amp[,bin:amp[:phase],...]\n"
      << "  --seed <hex>              LFSR seed for lfsr source (default 0xACE1)\n"
      << "  --shift <int>             Noise shaper shift for lfsr source (default 3)\n\n"
      << "Artifact options:\n"
      << "  --outdir <dir>            Output directory (default .)\n"
      << "  --x-out <name>            x_in memh filename (default x_in.memh)\n"
      << "  --y-out <name>            y_out memh filename (default y_out.memh)\n"
      << "  --frame-csv <name>        frame_stats.csv filename\n"
      << "  --metrics-json <name>     metrics.json filename\n"
      << "  --load-window-rom <file>  Load exact window ROM artifact\n"
      << "  --emit-window-rom <file>  Emit the used window ROM artifact\n"
      << "  --debug-dir <dir>         Directory for optional frame debug dumps\n"
      << "  --debug-frames <list>     Comma-separated frame indices for debug dumps\n\n"
      << "Behavior options:\n"
      << "  --quiet                   Suppress stdout summary\n"
      << "  --no-strict               Return success even if overflow/self-check fails\n"
      << "  --help                    Show this help\n";
}

} // namespace

int main(int argc, char **argv) {
  Config cfg;

  for (int i = 1; i < argc; ++i) {
    if (take_arg_int(i, argc, argv, "--n", cfg.N)) continue;
    if (take_arg_int(i, argc, argv, "--l", cfg.L)) continue;
    if (take_arg_int(i, argc, argv, "--h", cfg.H)) continue;
    if (take_arg_int(i, argc, argv, "--f", cfg.F)) continue;
    if (take_arg_int(i, argc, argv, "--g", cfg.G)) continue;
    if (take_arg_u64(i, argc, argv, "--thr2", cfg.THR2)) continue;
    if (take_arg_int(i, argc, argv, "--protect-dc", cfg.PROTECT_DC)) continue;
    if (take_arg_int(i, argc, argv, "--protect-nyq", cfg.PROTECT_NYQ)) continue;

    if (take_arg(i, argc, argv, "--input-mode", cfg.input_mode)) continue;
    if (take_arg(i, argc, argv, "--input-path", cfg.input_path)) continue;
    if (take_arg_int(i, argc, argv, "--ns", cfg.Ns)) continue;
    if (take_arg_int(i, argc, argv, "--amp", cfg.amp)) continue;
    if (take_arg(i, argc, argv, "--tones", cfg.tones_spec)) continue;
    if (take_arg_u32(i, argc, argv, "--seed", cfg.seed)) continue;
    if (take_arg_int(i, argc, argv, "--shift", cfg.SHIFT)) continue;
    if (take_arg_int(i, argc, argv, "--tone-bin", cfg.tone_bin)) continue;

    std::string s;
    if (take_arg(i, argc, argv, "--phase", s)) { cfg.phase = std::stod(s); continue; }
    if (take_arg(i, argc, argv, "--tone-bin-frac", s)) { cfg.tone_bin_frac = std::stod(s); continue; }

    if (take_arg(i, argc, argv, "--outdir", cfg.outdir)) continue;
    if (take_arg(i, argc, argv, "--x-out", cfg.x_out)) continue;
    if (take_arg(i, argc, argv, "--y-out", cfg.y_out)) continue;
    if (take_arg(i, argc, argv, "--frame-csv", cfg.frame_csv)) continue;
    if (take_arg(i, argc, argv, "--metrics-json", cfg.metrics_json)) continue;
    if (take_arg(i, argc, argv, "--load-window-rom", cfg.load_window_rom)) continue;
    if (take_arg(i, argc, argv, "--emit-window-rom", cfg.emit_window_rom)) continue;
    if (take_arg(i, argc, argv, "--debug-dir", cfg.debug_dir)) continue;
    if (take_arg(i, argc, argv, "--debug-frames", s)) { cfg.debug_frames = parse_int_set(s); continue; }

    if (take_flag(i, argc, argv, "--quiet")) { cfg.quiet = true; continue; }
    if (take_flag(i, argc, argv, "--no-strict")) { cfg.strict = false; continue; }
    if (take_flag(i, argc, argv, "--help") || take_flag(i, argc, argv, "-h")) {
      print_usage(argv[0]);
      return 0;
    }

    std::cerr << "Unknown or incomplete option: " << argv[i] << "\n";
    print_usage(argv[0]);
    return 1;
  }

  Phase2GoldenModel model(cfg);
  return model.run();
}
