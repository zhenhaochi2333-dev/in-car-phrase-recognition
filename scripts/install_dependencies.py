"""Install dependencies; --direct is an explicit per-process proxy bypass option."""
from pathlib import Path
import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", action="store_true", help="Use PyPI directly for this process only")
    args = parser.parse_args()
    env = os.environ.copy()
    if args.direct:
        env = {key: value for key, value in env.items() if "proxy" not in key.lower()}
        env["NO_PROXY"] = "*"
        env["PIP_CONFIG_FILE"] = os.devnull
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    if args.direct:
        cmd += ["--index-url", "https://pypi.org/simple"]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
