"""Unit tests for the local recorder's file and manifest helpers (no microphone)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("record_dataset", ROOT / "scripts" / "record_dataset.py")
assert SPEC is not None and SPEC.loader is not None
record_dataset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record_dataset)


class RecordDatasetTests(unittest.TestCase):
    def test_safe_name_and_dataset_round_trip(self):
        self.assertEqual(record_dataset.safe_name(" 学生 A / test "), "学生-A-test")
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "dataset.json"
            dataset = record_dataset.load_dataset(manifest)
            self.assertEqual(dataset["samples"], [])
            dataset["samples"].append({"path": "clips/yes.wav", "label": "yes"})
            record_dataset.save_dataset(manifest, dataset)
            self.assertEqual(record_dataset.load_dataset(manifest)["samples"][0]["label"], "yes")

    def test_write_wav_makes_the_expected_pcm16_clip(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "clip.wav"
            rms, peak = record_dataset.write_wav(target, np.zeros((16000, 1), dtype=np.float32))
            self.assertEqual((rms, peak), (0.0, 0.0))
            with wave.open(str(target), "rb") as stream:
                self.assertEqual((stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getnframes()),
                                 (16000, 1, 2, 16000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
