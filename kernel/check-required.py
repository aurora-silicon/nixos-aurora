#!/usr/bin/env python3
"""Fail unless the resolved kernel config has what every Aurora image needs.

The listed options must be built in or modules. The FAT default iocharset and
codepage need their NLS tables too: NixOS mounts the vfat /boot with them.
"""
from pathlib import Path
import re
import sys

REQUIRED = ('DM_CRYPT', 'DM_INTEGRITY', 'BT', 'NF_TABLES', 'EXFAT_FS', 'HID_GENERIC', 'NLS_UTF8')


def values(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        match = re.fullmatch(r'CONFIG_([A-Za-z0-9_]+)=(.*)', line)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def nls_option(charset):
    """The NLS option that provides an iocharset name, as fs/nls names them."""
    name = charset.lower()
    if name == 'utf8':
        return 'NLS_UTF8'
    if name == 'ascii':
        return 'NLS_ASCII'
    if match := re.fullmatch(r'cp(\d+)', name):
        return f'NLS_CODEPAGE_{match.group(1)}'
    if match := re.fullmatch(r'iso8859-(\d+)', name):
        return f'NLS_ISO8859_{match.group(1)}'
    return 'NLS_' + re.sub(r'[^A-Z0-9]', '_', name.upper())


def missing(config):
    wanted = list(REQUIRED)
    if config.get('VFAT_FS') in ('y', 'm'):
        iocharset = config.get('FAT_DEFAULT_IOCHARSET', '').strip('"')
        codepage = config.get('FAT_DEFAULT_CODEPAGE', '')
        if not iocharset or not codepage.isdigit():
            return ['FAT_DEFAULT_IOCHARSET/FAT_DEFAULT_CODEPAGE']
        wanted += [nls_option(iocharset), f'NLS_CODEPAGE_{codepage}']
    return [f'CONFIG_{name}' for name in dict.fromkeys(wanted) if config.get(name) not in ('y', 'm')]


if __name__ == '__main__':
    absent = missing(values(sys.argv[1]))
    if absent:
        sys.exit('Kernel options every Aurora image needs are not y or m: ' + ', '.join(absent))
