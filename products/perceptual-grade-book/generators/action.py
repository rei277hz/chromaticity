"""Execute one book producer and require every declared output."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--expected-output', action='append', default=[])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    output = args.output_dir
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Generator output must be absent or empty')
    output.mkdir(parents=True, exist_ok=True)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    subprocess.run([*command, '--output-dir', str(output)], check=True)
    for name in args.expected_output:
        if not (output / name).is_file():
            raise ValueError('Missing declared generator output: ' + name)


if __name__ == '__main__':
    main()
