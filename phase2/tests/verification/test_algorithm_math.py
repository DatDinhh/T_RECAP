"""Regression checks for the editable algorithm's rendered equations.

These tests do not run LaTeX or prove mathematical equivalence. They ensure that
source changes cannot silently reuse old images, malformed images cannot pass
publication checks, and the reported page 017 layout defect stays corrected.
Only disposable copies are modified. Run from phase2 with
python tests/verification/test_algorithm_math.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ALGORITHM = Path(__file__).resolve().parents[2] / 'docs/algorithm'
SPEC = importlib.util.spec_from_file_location('algorithm_math_under_test', ALGORITHM / 'render_math.py')
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RenderedMathRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='trecap-math-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'algorithm'
        shutil.copytree(ALGORITHM, self.root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.context = patch.object(renderer, 'ROOT', self.root)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.manifest_path = self.root / 'math_manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        self.row = next(r for r in self.manifest['formulas'] if r['kind'] == 'display')

    def rewrite_svg_and_reseal(self, transform):
        """Refresh the hash so geometry validation, not only hashing, is tested."""
        path = self.root / self.row['svg']
        node = ET.fromstring(path.read_bytes())
        transform(node)
        data = ET.tostring(node, encoding='utf-8', xml_declaration=True)
        path.write_bytes(data)
        self.row['svg_sha256'] = renderer.sha_bytes(data)
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_published_bundle_and_page017_are_readable(self):
        summary = renderer.check()
        self.assertEqual(summary['documents'], 107)
        self.assertEqual(summary['display_formulas'], 123)
        formulas = self.manifest['formulas']
        sample_range = next(r for r in formulas if r'\tag{3.1}' in r['tex'])
        saturation = next(r for r in formulas if r'\tag{3.2}' in r['tex'])
        # The reported defect stacked a horizontal set expression vertically.
        size = sample_range['dimensions']
        self.assertGreater(size['width_px'], 3 * size['height_px'])
        self.assertGreater(saturation['dimensions']['height_px'], size['height_px'])
        self.assertIn(r'\operatorname{sat}', saturation['tex'])
        page = (self.root / 'baseline/page-017.md').read_text(encoding='utf-8')
        self.assertIn('../' + saturation['svg'], page)
        self.assertNotIn('$$', page)

    def test_changed_source_cannot_reuse_an_old_image(self):
        path = self.root / self.row['source']
        source = path.read_text(encoding='utf-8')
        self.assertIn(self.row['tex'], source)
        path.write_text(source.replace(self.row['tex'], self.row['tex'] + '+1', 1), encoding='utf-8')
        with self.assertRaisesRegex(AssertionError, 'Formula source or mapping changed'):
            renderer.check()

    def test_missing_equation_image_is_rejected(self):
        (self.root / self.row['svg']).unlink()
        with self.assertRaises(FileNotFoundError):
            renderer.check()

    def test_zero_width_is_rejected_even_after_resealing_hash(self):
        self.rewrite_svg_and_reseal(lambda node: node.set('width', '0px'))
        with self.assertRaisesRegex(AssertionError, 'Collapsed equation dimensions'):
            renderer.check()

    def test_stretched_equation_is_rejected_even_after_resealing_hash(self):
        self.rewrite_svg_and_reseal(lambda node: node.set('width', str(float(node.get('width').removesuffix('px')) * 2) + 'px'))
        with self.assertRaisesRegex(AssertionError, 'aspect ratio'):
            renderer.check()

    def test_reintroduced_raw_math_is_rejected(self):
        page = self.root / 'baseline/page-017.md'
        page.write_text(page.read_text(encoding='utf-8') + '\n$$\nx+y\n$$\n', encoding='utf-8')
        with self.assertRaisesRegex(AssertionError, 'Stale rendered Markdown'):
            renderer.check()

    def test_external_glyph_dependency_is_rejected(self):
        def external_reference(node):
            ET.SubElement(node, '{' + renderer.SVG + '}use', {'href': 'https://example.invalid/font.svg#glyph'})
        self.rewrite_svg_and_reseal(external_reference)
        with self.assertRaisesRegex(AssertionError, 'Unresolved/external SVG reference'):
            renderer.check()

    def test_empty_vector_image_is_rejected(self):
        def remove_paths(node):
            for parent in node.iter():
                for child in list(parent):
                    if child.tag == '{' + renderer.SVG + '}path':
                        parent.remove(child)
        self.rewrite_svg_and_reseal(remove_paths)
        with self.assertRaisesRegex(AssertionError, 'no vector glyphs'):
            renderer.check()


if __name__ == '__main__':
    unittest.main(verbosity=2)
