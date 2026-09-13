"""Evaluate the fixed 12-class experiment model on labelled WAV files.

This script deliberately does not open a microphone or speaker.  It measures
offline, one-clip classification and the native model-call time only.  A live
continuous-listening test is still needed to report end-to-end latency.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import wave


ROOT = Path(__file__).resolve().parents[1]
LABELS = (
    "_silence_", "_unknown_", "down", "go", "left", "no",
    "off", "on", "right", "stop", "up", "yes",
)
SAMPLE_RATE = 16_000
SAMPLES_PER_CLIP = 16_000


def load_manifest(path: Path, labels: tuple[str, ...] = LABELS) -> list[dict[str, object]]:
    """Read and validate a local dataset manifest without loading its audio."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"找不到样本清单：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"样本清单不是有效 JSON：{path}（第 {exc.lineno} 行）") from exc
    records = raw.get("samples") if isinstance(raw, dict) else raw
    if not isinstance(records, list) or not records:
        raise ValueError("样本清单必须是非空数组，或包含 samples 数组的 JSON 对象")
    accepted = set(labels)
    normalised: list[dict[str, object]] = []
    seen_paths: set[Path] = set()
    seen_ids: set[str] = set()
    for number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"第 {number} 条样本不是 JSON 对象")
        relative_path, label = record.get("path"), record.get("label")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(f"第 {number} 条样本缺少 path")
        if not isinstance(label, str) or label not in accepted:
            expected = "、".join(labels)
            raise ValueError(f"第 {number} 条样本标签 {label!r} 不在固定 12 类中：{expected}")
        audio_path = (path.parent / relative_path).resolve()
        if Path(relative_path).is_absolute() or not audio_path.is_relative_to(path.parent.resolve()):
            raise ValueError(f"第 {number} 条音频路径必须位于样本清单目录内：{relative_path}")
        if not audio_path.is_file():
            raise ValueError(f"第 {number} 条样本音频不存在：{audio_path}")
        sample_id = str(record.get("id") or f"sample-{number:04d}")
        if audio_path in seen_paths:
            raise ValueError(f"第 {number} 条重复引用同一音频文件，不能重复计入统计：{audio_path}")
        if sample_id in seen_ids:
            raise ValueError(f"第 {number} 条样本 ID 重复：{sample_id}")
        seen_paths.add(audio_path)
        seen_ids.add(sample_id)
        item: dict[str, object] = {
            "id": sample_id,
            "path": audio_path,
            "label": label,
            "speaker": str(record.get("speaker") or "未标注"),
            "condition": str(record.get("condition") or "未标注"),
        }
        normalised.append(item)
    return normalised


def read_pcm(path: Path):
    """Return a padded, normalised one-second float32 mono clip."""
    import numpy as np

    try:
        with wave.open(str(path), "rb") as stream:
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            sample_rate = stream.getframerate()
            frames = stream.getnframes()
            compression = stream.getcomptype()
            raw = stream.readframes(frames)
    except (OSError, wave.Error) as exc:
        raise ValueError(f"无法读取 WAV：{path}（{exc}）") from exc
    if channels != 1 or sample_width != 2 or sample_rate != SAMPLE_RATE or compression != "NONE":
        raise ValueError(
            f"{path.name} 必须是 16 kHz、单声道、16 位未压缩 WAV；"
            f"当前为 {sample_rate} Hz、{channels} 声道、{sample_width * 8} 位、{compression}"
        )
    if not 1 <= frames <= SAMPLES_PER_CLIP:
        raise ValueError(f"{path.name} 长度必须在 1—{SAMPLES_PER_CLIP} 个采样点之间（最多 1 秒）")
    if len(raw) != frames * channels * sample_width:
        raise ValueError(f"{path.name} 的 WAV 数据被截断，不能用于评测")
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return np.pad(pcm, (0, SAMPLES_PER_CLIP - len(pcm))).astype(np.float32, copy=False)


