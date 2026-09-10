"""Future offline evaluation entry. This script HAS NOT been run for this delivery.

Requires real labeled 16 kHz, 16-bit mono WAV files. No speaker or microphone usage.
"""
from pathlib import Path
import argparse
import csv
import json
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Evaluate the 12-class C++ model on labeled audio; runs inference")
    parser.add_argument("manifest", type=Path, help="JSON list of {path, label}, WAV paths relative to the JSON")
    parser.add_argument("--output", type=Path, default=ROOT / "exports/evaluation")
    args = parser.parse_args()
    import ctypes
    import numpy as np
    sys.path.insert(0, str(ROOT / "app"))
    from phrase_lab.domain import LABELS, Settings
    from phrase_lab.engines import ExperimentEngine

    records = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list) or not records:
        raise ValueError("Manifest must be a non-empty list of labeled real audio files")
    engine = ExperimentEngine(Settings())
    matrix = np.zeros((12, 12), dtype=int)
    results = []
    try:
        for record in records:
            expected = LABELS.index(record["label"])
            path = args.manifest.parent / record["path"]
            with wave.open(str(path), "rb") as stream:
                if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getcomptype()) != (16000, 1, 2, "NONE"):
                    raise ValueError(f"Expected 16 kHz, mono, PCM16 WAV: {path}")
                if not 0 < stream.getnframes() <= 16000:
                    raise ValueError(f"Expected audio length in (0,1] seconds: {path}")
                pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32)/32768
            pcm = np.pad(pcm, (0, 16000-len(pcm))).astype(np.float32)
            logits, scores = np.empty(12, dtype=np.float64), np.empty(12, dtype=np.float64)
            start = time.perf_counter()
            code = engine.lib.lab_predict(engine.handle, pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                                          16000, logits.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                                          scores.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
            if code:
                raise RuntimeError(engine.lib.lab_last_error().decode())
            elapsed = (time.perf_counter()-start)*1000
            predicted = int(np.argmax(scores))
            matrix[expected, predicted] += 1
            results.append({"path": str(path), "label": LABELS[expected], "prediction": LABELS[predicted],
                            "score": float(scores[predicted]), "processing_ms": elapsed})
    finally:
        engine.close()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    times = [row["processing_ms"] for row in results]
    summary = {"samples": len(results), "accuracy": float(np.trace(matrix)/matrix.sum()),
               "labels": LABELS, "confusion_matrix_rows_true_columns_predicted": matrix.tolist(),
               "processing_ms_mean": float(np.mean(times)), "processing_ms_p95": float(np.percentile(times, 95)),
               "coverage": {name: int(matrix[i].sum()) for i, name in enumerate(LABELS)},
               "note": "Offline clip classification only. Not live event accuracy or end-to-end latency. No warm-up excluded."}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
