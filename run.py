#!/usr/bin/env python3
"""
财务数据脱敏工具 - 启动入口
运行此脚本启动 GUI 界面
"""

import warnings
# 过滤 openpyxl 透视缓存关系文件的 UserWarning（不影响功能，仅减少终端噪音）
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from sanitizer.app import SanitizerApp


def main():
    app = SanitizerApp()
    app.run()


if __name__ == "__main__":
    main()
