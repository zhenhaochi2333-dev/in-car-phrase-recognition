"""Download model data only. No inference, audio capture or playback."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{NAME}.tar.bz2"
FILES = {
    "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx": "encoder.onnx",
    "decoder-epoch-13-avg-2-chunk-8-left-64.onnx": "decoder.onnx",
    "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx": "joiner.onnx",
    "tokens.txt": "tokens.txt", "en.phone": "en.phone",
}


def main():
    target = ROOT / "models/custom"
    target.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    archive = cache / f"{NAME}.tar.bz2"
    if not archive.exists():
        part = archive.with_suffix(".part")
        print("Downloading official keyword model; audio devices remain closed", flush=True)
        request = urllib.request.Request(URL, headers={"User-Agent": "PhraseLab-Setup/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out)
        os.replace(part, archive)
    manifest = {"model": NAME, "source_url": URL, "files": {},
                "status": "downloaded; inference not tested", "chunk_size": 8,
                "feature_dim": 80, "tokens_type": "phone+ppinyin"}
    with tarfile.open(archive, "r:bz2") as tar:
        for original, local in FILES.items():
            member = tar.getmember(f"{NAME}/{original}")
            if not member.isfile() or member.size > 100_000_000:
                raise ValueError(f"Unexpected archive member: {original}")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError(f"Missing archive data: {original}")
            part = target / (local + ".part")
            with stream, part.open("wb") as out:
                shutil.copyfileobj(stream, out)
            if part.stat().st_size != member.size:
                raise ValueError(f"Incomplete file: {original}")
            os.replace(part, target / local)
            payload = (target / local).read_bytes()
            manifest["files"][local] = {"archive_name": original, "bytes": len(payload),
                                       "sha256": hashlib.sha256(payload).hexdigest()}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Model files prepared; sample audio was not extracted or played")


if __name__ == "__main__":
    main()
