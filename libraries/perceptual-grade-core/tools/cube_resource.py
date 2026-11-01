"""Extract the profile-free AP1 cube capacity resource from the adopted fit."""
import argparse
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_core.model.boundary_resource import FIELDS, FORMAT, load_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    with np.load(args.source, allow_pickle=False) as archive:
        validated = load_data(archive)
    data = {name: value for name, value in validated.items() if name in FIELDS}
    data['format'] = np.array(FORMAT)
    load_data(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output_dir/'d65_cube.npz', **data)


if __name__ == '__main__':
    main()
