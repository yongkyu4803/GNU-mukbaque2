"""Publish the current client production build as the tracked, Node-free web bundle."""
import shutil
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    source, output = root / "client" / "dist", root / "web"
    if not (source / "index.html").is_file():
        raise SystemExit("Build first: cd client && npm ci && npm run build")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)
    print(f"Published {output}")


if __name__ == "__main__":
    main()
