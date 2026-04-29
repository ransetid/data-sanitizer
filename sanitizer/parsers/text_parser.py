"""
纯文本文件解析器
支持 .txt 格式
"""

from pathlib import Path

from sanitizer.engine import SanitizeEngine
from sanitizer.parsers.base import BaseParser
from sanitizer.utils import read_text_file, write_text_file


class TextParser(BaseParser):
    """
    纯文本文件解析器

    读取整个文件内容，通过引擎脱敏后写回
    自动检测文件编码
    """

    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() == ".txt"

    def sanitize(self, input_path: str, output_path: str, engine: SanitizeEngine) -> dict:
        engine.set_current_file(input_path)
        stats_before = dict(engine.stats)

        # 读取原始文件
        content = read_text_file(input_path)

        # 脱敏处理
        sanitized = engine.process_text(content)

        # 写出（统一输出为 UTF-8）
        write_text_file(output_path, sanitized)

        return {
            "entities_found": engine.stats["entities_found"] - stats_before["entities_found"],
            "entities_replaced": engine.stats["entities_replaced"] - stats_before["entities_replaced"],
        }
