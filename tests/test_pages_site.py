import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pages = load('assemble_pages', ROOT / 'scripts/assemble-pages.py')
links = load('site_links', ROOT / 'docs/site-links.py')


class PagesSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.docs = self.root / 'documentation'
        for name, content in {
            'cache/nix-cache-info': b'StoreDir: /nix/store\n',
            'cache/example.narinfo': b'URL: https://example.invalid/immutable.nar.zst\nSig: existing\n',
            'index.html': b'<title>Aurora cache</title>',
            'channels.json': b'{"testing":"existing"}',
            'cache.pub': b'public-key',
        }.items():
            self.write(self.site / name, content)
        self.write(self.docs / 'index.html', b'guides')
        self.write(self.docs / 'options/index.html', b'option browser')
        self.write(self.docs / 'options/main.js', b'frontend')
        self.before = self.snapshot(self.site)

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    @staticmethod
    def snapshot(directory):
        return {p.relative_to(directory): p.read_bytes() for p in directory.rglob('*') if p.is_file()}

    def test_composition_preserves_cache_and_channels_byte_for_byte(self):
        pages.assemble(self.site, self.docs)
        after = self.snapshot(self.site)
        self.assertEqual({name: after[name] for name in self.before}, self.before)
        self.assertEqual(self.snapshot(self.site / 'docs'), self.snapshot(self.docs))

    def test_incomplete_site_is_refused_before_copying(self):
        (self.docs / 'options/index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'guides and the option browser'):
            pages.assemble(self.site, self.docs)
        self.assertEqual(self.snapshot(self.site), self.before)

    def test_symlinks_cannot_escape_into_the_pages_artifact(self):
        (self.docs / 'linked-cache').symlink_to(self.site / 'cache', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsupported entry'):
            pages.assemble(self.site, self.docs)
        self.assertEqual(self.snapshot(self.site), self.before)

    def test_existing_documentation_is_not_partially_overwritten(self):
        self.write(self.site / 'docs/keep', b'existing')
        before = self.snapshot(self.site)
        with self.assertRaises(FileExistsError):
            pages.assemble(self.site, self.docs)
        self.assertEqual(self.snapshot(self.site), before)

    def test_overlapping_staging_directories_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            pages.assemble(self.site, self.site)
        self.assertEqual(self.snapshot(self.site), self.before)


class PublishedLinkTests(unittest.TestCase):
    def rewrite(self, text):
        return links.on_page_markdown(text, SimpleNamespace(file=SimpleNamespace(src_uri='modules.md')))

    def test_repository_files_link_to_source_instead_of_missing_site_paths(self):
        self.assertEqual(self.rewrite('[Touch ID](../sep/README.md#setup)'),
                         '[Touch ID](https://github.com/aurora-silicon/nixos-aurora/blob/main/sep/README.md#setup)')

    def test_internal_guide_links_stay_available_to_mkdocs(self):
        text = '[Gaming](gaming.md#fex) [Options](/nixos-aurora/docs/options/) [Here](#here)'
        self.assertEqual(self.rewrite(text), text)

    def test_external_links_are_preserved(self):
        text = '[Example](https://example.com/path?q=value#heading)'
        self.assertEqual(self.rewrite(text), text)

    def test_reserved_index_and_browser_paths_use_the_published_reference_pages(self):
        self.assertEqual(self.rewrite('[Notes](README.md#hardware) [Reference](options.md)'),
                         '[Notes](reference.md#hardware) [Reference](options-reference.md)')
