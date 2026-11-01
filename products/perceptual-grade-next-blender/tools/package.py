"""Build a deterministic ZIP from the declared Next extension tree."""

import argparse
from pathlib import Path

from verification.packaging import package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tree", "output-dir", "inventory"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    package(
        args.tree,
        args.output_dir / "perceptual_grade_next.zip",
        inventory_path=args.inventory,
    )


if __name__ == "__main__":
    main()
