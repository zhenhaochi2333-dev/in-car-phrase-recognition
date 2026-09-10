"""Both engines are lazy: construction happens only on explicit start."""
import ctypes
from time import perf_counter
import numpy as np
from .domain import LABELS, ROOT, RecognitionEvent, Settings
from .keywords import compile_keywords


class SegmentState:
    def __init__(self, threshold: float):
        self.threshold = threshold
        self.clear()

    def clear(self):
        self.voiced = 0
        self.quiet = 0
        self.active = False
        self.matched = False

    def update(self, pcm) -> bool:
        rms = float(np.sqrt(np.mean(np.square(pcm)))) if len(pcm) else 0.0
        if rms >= self.threshold:
            self.voiced += len(pcm)
            self.quiet = 0
            if self.voiced >= 1600:
                self.active = True
        elif self.active:
            self.quiet += len(pcm)
            if self.quiet >= 9600:
                return True
        else:
            self.voiced = 0
        return False


class ExperimentEngine:
    name = "BC-ResNet / 实验"

    def __init__(self, settings: Settings):
        path = ROOT / "build/phrase_lab_core.dll"
        if not path.is_file():
            raise ValueError("实验动态库尚未构建，请执行 scripts/build_native.py")
        self.lib = ctypes.CDLL(str(path))
        self.lib.lab_create.restype = ctypes.c_void_p
        self.lib.lab_destroy.argtypes = [ctypes.c_void_p]
        self.lib.lab_destroy.restype = None
        self.lib.lab_last_error.restype = ctypes.c_char_p
        self.lib.lab_predict.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        self.lib.lab_predict.restype = ctypes.c_int
        self.handle = self.lib.lab_create()
        if not self.handle:
            raise RuntimeError(self.lib.lab_last_error().decode("utf-8", errors="replace"))
        self.settings = settings
        self.segment = SegmentState(settings.rms_threshold)
        self.reset()

    def reset(self):
        self.buffer = np.zeros(16000, dtype=np.float32)
        self.filled = self.pending = self.stable = 0
        self.candidate = -1
        self.armed = True
        self.since_match = 16000
        self.last_command = -1
        self.segment.clear()

    def feed(self, pcm) -> list[RecognitionEvent]:
        result = []
        if not len(pcm):
            return result
        end = self.segment.update(pcm)
        n = len(pcm)
        self.since_match += n
        if n >= 16000:
            self.buffer[:] = pcm[-16000:]
        else:
            self.buffer[:-n] = self.buffer[n:]
            self.buffer[-n:] = pcm
        self.filled += n
        self.pending += n
        if self.filled >= 16000 and self.pending >= 1600:
            self.pending %= 1600
            logits, scores = np.empty(12, dtype=np.float64), np.empty(12, dtype=np.float64)
            start = perf_counter()
            status = self.lib.lab_predict(self.handle,
                self.buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 16000,
                logits.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                scores.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
            elapsed = (perf_counter() - start) * 1000
            if status:
                raise RuntimeError(self.lib.lab_last_error().decode("utf-8", errors="replace"))
            index = int(np.argmax(scores))
            eligible = index >= 2 and scores[index] >= self.settings.threshold and self.segment.active
            if eligible:
                self.stable = self.stable + 1 if self.candidate == index else 1
                self.candidate = index
                can_repeat = index != self.last_command or self.since_match >= 12000
                if self.stable >= 2 and can_repeat and (self.armed or index != self.last_command):
                    self.armed = False
                    self.last_command, self.since_match = index, 0
                    self.segment.matched = True
                    result.append(RecognitionEvent("command", LABELS[index], self.name, float(scores[index]), elapsed))
            else:
                self.stable = 0
                self.candidate = -1
                if index < 2:
                    self.armed = True
        if end:
            if not self.segment.matched:
                result.append(RecognitionEvent("unknown", "未知 / 未匹配到口令", self.name))
            self.segment.clear()
            self.armed = True
            self.stable, self.candidate = 0, -1
        return result

    def close(self):
        if self.handle:
            self.lib.lab_destroy(self.handle)
            self.handle = None


class CustomEngine:
    name = "Zipformer / 自定义"

    def __init__(self, settings: Settings):
        import sherpa_onnx
        directory = ROOT / "models/custom"
        for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "en.phone"):
            if not (directory / name).is_file():
                raise ValueError(f"缺少模型文件 {name}，请执行 scripts/download_model.py")
        content, self.mapping = compile_keywords(settings.phrases, directory)
        from .runtime_files import prepare_runtime_files
        directory, keyword_file = prepare_runtime_files(directory, content)
        try:
            self.model = sherpa_onnx.KeywordSpotter(
                tokens=str(directory / "tokens.txt"), encoder=str(directory / "encoder.onnx"),
                decoder=str(directory / "decoder.onnx"), joiner=str(directory / "joiner.onnx"),
                keywords_file=str(keyword_file), num_threads=2, provider="cpu",
                keywords_score=1.0, keywords_threshold=settings.custom_threshold,
                num_trailing_blanks=2)
        finally:
            keyword_file.unlink(missing_ok=True)
        self.segment = SegmentState(settings.rms_threshold)
        self.reset()

    def reset(self):
        self.stream = self.model.create_stream()
        self.segment.clear()
        self.since_match = 16000
        self.last_keyword = ""

    def feed(self, pcm) -> list[RecognitionEvent]:
        start = perf_counter()
        end = self.segment.update(pcm)
        self.since_match += len(pcm)
        self.stream.accept_waveform(16000, np.ascontiguousarray(pcm, dtype=np.float32))
        result = []
        while self.model.is_ready(self.stream):
            self.model.decode_stream(self.stream)
            key = self.model.get_result(self.stream)
            if key:
                self.model.reset_stream(self.stream)
                if key not in self.mapping:
                    raise RuntimeError(f"识别器返回未配置的短语 ID：{key}")
                if self.segment.active:
                    self.segment.matched = True
                if self.segment.active and (key != self.last_keyword or self.since_match >= 12000):
                    self.last_keyword, self.since_match = key, 0
                    result.append(RecognitionEvent("command", self.mapping[key], self.name,
                                                   processing_ms=(perf_counter()-start)*1000))
        if end:
            if not self.segment.matched:
                result.append(RecognitionEvent("unknown", "未知 / 未匹配到短语", self.name))
            self.reset()
        return result

    def close(self):
        self.stream = None
        self.model = None


def make_engine(settings: Settings):
    settings.validate()
    return ExperimentEngine(settings) if settings.mode == "experiment" else CustomEngine(settings)