class NativePredictor:
    """Minimal direct wrapper for the fixed course C++ model."""

    def __init__(self, library: Path | None = None):
        library = library or ROOT / "build" / "phrase_lab_core.dll"
        if not library.is_file():
            raise ValueError("实验动态库尚未构建，请先运行 scripts/build_native.py")
        self.lib = ctypes.CDLL(str(library))
        self.lib.lab_create.restype = ctypes.c_void_p
        self.lib.lab_destroy.argtypes = [ctypes.c_void_p]
        self.lib.lab_destroy.restype = None
        self.lib.lab_last_error.restype = ctypes.c_char_p
        self.lib.lab_predict.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ]
        self.lib.lab_predict.restype = ctypes.c_int
        self.handle = self.lib.lab_create()
        if not self.handle:
            raise RuntimeError(self._last_error())

    def _last_error(self) -> str:
        raw = self.lib.lab_last_error()
        return raw.decode("utf-8", errors="replace") if raw else "C++ 核心没有返回错误说明"

    def predict(self, pcm):
        import numpy as np

        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        if pcm.shape != (SAMPLES_PER_CLIP,):
            raise ValueError(f"模型输入必须恰好有 {SAMPLES_PER_CLIP} 个采样点")
        logits = np.empty(len(LABELS), dtype=np.float64)
        scores = np.empty(len(LABELS), dtype=np.float64)
        started = time.perf_counter()
        status = self.lib.lab_predict(
            self.handle, pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(pcm),
            logits.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            scores.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if status:
            raise RuntimeError(self._last_error())
        index = int(np.argmax(scores))
        return LABELS[index], float(scores[index]), elapsed_ms, scores

    def close(self):
        if self.handle:
            self.lib.lab_destroy(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _group_results(rows: list[dict[str, object]], field: str) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row[field]), []).append(row)
    return {
        group: {
            "samples": len(group_rows),
            "correct": sum(bool(row["correct"]) for row in group_rows),
            "accuracy": _round(sum(bool(row["correct"]) for row in group_rows) / len(group_rows)),
        }
        for group, group_rows in sorted(groups.items())
    }


