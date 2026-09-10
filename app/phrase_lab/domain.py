from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
import json
import os
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
LABELS = ("_silence_", "_unknown_", "down", "go", "left", "no", "off", "on", "right", "stop", "up", "yes")
DISPLAY = {"_silence_": "静音", "_unknown_": "未知 / 未匹配到口令"}


@dataclass
class Phrase:
    text: str
    id: str = field(default_factory=lambda: "p" + uuid.uuid4().hex[:12])
    enabled: bool = True
    tokens: str = ""

    def validate(self):
        if not isinstance(self.text, str) or not isinstance(self.id, str):
            raise ValueError("短语文字和 ID 必须为字符串")
        self.text = " ".join(self.text.split())
        if not 1 <= len(self.text) <= 60:
            raise ValueError("短语长度需要在 1—60 个字符之间")
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z ']+", self.text):
            raise ValueError("短语只支持普通汉字、英文字母、空格和英文撇号")
        if not re.search(r"[\u4e00-\u9fffA-Za-z]", self.text):
            raise ValueError("短语至少包含一个汉字或英文字母")
        if not re.fullmatch(r"p[0-9a-f]{12}", self.id):
            raise ValueError("短语 ID 格式不正确")
        if not isinstance(self.enabled, bool) or not isinstance(self.tokens, str):
            raise ValueError("短语配置字段类型不正确")
        if len(self.tokens) > 2000 or any(c in self.tokens for c in "@#:/\r\n"):
            raise ValueError("高级词元不能包含 @ # : / 或换行")


@dataclass
class Settings:
    version: int = 1
    mode: str = "experiment"
    input_device: int = -1
    volume: int = 70
    rate: int = 0
    threshold: float = 0.70
    custom_threshold: float = 0.25
    rms_threshold: float = 0.004
    phrases: list[Phrase] = field(default_factory=lambda: [Phrase(text=x) for x in LABELS[2:]])

    def validate(self):
        if type(self.version) is not int or self.version != 1 or self.mode not in ("experiment", "custom"):
            raise ValueError("不支持的配置版本或识别模式")
        if type(self.input_device) is not int or self.input_device < -1:
            raise ValueError("输入设备索引不正确")
        if type(self.volume) is not int or type(self.rate) is not int:
            raise ValueError("音量和语速必须为整数")
        for name, value, lo, hi in (("音量", self.volume, 0, 100), ("语速", self.rate, -5, 5),
                                   ("实验阈值", self.threshold, 0.05, 0.99),
                                   ("自定义阈值", self.custom_threshold, 0.05, 0.99),
                                   ("有声阈值", self.rms_threshold, 0.0001, 0.2)):
            if type(value) not in (int, float) or not lo <= value <= hi:
                raise ValueError(f"{name}需要在 {lo}—{hi} 之间")
        if not isinstance(self.phrases, list) or not 0 <= len(self.phrases) <= 100:
            raise ValueError("最多保存 100 条短语")
        ids, texts = set(), set()
        for phrase in self.phrases:
            phrase.validate()
            if phrase.id in ids or phrase.text.casefold() in texts:
                raise ValueError(f"短语重复：{phrase.text}")
            ids.add(phrase.id)
            texts.add(phrase.text.casefold())

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls()
        if path.stat().st_size > 1_000_000:
            raise ValueError("设置文件过大")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("设置文件必须为 JSON 对象")
        # Automatic speech is a session choice, deliberately never loaded.
        allowed = {x for x in cls.__dataclass_fields__ if x != "phrases"}
        obj = cls(**{k: v for k, v in raw.items() if k in allowed})
        if "phrases" in raw:
            if not isinstance(raw["phrases"], list):
                raise ValueError("短语列表必须为 JSON 数组")
            obj.phrases = [Phrase(**x) for x in raw["phrases"]]
        obj.validate()
        return obj

    def save(self, path: Path):
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


@dataclass
class RecognitionEvent:
    kind: str
    text: str
    engine: str
    score: float | None = None
    processing_ms: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="milliseconds"))
