"""Assemble a relocatable, pinned Debian Xvfb fixture without host installation."""
import argparse
import io
from pathlib import Path
import tarfile


def unpack(archives, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for archive in archives:
        with archive.open('rb') as source:
            if source.read(8) != b'!<arch>\n':
                raise ValueError(f'Not a Debian ar archive: {archive}')
            found = False
            while header := source.read(60):
                if len(header) != 60 or header[58:] != b'`\n':
                    raise ValueError(f'Invalid Debian archive header: {archive}')
                size = int(header[48:58])
                data = source.read(size)
                if len(data) != size:
                    raise ValueError(f'Truncated Debian archive: {archive}')
                if size % 2:
                    source.read(1)
                if header[:16].decode('ascii').strip().rstrip('/').startswith('data.tar.'):
                    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as payload:
                        payload.extractall(destination, filter='data')
                    found = True
            if not found:
                raise ValueError(f'Debian archive has no data payload: {archive}')
    binary = destination / 'usr/bin/Xvfb'
    data = binary.read_bytes()
    # XkbBinDirectory has no runtime override in this pinned upstream build.
    # Keep the ELF layout intact while resolving xkbcomp from the fixture cwd.
    original, relocated = b'/usr/bin\0', b'usr/bin\0\0'
    if data.count(original) != 1:
        raise ValueError('Pinned Xvfb compiler-directory relocation no longer matches')
    binary.write_bytes(data.replace(original, relocated))
    for name in ('Xvfb', 'xkbcomp'):
        (destination / 'usr/bin' / name).chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, action='append', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.output_dir)


if __name__ == '__main__':
    main()
