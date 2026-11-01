"""Build the portable macOS diagnostic tools as a deterministic ZIP artifact."""
import argparse
from pathlib import Path
import stat
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / 'pg_undo_trace_macos.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(args.tree.rglob('*')):
            if path.is_file():
                relative = path.relative_to(args.tree)
                info = zipfile.ZipInfo(str(Path('pg_undo_trace_macos') / relative), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                permissions = 0o755 if path.suffix == '.command' else 0o644
                info.external_attr = (stat.S_IFREG | permissions) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        failed = archive.testzip()
        if failed:
            raise RuntimeError('Diagnostic bundle CRC verification failed: ' + failed)


if __name__ == '__main__':
    main()
