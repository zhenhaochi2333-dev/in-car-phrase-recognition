"""Compile only. Never load the resulting library or run inference."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, str(ROOT / "scripts/prepare_weights.py")], check=True)
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    compiler = shutil.which("g++")
    if compiler:
        command = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
                   "-shared", str(ROOT / "native/core.cpp"), "-o", str(output / "phrase_lab_core.dll")]
        if os.name == "nt":
            command += ["-static", "-static-libgcc", "-static-libstdc++"]
        subprocess.run(command, check=True)
    else:
        subprocess.run(["cmake", "-S", str(ROOT / "native"), "-B", str(output / "cmake")], check=True)
        subprocess.run(["cmake", "--build", str(output / "cmake"), "--config", "Release"], check=True)
        candidates = list((output / "cmake").rglob("phrase_lab_core.dll"))
        if not candidates:
            raise RuntimeError("Build completed without the expected Windows DLL")
        shutil.copy2(candidates[0], output / "phrase_lab_core.dll")
    files = ("native/core.cpp", "native/core.h", "native/generated/weights.hpp")
    (output / "manifest.json").write_text(json.dumps({
        "status": "compiled only; not loaded or executed",
        "sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
        "dll_sha256": hashlib.sha256((output / "phrase_lab_core.dll").read_bytes()).hexdigest(),
    }, indent=2), encoding="utf-8")
    print("C++ build complete. DLL not loaded; functionality not tested.")


if __name__ == "__main__":
    main()
