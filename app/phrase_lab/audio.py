"""Hardware adapters. No device is queried or opened at import time."""
import queue
import threading
import time
import numpy as np


class AudioPolicy:
    def __init__(self):
        self._lock = threading.RLock()
        self._allowed = True
        self._speaking = False
        self._until = 0.0

    @property
    def allowed(self):
        with self._lock:
            return self._allowed

    def shutdown(self):
        with self._lock:
            self._allowed = False

    def require(self):
        if not self.allowed:
            raise RuntimeError("应用正在关闭，不能启动新的音频任务")

    @property
    def suppressed(self):
        with self._lock:
            return self._speaking or time.monotonic() < self._until

    def begin_speech(self):
        with self._lock:
            self.require()
            self._speaking = True

    def end_speech(self):
        with self._lock:
            self._speaking = False
            self._until = time.monotonic() + 0.35


class Resampler:
    """Stateful low-pass + linear interpolation. Maintains a continuous sample clock."""
    def __init__(self, rate: float, target: int = 16000):
        self.rate, self.target = float(rate), target
        self.offset = 0
        self.next_position = 0.0
        self.previous = 0.0
        self.sos = self.zi = None
        if rate > target:
            from scipy.signal import butter
            self.sos = butter(10, target * 0.45, fs=rate, output="sos")
            self.zi = np.zeros((len(self.sos), 2))

    def feed(self, samples):
        x = np.asarray(samples, dtype=np.float64).reshape(-1)
        if not len(x):
            return np.empty(0, dtype=np.float32)
        if self.rate == self.target:
            return x.astype(np.float32)
        if self.sos is not None:
            from scipy.signal import sosfilt
            x, self.zi = sosfilt(self.sos, x, zi=self.zi)
        positions = np.arange(self.offset - 1, self.offset + len(x), dtype=np.float64)
        values = np.concatenate(([self.previous], x))
        step = self.rate / self.target
        count = max(0, int(np.floor((positions[-1]-self.next_position)/step)) + 1)
        dest = self.next_position + step * np.arange(count)
        result = np.interp(dest, positions, values).astype(np.float32)
        self.next_position += count * step
        self.offset += len(x)
        self.previous = float(x[-1])
        return result


def input_devices(policy: AudioPolicy):
    policy.require()
    import sounddevice as sd
    return [(index, str(device["name"])) for index, device in enumerate(sd.query_devices())
            if device["max_input_channels"] > 0]


class Microphone:
    def __init__(self, policy: AudioPolicy, device: int):
        self.policy, self.device = policy, device
        self.queue = queue.Queue(maxsize=50)
        self.stream = None
        self.overflow = threading.Event()

    def open(self):
        self.policy.require()
        import sounddevice as sd
        device = None if self.device == -1 else self.device
        info = sd.query_devices(device, "input")
        rate = 16000
        try:
            sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=rate)
        except sd.PortAudioError:
            rate = float(info["default_samplerate"])
        self.resampler = Resampler(rate)

        def callback(indata, frames, timing, status):
            if not self.policy.allowed or self.policy.suppressed:
                return
            if status:
                self.overflow.set()
            try:
                self.queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                self.overflow.set()

        self.policy.require()
        self.stream = sd.InputStream(device=device, samplerate=rate, channels=1, dtype="float32",
                                     blocksize=max(1, round(rate * 0.02)), callback=callback)
        try:
            self.policy.require()
            self.stream.start()
        except BaseException:
            self.stream.close()
            self.stream = None
            raise

    def read(self):
        pcm = self.resampler.feed(self.queue.get(timeout=0.1))
        if not np.all(np.isfinite(pcm)):
            raise RuntimeError("音频设备返回了非有限数值")
        return np.clip(pcm, -1.0, 1.0)

    def reset_resampler(self):
        self.resampler = Resampler(self.resampler.rate)

    def discard(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
                self.stream = None
        self.discard()
