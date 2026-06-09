# Canonical MEMH Hashing

## Purpose

This document defines the canonical memory-file encoding and SHA-256 hashing rule. The rule is strict because `memh` files become signoff artifacts consumed by RTL, board replay, and release checkers.

The hash is computed over the logical integer vector serialized in canonical `memh` form. It is not computed over arbitrary host file bytes.

## Canonical line format

Every canonical `memh` file uses:

- exactly one value per line;
- lowercase hexadecimal digits only;
- no `0x` prefix;
- no leading spaces;
- no trailing spaces;
- no comments;
- no blank lines;
- exactly one LF byte after every value;
- fixed digit count based on declared width.

CRLF is not canonical. Uppercase hex is not canonical. Variable-width lines are not canonical.

## Digit count

For width `W`, each line contains:

```text
ceil(W / 4)
```

hex digits.

Examples:

| Width | Digits |
|---:|---:|
| 12 | 3 |
| 16 | 4 |
| 17 | 5 |
| 27 | 7 |
| 28 | 7 |
| 36 | 9 |
| 37 | 10 |
| 56 | 14 |

## Unsigned encoding

For an unsigned `W`-bit file:

```text
0 <= value < 2^W
```

The line is the zero-padded lowercase hex representation of the value using exactly `ceil(W/4)` digits.

Example for unsigned 16-bit:

| Value | Encoded line |
|---:|---|
| 0 | `0000` |
| 1 | `0001` |
| 32768 | `8000` |
| 65535 | `ffff` |

Unsigned readers must mask to `W` bits and must not sign-extend.

## Signed encoding

For a signed `W`-bit file, the encoded value is the low `W` bits of the two's-complement representation, zero-padded to exactly `ceil(W/4)` hex digits.

Reader rule:

1. parse hex as unsigned;
2. mask to `W` bits;
3. sign-extend from bit `W-1`.

Example for signed 12-bit stream files:

| Logical value | Low 12-bit encoding | Line |
|---:|---:|---|
| 0 | `0x000` | `000` |
| 1 | `0x001` | `001` |
| 2047 | `0x7ff` | `7ff` |
| -1 | `0xfff` | `fff` |
| -2048 | `0x800` | `800` |

Example for signed 17-bit twiddles:

| Logical value | Line |
|---:|---|
| +32768 | `08000` |
| -32768 | `18000` |
| -1 | `1ffff` |

## Baseline artifact signedness

| File | Signedness | Width |
|---|---|---:|
| `x_in.memh` | signed | `N = 12` |
| `y_out.memh` | signed | `N = 12` |
| `window_qw.memh` | unsigned | `W_Qw = 16` |
| `twiddle_re.memh` | signed | `W_tw = 17` |
| `twiddle_im.memh` | signed | `W_tw = 17` |
| `twiddle_inv_re.memh` | signed | `W_tw = 17` |
| `twiddle_inv_im.memh` | signed | `W_tw = 17` |

## Canonical hash procedure

To compute a canonical SHA-256 hash:

1. load the logical integer vector using the declared signedness and width;
2. range-check every logical value;
3. re-serialize every value into canonical fixed-width lowercase hex;
4. append exactly one LF byte after every value;
5. compute SHA-256 over those bytes.

Pseudocode:

```text
bytes = empty
for value in logical_values:
    encoded = encode_fixed_width_hex(value, width, signedness)
    bytes += ascii(encoded)
    bytes += b"\n"
sha256 = SHA256(bytes)
```

This means a checker may normalize an input file before hashing. The recorded hash is the hash of the canonical serialization, not necessarily the literal bytes in the source file.

## Why raw-file hashing is not enough

These files describe the same logical vector but have different raw bytes:

```text
001\n002\nfff\n
001\r\n002\r\nfff\r\n
001  \n002\nFFF\n
0x001\n0x002\n0xfff\n
1\n2\nfff\n```

Only the first form is canonical for signed 12-bit. Raw-byte hashing would treat line endings, whitespace, and case as different logical data. Canonical logical hashing avoids platform noise while still enforcing exact integer content.

## Rejection vs normalization

The checker may support two modes:

| Mode | Behavior |
|---|---|
| `strict` | reject non-canonical formatting immediately |
| `normalize-check` | parse, normalize in memory, hash canonical bytes, and warn/fail based on policy |

Release freeze should use strict mode. Developer convenience tools may support normalize-check to identify repairable formatting problems.

## Writer requirements

Artifact writers must emit canonical bytes directly. Do not rely on the checker to repair output.

Writer checklist:

- open text/binary output with LF behavior controlled;
- format using lowercase hex;
- pad to fixed digit count;
- write exactly one `\n` after each value;
- do not write a BOM;
- do not write comments;
- do not write trailing blank line beyond the required LF after the last value.

Note: a file with one LF after the last value necessarily ends with a newline. That is correct.

## Reader requirements

Readers should:

1. reject blank lines in strict mode;
2. reject comments;
3. reject signs such as `-001`;
4. reject `0x` prefixes;
5. reject values outside the declared width;
6. for signed files, sign-extend only after masking to width;
7. return logical integers, not raw unsigned encodings.

## Hash fields

Hash fields appear in:

```text
coeff_manifest.json
config.json
test_vectors.json
metrics.json
quality_bounds.json
artifact_index.json
stream_hashes.json
frozen_release_manifest.json
```

Every hash field stores a 64-character lowercase hexadecimal SHA-256 digest.

## Minimum tests

The canonical hash module should test:

| Test | Expected behavior |
|---|---|
| signed 12-bit `-1` | encoded as `fff` |
| signed 12-bit `-2048` | encoded as `800` |
| signed 17-bit `+32768` | encoded as `08000` |
| signed 17-bit `-32768` | encoded as `18000` |
| unsigned 16-bit `32768` | encoded as `8000` |
| uppercase input | rejected in strict mode |
| CRLF input | rejected in strict mode, normalized in normalize-check mode if allowed |
| missing final LF | rejected in strict mode |
| extra blank line | rejected |
| width overflow | rejected |

## Command-line expectations

`tools/hash_memh.py` should eventually support:

```bash
python tools/hash_memh.py \
  --path artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh \
  --width 12 \
  --signed \
  --strict
```

`tools/artifact_check.py` should use the same library code. Do not implement hashing twice.

