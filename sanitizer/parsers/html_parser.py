"""
HTML 文件解析器
支持 .html, .htm 格式
"""

from pathlib import Path

from sanitizer.engine import SanitizeEngine
from sanitizer.parsers.base import BaseParser
from sanitizer.utils import read_text_file, write_text_file


class HtmlParser(BaseParser):
    """
    HTML 文件解析器

    使用 BeautifulSoup 解析 HTML：
    - 遍历所有文本节点（NavigableString）
    - 对文本内容调用引擎脱敏
    - 保留 DOM 结构和 HTML 属性不变
    """

    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in {".html", ".htm"}

    def sanitize(self, input_path: str, output_path: str, engine: SanitizeEngine) -> dict:
        from bs4 import BeautifulSoup, NavigableString

        engine.set_current_file(input_path)
        stats_before = dict(engine.stats)

        # 读取原始文件
        content = read_text_file(input_path)

        # 解析 HTML
        soup = BeautifulSoup(content, "html.parser")

        # 遍历所有文本节点
        # 跳过 script 和 style 标签内的内容
        skip_tags = {"script", "style", "code", "pre"}

        for text_node in soup.find_all(string=True):
            if not isinstance(text_node, NavigableString):
                continue

            # 跳过特定标签内的文本
            if text_node.parent and text_node.parent.name in skip_tags:
                continue

            original = str(text_node)
            if not original.strip():
                continue

            sanitized = engine.process_text(original)
            if sanitized != original:
                text_node.replace_with(NavigableString(sanitized))

        # 写出
        write_text_file(output_path, str(soup))

        return {
            "entities_found": engine.stats["entities_found"] - stats_before["entities_found"],
            "entities_replaced": engine.stats["entities_replaced"] - stats_before["entities_replaced"],
        }
