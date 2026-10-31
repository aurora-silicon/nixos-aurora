#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rebuild the source-only compiler input, excluding receipts, models and oracles."""
import gzip,hashlib,io,json,tarfile,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
pin=json.loads((root/'sources.json').read_text())['mil-hwx-compiler']
url=pin['repository'].replace('https://github.com/','https://codeload.github.com/')+'/tar.gz/'+pin['commit']
with urllib.request.urlopen(url,timeout=120) as response: data=response.read()
assert hashlib.sha256(data).hexdigest()==pin['upstream_archive_sha256']
raw=io.BytesIO()
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as src, tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as dst:
 for item in pin['source_files']:
  path=pin['archive_root']+'/'+item['path'];old=src.getmember(path);content=src.extractfile(old).read()
  assert hashlib.sha256(content).hexdigest()==item['sha256'];content.decode('utf-8')
  member=tarfile.TarInfo(path);member.size=len(content);member.mode=old.mode;member.mtime=0
  dst.addfile(member,io.BytesIO(content))
result=gzip.compress(raw.getvalue(),mtime=0)
assert hashlib.sha256(result).hexdigest()==pin['sha256']
(root/pin['local_archive']).write_bytes(result)
print(pin['sha256'])
