#!/usr/bin/env python3
"""Select local Buck execution in a disposable consumer checkout."""

import argparse
from pathlib import Path
import re

BEGIN = "# BEGIN Remote execution settings\n"
END = "# END Remote execution settings\n"
BEGIN_MARKERS = (
    BEGIN,
    "# BEGIN NativeLink settings\n",
    "# BEGIN NativeLink settings (managed by remote_execution/re)\n",
)
END_MARKERS = (END, "# END NativeLink settings\n")


def local_config(original):
    begin_count = sum(original.count(marker) for marker in BEGIN_MARKERS)
    end_count = sum(original.count(marker) for marker in END_MARKERS)
    if begin_count == 0 and end_count == 0:
        pattern = None
    elif begin_count != 1 or end_count != 1:
        raise RuntimeError("Incomplete or duplicate managed remote execution block")
    else:
        begin = next(marker for marker in BEGIN_MARKERS if marker in original)
        end = END if begin == BEGIN else END_MARKERS[1]
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
        if not pattern.search(original):
            raise RuntimeError("Reversed managed remote execution block markers")
    outside = pattern.sub("", original) if pattern else original
    if re.search(r"^\[(?:build|buck2|buck2_re_client|remote_execution)\][ \t]*$", outside, re.MULTILINE):
        raise RuntimeError("Buck execution settings exist outside the managed block")
    block = "\n".join([
        BEGIN.rstrip(),
        "[build]",
        "  execution_platforms = prelude//platforms:default",
        "",
        "[buck2]",
        "  digest_algorithms = SHA256",
        "",
        "[remote_execution]",
        "  enabled = false",
        END.rstrip(),
        "",
    ])
    if pattern:
        return pattern.sub(lambda _: block, original)
    return original + ("\n" if original and not original.endswith("\n\n") else "") + block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="consumer checkout root (default: current directory)")
    root = Path(parser.parse_args().repo).resolve()
    config = root / ".buckconfig"
    config.write_text(local_config(config.read_text()))


if __name__ == "__main__":
    main()
