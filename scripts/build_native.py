"""Compile only. Never load the resulting library or run inference.

The course core requires C++17.  In particular, an old Dev-C++/MinGW may
appear on PATH but cannot build this project, so it must not prevent a newer
MSVC installation from being used.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import struct
import sys
import sysconfig
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def gxx_version(compiler: str) -> tuple[int, ...] | None:
    """Return a GCC version when it can be determined without compiling."""
    try:
        result = subprocess.run(
            [compiler, "-dumpfullversion", "-dumpversion"],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"\d+(?:\.\d+)*", result.stdout)
    return tuple(int(part) for part in match.group(0).split(".")) if match else None


def find_msvc_environment() -> Path | None:
    """Find a 64-bit Visual C++ environment without requiring it on PATH."""
    candidates: list[Path] = []
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = program_files_x86 / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        result = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            capture_output=True, text=True,
        )
        installation = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
        if installation is not None:
            candidates.append(installation / "VC" / "Auxiliary" / "Build" / "vcvars64.bat")
    for program_files in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")), program_files_x86):
        root = program_files / "Microsoft Visual Studio"
        if root.is_dir():
            candidates.extend(root.glob("*/*/VC/Auxiliary/Build/vcvars64.bat"))
    usable = [path for path in candidates if path.is_file()]
    return max(usable, key=lambda path: path.stat().st_mtime) if usable else None


def gxx_matches_python(compiler: str) -> bool:
    """Reject a 32-bit MinGW on a 64-bit Python before selecting a toolchain."""
    if os.name != "nt":
        return True
    try:
        result = subprocess.run([compiler, "-dumpmachine"], check=True,
                                capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return result.stdout.strip().lower().startswith("x86_64-")


def validate_candidate(candidate: Path) -> None:
    """Inspect PE headers without loading or executing the DLL."""
    if os.name != "nt":
        return
    raw = candidate.read_bytes()
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise RuntimeError("候选文件不是有效的 Windows DLL；原 DLL 保持不变")
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if offset + 24 > len(raw) or raw[offset:offset + 4] != b"PE\0\0":
        raise RuntimeError("候选 DLL 的 PE 文件头无效；原 DLL 保持不变")
    machine = struct.unpack_from("<H", raw, offset + 4)[0]
    characteristics = struct.unpack_from("<H", raw, offset + 22)[0]
    if machine != 0x8664 or not characteristics & 0x2000:
        raise RuntimeError("候选 DLL 不是 64 位 x86 Windows 动态库；原 DLL 保持不变")


def activate_candidate(candidate: Path, output: Path) -> None:
    """Atomically replace the runtime DLL only after a successful compile."""
    library = output / "phrase_lab_core.dll"
    validate_candidate(candidate)
    try:
        os.replace(candidate, library)
    except PermissionError as exc:
        pending = output / "phrase_lab_core.pending.dll"
        os.replace(candidate, pending)
        raise RuntimeError(
            "新的 C++ DLL 已成功编译，但当前识别窗口正在使用旧 DLL，无法安全替换。"
            f"请完全关闭短语识别窗口后重试；候选文件保留在：{pending}"
        ) from exc


def build_with_gxx(compiler: str, output: Path) -> dict[str, str]:
    candidate = output / "phrase_lab_core.candidate.dll"
    command = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
               "-shared", str(ROOT / "native/core.cpp"), "-o", str(candidate)]
    if os.name == "nt":
        command += ["-static", "-static-libgcc", "-static-libstdc++"]
    subprocess.run(command, check=True)
    activate_candidate(candidate, output)
    version = gxx_version(compiler)
    return {"kind": "g++", "path": compiler, "version": ".".join(map(str, version or ())) }


def build_with_msvc(vcvars: Path, output: Path) -> dict[str, str]:
    source = ROOT / "native/core.cpp"
    candidate = output / "phrase_lab_core.candidate.dll"
    object_file = output / "core.candidate.obj"
    command = (
        f'call "{vcvars}" >nul && '
        'cl.exe /nologo /std:c++17 /O2 /W4 /EHsc /MT /utf-8 /LD '
        f'"{source}" /Fo:"{object_file}" /Fe:"{candidate}"'
    )
    # `call` is a cmd.exe builtin.  Passing it as an argv item makes Python's
    # Windows command-line quoting add a literal quote before vcvars64.bat;
    # use the Windows shell for this fixed, locally generated build command.
    subprocess.run(command, shell=True, check=True)
    activate_candidate(candidate, output)
    return {"kind": "MSVC", "environment": str(vcvars)}


def build_with_cmake(output: Path) -> dict[str, str] | None:
    cmake = shutil.which("cmake")
    if cmake is None:
        return None
    subprocess.run([cmake, "-S", str(ROOT / "native"), "-B", str(output / "cmake")], check=True)
    subprocess.run([cmake, "--build", str(output / "cmake"), "--config", "Release"], check=True)
    candidates = list((output / "cmake").rglob("phrase_lab_core.dll"))
    if not candidates:
        raise RuntimeError("CMake build completed without the expected Windows DLL")
    candidate = output / "phrase_lab_core.candidate.dll"
    shutil.copy2(candidates[0], candidate)
    activate_candidate(candidate, output)
    return {"kind": "CMake", "path": cmake}


def main():
    if os.name == "nt" and sysconfig.get_platform() != "win-amd64":
        raise RuntimeError("本项目的 Windows 构建需要 64 位 x86 Python 3.11 或更新版本")
    subprocess.run([sys.executable, str(ROOT / "scripts/prepare_weights.py")], check=True)
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    compiler = shutil.which("g++")
    version = gxx_version(compiler) if compiler else None
    if compiler and version and version >= (7,) and gxx_matches_python(compiler):
        compiler_info = build_with_gxx(compiler, output)
    else:
        if compiler:
            rendered = ".".join(map(str, version or ())) or "unknown"
            print(f"Skipping g++ {rendered}: C++17 and a compiler matching the Python architecture are required.")
        vcvars = find_msvc_environment() if os.name == "nt" else None
        if vcvars is not None:
            compiler_info = build_with_msvc(vcvars, output)
        else:
            compiler_info = build_with_cmake(output)
            if compiler_info is None:
                raise RuntimeError(
                    "No C++17 compiler was found. Install Visual Studio C++ Build Tools, "
                    "CMake, or g++ 7+ and run this script again."
                )
    files = ("native/core.cpp", "native/core.h", "native/generated/weights.hpp")
    (output / "manifest.json").write_text(json.dumps({
        "status": "compiled only; not loaded or executed",
        "compiler": compiler_info,
        "sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
        "dll_sha256": hashlib.sha256((output / "phrase_lab_core.dll").read_bytes()).hexdigest(),
    }, indent=2), encoding="utf-8")
    print("C++ build complete. DLL not loaded; functionality not tested.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"构建未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)
