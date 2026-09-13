"""Read and compile source text only; never import the application or run inference."""
from pathlib import Path
import ast
import hashlib
import importlib.metadata
import json
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    sources = (sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
               + sorted((ROOT / "tests").glob("*.py")))
    for path in sources:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")  # compile only; deliberately no exec() or import
    configs = list((ROOT / ".vscode").glob("*.json"))
    for path in configs:
        json.loads(path.read_text(encoding="utf-8"))
    icons = sorted((ROOT / "app/phrase_lab/assets").glob("*.svg"))
    for path in icons:
        ET.parse(path)
    dependencies = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = line.split(";")[0].strip()
        name, expected = requirement.split("==")
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise ValueError(f"Dependency version mismatch: {name} {actual} != {expected}")
        dependencies[name] = actual
    model_dir = ROOT / "models/custom"
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        raw = (model_dir / name).read_bytes()
        if len(raw) != info["bytes"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise ValueError(f"Model data does not match download manifest: {name}")
    provenance = json.loads((ROOT / "native/generated/provenance.json").read_text(encoding="utf-8"))
    source = ROOT / provenance["source"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != provenance["sha256"]:
        raise ValueError("Original course parameter file changed after header generation")
    build = json.loads((ROOT / "build/manifest.json").read_text(encoding="utf-8"))
    for name, digest in build["sources"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"C++ rebuild required: {name}")
    library = ROOT / "build/phrase_lab_core.dll"
    if hashlib.sha256(library.read_bytes()).hexdigest() != build["dll_sha256"]:
        raise ValueError("Compiled DLL changed after build")
    lines = ["# 静态检查记录", "", "本记录由 scripts/static_check.py 生成。本脚本不执行应用或模型；界面的离屏排版检查另见《05-界面设计与排版检查》。", "",
             f"- Python 源文件：{len(sources)} 个，AST 解析及源码编译通过。",
             f"- VS Code JSON 配置：{len(configs)} 个，语法解析通过。",
             f"- SVG 控件图标：{len(icons)} 个，XML 语法解析通过。",
             "- C++ 核心：构建清单与当前源码、派生权重及 DLL 哈希一致。",
             f"- 自定义模型文件：{len(manifest['files'])} 个，尺寸和下载后记录的 SHA-256 一致。",
             "- 原始课程 table.c：与提取参数时的 SHA-256 一致。",
             "- 依赖版本：与 requirements.txt 一致。", "", "## 依赖版本", ""]
    lines += [f"- {name} {version}" for name, version in dependencies.items()]
    lines += ["", "## 本静态检查脚本不执行的操作", "", "实际已完成的联调与功能检查另见《06-实机与交互验证》，以下仅描述本脚本范围。", "", "- 可见桌面窗口的交互与业务功能验证。", "- 动态库加载、特征计算、模型推理和音频文件识别。",
              "- 麦克风、声卡设备查询与采集。", "- TTS 合成、扬声器播放及声音通知。",
              "- 正确率、混淆矩阵、延迟、抗噪及回声互锁的功能验证。", "",
              "本记录不能用作功能或性能验收结论。下载后的哈希记录用于本地完整性检查，不是独立的上游签名验证。", ""]
    with (ROOT / "docs/04-静态检查记录.md").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
    print(f"Static checks passed: {len(sources)} Python sources, {len(configs)} configs, model/build provenance.")
    print("Application, inference, audio devices and TTS were NOT executed.")


if __name__ == "__main__":
    main()
