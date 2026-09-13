"""Exercise real Qt buttons and dialogs with isolated settings and silent workers."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton
from phrase_lab.appearance import configure_application
from phrase_lab.domain import Phrase, RecognitionEvent, Settings
from phrase_lab import ui


class SilentRecognition(QObject):
    event = Signal(object)
    state = Signal(str)
    level = Signal(float)
    error = Signal(str)
    finished = Signal()
    instances = []

    def __init__(self, policy, settings, parent=None):
        super().__init__(parent)
        self.policy, self.settings = policy, settings
        self.cancelled = threading.Event()
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True
        self.state.emit("正在监听")

    def stop(self):
        self.cancelled.set()

    def isRunning(self):
        return self.running

    def finish(self):
        self.running = False
        self.finished.emit()


class SilentSpeech(QObject):
    state = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, policy, text, volume, rate, parent=None):
        super().__init__(parent)
        self.policy, self.text = policy, text
        self.cancelled = threading.Event()

    def start(self):
        self.state.emit("正在合成播报；请等播完后再说下一句")

    def stop(self):
        self.cancelled.set()

    def finish(self):
        self.policy.end_speech()
        self.finished.emit()


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp.name) / "settings.json"
        Settings(mode="custom", phrases=[Phrase(text) for text in
            ("打开空调", "关闭空调", "打开车窗", "关闭车窗", "播放音乐", "停止播放")]).save(self.settings_path)
        SilentRecognition.instances = []
        self.rpatch = patch.object(ui, "RecognitionWorker", SilentRecognition)
        self.spatch = patch.object(ui, "SpeechWorker", SilentSpeech)
        self.rpatch.start()
        self.spatch.start()
        self.window = ui.MainWindow(settings_path=self.settings_path)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.stop_all()
        if self.window.recognizer is not None:
            self.window.recognizer.finish()
        if self.window.speaker is not None:
            self.window.speaker.finish()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.spatch.stop()
        self.rpatch.stop()
        self.temp.cleanup()

    def click(self, control):
        self.assertTrue(control.isEnabled(), control.text())
        QTest.mouseClick(control, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def open_edit(self, control, text, expected_error=None):
        errors = []

        def fill():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertIsInstance(dialog, ui.PhraseDialog)
                dialog.text.setText(text)
                buttons = dialog.findChild(QDialogButtonBox)
                self.click(buttons.button(QDialogButtonBox.StandardButton.Save))
                if expected_error:
                    self.assertTrue(dialog.isVisible())
                    self.assertIn(expected_error, dialog.error.text())
                else:
                    self.assertFalse(dialog.isVisible(), dialog.error.text())
            except BaseException as exc:
                errors.append(exc)
            finally:
                if dialog is not None and dialog.isVisible():
                    dialog.reject()

        QTimer.singleShot(0, fill)
        self.click(control)
        if errors:
            raise errors[0]

    def listen(self):
        self.click(self.window.start_button)
        self.assertIsNotNone(self.window.recognizer)
        self.window.navigate(1)
        self.app.processEvents()
        return self.window.recognizer

    def test_editing_waits_for_stop_and_both_workers_to_finish(self):
        old = self.listen()
        self.window.autospeak.setChecked(True)
        old.event.emit(RecognitionEvent("command", "打开空调", "Zipformer / 自定义"))
        speaker = self.window.speaker
        self.assertIsNotNone(speaker)
        self.assertFalse(self.window.add_phrase_button.isEnabled())
        original = self.settings_path.read_bytes()
        self.window.accept_phrase(Phrase("打开导航"))
        self.assertEqual(self.settings_path.read_bytes(), original)
        self.window.stop_all()
        self.assertTrue(old.cancelled.is_set())
        self.assertTrue(speaker.cancelled.is_set())
        old.finish()
        self.assertFalse(self.window.add_phrase_button.isEnabled())
        speaker.finish()
        self.assertTrue(self.window.add_phrase_button.isEnabled())
        self.open_edit(self.window.add_phrase_button, "打开导航")
        self.assertIn("打开导航", [p.text for p in Settings.load(self.settings_path).phrases])
        self.assertIsNone(self.window.recognizer)
        self.assertEqual(len(SilentRecognition.instances), 1)
        self.assertEqual(len(self.window.history), 1)
        self.assertTrue(self.window.autospeak.isChecked())
        self.window.navigate(0)
        self.click(self.window.start_button)
        self.assertIn("打开导航", [p.text for p in self.window.recognizer.settings.phrases])

    def test_duplicate_and_oov_stay_in_dialog_without_saving(self):
        self.window.navigate(1)
        original = self.settings_path.read_bytes()
        self.open_edit(self.window.add_phrase_button, "打开空调", "重复")
        self.open_edit(self.window.add_phrase_button, "qzxqzxqzx", "英文词典不包含")
        self.assertEqual(self.settings_path.read_bytes(), original)
        self.assertIsNone(self.window.recognizer)

    def test_edit_delete_and_toggle_apply_on_next_manual_start(self):
        self.window.navigate(1)
        self.window.phrase_table.selectRow(0)
        self.open_edit(self.window.edit_phrase_button, "打开导航")
        self.click(self.window.delete_phrase_button)
        self.window.phrase_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertIsNone(self.window.recognizer)
        self.window.navigate(0)
        self.click(self.window.start_button)
        current = self.window.recognizer.settings
        self.assertEqual(len(SilentRecognition.instances), 1)
        self.assertEqual(len(current.phrases), 5)
        self.assertFalse(current.phrases[0].enabled)
        self.assertNotIn("打开导航", [p.text for p in current.phrases])
        self.assertEqual(current, Settings.load(self.settings_path))

    def test_stopping_keeps_editor_locked_until_worker_has_exited(self):
        old = self.listen()
        self.window.navigate(0)
        self.click(self.window.stop_button)
        self.assertFalse(self.window.add_phrase_button.isEnabled())
        self.assertFalse(self.window.mode.isEnabled())
        self.assertFalse(self.window.save_settings_button.isEnabled())
        old.finish()
        self.assertIsNone(self.window.recognizer)
        self.assertTrue(self.window.add_phrase_button.isEnabled())
        self.assertTrue(self.window.mode.isEnabled())
        self.assertTrue(self.window.save_settings_button.isEnabled())
        self.assertEqual(len(SilentRecognition.instances), 1)

    def test_empty_library_cannot_start_and_editor_stays_available(self):
        self.window.navigate(1)
        for row in range(self.window.phrase_table.rowCount()):
            self.window.phrase_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.window.navigate(0)
        self.click(self.window.start_button)
        self.assertIsNone(self.window.recognizer)
        self.assertTrue(self.window.add_phrase_button.isEnabled())
        self.window.phrase_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.navigate(0)
        self.click(self.window.start_button)
        self.assertIsNotNone(self.window.recognizer)

    def test_settings_and_mode_switch_require_stopped_session(self):
        old = self.listen()
        self.assertFalse(self.window.mode.isEnabled())
        self.assertFalse(self.window.device.isEnabled())
        self.assertFalse(self.window.save_settings_button.isEnabled())
        self.window.stop_all()
        old.finish()
        self.window.navigate(2)
        self.window.volume.setValue(35)
        self.window.kws_threshold.setValue(0.45)
        self.click(self.window.save_settings_button)
        self.assertIsNone(self.window.recognizer)
        self.window.navigate(0)
        self.window.mode.setCurrentIndex(0)
        self.assertIsNone(self.window.recognizer)
        self.click(self.window.start_button)
        self.assertEqual(self.window.recognizer.settings.volume, 35)
        self.assertEqual(self.window.recognizer.settings.custom_threshold, 0.45)
        self.assertEqual(self.window.recognizer.settings.mode, "experiment")

    def test_mode_and_input_hints_explain_course_scope(self):
        self.window.navigate(0)
        self.window.mode.setCurrentIndex(self.window.mode.findData("experiment"))
        self.app.processEvents()
        self.assertIn("固定统计", self.window.mode_hint.text())
        self.assertIn("straight", self.window.mode_hint.text())
        self.window.mode.setCurrentIndex(self.window.mode.findData("custom"))
        self.app.processEvents()
        self.assertIn("扩展功能", self.window.mode_hint.text())
        self.assertIn("系统默认", self.window.device_hint.text())
        self.window.device.addItem("Stereo Mix #99", 99)
        self.window.device.setCurrentIndex(self.window.device.findData(99))
        self.app.processEvents()
        self.assertIn("虚拟或混音", self.window.device_hint.text())

    def test_quiet_input_updates_idle_card_without_history_or_speech(self):
        worker = self.listen()
        self.window.autospeak.setChecked(True)
        worker.state.emit("静音 / 等待短语")
        self.assertIn("静音", self.window.result_text.text())
        self.assertEqual(len(self.window.history), 0)
        self.assertIsNone(self.window.speaker)
        worker.state.emit("检测到声音")
        self.assertIn("正在识别", self.window.result_text.text())
        self.window.autospeak.setChecked(False)
        worker.event.emit(RecognitionEvent("command", "yes", "BC-ResNet / 实验"))
        worker.state.emit("静音 / 等待短语")
        self.assertEqual(self.window.result_text.text(), "yes")
        self.assertEqual(len(self.window.history), 1)

    def test_import_export_search_and_saved_phrases_while_stopped(self):
        self.window.navigate(1)
        buttons = {b.text(): b for b in self.window.phrase_editor.findChildren(QPushButton)}
        target = Path(self.temp.name) / "phrases.json"
        with patch.object(ui.QFileDialog, "getSaveFileName", return_value=(str(target), "JSON")):
            self.click(buttons["导出"])
        rows = json.loads(target.read_text(encoding="utf-8"))
        rows.append({"text": "打开导航", "id": "p0123456789ab", "enabled": True, "tokens": ""})
        target.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        with patch.object(ui.QFileDialog, "getOpenFileName", return_value=(str(target), "JSON")):
            self.click(buttons["导入"])
        self.assertIsNone(self.window.recognizer)
        self.assertEqual(len(Settings.load(self.settings_path).phrases), 7)
        self.window.phrase_search.setText("导航")
        visible = [i for i in range(7) if not self.window.phrase_table.isRowHidden(i)]
        self.assertEqual(visible, [6])
        self.window.phrase_table.selectRow(6)
        self.assertTrue(self.window.edit_phrase_button.isEnabled())
        self.window.phrase_search.setText("找不到的短语")
        self.assertFalse(self.window.edit_phrase_button.isEnabled())
        self.assertTrue(self.window.add_phrase_button.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
