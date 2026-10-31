#!/usr/bin/env python3
"""Place pinned source archives in the Nix store before a build.

fetchurl's outputs are fixed-output paths: their store path depends only on
the name and the SHA-256, so an archive added with `nix-store --add-fixed`
under the same name is exactly the path the build would fetch. This lets CI
take archives from the verified source cache (or codeload, with backoff that
honours Retry-After) instead of fetchurl's three quick retries, which fail on
codeload rate limits. Every archive is checked against sources.json first.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import updatelib as lib  # noqa: E402

MIRROR = 'https://github.com/aurora-silicon/nixos-aurora/releases/download/source-cache'
# Flake package -> sources it fetches with fetchurl.
NEEDS = {
    'logos': [],  # licensed artwork is vendored in this Git source
    'kernel': ['kernel-aurora', 'bindgen'],
    'bindgen': ['bindgen'],
    'aura': ['aura'],
    'uboot': ['uboot-aurora'],
    'mesa': ['mesa-aurora'],
    'rusticl': ['mesa-aurora'],
    'lavapipe': ['mesa-aurora'],
    'graphics': ['mesa-aurora'],
    'fex-mesa': ['mesa-aurora'],
    'flatpak-gl': ['mesa-aurora'],
    'alsa-utils': ['alsa-utils'],
    'audio': ['aurora-audio'],
    'ucm': ['alsa-ucm-conf-aurora'],
    'firstboot': ['aurora-firstboot'],
    'libfprint': ['libfprint'],
    'fprintd': [],  # nixpkgs' pinned release, with the local companion patch
    'avd-fw': ['avd-fw'],
    'omarchy-ane-tools': ['omarchy-ane-tools'],
    'mil-hwx-compiler': ['mil-hwx-compiler', 'mil-hwx-compiler/gnustep-base'],
    'upower': ['upower-aurora'],
    'speakerguardd': ['speakerguardd'],
    'mutter': [],
    'speakersafetyd': [],
    'bankstown': ['bankstown'],
    'neo-platform': ['aurora-neo-platform-config'],
    'aurora-bless': ['aurora-bless'],
}


def archives():
    """{source key: (store name, urls, sha256)} as overlay.nix fetches them."""
    pins = json.loads((ROOT / 'sources.json').read_text())
    mirror = os.environ.get('AURORA_SOURCE_MIRROR', MIRROR).rstrip('/')
    result = {}
    for key, pin in pins.items():
        name = f'{key}-{pin["commit"]}.tar.gz'
        result[key] = (name, ([f'{mirror}/{name}'] if mirror and pin.get('redistribute_source', True) else []) + [pin['source_url']], pin['sha256'])
    for key, record in pins.items():
        for dependency, pin in record.get('extra_sources', {}).items():
            name = f'{dependency}-{pin["commit"]}.tar.gz'
            result[f'{key}/{dependency}'] = (name, [pin['source_url']], pin['sha256'])
    bindgen = json.loads((ROOT / 'bindgen/sources.json').read_text())
    name = f'rust-bindgen-{bindgen["version"]}.tar.gz'
    result['bindgen'] = (name, ([f'{mirror}/{name}'] if mirror else []) + [bindgen['source_url']],
                         bindgen['source_sha256'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', nargs='*', help='flake packages about to be built (default: every source)')
    args = parser.parse_args()
    known = archives()
    wanted = sorted({key for package in args.packages for key in NEEDS.get(package, known)} if args.packages
                    else known)
    with tempfile.TemporaryDirectory(prefix='aurora-prefetch-') as temporary:
        for key in wanted:
            name, urls, digest = known[key]
            path = Path(temporary) / name
            used = lib.download(urls, path, sha256=digest, token=os.environ.get('GH_TOKEN'))
            store = subprocess.check_output(['nix-store', '--add-fixed', 'sha256', str(path)], text=True).strip()
            path.unlink()
            print(f'{key}: {store} (from {used})')


if __name__ == '__main__':
    main()
