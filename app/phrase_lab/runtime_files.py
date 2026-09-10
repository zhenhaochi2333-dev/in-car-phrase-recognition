"""ASCII runtime copies for native Windows libraries with narrow path APIs."""
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def prepare_runtime_files(source: Path, keyword_text: str) -> tuple[Path, Path]:
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    base.mkdir(parents=True, exist_ok=True)
    if not str(base).isascii() and os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(base), buffer, len(buffer))
        if 0 < length < len(buffer):
            base = Path(buffer.value)
    if not str(base).isascii():
        raise RuntimeError("识别引擎需要英文运行缓存路径，请为 LOCALAPPDATA 配置可用的英文路径")
    project_id = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
    directory = base / "PhraseLab" / "runtime" / project_id
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
        original, cached = source / name, directory / name
        digest = hashlib.sha256(original.read_bytes()).digest()
        if not cached.is_file() or hashlib.sha256(cached.read_bytes()).digest() != digest:
            temporary = cached.with_suffix(cached.suffix + ".tmp")
            shutil.copyfile(original, temporary)
            os.replace(temporary, cached)
    # A unique file also keeps concurrent instances' phrase lists independent.
    fd, filename = tempfile.mkstemp(prefix="keywords-", suffix=".txt", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(keyword_text)
    return directory, Path(filename)
