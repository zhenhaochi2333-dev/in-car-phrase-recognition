"""Generate a read-only parameter header; never execute or alter course code."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "课程资料/新版/table.c"
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    start, end = text.index("double cnn_head_0_weight"), text.index("double* weights")
    arrays = re.sub(r"(?m)^double ", "static const double ", text[start:end])
    pointers = []
    for name in ("weights", "biass", "running_means", "running_vars"):
        match = re.search(r"double\* " + name + r"\[\]\s*=\s*\{([^}]+)\}", text, re.S)
        if match is None:
            raise ValueError(f"Missing parameter index: {name}")
        values = match.group(1).replace("(double*)", "(const double*)")
        pointers.append(f"static const double* const {name}[] = {{{values}}};")
    out = ROOT / "native/generated"
    out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    (out / "weights.hpp").write_text(
        f"// Derived from course table.c; SHA256 {digest}\n#pragma once\n"
        + "namespace course {\n" + arrays + "\n".join(pointers) + "\n}\n",
        encoding="utf-8",
    )
    (out / "provenance.json").write_text(json.dumps({
        "source": "课程资料/新版/table.c", "sha256": digest,
        "operation": "Extract numeric arrays and pointer indices only; original untouched",
        "validation": "No inference or functional testing performed",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Generated native/generated/weights.hpp (data conversion only)")


if __name__ == "__main__":
    main()
