// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jaeson
// phase1_golden.cpp (C++17)
// Bit-accurate golden model for Phase 1: Haar(2-sample) + hard threshold + recon + metrics
// Compile: g++ -O2 -std=c++17 phase1_golden.cpp -o golden
// Run:     ./golden --nsamp 10000 --n 12 --thresh 16 --shift 3 --seed 0xACE1
// Produces: x.memh, y.memh, sup.memh, metrics.json

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <algorithm>

struct Config {
  int      N       = 12;      // sample bit-width
  int      SHIFT   = 3;       // noise shaper smoothing
  int      THRESH  = 0;       // threshold (magnitude compare)
  uint32_t SEED    = 0xACE1u; // LFSR seed (must be non-zero)
  int      NSAMP   = 10000;   // number of samples to generate/process (should be even)
  std::string x_path   = "x.memh";
  std::string y_path   = "y.memh";
  std::string sup_path = "sup.memh";
  std::string met_path = "metrics.json";
};

// Helpers: saturation / sign / arithmetic shift
static inline int32_t satN(int64_t v, int N) {
  const int64_t lo = -(int64_t(1) << (N - 1));
  const int64_t hi =  (int64_t(1) << (N - 1)) - 1;
  if (v < lo) return (int32_t)lo;
  if (v > hi) return (int32_t)hi;
  return (int32_t)v;
}

// Arithmetic shift right that matches hardware: rounds toward -infinity.
static inline int32_t asr(int32_t v, unsigned sh) {
  if (sh == 0) return v;
  if (v >= 0) return (int32_t)(v >> sh);
  // emulate sign-extension shift for negatives
  // Example: -3 >>> 1 == -2
  int32_t av = -v;
  int32_t bias = (1u << sh) - 1u;
  return -(int32_t)((av + bias) >> sh);
}

// Divide-by-2 with rounding: ties away from zero 
static inline int32_t round_div2_ties_away(int32_t num) {
  if ((num & 1) == 0) return (int32_t)(num / 2); // exact
  if (num >= 0) return (int32_t)((num + 1) / 2);
  return (int32_t)((num - 1) / 2);
}

static inline int32_t iabs32(int32_t v) {
  // safe for our ranges 
  return (v < 0) ? -v : v;
}

// LFSR + noise mapping + shaper
static inline uint32_t lfsr_step16(uint32_t s) {
  // 16-bit LFSR example:
  // new_bit = bit0 ^ bit2 ^ bit3 ^ bit5 (when shifting right)
  // Keep exactly same taps in RTL.
  uint32_t b = ((s >> 0) ^ (s >> 2) ^ (s >> 3) ^ (s >> 5)) & 1u;
  s = (s >> 1) | (b << 15);
  return (s & 0xFFFFu);
}

static inline int32_t map_lfsr_to_signedN(uint32_t lfsr, int N) {
  // Take low N bits as unsigned and center to signed by subtracting 2^(N-1)
  uint32_t mask = (N == 32) ? 0xFFFFFFFFu : ((1u << N) - 1u);
  uint32_t u = lfsr & mask;                // 0 .. 2^N-1
  int32_t  s = (int32_t)u - (1 << (N - 1)); // -2^(N-1) .. 2^(N-1)-1
  return s;
}

static inline int32_t noise_shaper_step(int32_t &state, int32_t u, int SHIFT, int N) {
  // state = state + ((u - state) >>> SHIFT)
  int32_t diff = (int32_t)(u - state);
  int32_t delta = asr(diff, (unsigned)SHIFT);
  state = (int32_t)(state + delta);
  // output clipped to N-bit range 
  return satN(state, N);
}

// Haar pair processing
struct PairOut {
  int32_t y0 = 0, y1 = 0;
  int32_t a  = 0, d  = 0, abs_d = 0;
  int     suppressed = 0; // 1 if |d| < THRESH else 0
};

