"""Numerical boundary tests separate from the RTL scoreboard fixtures."""
import unittest
import numpy as np

from reference import accumulate, coefficients, convert, round_away, validate_pairs


class ReferenceTests(unittest.TestCase):
    def test_rejects_malformed_pairs(self):
        for pairs in ([], [1, 2], [[1]], [[1, 2, 3]], [[-1, 128]], [[128, 256]], [[0.5, 128]]):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                validate_pairs(pairs)

    def test_rejects_invalid_gain(self):
        for gain in (-1, 4, 0.5, "2"):
            with self.subTest(gain=gain), self.assertRaises(ValueError):
                convert([[128, 128]], gain)

    def test_exact_one_pair_with_zero_boundaries(self):
        taps = coefficients()
        actual = accumulate([[255, 0]])
        expected = np.array([255*taps[40], 255*taps[41], -255*taps[42], -255*taps[43]])
        np.testing.assert_array_equal(actual, expected)

    def test_byte_complement_negates_accumulator(self):
        rng = np.random.default_rng(731)
        pairs = rng.integers(0, 256, (73, 2))
        np.testing.assert_array_equal(accumulate(255-pairs), -accumulate(pairs))

    def test_half_ties_both_signs(self):
        for shift in range(13, 17):
            values = np.array([2047, -2048]) * (1 << shift) + (1 << (shift-1))
            np.testing.assert_array_equal(round_away(values, shift), [2048, -2048])
            np.testing.assert_array_equal(round_away(-values, shift), [-2048, 2048])

    def test_clamp_is_asymmetric_signed12(self):
        rng = np.random.default_rng(191)
        pairs = rng.integers(0, 2, (2500, 2)) * 255
        result = convert(pairs, 3)
        self.assertTrue(np.any(result["rounded"] > 2047))
        self.assertTrue(np.any(result["rounded"] < -2048))
        self.assertEqual(int(result["samples"].max()), 2047)
        self.assertEqual(int(result["samples"].min()), -2048)
        np.testing.assert_array_equal(result["clipped"], result["samples"] != result["rounded"])

    def test_exact_four_samples_per_pair(self):
        for count in (1, 2, 9, 10, 11, 127, 96000):
            with self.subTest(count=count):
                result = convert(np.full((count, 2), 128), 1)
                self.assertEqual(len(result["samples"]), 4*count)
                self.assertEqual(int(result["clipped"].sum()), 0)

    def test_iq_orientation_changes_output(self):
        n = np.arange(64)
        pairs = np.rint(127.5 + 80*np.stack([np.cos(2*np.pi*n/8), np.sin(2*np.pi*n/8)], axis=1)).astype(int)
        self.assertFalse(np.array_equal(convert(pairs)["samples"], convert(pairs[:, ::-1])["samples"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
