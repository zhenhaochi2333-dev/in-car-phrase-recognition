"""Opt-in test for stop, edit, then manually restart with the real microphone."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


@unittest.skipUnless(os.environ.get("PHRASE_LAB_REAL_MICROPHONE") == "1", "Real microphone test requires explicit opt-in")
class RealMicrophoneUpdate(unittest.TestCase):
    def test_stopped_phrase_edit_applies_after_manual_microphone_restart(self):
        import sounddevice as sd
        from PySide6.QtWidgets import QApplication
        from phrase_lab.appearance import configure_application
        from phrase_lab.domain import Phrase, Settings
        from phrase_lab.ui import MainWindow
        app = QApplication.instance() or QApplication([])
        configure_application(app)
        devices = sd.query_devices()
        device = next(i for i, x in enumerate(devices) if x["max_input_channels"] > 0
                      and x["hostapi"] == 0 and "麦克风阵列" in x["name"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            Settings(mode="custom", input_device=device).save(path)
            window = MainWindow(settings_path=path)
            window.show()

            def wait_for(predicate, timeout=15):
                deadline = time.monotonic()+timeout
                while time.monotonic() < deadline:
                    # Yield the Python GIL as well as dispatching Qt signals:
                    # repeated native qWait calls can starve Python QThread.run.
                    time.sleep(0.02)
                    app.processEvents()
                    if predicate():
                        return
                self.fail(window.message.text())

            try:
                window.start_listening()
                wait_for(lambda: window.input_connected)
                old = window.recognizer
                self.assertFalse(window.add_phrase_button.isEnabled())
                window.stop_all()
                wait_for(lambda: window.recognizer is None)
                self.assertTrue(window.add_phrase_button.isEnabled())
                window.accept_phrase(Phrase("打开导航"))
                self.assertIsNone(window.recognizer)
                window.start_listening()
                wait_for(lambda: window.recognizer is not None and window.recognizer is not old and window.input_connected)
                self.assertIn("打开导航", [p.text for p in window.recognizer.settings.phrases])
                wait_for(lambda: window.state_text.text() in ("检测到声音", "静音 / 等待短语"))
                self.assertFalse(window.add_phrase_button.isEnabled())
                self.assertIsNone(window.speaker)
                print("Stop/edit/manual restart released and reopened the microphone; no TTS played.", flush=True)
            finally:
                window.stop_all()
                wait_for(lambda: window.recognizer is None, timeout=20)
                window.close()
                window.deleteLater()
                app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
