import argparse
import json
from pathlib import Path
import sys

from .checker import verify, solver_identity
from .model import VerificationError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify handwritten automata against separate .inv requirements")
    parser.add_argument("source")
    parser.add_argument("requirements")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--require-property", action="append", default=[], dest="required_properties")
    parser.add_argument('--require-witness', action='append', default=[], dest='required_witnesses')
    parser.add_argument('--require-mutation', action='append', default=[], dest='required_mutations')
    parser.add_argument('--input-closure')
    args = parser.parse_args(argv)
    if args.timeout_ms <= 0:
        parser.error("timeout must be positive")
    try:
        hashes = None
        if args.input_closure:
            from . import closure
            hashes = closure.validate(args.input_closure, args.source, args.requirements,
                                      properties=args.required_properties, witnesses=args.required_witnesses,
                                      mutations=args.required_mutations, verifier_dir=Path(__file__).parent,
                                      solver_hashes=solver_identity())
        report = verify(args.source, args.requirements, args.output, args.timeout_ms,
                        args.required_properties, args.required_witnesses, args.required_mutations)
        if report['ok'] and hashes is not None:
            closure.bind_receipt(args.output, hashes)
    except (VerificationError, ValueError, KeyError, TypeError, SyntaxError) as error:
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "receipt.json").unlink(missing_ok=True)
        report = {"version": 1, "ok": False, "error": str(error)}
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Verification failed: " + str(error), file=sys.stderr)
        return 1
    failures = [item["name"] for item in report["obligations"] + report["mutations"] if not item["ok"]]
    if failures:
        print("Verification failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"Verified {len(report['obligations'])} obligations and {len(report['mutations'])} mutation controls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
