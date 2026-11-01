"""Build the picker ZIP from its declared runtime source tree."""
import argparse
from pathlib import Path

from verification.packaging import package
from verification.invariant_report import InvariantProofs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tree', 'output-dir', 'inventory', 'proofs'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    package(args.tree, args.output_dir / 'hdr_color_picker.zip', inventory_path=args.inventory,
            proof_requirement=InvariantProofs(args.proofs))


if __name__ == '__main__':
    main()
