"""Offline synthetic probes, not a human accuracy benchmark. Never opens audio devices.

SAPI writes English speech directly to WAV files; nothing is played aloud.
Run with --tag before / after to compare identical cached samples.
"""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from phrase_lab.domain import LABELS, Settings


def create_probes(folder, words):
    import pythoncom
    from win32com.client import Dispatch
    pythoncom.CoInitialize()
    voice = token = stream = None
    try:
        voice = Dispatch("SAPI.SpVoice")
        for token in voice.GetVoices():
            if "409" in token.GetAttribute("Language").lower().split(";"):
                voice.Voice = token
                break
        else:
            raise RuntimeError("An English SAPI voice is required")
        for rate in (-2, 0, 2):
            for word in words:
                path = folder / f"{word}_{rate}.wav"
                if path.exists():
                    continue
                stream = Dispatch("SAPI.SpFileStream")
                stream.Format.Type = 18  # SAFT16kHz16BitMono
                stream.Open(str(path.resolve()), 3, False)
                try:
                    voice.AudioOutputStream = stream
                    voice.Rate = rate
                    voice.Speak(word, 16)  # Synchronous plain text, file output only.
                finally:
                    stream.Close()
    finally:
        voice = token = stream = None
        pythoncom.CoUninitialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="current")
    parser.add_argument("--mode", choices=("experiment", "custom", "both"), default="both")
    parser.add_argument("--custom-threshold", type=float, default=Settings.custom_threshold)
    parser.add_argument("--rms-threshold", type=float, default=Settings.rms_threshold)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    if not args.tag.replace("-", "").replace("_", "").isalnum():
        parser.error("tag must contain only letters, numbers, hyphens or underscores")
    if not math.isfinite(args.gain) or not 0 < args.gain <= 1:
        parser.error("gain must be in (0, 1]")
    try:
        Settings(custom_threshold=args.custom_threshold, rms_threshold=args.rms_threshold).validate()
    except ValueError as exc:
        parser.error(str(exc))
    import numpy as np
    from phrase_lab.engines import make_engine
    folder = ROOT / "exports/english-diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    words = list(LABELS[2:]) + ["cat", "seven", "bird", "house", "tree"]
    create_probes(folder, words)
    probes = []
    for rate in (-2, 0, 2):
        for word in words:
            with wave.open(str(folder / f"{word}_{rate}.wav"), "rb") as source:
                assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
                pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32)/32768
            probes.append((word, rate, np.pad(pcm, (16000, 24000))))
    probes += [("silence", 0, np.zeros(48000, dtype=np.float32)),
               ("noise", 0, np.random.default_rng(13).normal(0, 0.015, 48000).astype(np.float32))]
    rows = []
    modes = ("experiment", "custom") if args.mode == "both" else (args.mode,)
    for mode in modes:
        settings = Settings(mode=mode, custom_threshold=args.custom_threshold, rms_threshold=args.rms_threshold)
        settings.validate()
        engine = make_engine(settings)
        try:
            for expected, rate, pcm in probes:
                engine.reset()
                events = []
                for start in range(0, len(pcm), 320):
                    events.extend(engine.feed(pcm[start:start+320] * args.gain))
                commands = [event.text for event in events if event.kind == "command"]
                row = {"mode": mode, "expected": expected, "rate": rate, "commands": commands,
                       "events": [asdict(event) for event in events]}
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "events"}), flush=True)
        finally:
            engine.close()
    summaries = {}
    for mode in modes:
        positive = [row for row in rows if row["mode"] == mode and row["expected"] in LABELS[2:]]
        negative = [row for row in rows if row["mode"] == mode and row["expected"] not in LABELS[2:]]
        summaries[mode] = {"exact_command_probes": sum(row["commands"] == [row["expected"]] for row in positive),
                           "positive_probes": len(positive),
                           "negative_probes_with_commands": sum(bool(row["commands"]) for row in negative),
                           "negative_probes": len(negative)}
    report = {"note": "SAPI Zira synthetic offline probes only; not human accuracy or real microphone latency.",
              "parameters": vars(args),
              "summary": summaries, "rows": rows}
    (folder / f"{args.tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries), flush=True)


if __name__ == "__main__":
    main()
