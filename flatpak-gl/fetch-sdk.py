#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch pinned public SDK objects with curl; let OSTree verify their graph.

The pinned libostree HTTP clients return 403 for these objects while curl GET
returns the exact pinned commit bytes. This adapter changes only the HTTP
client: the origin, TLS verification, OSTree checksums and Nix hash stay fixed.
It serves only OSTree repository objects on a private loopback listener.
"""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Thread

ORIGIN = 'https://dl.flathub.org/repo'
OBJECT = re.compile(r'/objects/[0-9a-f]{2}/[0-9a-f]{62}\.(?:commit|commitmeta|dirtree|dirmeta|filez)')


def allowed(path):
    return OBJECT.fullmatch(path) is not None or path in ('/summary', '/summary.sig', '/config')


def fetch(path, destination, ca_file):
    result = subprocess.run([
        'curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https',
        '--proto-redir', '=https', '--cacert', str(ca_file), '--connect-timeout', '30',
        '--max-time', '300', '--max-filesize', str(512 * 1024**2), '--retry', '5',
        '--retry-max-time', '600', '--output', str(destination), '--write-out', '%{http_code}',
        ORIGIN + path,
    ], capture_output=True, text=True)
    status = int(result.stdout) if result.stdout.isdigit() else 502
    if not 200 <= status <= 599:
        status = 502
    if result.returncode != 0 and status == 200:
        status = 502
    return status


@contextmanager
def object_server(ca_file, downloader=fetch):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            self.serve(False)

        def do_GET(self):
            self.serve(True)

        def serve(self, body):
            if not allowed(self.path):
                self.send_error(404)
                return
            with tempfile.TemporaryDirectory(prefix='aurora-sdk-object-') as temporary:
                path = Path(temporary) / 'object'
                if self.path == '/config':
                    path.write_text('[core]\nrepo_version=1\nmode=archive-z2\n')
                    status = 200
                else:
                    status = downloader(self.path, path, ca_file)
                if status != 200:
                    self.send_error(status, 'Public SDK object unavailable')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(path.stat().st_size))
                self.end_headers()
                if body:
                    with path.open('rb') as stream:
                        shutil.copyfileobj(stream, self.wfile)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def fetch_sdk(repo, refs, ca_file):
    if not refs or not all(re.fullmatch(r'runtime/org\.freedesktop\.(?:Sdk|Platform|Sdk\.Extension\.llvm22)/aarch64/(?:25|26)\.08', ref)
                           and re.fullmatch('[0-9a-f]{64}', commit) for ref, commit in refs.items()):
        raise ValueError('Expected pinned Freedesktop SDK refs and full OSTree commits')
    def ostree(*args):
        subprocess.run(['ostree', f'--repo={repo}', *args], check=True)
    with object_server(ca_file) as url:
        ostree('remote', 'add', '--no-gpg-verify', 'source', url)
        for ref, commit in sorted(refs.items()):
            print(f'Fetching pinned SDK {ref}: {commit}', flush=True)
            ostree('pull', '--depth=0', 'source', commit)
            ostree('refs', '--create=' + ref, commit)
        ostree('remote', 'delete', 'source')
    # Verify the complete downloaded graph, not merely its commit metadata.
    ostree('fsck', '--all')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--refs', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    args = parser.parse_args()
    fetch_sdk(args.repo, json.loads(args.refs.read_text()), args.ca_file)
