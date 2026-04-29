"""
文件解析器模块
支持的文件类型：Excel (.xlsx/.xls/.csv), Word (.docx), PDF, TXT, HTML
"""

from sanitizer.parsers.excel_parser import ExcelParser
from sanitizer.parsers.word_parser import WordParser
from sanitizer.parsers.pdf_parser import PdfParser
from sanitizer.parsers.text_parser import TextParser
from sanitizer.parsers.html_parser import HtmlParser

# 所有可用的解析器，按优先级排列
ALL_PARSERS = [
    ExcelParser(),
    WordParser(),
    PdfParser(),
    TextParser(),
    HtmlParser(),
]


def get_parser_for_file(file_path: str):
    """根据文件路径获取合适的解析器"""
    for parser in ALL_PARSERS:
        if parser.can_handle(file_path):
            return parser
    return None
