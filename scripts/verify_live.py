"""Opt-in acoustic hardware verification. Opens the GUI, microphone and speakers.

Synthesized test phrases travel through the physical speaker and microphone.
Only result/state metadata is saved. This is not a human accuracy benchmark.
The application remains open and listening after the selected test phrases.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--input-volume", type=int, default=70)
    parser.add_argument("--manual", action="store_true", help="Open and listen for human speech; do not play test inputs")
    parser.add_argument("--page", choices=("workbench", "phrases", "settings"), default="workbench")
    parser.add_argument("--mode", choices=("experiment", "custom"), help="Use this recognition mode; otherwise keep the saved mode")
    args = parser.parse_args()
    if not 0 <= args.input_volume <= 100:
        parser.error("input volume must be in 0..100")
    sys.path.insert(0, str(ROOT / "app"))
    import sounddevice as sd
    from PySide6.QtCore import QObject, QTimer, Slot
    from PySide6.QtWidgets import QApplication
    from phrase_lab.appearance import configure_application
    from phrase_lab.audio import AudioPolicy
    from phrase_lab.domain import Settings
    from phrase_lab.ui import MainWindow
    from phrase_lab.workers import SpeechWorker

    info = sd.query_devices(args.device, "input")
    if not any(word in info["name"].casefold() for word in ("microphone", "mic ", "麦克风")):
        raise RuntimeError("Select the actual microphone array, not Stereo Mix or a loopback input")
    settings = Settings.load(ROOT / "data/settings.json")
    settings.input_device = args.device
    if args.mode is not None:
        settings.mode = args.mode
    settings.save(ROOT / "data/settings.json")
    output = ROOT / "exports"
    output.mkdir(exist_ok=True)
    log_path = output / f"hardware-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    app = QApplication(sys.argv[:1])
    configure_application(app)
    window = MainWindow()
    area = app.primaryScreen().availableGeometry()
    window.resize(min(1320, area.width()-48), min(900, area.height()-64))
    window.navigate(("workbench", "phrases", "settings").index(args.page))
    window.show()

    class Verification(QObject):
        def __init__(self):
            super().__init__(window)
            self.started = time.perf_counter()
            self.source = None
            self.inputs = (["yes", "stop", "left"] if settings.mode == "experiment" else
                           [phrase.text for phrase in settings.phrases if phrase.enabled][:3])
            self.index = 0
            self.ready = False
            self.done = False
            self.matches = []
            self.errors = []
            self.peak_level = 0.0
            self.observed_speaker = None
            self.observed_recognizer = None
            self.active_input = None
            self.log("environment", microphone=dict(info), default_devices=list(sd.default.device),
                     input_volume=args.input_volume, result_speech_volume=settings.volume, manual=args.manual)
            self.poll = QTimer(self)
            self.poll.setInterval(100)
            self.poll.timeout.connect(self.observe)

        def log(self, event, **fields):
            record = {"elapsed_s": round(time.perf_counter()-self.started, 3), "event": event, **fields}
            line = json.dumps(record, ensure_ascii=False)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            print(line, flush=True)

        def start(self):
            window.refresh_devices()
            window.autospeak.setChecked(True)
            window.start_listening()
            if window.recognizer is None:
                self.log("startup_failure", message=window.message.text())
                self.done = True
                return
            self.attach_recognizer()
            self.poll.start()
            QTimer.singleShot(20000, self.check_startup)

        def attach_recognizer(self):
            worker = window.recognizer
            if worker is not None and worker is not self.observed_recognizer:
                self.observed_recognizer = worker
                worker.event.connect(self.on_result)
                worker.state.connect(self.on_state)
                worker.error.connect(self.on_error)
                worker.level.connect(self.on_level)
                self.log("recognizer_session_started", mode=worker.settings.mode,
                         enabled_phrases=[p.text for p in worker.settings.phrases if p.enabled])

        @Slot(str)
        def on_state(self, state):
            if not self.ready and state == "正在监听":
                self.ready = True
                self.log("microphone_listening")
                window.tell("麦克风已连接。请说出短语，识别成功后会合成播报。")
                if not args.manual:
                    QTimer.singleShot(1200, self.next_input)
            if state in ("正在播报 / 等待余音结束", "已停止监听"):
                self.log("recognition_state", state=state)

        @Slot(float)
        def on_level(self, rms):
            self.peak_level = max(self.peak_level, rms)

        @Slot(str)
        def on_error(self, message):
            self.errors.append(message)
            self.log("error", message=message)

        @Slot(object)
        def on_result(self, result):
            if self.done:
                return
            if result.kind == "command":
                self.matches.append({"expected": self.active_input, "actual": result.text})
            self.log("recognition_result", expected=self.active_input, result=asdict(result))

        def next_input(self):
            if self.done or window.closing or not window.active() or window.recognizer.cancelled.is_set():
                self.log("verification_cancelled")
                self.done = True
                self.poll.stop()
                return
            if self.index >= len(self.inputs):
                self.finish()
                return
            if window.speaker is not None or window.policy.suppressed:
                QTimer.singleShot(500, self.next_input)
                return
            self.active_input = self.inputs[self.index]
            self.log("acoustic_input_start", phrase=self.active_input)
            self.source = SpeechWorker(AudioPolicy(), self.active_input, args.input_volume, 0, window)
            self.source.error.connect(self.on_error)
            self.source.finished.connect(self.input_finished)
            self.source.start()

        @Slot()
        def input_finished(self):
            source, self.source = self.source, None
            if source is not None:
                source.deleteLater()
            self.log("acoustic_input_finished", phrase=self.active_input)
            self.index += 1
            QTimer.singleShot(6000, self.next_input)

        def observe(self):
            self.attach_recognizer()
            if window.speaker is not None and window.speaker is not self.observed_speaker:
                self.observed_speaker = window.speaker
                self.log("result_speech_started", text=window.speaker.text)
                window.speaker.error.connect(self.on_error)
                window.speaker.finished.connect(self.result_speech_finished)
            if window.closing and self.source is not None:
                self.source.stop()
            if not args.manual and not self.done and self.ready and not window.active():
                self.log("recognition_stopped_before_completion")
                self.done = True
                self.poll.stop()

        @Slot()
        def result_speech_finished(self):
            self.log("result_speech_finished")

        def check_startup(self):
            if not self.ready and not self.done:
                self.log("startup_timeout", message=window.message.text())
                self.done = True
                self.poll.stop()

        def finish(self):
            self.done = True
            self.poll.stop()
            matched = {x["expected"] for x in self.matches if x["actual"] == x["expected"]}
            self.log("summary", input_phrases=self.inputs, matched_phrases=sorted(matched),
                     microphone_peak_rms=self.peak_level, errors=self.errors,
                     note="Synthetic acoustic smoke test only; not human accuracy or latency benchmark")
            window.tell(f"硬件验证：{len(matched)}/{len(self.inputs)} 条合成口令命中。当前继续监听，可直接说话测试。")

    verification = Verification()
    QTimer.singleShot(300, verification.start)
    print(f"Hardware verification log: {log_path}", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
