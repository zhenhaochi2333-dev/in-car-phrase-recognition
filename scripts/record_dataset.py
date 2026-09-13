"""Explicitly record local one-second WAV samples for the fixed 12-class test.

Nothing is recorded until this script is run and Enter is pressed for a take.
All WAV files and the JSON manifest stay in the selected local project folder;
the script has no network access or upload step.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
import wave


ROOT = Path(__file__).resolve().parents[1]
LABELS = (
    "_silence_", "_unknown_", "down", "go", "left", "no",
    "off", "on", "right", "stop", "up", "yes",
)
SAMPLE_RATE = 16_000
SAMPLES_PER_CLIP = 16_000


def safe_name(value: str) -> str:
    rendered = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip())
    return rendered.strip("-") or "sample"


def list_input_devices(sd) -> None:
    print("可用输入设备：")
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            marker = "（系统默认）" if index == sd.default.device[0] else ""
            print(f"  {index}: {info['name']}，{info['max_input_channels']} 声道 {marker}")


def selected_device(sd, requested: int | None) -> tuple[int, dict]:
    device = requested if requested is not None else int(sd.default.device[0])
    if device < 0:
        raise ValueError("没有系统默认输入设备；先用 --list-devices 查看设备编号，再通过 --device 指定")
    info = sd.query_devices(device, "input")
    if info["max_input_channels"] < 1:
        raise ValueError(f"设备 {device} 不支持输入")
    sd.check_input_settings(device=device, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    return device, dict(info)


def load_dataset(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "schema_version": 1,
            "sample_rate": SAMPLE_RATE,
            "clip_duration_seconds": 1,
            "samples": [],
        }
    try:
        existing = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"现有样本清单不是有效 JSON：{path}（第 {exc.lineno} 行）") from exc
    if not isinstance(existing, dict) or not isinstance(existing.get("samples"), list):
        raise ValueError(f"现有样本清单格式不正确：{path}")
    return existing


def save_dataset(path: Path, dataset: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def write_wav(path: Path, recording) -> tuple[float, float]:
    import numpy as np

    mono = np.asarray(recording, dtype=np.float32).reshape(-1)
    if len(mono) != SAMPLES_PER_CLIP:
        raise RuntimeError(f"录音采样数异常：{len(mono)} != {SAMPLES_PER_CLIP}")
    if not np.isfinite(mono).all():
        raise ValueError("录音含有非有限数值，不能写入评测样本")
    rms = float(np.sqrt(np.mean(np.square(mono))))
    peak = float(np.max(np.abs(mono)))
    pcm16 = np.clip(np.rint(mono * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm16.tobytes())
    return rms, peak


def label_prompt(label: str) -> str:
    if label == "_silence_":
        return "请保持安静。"
    if label == "_unknown_":
        return "请说一个不属于十个口令的英语词，例如 straight；它应作为未知类。"
    return f"请说：{label}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="只列出输入设备，不录音")
    parser.add_argument("--label", choices=LABELS, help="本次要采集的固定类别")
    parser.add_argument("--count", type=int, default=3, help="采集条数，默认每类 3 条")
    parser.add_argument("--speaker", help="说话人代号，例如 student-a；录音模式必填")
    parser.add_argument("--condition", default="clean", help="环境标记，例如 clean、noise")
    parser.add_argument("--device", type=int, help="输入设备编号；默认使用系统默认输入")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "evaluation_samples",
                        help="本地样本目录，默认 data/evaluation_samples")
    parser.add_argument("--countdown", type=int, default=3, help="每次按下 Enter 后的倒计时秒数")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count 至少为 1")
    if args.countdown < 0:
        parser.error("--countdown 不能小于 0")
    if not args.list_devices and (not args.label or not args.speaker or not args.speaker.strip()):
        parser.error("录音需要 --label 和 --speaker；可先使用 --list-devices")
    import sounddevice as sd

    if args.list_devices:
        list_input_devices(sd)
        return 0
    device, info = selected_device(sd, args.device)
    output = args.output.resolve()
    clips = output / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "dataset.json"
    dataset = load_dataset(manifest_path)
    print("本次录音只保存在本机；不会上传。按 Ctrl+C 可在下一条开始前退出。")
    print(f"输入设备：{device} - {info['name']}")
    print(f"标签：{args.label}；{label_prompt(args.label)}")
    for take in range(1, args.count + 1):
        input(f"\n第 {take}/{args.count} 条。准备好后按 Enter，倒计时结束立刻说话：")
        for remaining in range(args.countdown, 0, -1):
            print(remaining, flush=True)
            time.sleep(1)
        print("开始录音（1 秒）…", flush=True)
        recording = sd.rec(SAMPLES_PER_CLIP, samplerate=SAMPLE_RATE, channels=1,
                           dtype="float32", device=device)
        sd.wait()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{safe_name(args.label)}-{safe_name(args.speaker)}-{safe_name(args.condition)}-{stamp}-{uuid.uuid4().hex[:6]}.wav"
        target = clips / name
        rms, peak = write_wav(target, recording)
        relative = target.relative_to(output).as_posix()
        dataset["samples"].append({
            "id": "sample-" + uuid.uuid4().hex[:12],
            "path": relative,
            "label": args.label,
            "speaker": args.speaker.strip(),
            "condition": args.condition.strip() or "未标注",
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "input_device": {"index": device, "name": info["name"]},
            "rms": round(rms, 6),
            "peak": round(peak, 6),
        })
        save_dataset(manifest_path, dataset)
        print(f"已保存：{target.name}（RMS {rms:.4f}，峰值 {peak:.4f}）")
        if args.label != "_silence_" and rms < 0.004:
            print("警告：音量很低。请确认选择的是实际麦克风而不是立体声混音，再重录这一条。")
    print(f"\n完成。本地样本清单：{manifest_path}")
    print("收齐 12 类后可运行：")
    print(f'  .\\.venv\\Scripts\\python.exe scripts\\evaluate_dataset.py "{manifest_path}" --require-all-labels')
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消；已经保存的录音和清单条目保留在本机。", file=sys.stderr)
        raise SystemExit(130)
