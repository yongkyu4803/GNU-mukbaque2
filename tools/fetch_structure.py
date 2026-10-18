"""Download a PDB entry into structures/.

    python tools/fetch_structure.py 2ZTA

Structures are not committed to the project: they are other people's data,
they are large, and RCSB is the authoritative copy. This script exists so
the reference entry used by tests/test_real_structure.py can be fetched
reproducibly rather than passed around by hand.

Some leucine zipper entries worth looking at:
    2ZTA  GCN4 leucine zipper -- the reference parallel two-stranded coil
    1YSA  GCN4 bZIP bound to DNA (shows the basic region as well)
    1FOS  Fos/Jun heterodimer on DNA
    1GU4  Max homodimer (bHLH-Zip)
    1U0I  designed antiparallel coil -- a useful negative control
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

RCSB = "https://files.rcsb.org/download/{code}.pdb"
DEST = Path(__file__).resolve().parent.parent / "structures"


def fetch(code: str) -> Path:
    code = code.strip().upper()
    if len(code) != 4 or not code.isalnum():
        raise SystemExit(f"'{code}' is not a four-character PDB code")

    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / f"{code}.pdb"
    if out.exists():
        print(f"{out} already present ({out.stat().st_size / 1024:.1f} KB)")
        return out

    url = RCSB.format(code=code)
    print(f"fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"no PDB entry '{code}'") from exc
        raise SystemExit(f"download failed: {exc}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"download failed: {exc.reason}") from exc

    if not data.lstrip().startswith(b"HEADER"):
        raise SystemExit(
            f"what came back does not look like a PDB file "
            f"({len(data)} bytes); not saving it"
        )

    out.write_bytes(data)
    print(f"wrote {out} ({len(data) / 1024:.1f} KB)")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for code in argv:
        fetch(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
