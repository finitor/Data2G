#!/usr/bin/env python3
"""Check 64-bit ELF LOAD/RELRO and uncompressed ZIP alignment in an APK.

Uses only the standard library. See Android's 16 KB page-size guidance:
https://developer.android.com/guide/practices/page-sizes
"""
import argparse
import struct
import sys
import zipfile
from pathlib import Path

PAGE = 16384
PT_LOAD = 1
PT_GNU_RELRO = 0x6474E552


def check(apk: Path) -> list[str]:
    errors = []
    count = 0
    with apk.open('rb') as raw, zipfile.ZipFile(apk) as archive:
        for item in archive.infolist():
            if not item.filename.startswith(('lib/arm64-v8a/', 'lib/x86_64/')) or not item.filename.endswith('.so'):
                continue
            data = archive.read(item)
            if data[:6] != b'\x7fELF\x02\x01':
                errors.append(f'{item.filename}: expected little-endian ELF64')
                continue
            try:
                offset = struct.unpack_from('<Q', data, 32)[0]
                size, number = struct.unpack_from('<HH', data, 54)
                if size < 56:
                    raise ValueError('invalid ELF program header size')
                headers = [struct.unpack_from('<IIQQQQQQ', data, offset + i * size) for i in range(number)]
                loads = [p for p in headers if p[0] == PT_LOAD]
                if not loads or any(p[-1] < PAGE for p in loads):
                    errors.append(f'{item.filename}: LOAD alignment below 16 KB')
                for relro in (p for p in headers if p[0] == PT_GNU_RELRO):
                    end = relro[3] + relro[6]
                    whole_tail = any(p[1] & 2 and p[3] <= relro[3] and p[3] + p[6] == end for p in loads)
                    if end % PAGE and not whole_tail:
                        errors.append(f'{item.filename}: RELRO end is not 16 KB aligned and shares writable data')
                if item.compress_type == zipfile.ZIP_STORED:
                    raw.seek(item.header_offset)
                    header = raw.read(30)
                    name_len, extra_len = struct.unpack_from('<HH', header, 26)
                    if (item.header_offset + 30 + name_len + extra_len) % PAGE:
                        errors.append(f'{item.filename}: uncompressed ZIP data is not 16 KB aligned')
                count += 1
            except (struct.error, ValueError) as exc:
                errors.append(f'{item.filename}: {exc}')
    if not count:
        errors.append('no 64-bit native libraries found')
    print(f'{apk.name}: checked {count} 64-bit native libraries')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    args = parser.parse_args()
    errors = check(args.apk)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print('16 KB native and APK alignment verified')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
