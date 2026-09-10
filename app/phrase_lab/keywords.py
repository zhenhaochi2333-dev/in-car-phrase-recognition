"""Configuration preparation only: no inference or audio side effects."""
from pathlib import Path
import re
from .domain import Phrase


def compile_keywords(phrases: list[Phrase], model_dir: Path) -> tuple[str, dict[str, str]]:
    from sherpa_onnx.utils import text2token

    tokens_path, lexicon_path = model_dir / "tokens.txt", model_dir / "en.phone"
    if not tokens_path.exists() or not lexicon_path.exists():
        raise ValueError("缺少关键词模型词表，请运行 scripts/download_model.py")
    vocabulary = {line.rsplit(maxsplit=1)[0] for line in tokens_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    lexicon = {line.split()[0] for line in lexicon_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    lines, mapping, sequences = [], {}, {}
    for phrase in phrases:
        phrase.validate()
        if not phrase.enabled:
            continue
        if phrase.tokens.strip():
            sequence = phrase.tokens.split()
        else:
            # Separate Chinese runs and English words, retaining whole Chinese phrases for polyphones.
            pieces = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+(?:'[A-Za-z]+)*", phrase.text)
            words = []
            for piece in pieces:
                if re.fullmatch(r"[A-Za-z']+", piece):
                    match = next((x for x in (piece.upper(), piece.lower(), piece) if x in lexicon), None)
                    if match is None:
                        raise ValueError(f"英文词典不包含 {piece}；请换词或填写高级音素")
                    words.append(match)
                else:
                    words.append(piece)
            converted = text2token([" ".join(words)], str(tokens_path), tokens_type="phone+ppinyin",
                                   lexicon=str(lexicon_path))
            if len(converted) != 1:
                raise ValueError(f"无法转换短语：{phrase.text}，可填写高级词元修正读音")
            sequence = converted[0]
        invalid = [x for x in sequence if x not in vocabulary or x.startswith("<")]
        if not sequence or invalid:
            raise ValueError(f"{phrase.text} 存在模型不支持的词元：{' '.join(invalid)}")
        key = tuple(sequence)
        if key in sequences:
            raise ValueError(f"{phrase.text} 与 {sequences[key]} 发音词元相同，请只启用其中一个")
        sequences[key] = phrase.text
        lines.append(" ".join(sequence) + f" @{phrase.id}")
        mapping[phrase.id] = phrase.text
    if not lines:
        raise ValueError("至少需要启用一条自定义短语")
    return "\n".join(lines) + "\n", mapping
