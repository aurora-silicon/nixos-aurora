#!/usr/bin/env python3
"""Verify signed NARs through HTTP, including absolute release download URLs."""
import argparse
from functools import partial
import http.server
from pathlib import Path
import re
import subprocess
import threading

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def verify(directory, public_key):
    paths = []
    for info in sorted(directory.glob('*.narinfo')):
        if info.is_symlink() or not re.fullmatch(r'[a-z0-9]{32}\.narinfo', info.name):
            raise ValueError('unsafe NAR metadata')
        fields = dict(line.split(': ', 1) for line in info.read_text().splitlines() if not line.startswith('Sig: '))
        path = fields['StorePath']
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/\s]+', path):
            raise ValueError('invalid store path')
        paths.append(path)
    if not paths:
        raise ValueError('cache contains no NAR metadata')
    # The file:// backend treats URL as a local filename. HTTP uses Nix's
    # relative/absolute URL resolution and therefore exercises the real URLs.
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(directory.resolve())))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        subprocess.run(['nix', 'store', 'verify', '--store', f'http://127.0.0.1:{server.server_port}',
                        '--sigs-needed', '1', '--trusted-public-keys', public_key.strip(), *paths], check=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(f'Verified {len(paths)} published cache paths through HTTP')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    args = parser.parse_args()
    verify(args.cache_dir, args.public_key.read_text())