def make_summary(rows: list[dict[str, object]], labels: tuple[str, ...] = LABELS) -> dict[str, object]:
    """Build serialisable accuracy, matrix, class and timing statistics."""
    if not rows:
        raise ValueError("没有可统计的样本")
    index = {label: number for number, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for row in rows:
        actual = index[str(row["label"])]
        predicted = index[str(row["predicted"])]
        matrix[actual][predicted] += 1
    per_class: dict[str, dict[str, object]] = {}
    for position, label in enumerate(labels):
        true_positive = matrix[position][position]
        support = sum(matrix[position])
        predicted = sum(matrix[row][position] for row in range(len(labels)))
        false_positive = predicted - true_positive
        recall = true_positive / support if support else None
        precision = true_positive / predicted if predicted else None
        # Zero true positives means F1=0 for a represented class. Only a class
        # with neither actual nor predicted samples has an undefined F1.
        f1 = 2 * true_positive / (support + predicted) if support + predicted else None
        per_class[label] = {
            "samples": support,
            "correct": true_positive,
            "predicted": predicted,
            "false_positive": false_positive,
            "recall": _round(recall),
            "precision": _round(precision),
            "f1": _round(f1),
        }
    times = [float(row["processing_ms"]) for row in rows]
    correct = sum(bool(row["correct"]) for row in rows)
    missing = [label for label in labels if not per_class[label]["samples"]]
    return {
        "schema_version": 1,
        "evaluation": "fixed-12-class offline WAV classification",
        "scope_note": (
            "处理耗时仅包含 C++ 模型一次推理，不包含录音、连续分段、界面显示或播报；"
            "本报告不能代替端到端延迟结论。"
        ),
        "samples": len(rows),
        "correct": correct,
        "accuracy": _round(correct / len(rows)),
        "labels": list(labels),
        "confusion_matrix": matrix,
        "coverage": {
            "required_classes": len(labels),
            "covered_classes": len(labels) - len(missing),
            "all_required_classes_present": not missing,
            "classes_without_samples": missing,
        },
        "per_class": per_class,
        "by_speaker": _group_results(rows, "speaker"),
        "by_condition": _group_results(rows, "condition"),
        "model_processing_ms": {
            "mean": _round(statistics.fmean(times)),
            "p50": _round(_percentile(times, 0.50)),
            "p95": _round(_percentile(times, 0.95)),
            "max": _round(max(times)),
        },
    }


def markdown_report(summary: dict[str, object], manifest: Path, warmup: int) -> str:
    labels = summary["labels"]
    lines = [
        "# 12 类离线识别评测结果",
        "",
        f"- 样本清单：`{manifest}`",
        f"- 样本数：{summary['samples']}；正确数：{summary['correct']}；准确率：{summary['accuracy']:.2%}",
        f"- 预热次数：{warmup}（不计入统计）",
        f"- 范围：{summary['scope_note']}",
        "",
        "## 覆盖情况",
        "",
        f"- 已覆盖 {summary['coverage']['covered_classes']}/{summary['coverage']['required_classes']} 个固定类别。",
        f"- 缺失类别：{'、'.join(summary['coverage']['classes_without_samples']) or '无'}。",
        "",
        "## 每类指标",
        "",
        "| 标签 | 样本 | 正确 | Recall | Precision | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, values in summary["per_class"].items():
        fmt = lambda value: "—" if value is None else f"{value:.3f}"
        lines.append(
            f"| {label} | {values['samples']} | {values['correct']} | {fmt(values['recall'])} | "
            f"{fmt(values['precision'])} | {fmt(values['f1'])} |"
        )
    lines += [
        "",
        "## 模型单次推理耗时",
        "",
        f"平均 {summary['model_processing_ms']['mean']:.3f} ms；"
        f"P50 {summary['model_processing_ms']['p50']:.3f} ms；"
        f"P95 {summary['model_processing_ms']['p95']:.3f} ms；"
        f"最大 {summary['model_processing_ms']['max']:.3f} ms。",
        "",
        "## 混淆矩阵",
        "",
        "行是真实标签，列是预测标签。",
        "",
        "| 真\\预测 | " + " | ".join(labels) + " |",
        "| --- | " + " | ".join(["---:"] * len(labels)) + " |",
    ]
    for label, counts in zip(labels, summary["confusion_matrix"]):
        lines.append("| " + label + " | " + " | ".join(map(str, counts)) + " |")
    return "\n".join(lines) + "\n"


def _ensure_empty_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"输出目录已存在且非空，拒绝覆盖既有结果：{resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="带 path、label 的本地 JSON 样本清单")
    parser.add_argument("--output", type=Path, help="新的空输出目录；默认使用带时间戳的 exports 目录")
    parser.add_argument("--warmup", type=int, default=1, help="首条样本预热推理次数（默认 1）")
    parser.add_argument("--require-all-labels", action="store_true", help="缺少固定 12 类任一类别时不开始评测")
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup 不能小于 0")
    manifest = args.manifest.resolve()
    records = load_manifest(manifest)
    present = {str(record["label"]) for record in records}
    missing = [label for label in LABELS if label not in present]
    if args.require_all_labels and missing:
        parser.error("样本清单缺少固定类别：" + "、".join(missing))
    output = args.output or ROOT / "exports" / f"evaluation-{time.strftime('%Y%m%d-%H%M%S')}"
    output = _ensure_empty_output(output)
    print("只读取本地 WAV 并运行离线模型；不会打开麦克风或扬声器。", flush=True)
    pcm_records = [(record, read_pcm(Path(record["path"]))) for record in records]
    rows: list[dict[str, object]] = []
    with NativePredictor() as predictor:
        for _ in range(args.warmup):
            predictor.predict(pcm_records[0][1])
        for record, pcm in pcm_records:
            predicted, score, elapsed, _scores = predictor.predict(pcm)
            rows.append({
                "id": record["id"],
                "path": str(Path(record["path"])),
                "label": record["label"],
                "predicted": predicted,
                "correct": predicted == record["label"],
                "score": round(score, 6),
                "processing_ms": round(elapsed, 6),
                "speaker": record["speaker"],
                "condition": record["condition"],
            })
    summary = make_summary(rows)
    summary["provenance"] = {
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "native_dll_sha256": hashlib.sha256((ROOT / "build/phrase_lab_core.dll").read_bytes()).hexdigest(),
        "warmup_iterations": args.warmup,
    }
    with (output / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.md").write_text(markdown_report(summary, manifest, args.warmup), encoding="utf-8")
    print(f"评测完成：{summary['correct']}/{summary['samples']}，准确率 {summary['accuracy']:.2%}")
    print(f"结果已写入：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
