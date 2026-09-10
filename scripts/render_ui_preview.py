"""Render actual idle widgets offscreen for visual review only.

No recognition, device enumeration, microphone, TTS, sample results, or user
settings writes. Audio dependencies are blocked in this preview process.
"""
import importlib.abc
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class BlockAudioImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"sounddevice", "sherpa_onnx", "pythoncom", "win32com", "winsound"}:
            raise RuntimeError(f"Audio/model dependency forbidden during visual preview: {fullname}")
        return None


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.meta_path.insert(0, BlockAudioImports())
    sys.path.insert(0, str(ROOT / "app"))
    from PySide6.QtWidgets import QApplication
    from phrase_lab.appearance import configure_application
    from phrase_lab.ui import MainWindow, PhraseDialog
    from phrase_lab.domain import Phrase
    from phrase_lab.workers import RecognitionWorker, SpeechWorker

    def forbid_worker(*args, **kwargs):
        raise RuntimeError("Background audio tasks are forbidden during visual preview")

    RecognitionWorker.start = forbid_worker
    SpeechWorker.start = forbid_worker
    app = QApplication([])
    configure_application(app)
    window = MainWindow()
    window.resize(1320, 900)
    window.show()  # Offscreen platform: this does not open a desktop window.
    output = ROOT / "docs/ui"
    output.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(("workbench", "phrases", "settings")):
        window.navigate(index)
        app.processEvents()
        if not window.grab().save(str(output / f"{name}.png")):
            raise RuntimeError("Unable to save UI preview")
    window.navigate(0)
    window.resize(1060, 700)
    app.processEvents()
    window.grab().save(str(output / "compact.png"))
    dialog = PhraseDialog(Phrase(""), window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(output / "phrase-dialog.png"))
    dialog.close()
    window.close()
    print("Offscreen visual previews saved to docs/ui. No recognition, audio, or business actions executed.")


if __name__ == "__main__":
    main()
