"""
PDF 文件解析器
使用 PyMuPDF (fitz) 进行文本提取和 redaction
"""

import logging
from pathlib import Path

from sanitizer.engine import SanitizeEngine
from sanitizer.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PdfParser(BaseParser):
    """
    PDF 文件解析器

    使用 PyMuPDF 的 redaction 功能：
    1. 遍历每页的文本 span
    2. 对每个文本调用引擎检测敏感信息
    3. 对命中的区域添加 redact annotation（遮盖）并写入替换文本
    4. 应用所有 redaction
    """

    def can_handle(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() == ".pdf"

    def sanitize(self, input_path: str, output_path: str, engine: SanitizeEngine) -> dict:
        import fitz  # PyMuPDF

        engine.set_current_file(input_path)
        stats_before = dict(engine.stats)

        doc = fitz.open(input_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            self._process_page(page, engine)

        # 保存
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_path)
        doc.close()

        return {
            "entities_found": engine.stats["entities_found"] - stats_before["entities_found"],
            "entities_replaced": engine.stats["entities_replaced"] - stats_before["entities_replaced"],
        }

    @staticmethod
    def _process_page(page, engine: SanitizeEngine):
        """
        处理单个 PDF 页面

        获取页面的文本字典，遍历每个 text block 中的每个 span，
        检测敏感信息并用 redaction annotation 替换
        """
        import fitz

        # 获取页面文本信息（按 block -> line -> span 层级组织）
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        has_redactions = False

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 只处理文本 block
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    original_text = span.get("text", "")
                    if not original_text or not original_text.strip():
                        continue

                    # 调用引擎处理
                    sanitized_text = engine.process_text(original_text)

                    # 如果文本发生了变化，添加 redaction
                    if sanitized_text != original_text:
                        bbox = fitz.Rect(span["bbox"])
                        font_size = span.get("size", 11)

                        # 添加 redaction annotation
                        page.add_redact_annot(
                            bbox,
                            text=sanitized_text,
                            fontsize=font_size,
                            fill=(1, 1, 1),  # 白色填充背景
                        )
                        has_redactions = True

        # 应用所有 redaction
        if has_redactions:
            page.apply_redactions()
