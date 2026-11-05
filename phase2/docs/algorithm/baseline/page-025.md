# Baseline PDF page 025

Historical Part I, core algorithm. Printed page 12. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=25).

[Previous](page-024.md) | [Index](../README.md) | [Next](page-026.md)

```text
 5:   span ← 2^s, half ← 2^(s-1)
 6:   for base = 0 to L - 1 step span do
 7:      for j = 0 to half - 1 do
 8:          e ← jL/span
 9:          t ← cmul(A[base + j + half ], Wfwd[e])
10:           a ← A[base + j]
11:           A[base + j] ← rnd2(a + t)
12:           A[base + j + half ] ← rnd2(a - t)
13:       end for
14:    end for
15: end for
16: return X ← A
```

### Algorithm 5 Exact custom IFFTunscaled integer algorithm

```text
Require: conjugate-symmetric masked spectrum Xb[0:L - 1] with F fractional bits; frozen inverse twiddle table Winv[e]
Ensure: unscaled complex time-domain vector v[0:L - 1] in natural order
 1: for k = 0 to L - 1 do
 2:    B[k] ←Xb[bitrevP (k)]
 3: end for
 4: for s = 1 to P do
 5:    span ← 2^s, half ← 2^(s-1)
 6:    for base = 0 to L - 1 step span do
 7:        for j = 0 to half - 1 do
 8:           e ← jL/span
 9:           t ← cmul(B[base + j + half ], Winv[e])
10:            a ← B[base + j]
11:            B[base + j] ← a + t
12:            B[base + j + half ] ← a - t
13:         end for
14:     end for
15: end for
16: return v ← B
```

All additions and subtractions in Algorithms 4 and 5 shall be sign-extended before the defined rounding or storage step. Silent truncation before rnd2, `rnd_shr`, or threshold comparison is not allowed.

## 7 Metrics and Artifact Contract

### 7.1 Spectral metrics

The unique-bin weight is

$$
\omega[k]=\begin{cases}1,&k=0\\1,&k=L/2\\2,&1\le k\le L/2-1.\end{cases}\tag{7.1}
$$