static inline PairOut haar_pair(int32_t x0, int32_t x1, int THRESH, int N) {
  PairOut o;

  // widen into 32-bit safe math
  int32_t a = (int32_t)(x0 + x1);
  int32_t d = (int32_t)(x0 - x1);
  int32_t abs_d = iabs32(d);

  o.a = a; o.d = d; o.abs_d = abs_d;

  int32_t d_p = 0;
  if (abs_d < THRESH) {
    o.suppressed = 1;
    d_p = 0;
  } else {
    o.suppressed = 0;
    d_p = d;
  }

  // reconstruct: y0=(a+d')/2, y1=(a-d')/2 with rounding + saturation
  int32_t num0 = (int32_t)(a + d_p);
  int32_t num1 = (int32_t)(a - d_p);

  int32_t y0 = round_div2_ties_away(num0);
  int32_t y1 = round_div2_ties_away(num1);

  o.y0 = satN(y0, N);
  o.y1 = satN(y1, N);

  return o;
}

// Vector dumping memh N-bit two's complement per line
static inline uint32_t to_twosN(int32_t v, int N) {
  // Convert signed int32 to N-bit two's complement unsigned representation
  uint64_t mask = (N == 64) ? ~0ull : ((1ull << N) - 1ull);
  uint64_t uv = (uint64_t)(uint32_t)v; // two's complement preserved in low bits
  return (uint32_t)(uv & mask);
}

static void dump_memh_samples(const std::string &path, const std::vector<int32_t> &samps, int N) {
  std::ofstream f(path);
  if (!f) { throw std::runtime_error("Failed to open " + path); }

  int hexw = (N + 3) / 4; // digits
  for (auto v : samps) {
    uint32_t u = to_twosN(v, N);
    f << std::hex << std::uppercase << std::setw(hexw) << std::setfill('0') << u << "\n";
  }
}

static void dump_memh_flags(const std::string &path, const std::vector<int> &flags) {
  std::ofstream f(path);
  if (!f) { throw std::runtime_error("Failed to open " + path); }
  for (auto b : flags) f << (b ? "1" : "0") << "\n";
}

static void dump_metrics_json(const std::string &path,
                              uint64_t total_pairs,
                              uint64_t suppressed_pairs,
                              uint64_t sum_abs_err,
                              uint64_t sum_sq_err) {
  std::ofstream f(path);
  if (!f) { throw std::runtime_error("Failed to open " + path); }
  f << "{\n";
  f << "  \"total_pairs\": " << total_pairs << ",\n";
  f << "  \"suppressed_pairs\": " << suppressed_pairs << ",\n";
  f << "  \"sum_abs_err\": " << sum_abs_err << ",\n";
  f << "  \"sum_sq_err\": " << sum_sq_err << "\n";
  f << "}\n";
}

// CLI parsing 
static bool take_arg(int &i, int argc, char **argv, const char *name, std::string &out) {
  if (std::strcmp(argv[i], name) == 0 && i + 1 < argc) { out = argv[++i]; return true; }
  return false;
}
static bool take_arg_int(int &i, int argc, char **argv, const char *name, int &out) {
  std::string s;
  if (take_arg(i, argc, argv, name, s)) { out = std::stoi(s, nullptr, 0); return true; }
  return false;
}
static bool take_arg_u32(int &i, int argc, char **argv, const char *name, uint32_t &out) {
  std::string s;
  if (take_arg(i, argc, argv, name, s)) { out = (uint32_t)std::stoul(s, nullptr, 0); return true; }
  return false;
}

