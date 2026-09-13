"""Unit tests for local dataset validation and report statistics (no audio device)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evaluate_dataset", ROOT / "scripts" / "evaluate_dataset.py")
assert SPEC is not None and SPEC.loader is not None
evaluate_dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_dataset)


class EvaluateDatasetTests(unittest.TestCase):
    def make_wav(self, path: Path, frames: int = 16000):
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * frames)

    def test_manifest_uses_paths_relative_to_its_own_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            clips = folder / "clips"
            clips.mkdir()
            self.make_wav(clips / "yes.wav")
            manifest = folder / "dataset.json"
            manifest.write_text(json.dumps({"samples": [{
                "id": "one", "path": "clips/yes.wav", "label": "yes",
                "speaker": "student-a", "condition": "clean",
            }]}), encoding="utf-8")
            records = evaluate_dataset.load_manifest(manifest)
            self.assertEqual(records[0]["path"], (clips / "yes.wav").resolve())
            self.assertEqual(records[0]["speaker"], "student-a")
            pcm = evaluate_dataset.read_pcm(clips / "yes.wav")
            self.assertEqual(pcm.shape, (16000,))

    def test_invalid_label_is_rejected_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_wav(folder / "word.wav")
            manifest = folder / "dataset.json"
            manifest.write_text(json.dumps([{"path": "word.wav", "label": "straight"}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "固定 12 类"):
                evaluate_dataset.load_manifest(manifest)

    def test_summary_marks_missing_classes_and_reports_matrix(self):
        rows = [
            {"label": "yes", "predicted": "yes", "correct": True, "processing_ms": 2.0,
             "speaker": "a", "condition": "clean"},
            {"label": "no", "predicted": "yes", "correct": False, "processing_ms": 4.0,
             "speaker": "b", "condition": "noise"},
        ]
        summary = evaluate_dataset.make_summary(rows)
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertIn("down", summary["coverage"]["classes_without_samples"])
        yes = evaluate_dataset.LABELS.index("yes")
        no = evaluate_dataset.LABELS.index("no")
        self.assertEqual(summary["confusion_matrix"][yes][yes], 1)
        self.assertEqual(summary["confusion_matrix"][no][yes], 1)
        self.assertEqual(summary["by_condition"]["noise"]["accuracy"], 0.0)
        self.assertEqual(summary["per_class"]["no"]["f1"], 0.0)
        self.assertIsNone(summary["per_class"]["down"]["f1"])

    def test_duplicate_audio_and_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_wav(folder / "one.wav")
            self.make_wav(folder / "two.wav")
            manifest = folder / "dataset.json"
            for samples in (
                [{"path": "one.wav", "label": "yes"}, {"path": "./one.wav", "label": "yes"}],
                [{"id": "same", "path": "one.wav", "label": "yes"},
                 {"id": "same", "path": "two.wav", "label": "no"}],
            ):
                manifest.write_text(json.dumps(samples), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "重复"):
                    evaluate_dataset.load_manifest(manifest)

    def test_truncated_wav_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "truncated.wav"
            self.make_wav(clip)
            clip.write_bytes(clip.read_bytes()[:-200])
            with self.assertRaisesRegex(ValueError, "截断"):
                evaluate_dataset.read_pcm(clip)

    def test_manifest_cannot_reference_files_outside_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_wav(folder / "outside.wav")
            dataset = folder / "dataset"
            dataset.mkdir()
            manifest = dataset / "dataset.json"
            manifest.write_text(json.dumps([{"path": "../outside.wav", "label": "yes"}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "目录内"):
                evaluate_dataset.load_manifest(manifest)

    @unittest.skipUnless((ROOT / "build" / "phrase_lab_core.dll").is_file(), "Native DLL has not been built")
    def test_cli_creates_an_offline_report_without_opening_audio_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            clip = folder / "silence.wav"
            self.make_wav(clip)
            manifest = folder / "dataset.json"
            manifest.write_text(json.dumps({"samples": [{
                "path": "silence.wav", "label": "_silence_", "speaker": "test", "condition": "clean",
            }]}), encoding="utf-8")
            output = folder / "output"
            with patch.object(evaluate_dataset.sys, "argv", [
                "evaluate_dataset.py", str(manifest), "--output", str(output), "--warmup", "0",
            ]):
                self.assertEqual(evaluate_dataset.main(), 0)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["samples"], 1)
            self.assertEqual(summary["correct"], 1)
            self.assertTrue((output / "predictions.csv").is_file())
            self.assertTrue((output / "summary.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
