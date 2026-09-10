from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import csv
import json
import math
import shutil

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QLineEdit, QMainWindow, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .appearance import STYLE, icon, label, set_badge
from .layout import WorkspaceLayout
from .audio import AudioPolicy, input_devices
from .domain import ROOT, Phrase, RecognitionEvent, Settings
from .keywords import compile_keywords
from .workers import RecognitionWorker, SpeechWorker

class PhraseDialog(QDialog):
    def __init__(self, phrase: Phrase, parent=None, validator=None):
        super().__init__(parent)
        self.setWindowTitle("设置识别短语")
        self.setMinimumWidth(530)
        self.phrase = deepcopy(phrase)
        self.validator = validator
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(label("编辑短语" if phrase.text else "添加一条短语", "sectionTitle"))
        layout.addWidget(label("写下你希望电脑识别的话。识别成功后，可朗读这段文字。", "subtle", True))
        form = QFormLayout()
        form.setSpacing(14)
        self.text = QLineEdit(phrase.text)
        self.text.setPlaceholderText("例如：打开空调 / TURN ON THE LIGHT")
        self.enabled = QCheckBox("启用这条短语")
        self.enabled.setChecked(phrase.enabled)
        self.tokens = QLineEdit(phrase.tokens)
        self.tokens.setPlaceholderText("用空格分隔模型词元")
        form.addRow("识别短语", self.text)
        form.addRow("", self.enabled)
        layout.addLayout(form)
        self.advanced = QCheckBox("手动设置发音")
        self.advanced.setChecked(bool(phrase.tokens))
        layout.addWidget(self.advanced)
        self.advanced_fields = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_fields)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self.tokens)
        advanced_layout.addWidget(label("通常无需填写。仅在多音字或英文词典外词需要修正时，使用模型词表中的词元。", "subtle", True))
        self.advanced_fields.setVisible(bool(phrase.tokens))
        self.advanced.toggled.connect(self.advanced_fields.setVisible)
        layout.addWidget(self.advanced_fields)
        self.error = label("", wrap=True)
        self.error.setStyleSheet("color: #b5473c")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        controls.accepted.connect(self.submit)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def submit(self):
        try:
            self.phrase.text = self.text.text()
            self.phrase.tokens = self.tokens.text().strip() if self.advanced.isChecked() else ""
            self.phrase.enabled = self.enabled.isChecked()
            self.phrase.validate()
            if self.validator is not None:
                self.validator(self.phrase)
        except Exception as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class MainWindow(WorkspaceLayout, QMainWindow):
    def __init__(self, settings_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("声语 · 车内短语识别实验")
        self.setWindowIcon(icon("wave", "#3567e8", 32))
        self.resize(1320, 900)
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(STYLE)
        self.policy = AudioPolicy()
        self.recognizer = self.speaker = None
        self.closing = False
        self._initializing = True
        self.input_connected = False
        self.history: list[RecognitionEvent] = []
        self.settings_path = settings_path if settings_path is not None else ROOT / "data/settings.json"
        self.settings_problem = ""
        try:
            self.settings = Settings.load(self.settings_path)
        except Exception as exc:
            self.settings = Settings()
            self.settings_problem = f"设置文件加载失败，已使用默认值：{exc}"
        self.build_window()
        self.render_phrases()
        self.update_model_status()
        self.update_controls()
        self.mode_changed()
        if self.settings_problem:
            self.tell(self.settings_problem, True)
        else:
            self.tell("就绪。选择识别模式，点击开始监听。")
        self.close_timer = QTimer(self)
        self.close_timer.setInterval(80)
        self.close_timer.timeout.connect(self.finish_close)
        self._initializing = False
        self.device.currentIndexChanged.connect(self.device_changed)

    def tell(self, text, error=False):
        self.message.setText(text)
        self.message.setStyleSheet("color: #a43c32;" if error else "color: #3b536d;")

    @Slot(str)
    def on_worker_error(self, text):
        self.tell(text, True)

    def active(self):
        return self.recognizer is not None

    def can_edit(self):
        return self.policy.allowed and not self.closing and self.recognizer is None and self.speaker is None

    def require_editing(self):
        if not self.can_edit():
            self.tell("请先停止监听，等待当前播报结束后再修改。")
            return False
        return True

    def update_controls(self):
        active, audible = self.active(), self.policy.allowed
        editing = self.can_edit()
        self.start_button.setEnabled(editing)
        self.stop_button.setEnabled(active or self.speaker is not None)
        self.mode.setEnabled(editing)
        self.device.setEnabled(editing)
        self.refresh_devices_button.setEnabled(editing)
        self.autospeak.setEnabled(audible and not self.closing)
        self.phrase_editor.setEnabled(editing)
        self.settings_editor.setEnabled(editing)
        self.settings_lock_note.setText("设置已锁定，请先在识别工作台停止监听和播报。" if not editing else
                                       "修改并保存设置后，点击开始监听时生效。")
        self.start_button.setText("运行中" if active else "开始监听")
        self.update_library_note()
        self.update_history_actions()
        self.update_phrase_actions()
        self.update_session_badge()

    def update_session_badge(self):
        if self.closing:
            text, tone = "●  正在关闭", "amber"
        elif self.speaker is not None:
            text, tone = "●  播报中", "blue"
        elif self.recognizer is not None:
            text, tone = ("●  正在停止", "amber") if self.recognizer.cancelled.is_set() else ("●  识别已开启", "green")
        else:
            text, tone = "●  待机", "neutral"
        set_badge(self.session_badge, text, tone)
        self.footer_status.setText("麦克风已连接" if self.input_connected else "任务运行中" if self.active() or self.speaker else "未连接麦克风")

    def update_history_actions(self):
        if not hasattr(self, "replay_button"):
            return
        row = self.history_table.currentRow()
        selected = 0 <= row < len(self.history) and self.history[row].kind == "command"
        self.replay_button.setEnabled(selected and self.policy.allowed and self.speaker is None and not self.closing)
        self.replay_button.setToolTip("根据所选文字合成朗读" if selected else "先在会话记录中选择一条已识别的短语")
        self.export_history_button.setEnabled(bool(self.history))
        self.clear_history_button.setEnabled(bool(self.history))
        self.history_count.setText(f"{len(self.history)} 条记录")
        self.history_stack.setCurrentIndex(1 if self.history else 0)

    def update_phrase_actions(self):
        if not hasattr(self, "edit_phrase_button"):
            return
        row = self.phrase_table.currentRow()
        selected = 0 <= row < len(self.settings.phrases) and not self.phrase_table.isRowHidden(row)
        self.edit_phrase_button.setEnabled(selected)
        self.delete_phrase_button.setEnabled(selected)
        self.edit_phrase_button.setToolTip("编辑所选短语" if selected else "先在列表中选择一条短语")
        self.delete_phrase_button.setToolTip("删除所选短语" if selected else "先在列表中选择一条短语")

    def filter_phrases(self):
        query = self.phrase_search.text().strip().casefold()
        visible = 0
        for row, phrase in enumerate(self.settings.phrases):
            show = query in phrase.text.casefold()
            self.phrase_table.setRowHidden(row, not show)
            visible += int(show)
        if self.phrase_table.currentRow() >= 0 and self.phrase_table.isRowHidden(self.phrase_table.currentRow()):
            self.phrase_table.setCurrentCell(-1, -1)
        self.phrase_stack.setCurrentIndex(0 if visible else 1)
        self.update_phrase_actions()

    def auto_speech_changed(self, value):
        if not value and self.speaker is not None:
            self.speaker.stop()

    def refresh_devices(self):
        try:
            saved = self.device.currentData()
            devices = input_devices(self.policy)
            self.device.blockSignals(True)
            try:
                self.device.clear()
                self.device.addItem("系统默认麦克风", -1)
                for index, name in devices:
                    self.device.addItem(f"{name}  #{index}", index)
                found = self.device.findData(saved)
                self.device.setCurrentIndex(max(0, found))
            finally:
                self.device.blockSignals(False)
            if saved != self.device.currentData():
                self.device_changed()
            else:
                self.tell("设备列表已更新。")
        except Exception as exc:
            self.tell(str(exc), True)

    def snapshot(self):
        settings = deepcopy(self.settings)
        settings.mode = self.mode.currentData()
        settings.input_device = self.device.currentData()
        settings.threshold = self.exp_threshold.value()
        settings.custom_threshold = self.kws_threshold.value()
        settings.rms_threshold = self.rms_threshold.value()
        settings.volume, settings.rate = self.volume.value(), self.rate.value()
        settings.validate()
        return settings

    def persist(self):
        if not self.can_edit():
            raise ValueError("请先停止监听，等待当前播报结束后再修改。")
        current = self.snapshot()
        self.validate_keywords(current)
        if self.settings_problem and self.settings_path.exists():
            recovery = self.settings_path.with_name(f"settings.invalid-{datetime.now():%Y%m%d-%H%M%S}.json")
            shutil.copy2(self.settings_path, recovery)
            self.settings_problem = ""
        current.save(self.settings_path)
        self.settings = current

    @staticmethod
    def validate_keywords(settings):
        directory = ROOT / "models/custom"
        if any(p.enabled for p in settings.phrases) and all((directory / x).is_file() for x in ("tokens.txt", "en.phone")):
            compile_keywords(settings.phrases, directory)

    def apply_saved_settings(self, message):
        self.tell(message + " 点击开始监听后使用新配置。")
        self.update_controls()

    def save_from_ui(self):
        try:
            self.persist()
            self.apply_saved_settings("设置已保存。")
        except Exception as exc:
            self.tell(str(exc), True)

    def mode_changed(self):
        if hasattr(self, "message"):
            custom = self.mode.currentData() == "custom"
            set_badge(self.mode_badge, "自定义短语" if custom else "实验口令", "blue")
            self.update_library_note()
            if not self._initializing:
                self.save_from_ui()

    def device_changed(self):
        if not self._initializing:
            self.save_from_ui()

    def update_library_note(self):
        if not self.can_edit():
            text = "短语库已锁定。请先到「识别工作台」点击停止，待监听和播报结束后再添加或修改短语。"
        elif self.mode.currentData() != "custom":
            text = "当前为实验模式，也可编辑短语库。切换到「自定义短语」后使用此处的列表。"
        else:
            text = "添加想让电脑识别的短语并启用，开始监听后即可使用。"
        self.library_note.setText(text)

    def start_listening(self):
        if not self.can_edit():
            return
        try:
            self.policy.require()
            self.persist()
        except Exception as exc:
            self.tell(str(exc), True)
            return
        self.launch_recognizer()

    def launch_recognizer(self):
        if self.closing or self.active() or self.speaker is not None:
            return
        worker = None
        try:
            self.policy.require()
            if self.settings.mode == "custom" and not any(p.enabled for p in self.settings.phrases):
                raise ValueError("请先在短语库添加或启用至少一条短语")
            worker = RecognitionWorker(self.policy, deepcopy(self.settings), self)
            worker.event.connect(self.on_result)
            worker.state.connect(self.on_worker_state)
            worker.level.connect(self.on_level)
            worker.error.connect(self.on_worker_error)
            worker.finished.connect(self.recognition_finished)
            self.recognizer = worker
            self.input_connected = False
            self.update_controls()
            self.tell("正在加载模型。可随时点击停止；加载完成前不会开始采集。")
            worker.start()
        except Exception as exc:
            if worker is not None and not worker.isRunning():
                self.recognizer = None
                worker.deleteLater()
            self.update_controls()
            self.tell(str(exc), True)

    def stop_all(self):
        if self.recognizer is not None:
            self.recognizer.stop()
        if self.speaker is not None:
            self.speaker.stop()
        self.state_text.setText("正在停止…" if self.active() or self.speaker else "待机 · 尚未录音")
        self.update_controls()

    @Slot()
    def recognition_finished(self):
        worker, self.recognizer = self.recognizer, None
        self.input_connected = False
        if worker is not None:
            worker.deleteLater()
        self.update_controls()

    @Slot(str)
    def on_worker_state(self, text):
        self.state_text.setText(text)
        if text == "正在监听":
            self.input_connected = True
            if self.message.text().startswith("正在加载模型"):
                self.tell("麦克风已连接，可以说话。修改短语或设置前，请先停止监听。")
        self.update_session_badge()

    @Slot(float)
    def on_level(self, rms):
        db = 20 * math.log10(max(rms, 1e-6))
        self.meter.setValue(round(max(0, min(100, (db + 60) / 60 * 100))))

    @Slot(object)
    def on_result(self, event):
        if (self.closing or not self.policy.allowed or self.policy.suppressed
                or self.recognizer is None or self.recognizer.cancelled.is_set()):
            return
        self.history.append(event)
        if len(self.history) > 2000:
            self.history.pop(0)
            self.history_table.removeRow(0)
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)
        score = "—" if event.score is None else f"{event.score:.3f}"
        elapsed = "—" if event.processing_ms is None else f"{event.processing_ms:.1f} ms"
        for col, value in enumerate((event.timestamp[11:], event.text, score, elapsed)):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self.history_table.setItem(row, col, item)
        self.update_history_actions()
        self.history_table.scrollToBottom()
        self.result_text.setText(event.text)
        self.result_text.setStyleSheet("font-size: 23px;" if len(event.text) > 24 else "")
        self.result_hint.setText("已识别到短语" if event.kind == "command" else "试试调整说话距离，或检查短语设置")
        self.result_engine.setText("自定义短语" if "Zipformer" in event.engine else "实验口令")
        self.result_engine.setToolTip(event.engine)
        self.result_score.setText(score)
        self.result_time.setText(elapsed)
        if event.kind == "command" and self.autospeak.isChecked():
            self.speak(event.text)

    def speak(self, text):
        if self.speaker is not None:
            self.tell("上一条播报尚未结束，此次不排队。")
            return
        try:
            self.policy.require()
            worker = SpeechWorker(self.policy, text, self.volume.value(), self.rate.value(), self)
            worker.state.connect(self.on_worker_state)
            worker.error.connect(self.on_worker_error)
            worker.finished.connect(self.speech_finished)
            self.policy.begin_speech()
            self.speaker = worker
            self.update_controls()
            worker.start()
        except Exception as exc:
            self.policy.end_speech()
            self.tell(str(exc), True)

    @Slot()
    def speech_finished(self):
        worker, self.speaker = self.speaker, None
        if worker is not None:
            worker.deleteLater()
        self.update_controls()

    def replay(self):
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self.history):
            self.tell("请先选择一条识别记录。")
        elif self.history[row].kind != "command":
            self.tell("静音和未知结果不进行语音播报。")
        else:
            self.speak(self.history[row].text)

    def render_phrases(self):
        selected = self.phrase_table.currentRow()
        self.phrase_table.blockSignals(True)
        self.phrase_table.setRowCount(len(self.settings.phrases))
        for row, phrase in enumerate(self.settings.phrases):
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(Qt.CheckState.Checked if phrase.enabled else Qt.CheckState.Unchecked)
            self.phrase_table.setItem(row, 0, enabled)
            for col, value in ((1, phrase.text), (2, "手动设置" if phrase.tokens else "自动转换")):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip(phrase.text if col == 1 else phrase.tokens or "根据短语自动转换发音")
                self.phrase_table.setItem(row, col, item)
        self.phrase_table.blockSignals(False)
        if 0 <= selected < len(self.settings.phrases):
            self.phrase_table.selectRow(selected)
        enabled_count = sum(p.enabled for p in self.settings.phrases)
        self.phrase_count.setText(f"{enabled_count} / {len(self.settings.phrases)} 条启用")
        self.filter_phrases()

    def accept_phrase(self, phrase, index=None):
        if not self.require_editing():
            return
        old = deepcopy(self.settings.phrases)
        try:
            if index is None:
                self.settings.phrases.append(phrase)
            else:
                self.settings.phrases[index] = phrase
            self.persist()
            self.render_phrases()
            self.phrase_search.clear()
            selected = len(self.settings.phrases)-1 if index is None else index
            self.phrase_table.selectRow(selected)
            self.phrase_table.scrollToItem(self.phrase_table.item(selected, 1))
            self.apply_saved_settings("短语已保存。")
        except Exception as exc:
            self.settings.phrases = old
            self.render_phrases()
            self.tell(str(exc), True)

    def add_phrase(self):
        if not self.require_editing():
            return
        dialog = PhraseDialog(Phrase(""), self, self.validate_phrase_proposal)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.accept_phrase(dialog.phrase)

    def edit_phrase(self):
        if not self.require_editing():
            return
        index = self.phrase_table.currentRow()
        if index < 0:
            self.tell("请先选择一条短语。")
            return
        dialog = PhraseDialog(self.settings.phrases[index], self, lambda phrase: self.validate_phrase_proposal(phrase, index))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.accept_phrase(dialog.phrase, index)

    def validate_phrase_proposal(self, phrase, index=None):
        candidate = deepcopy(self.settings)
        if index is None:
            candidate.phrases.append(deepcopy(phrase))
        else:
            candidate.phrases[index] = deepcopy(phrase)
        candidate.validate()
        self.validate_keywords(candidate)

    def delete_phrase(self):
        if not self.require_editing():
            return
        index = self.phrase_table.currentRow()
        if index < 0:
            return
        old = deepcopy(self.settings.phrases)
        try:
            removed = self.settings.phrases.pop(index)
            self.persist()
            self.render_phrases()
            self.apply_saved_settings(f"已删除：{removed.text}。")
        except Exception as exc:
            self.settings.phrases = old
            self.render_phrases()
            self.tell(str(exc), True)

    def phrase_toggled(self, item):
        if item.column() != 0:
            return
        if not self.require_editing():
            self.render_phrases()
            return
        phrase = deepcopy(self.settings.phrases[item.row()])
        phrase.enabled = item.checkState() == Qt.CheckState.Checked
        self.accept_phrase(phrase, item.row())

    def check_keywords(self):
        try:
            _, mapping = compile_keywords(self.settings.phrases, ROOT / "models/custom")
            self.tell(f"{len(mapping)} 条启用短语的词元配置有效；没有运行模型或音频设备。")
        except Exception as exc:
            self.tell(str(exc), True)

    def import_phrases(self):
        if not self.require_editing():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "导入短语列表", str(ROOT), "JSON (*.json)")
        if not filename:
            return
        old = deepcopy(self.settings.phrases)
        try:
            path = Path(filename)
            if path.stat().st_size > 1_000_000:
                raise ValueError("导入文件过大")
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, list):
                raise ValueError("请导入由“导出短语”生成的 JSON 数组")
            self.settings.phrases = [Phrase(**row) for row in raw]
            self.persist()
            self.render_phrases()
            self.apply_saved_settings("短语列表已导入并保存。")
        except Exception as exc:
            self.settings.phrases = old
            self.render_phrases()
            self.tell(str(exc), True)

    def export_phrases(self):
        filename, _ = QFileDialog.getSaveFileName(self, "导出短语列表", str(ROOT / "phrases.json"), "JSON (*.json)")
        if filename:
            try:
                Path(filename).write_text(json.dumps([asdict(p) for p in self.settings.phrases], ensure_ascii=False, indent=2), encoding="utf-8")
                self.tell("短语列表已导出。")
            except Exception as exc:
                self.tell(str(exc), True)

    def export_history(self):
        if not self.history:
            self.tell("还没有识别记录，未生成测试结果。")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "导出本次会话记录", str(ROOT / "recognition.csv"), "CSV (*.csv)")
        if filename:
            try:
                with open(filename, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(asdict(self.history[0])))
                    writer.writeheader()
                    writer.writerows(asdict(event) for event in self.history)
                self.tell("会话记录已导出；其中不包含真实标签或准确率。")
            except Exception as exc:
                self.tell(str(exc), True)

    def clear_history(self):
        self.history.clear()
        self.history_table.setRowCount(0)
        self.result_text.setText("准备好，听你说")
        self.result_text.setStyleSheet("")
        self.result_hint.setText("记录已清空，下一条识别结果会显示在这里")
        self.result_engine.setText("等待识别")
        self.result_score.setText("—")
        self.result_time.setText("—")
        self.update_history_actions()

    def update_model_status(self):
        native = (ROOT / "build/phrase_lab_core.dll").is_file()
        custom = all((ROOT / "models/custom" / x).is_file() for x in
                     ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "en.phone"))
        if hasattr(self, "model_status"):
            set_badge(self.native_badge, "文件就绪" if native else "待构建", "green" if native else "amber")
            set_badge(self.custom_badge, "文件就绪" if custom else "待下载", "green" if custom else "amber")
            self.model_status.setText("文件就绪仅表示所需文件存在；准确率和响应延迟应以独立测试的统计结果为准。")

    def closeEvent(self, event):
        if self.recognizer is None and self.speaker is None:
            event.accept()
            return
        self.closing = True
        self.policy.shutdown()
        self.stop_all()
        self.centralWidget().setEnabled(False)
        self.tell("正在安全关闭后台任务；模型加载阶段可能需要稍等。")
        self.close_timer.start()
        event.ignore()

    def finish_close(self):
        if self.recognizer is None and self.speaker is None:
            self.close_timer.stop()
            self.close()