int main(int argc, char **argv) {
  Config cfg;

  for (int i = 1; i < argc; i++) {
    take_arg_int(i, argc, argv, "--n", cfg.N);
    take_arg_int(i, argc, argv, "--shift", cfg.SHIFT);
    take_arg_int(i, argc, argv, "--thresh", cfg.THRESH);
    take_arg_int(i, argc, argv, "--nsamp", cfg.NSAMP);
    take_arg_u32(i, argc, argv, "--seed", cfg.SEED);

    std::string s;
    if (take_arg(i, argc, argv, "--xout", s)) cfg.x_path = s;
    if (take_arg(i, argc, argv, "--yout", s)) cfg.y_path = s;
    if (take_arg(i, argc, argv, "--supout", s)) cfg.sup_path = s;
    if (take_arg(i, argc, argv, "--metrics", s)) cfg.met_path = s;
  }

  if (cfg.SEED == 0) {
    std::cerr << "ERROR: seed must be non-zero for LFSR.\n";
    return 1;
  }
  if (cfg.NSAMP % 2 != 0) {
    std::cerr << "NOTE: nsamp must be even; rounding down by 1.\n";
    cfg.NSAMP -= 1;
  }
  if (cfg.N < 2 || cfg.N > 30) {
    std::cerr << "ERROR: N out of supported range for this demo (2..30).\n";
    return 1;
  }

  // Streams
  std::vector<int32_t> x_stream;
  std::vector<int32_t> y_stream;
  std::vector<int> suppressed_flags;

  x_stream.reserve(cfg.NSAMP);
  y_stream.reserve(cfg.NSAMP);
  suppressed_flags.reserve(cfg.NSAMP / 2);

  // Metrics
  uint64_t total_pairs = 0;
  uint64_t suppressed_pairs = 0;
  uint64_t sum_abs_err = 0;
  uint64_t sum_sq_err  = 0;

  // Generator state
  uint32_t lfsr = cfg.SEED & 0xFFFFu;
  int32_t shaper_state = 0;

  bool have_x0 = false;
  int32_t x0 = 0;

  for (int n = 0; n < cfg.NSAMP; n++) {
    // LFSR
    lfsr = lfsr_step16(lfsr);

    // map -> signed noise -> shaper -> x[n]
    int32_t u = map_lfsr_to_signedN(lfsr, cfg.N);
    int32_t x = noise_shaper_step(shaper_state, u, cfg.SHIFT, cfg.N);

    x_stream.push_back(x);

    // pair assemble
    if (!have_x0) {
      x0 = x;
      have_x0 = true;
    } else {
      int32_t x1 = x;
      have_x0 = false;

      PairOut po = haar_pair(x0, x1, cfg.THRESH, cfg.N);

      // serialize outputs
      y_stream.push_back(po.y0);
      y_stream.push_back(po.y1);

      // metrics
      total_pairs++;
      suppressed_pairs += (uint64_t)po.suppressed;
      suppressed_flags.push_back(po.suppressed);

      int32_t e0 = (int32_t)(x0 - po.y0);
      int32_t e1 = (int32_t)(x1 - po.y1);

      sum_abs_err += (uint64_t)iabs32(e0) + (uint64_t)iabs32(e1);
      sum_sq_err  += (uint64_t)((int64_t)e0 * (int64_t)e0) + (uint64_t)((int64_t)e1 * (int64_t)e1);
    }
  }

  // Sanity: THRESH=0 must be lossless (bit-exact)
  if (cfg.THRESH == 0) {
    bool ok = true;
    if (x_stream.size() != y_stream.size()) ok = false;
    else {
      for (size_t i = 0; i < x_stream.size(); i++) {
        if (x_stream[i] != y_stream[i]) { ok = false; break; }
      }
    }
    if (!ok || sum_abs_err != 0 || sum_sq_err != 0) {
      std::cerr << "ERROR: THRESH=0 sanity failed (should be lossless).\n";
      return 2;
    }
  }

  // Dump files
  try {
    dump_memh_samples(cfg.x_path, x_stream, cfg.N);
    dump_memh_samples(cfg.y_path, y_stream, cfg.N);
    dump_memh_flags(cfg.sup_path, suppressed_flags);
    dump_metrics_json(cfg.met_path, total_pairs, suppressed_pairs, sum_abs_err, sum_sq_err);
  } catch (const std::exception &e) {
    std::cerr << "ERROR: " << e.what() << "\n";
    return 3;
  }

  // Print quick summary
  double sup_ratio = (total_pairs == 0) ? 0.0 : double(suppressed_pairs) / double(total_pairs);
  std::cout << "Done.\n";
  std::cout << "  N=" << cfg.N << " SHIFT=" << cfg.SHIFT << " THRESH=" << cfg.THRESH << " NSAMP=" << cfg.NSAMP << "\n";
  std::cout << "  total_pairs=" << total_pairs
            << " suppressed_pairs=" << suppressed_pairs
            << " suppressed_ratio=" << sup_ratio << "\n";
  std::cout << "  sum_abs_err=" << sum_abs_err << " sum_sq_err=" << sum_sq_err << "\n";
  std::cout << "  wrote: " << cfg.x_path << ", " << cfg.y_path << ", " << cfg.sup_path << ", " << cfg.met_path << "\n";

  return 0;
}
