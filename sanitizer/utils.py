"""
工具函数模块
提供文件遍历、编码检测、路径计算等通用功能
"""

import os
from pathlib import Path
from typing import Optional

import chardet

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".xlsx", ".xls", ".csv", ".tsv",
    ".txt",
    ".docx",
    ".pdf",
    ".html", ".htm",
}

# 文件类型分组（用于统计显示）
FILE_TYPE_GROUPS = {
    "Excel": {".xlsx", ".xls"},
    "CSV/TSV": {".csv", ".tsv"},
    "Word": {".docx"},
    "PDF": {".pdf"},
    "文本": {".txt"},
    "HTML": {".html", ".htm"},
}


def scan_folder(folder_path: str) -> list[dict]:
    """
    递归扫描文件夹，返回支持的文件列表

    返回值格式：
    [
        {
            "path": "/absolute/path/to/file.xlsx",
            "relative": "subfolder/file.xlsx",
            "extension": ".xlsx",
            "size": 12345,
        },
        ...
    ]
    """
    folder = Path(folder_path)
    files = []

    for root, _dirs, filenames in os.walk(folder):
        # 跳过隐藏文件夹
        root_path = Path(root)
        if any(part.startswith(".") for part in root_path.parts):
            continue

        for filename in filenames:
            # 跳过隐藏文件和临时文件
            if filename.startswith(".") or filename.startswith("~$"):
                continue

            file_path = root_path / filename
            ext = file_path.suffix.lower()

            if ext in SUPPORTED_EXTENSIONS:
                files.append({
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(folder)),
                    "extension": ext,
                    "size": file_path.stat().st_size,
                })

    # 按相对路径排序，方便查看
    files.sort(key=lambda f: f["relative"])
    return files


def get_file_type_stats(files: list[dict]) -> dict[str, int]:
    """
    统计文件类型分布

    返回值格式：{"Excel": 5, "PDF": 3, ...}
    """
    stats = {}
    for file_info in files:
        ext = file_info["extension"]
        for group_name, extensions in FILE_TYPE_GROUPS.items():
            if ext in extensions:
                stats[group_name] = stats.get(group_name, 0) + 1
                break
    return stats


def get_output_folder(source_folder: str) -> str:
    """
    计算输出文件夹路径：与源文件夹同级的 {name}_脱敏 目录

    例：/data/financial_reports -> /data/financial_reports_脱敏
    """
    source = Path(source_folder)
    output_name = f"{source.name}_脱敏"
    return str(source.parent / output_name)


def ensure_output_structure(source_folder: str, output_folder: str):
    """
    在输出目录中创建与源目录一致的子文件夹结构
    """
    source = Path(source_folder)
    output = Path(output_folder)

    # 创建输出根目录
    output.mkdir(parents=True, exist_ok=True)

    # 遍历源目录的所有子目录，在输出目录中创建对应结构
    for root, dirs, _files in os.walk(source):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        root_path = Path(root)
        relative = root_path.relative_to(source)
        target_dir = output / relative
        target_dir.mkdir(parents=True, exist_ok=True)


def compute_output_path(
    source_file: str,
    source_folder: str,
    output_folder: str,
    engine=None,
) -> str:
    """
    计算单个文件的输出路径，保持目录结构

    对于 .xls 文件，输出扩展名改为 .xlsx
    如果提供了 engine，会对文件名和文件夹名进行脱敏
    """
    source = Path(source_file)
    relative = source.relative_to(source_folder)

    if engine:
        # 对路径中每一段（文件夹名 + 文件名）进行脱敏
        parts = list(relative.parts)
        sanitized_parts = []
        for part in parts:
            # 分离文件名和扩展名（仅最后一段）
            if part == parts[-1]:
                stem = Path(part).stem
                ext = Path(part).suffix
                sanitized_stem = engine.process_text(stem)
                sanitized_parts.append(f"{sanitized_stem}{ext}")
            else:
                sanitized_parts.append(engine.process_text(part))
        relative = Path(*sanitized_parts)

    output_path = Path(output_folder) / relative

    # xls 输出为 xlsx
    if output_path.suffix.lower() == ".xls":
        output_path = output_path.with_suffix(".xlsx")

    return str(output_path)


def detect_encoding(file_path: str) -> str:
    """
    检测文件编码，返回编码名称

    使用 chardet 库检测，如果检测失败则默认返回 utf-8
    """
    with open(file_path, "rb") as f:
        raw = f.read(10000)  # 读取前 10KB 用于检测
    result = chardet.detect(raw)
    encoding = result.get("encoding", "utf-8")
    confidence = result.get("confidence", 0)

    # 如果置信度太低，使用 utf-8
    if confidence < 0.5 or encoding is None:
        return "utf-8"

    return encoding


def read_text_file(file_path: str, encoding: Optional[str] = None) -> str:
    """
    读取文本文件，自动检测编码

    如果指定了 encoding 则使用指定编码，否则自动检测
    """
    if encoding is None:
        encoding = detect_encoding(file_path)

    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            return f.read()
    except UnicodeDecodeError:
        # 回退到 utf-8 + replace
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def write_text_file(file_path: str, content: str, encoding: str = "utf-8"):
    """写入文本文件"""
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding=encoding) as f:
        f.write(content)
