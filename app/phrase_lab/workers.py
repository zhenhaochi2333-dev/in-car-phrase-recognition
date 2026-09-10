"""Workers are started only by explicit user actions; no auto-start or audio import."""
import queue
import re
import threading
import time
from PySide6.QtCore import QThread, Signal
from .audio import AudioPolicy, Microphone
from .domain import Settings


class RecognitionWorker(QThread):
    event = Signal(object)
    state = Signal(str)
    level = Signal(float)
    error = Signal(str)

    def __init__(self, policy: AudioPolicy, settings: Settings, parent=None):
        super().__init__(parent)
        self.policy, self.settings = policy, settings
        self.cancelled = threading.Event()

    def stop(self):
        self.cancelled.set()

    def run(self):
        from .engines import make_engine
        import numpy as np
        microphone = engine = None
        try:
            self.policy.require()
            self.state.emit("正在加载识别模型…")
            engine = make_engine(self.settings)
            if self.cancelled.is_set():
                return
            self.policy.require()
            microphone = Microphone(self.policy, self.settings.input_device)
            microphone.open()
            self.state.emit("正在监听")
            suspended, last_status, last_received = False, 0.0, time.monotonic()
            while not self.cancelled.is_set() and self.policy.allowed:
                if self.policy.suppressed:
                    microphone.discard()
                    if not suspended:
                        suspended = True
                        self.state.emit("正在播报 / 等待余音结束")
                    self.cancelled.wait(0.03)
                    last_received = time.monotonic()
                    continue
                if suspended:
                    microphone.discard()
                    microphone.reset_resampler()
                    engine.reset()
                    suspended = False
                    self.state.emit("正在监听")
                if microphone.overflow.is_set():
                    microphone.discard()
                    microphone.reset_resampler()
                    engine.reset()
                    microphone.overflow.clear()
                    self.state.emit("输入积压已清理，识别状态已重置")
                try:
                    pcm = microphone.read()
                except queue.Empty:
                    if time.monotonic() - last_received > 5:
                        raise RuntimeError("5 秒未收到音频，请检查麦克风连接与系统权限")
                    continue
                last_received = time.monotonic()
                if not len(pcm) or self.policy.suppressed or self.cancelled.is_set():
                    continue
                rms = float(np.sqrt(np.mean(pcm * pcm)))
                if time.monotonic()-last_status > 0.15:
                    self.level.emit(rms)
                    self.state.emit("检测到声音" if rms >= self.settings.rms_threshold else "静音 / 等待短语")
                    last_status = time.monotonic()
                for event in engine.feed(pcm):
                    if not self.policy.suppressed and not self.cancelled.is_set() and self.policy.allowed:
                        self.event.emit(event)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if microphone is not None:
                try:
                    microphone.close()
                except Exception as exc:
                    self.error.emit(f"关闭麦克风时发生错误：{exc}")
            if engine is not None:
                try:
                    engine.close()
                except Exception as exc:
                    self.error.emit(f"关闭识别引擎时发生错误：{exc}")
            self.level.emit(0.0)
            self.state.emit("已停止监听")


class SpeechWorker(QThread):
    state = Signal(str)
    error = Signal(str)

    def __init__(self, policy: AudioPolicy, text: str, volume: int, rate: int, parent=None):
        super().__init__(parent)
        self.policy, self.text, self.volume, self.rate = policy, text, volume, rate
        self.cancelled = threading.Event()

    def stop(self):
        self.cancelled.set()

    def run(self):
        initialized = False
        voice = selected = token = None
        try:
            self.policy.require()
            if self.cancelled.is_set():
                return
            import pythoncom
            from win32com.client import Dispatch
            pythoncom.CoInitialize()
            initialized = True
            voice = Dispatch("SAPI.SpVoice")
            chinese = bool(re.search(r"[\u4e00-\u9fff]", self.text))
            for token in voice.GetVoices():
                langs = token.GetAttribute("Language").lower().split(";")
                if ("804" if chinese else "409") in langs:
                    selected = token
                    break
            if selected is None:
                raise RuntimeError("找不到可用的中文系统声音" if chinese else "找不到可用的英文系统声音")
            voice.Voice = selected
            voice.Volume, voice.Rate = self.volume, self.rate
            self.policy.require()
            if self.cancelled.is_set():
                return
            self.state.emit("正在合成播报；请等播完后再说下一句")
            # SVSFlagsAsync | SVSFIsNotXML: text cannot be interpreted as SAPI XML.
            voice.Speak(self.text, 1 | 16)
            while not voice.WaitUntilDone(20):
                if self.cancelled.is_set() or not self.policy.allowed:
                    voice.Speak("", 1 | 2 | 16)
                    break
        except Exception as exc:
            if not self.cancelled.is_set():
                self.error.emit(f"播报失败：{exc}")
        finally:
            # Release every retained COM object before uninitializing this thread.
            selected = token = voice = None
            if initialized:
                pythoncom.CoUninitialize()
            self.policy.end_speech()
            self.state.emit("播报结束")
