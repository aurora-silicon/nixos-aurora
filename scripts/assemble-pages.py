#!/usr/bin/env python3
"""Add the documentation site to an authenticated cache's Pages tree."""
import argparse
from pathlib import Path
import shutil


def assemble(site, documentation):
    site, documentation = Path(site).resolve(), Path(documentation).resolve()
    if site.is_relative_to(documentation) or documentation.is_relative_to(site):
        raise ValueError('cache and documentation staging directories must be separate')
    if not (site / 'cache/nix-cache-info').is_file() or not (site / 'index.html').is_file():
        raise ValueError('expected an assembled cache site')
    if not all((documentation / name).is_file() for name in ('index.html', 'options/index.html')):
        raise ValueError('documentation must contain guides and the option browser')
    for path in documentation.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f'documentation contains an unsupported entry: {path}')
    # Copy into one owned subtree; cache metadata and channel state stay byte-identical.
    shutil.copytree(documentation, site / 'docs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--documentation', type=Path, required=True)
    args = parser.parse_args()
    assemble(args.site, args.documentation)
