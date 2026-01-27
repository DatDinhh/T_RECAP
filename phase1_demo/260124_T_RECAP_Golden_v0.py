# T-RECAP Phase 1 (DE10-Lite) Haar Demo — Python Golden Model v0 1/24/26 (Applebee)
#
# LFSR -> signed noise u[n] ->  noise shaper -> x[n]
# Pairing (x0,x1) -> Haar forward (a,d) -> selective suppression -> Haar inverse -> y
# Metrics: total pairs, suppressed pairs, sum abs err, sum sq err

import csv
from dataclasses import dataclass


# Output metrics
@dataclass
class Metrics:
    total_pairs: int = 0
    suppressed_pairs: int = 0
    sum_abs_err: int = 0
    sum_sq_err: int = 0

# Run parameters
K = 1280            # Number of Haar pairs
N = 12              # Sample bit width x[n] y[n] 
T = 16              # Threshold max = 2**N - 1
SHIFT = 3           # Noise-shaper smoothing factor
W = 16              # LFSR bit width
rseed = 0xACE1      # LFSR initial state

# Functions

def satN(z: int, N: int):
    
    lo = -(1 << (N - 1))
    hi = (1 << (N - 1)) - 1
    if z < lo:
        return lo
    if z > hi:
        return hi
    return z


def asr(z: int, k: int):

    if k < 0:
        raise ValueError("asr: k must be >= 0")
    return z >> k


def rnd2(q: int):

    if (q & 1) == 0:  # even
        return q // 2
    # odd
    if q >= 0:
        return (q + 1) // 2
    else:
        return (q - 1) // 2


def lfsr_step(r: int, W: int):

    if r == 0:
        raise ValueError("LFSR state must be non-zero (rseed != 0)")
   
    b = ((r >> 0) ^ (r >> 2) ^ (r >> 3) ^ (r >> 5)) & 0x1
    r_next = ((b << (W - 1)) | (r >> 1)) & ((1 << W) - 1)
    return r_next


def lfsr_to_signed_noise(r: int, N: int):

    u_t = r & ((1 << N) - 1)
    u = u_t - (1 << (N - 1))
    return u


def run_trecap_phase1_csv(K_pairs: int, N: int, T: int, SHIFT: int, W: int, rseed: int, csv_path: str,):

    if K_pairs <= 0:
        raise ValueError("K_pairs must be positive")
    if rseed == 0:
        raise ValueError("rseed must be non-zero")

    r = rseed & ((1 << W) - 1)
    s = 0  
    metrics = Metrics()

    x_stream = []
    y_stream = []

    have_x0 = False
    x0 = 0
    pair_k = 0

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["K_Pairs", "N", "T", "SHIFT", "W", "r_seed"])
        w.writerow([K_pairs, N, T, SHIFT, W, rseed])
        w.writerow(["k", "x0", "x1", "a", "d", "sk", "d_prime", "y0", "y1"])

        # Iterate over 2K samples 
        for n in range(2 * K_pairs):
            r = lfsr_step(r, W)

            u = lfsr_to_signed_noise(r, N)

            s = s + asr(u - s, SHIFT)

            x = satN(s, N)
            
            x_stream.append(x)

            if not have_x0:
                x0 = x
                have_x0 = True
            else:
                x1 = x
                have_x0 = False

                a = x0 + x1
                d = x0 - x1

                sk = 1 if abs(d) < T else 0
                d_prime = (1 - sk) * d

                y0 = satN(rnd2(a + d_prime), N)
                y1 = satN(rnd2(a - d_prime), N)

                y_stream.append(y0)
                y_stream.append(y1)

                e0 = x0 - y0
                e1 = x1 - y1

                metrics.total_pairs += 1
                metrics.suppressed_pairs += sk
                metrics.sum_abs_err += abs(e0) + abs(e1)
                metrics.sum_sq_err += e0 * e0 + e1 * e1
                
                w.writerow([pair_k, x0, x1, a, d, sk, d_prime, y0, y1])
                pair_k += 1

    return x_stream, y_stream, metrics

def run_trecap_phase1(K_pairs: int, N: int, T: int, SHIFT: int, W: int, rseed: int):

    if K_pairs <= 0:
        raise ValueError("K_pairs must be positive")
    if rseed == 0:
        raise ValueError("rseed must be non-zero")

    r = rseed & ((1 << W) - 1)
    s = 0  
    metrics = Metrics()

    x_stream = []
    y_stream = []

    have_x0 = False
    x0 = 0


        # Iterate over 2K samples 
    for n in range(2 * K_pairs):
        r = lfsr_step(r, W)

        u = lfsr_to_signed_noise(r, N)

        s = s + asr(u - s, SHIFT)

        x = satN(s, N)
            
        x_stream.append(x)

        if not have_x0:
            x0 = x
            have_x0 = True
        else:
            x1 = x
            have_x0 = False

            a = x0 + x1
            d = x0 - x1

            sk = 1 if abs(d) < T else 0
            d_prime = (1 - sk) * d

            y0 = satN(rnd2(a + d_prime), N)
            y1 = satN(rnd2(a - d_prime), N)

            y_stream.append(y0)
            y_stream.append(y1)

            e0 = x0 - y0
            e1 = x1 - y1

            metrics.total_pairs += 1
            metrics.suppressed_pairs += sk
            metrics.sum_abs_err += abs(e0) + abs(e1)
            metrics.sum_sq_err += e0 * e0 + e1 * e1
                
           

    return x_stream, y_stream, metrics


def exact_reconstruction(): # make sure y = x for T=0

    K = 200
    x, y, m = run_trecap_phase1(K_pairs=K, N=N, T=0, SHIFT=SHIFT, W=W, rseed=rseed)
    assert x == y, "Sanity check failed: y != x when T=0"
    assert m.sum_abs_err == 0, "Sanity check failed: sum_abs_err != 0 when T=0"
    assert m.sum_sq_err == 0, "Sanity check failed: sum_sq_err != 0 when T=0"
    print("Sanity check passed: exact reconstruction when T=0")



# Main Function 
if __name__ == "__main__":
    csv_file = "haar_pair.csv"
    x, y, m = run_trecap_phase1_csv(K_pairs=K, N=N, T=T, SHIFT=SHIFT, W=W, rseed=rseed, csv_path=csv_file)

    print("First 10 x:", x[:10])
    print("First 10 y:", y[:10])
    print("Metrics:", m)
    print("Suppressed ratio:", m.suppressed_pairs / m.total_pairs)

    exact_reconstruction()
