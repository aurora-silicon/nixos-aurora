#!/usr/bin/env python3
"""Sign Nix binary-cache metadata (narinfo files) without the NAR data.

A Nix cache signature covers only the store path, NAR hash, NAR size and
references, so the signing job never needs the (large) NAR files, a Nix
store or network access. The key is a Nix secret key (`name:base64` of the
64-byte Ed25519 secret) read from stdin; OpenSSL does the signing. The
release job afterwards verifies every signature and NAR with Nix itself.

`verify` checks existing signatures against a public key the same way.
"""
import argparse
import base64
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PKCS8_ED25519 = bytes.fromhex('302e020100300506032b657004220420')
SPKI_ED25519 = bytes.fromhex('302a300506032b6570032100')
NARINFO = re.compile(r'[a-z0-9]{32}\.narinfo')


def parse(text):
    fields, signatures = {}, []
    for line in text.splitlines():
        name, separator, value = line.partition(': ')
        if not separator:
            raise ValueError(f'malformed narinfo line: {line!r}')
        if name == 'Sig':
            signatures.append(value)
        elif name in fields:
            raise ValueError(f'duplicate narinfo field {name}')
        else:
            fields[name] = value
    for name in ('StorePath', 'NarHash', 'NarSize'):
        if name not in fields:
            raise ValueError(f'narinfo lacks {name}')
    if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/\s]+', fields['StorePath']):
        raise ValueError('invalid store path')
    if not re.fullmatch(r'sha256:[0-9a-df-np-sv-z]{52}', fields['NarHash']):
        raise ValueError('NarHash must be sha256 in Nix base-32 form')
    return fields, signatures


def fingerprint(fields):
    """Nix's ValidPathInfo::fingerprint."""
    references = ','.join('/nix/store/' + ref for ref in fields.get('References', '').split())
    return f'1;{fields["StorePath"]};{fields["NarHash"]};{int(fields["NarSize"])};{references}'.encode()


def load_secret(text):
    name, separator, encoded = text.strip().partition(':')
    raw = base64.b64decode(encoded, validate=True) if separator else b''
    if not name or len(raw) != 64:
        raise ValueError('expected a Nix secret key: name:base64(64 bytes)')
    return name, raw[:32], raw[32:]


def load_public(text):
    name, separator, encoded = text.strip().partition(':')
    raw = base64.b64decode(encoded, validate=True) if separator else b''
    if not name or len(raw) != 32:
        raise ValueError('expected a Nix public key: name:base64(32 bytes)')
    return name, raw


def openssl(*args, data=None):
    return subprocess.run(['openssl', *args], input=data, capture_output=True, check=True).stdout


def sign(directory, secret_text, public_text):
    name, seed, embedded_public = load_secret(secret_text)
    public_name, public = load_public(public_text)
    if (name, embedded_public) != (public_name, public):
        raise ValueError('the signing key is not the committed public key')
    with tempfile.TemporaryDirectory(prefix='aurora-nix-sign-') as temporary:
        key = Path(temporary) / 'key.der'
        key.touch(mode=0o600)
        key.write_bytes(PKCS8_ED25519 + seed)
        derived = openssl('pkey', '-inform', 'DER', '-in', str(key), '-pubout', '-outform', 'DER')
        if derived != SPKI_ED25519 + public:
            raise ValueError('the secret key does not derive the committed public key')
        message = Path(temporary) / 'message'
        count = 0
        for path in sorted(Path(directory).iterdir()):
            if not NARINFO.fullmatch(path.name) or path.is_symlink():
                if path.name != 'nix-cache-info':
                    raise ValueError(f'unexpected cache metadata file: {path.name}')
                continue
            fields, signatures = parse(path.read_text())
            message.write_bytes(fingerprint(fields))
            signature = openssl('pkeyutl', '-sign', '-keyform', 'DER', '-inkey', str(key), '-rawin',
                                '-in', str(message))
            kept = [sig for sig in signatures if not sig.startswith(name + ':')]
            lines = [line for line in path.read_text().splitlines() if not line.startswith('Sig: ')]
            lines += [f'Sig: {sig}' for sig in kept] + [f'Sig: {name}:{base64.b64encode(signature).decode()}']
            path.write_text('\n'.join(lines) + '\n')
            count += 1
    return count


def verify(directory, public_text):
    name, public = load_public(public_text)
    with tempfile.TemporaryDirectory(prefix='aurora-nix-verify-') as temporary:
        key = Path(temporary) / 'public.der'
        key.write_bytes(SPKI_ED25519 + public)
        message, signature_file = Path(temporary) / 'message', Path(temporary) / 'signature'
        count = 0
        for path in sorted(Path(directory).glob('*.narinfo')):
            fields, signatures = parse(path.read_text())
            ours = [sig.split(':', 1)[1] for sig in signatures if sig.startswith(name + ':')]
            if len(ours) != 1:
                raise ValueError(f'{path.name}: expected one {name} signature, found {len(ours)}')
            message.write_bytes(fingerprint(fields))
            signature_file.write_bytes(base64.b64decode(ours[0], validate=True))
            openssl('pkeyutl', '-verify', '-pubin', '-keyform', 'DER', '-inkey', str(key), '-rawin',
                    '-in', str(message), '-sigfile', str(signature_file))
            count += 1
    return count


def generate_dry_run_key(secret_path, public_path, name='aurora-dry-run-1'):
    """A throwaway Ed25519 key in Nix's format, for dry runs only."""
    import os
    seed = os.urandom(32)
    with tempfile.TemporaryDirectory(prefix='aurora-nix-key-') as temporary:
        key = Path(temporary) / 'key.der'
        key.write_bytes(PKCS8_ED25519 + seed)
        public = openssl('pkey', '-inform', 'DER', '-in', str(key), '-pubout', '-outform', 'DER')[-32:]
    descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(f'{name}:{base64.b64encode(seed + public).decode()}')
    Path(public_path).write_text(f'{name}:{base64.b64encode(public).decode()}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    signer = commands.add_parser('sign', help='sign every narinfo; the secret key arrives on stdin')
    signer.add_argument('--metadata', type=Path, required=True)
    signer.add_argument('--public-key', type=Path, required=True)
    checker = commands.add_parser('verify')
    checker.add_argument('--metadata', type=Path, required=True)
    checker.add_argument('--public-key', type=Path, required=True)
    generator = commands.add_parser('generate-dry-run-key')
    generator.add_argument('--secret', type=Path, required=True)
    generator.add_argument('--public', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'generate-dry-run-key':
        generate_dry_run_key(args.secret, args.public)
        return
    if args.command == 'sign':
        count = sign(args.metadata, sys.stdin.read(), args.public_key.read_text())
        print(f'Signed {count} narinfo files')
    else:
        print(f'Verified {verify(args.metadata, args.public_key.read_text())} narinfo signatures')


if __name__ == '__main__':
    main()
