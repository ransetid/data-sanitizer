# -*- mode: python ; coding: utf-8 -*-
"""
DataSanitizer PyInstaller 打包配置

用法：
  pyinstaller DataSanitizer.spec

构建产物：
  macOS → dist/DataSanitizer.app
  Windows → dist/DataSanitizer/DataSanitizer.exe  (或 dist/DataSanitizer.exe)
"""

import sys
from pathlib import Path

# ─── 路径 ──────────────────────────────────────────────────────────────────
HERE = Path(SPECPATH)           # data-sanitizer/
ENTRY = str(HERE / "run.py")

# ─── 数据文件 ──────────────────────────────────────────────────────────────
# (源文件, 打包后目标目录)  目标目录 "." 表示放在 _MEIPASS 根
datas = [
    (str(HERE / "keywords.txt"), "."),
]

# ─── 隐式导入（lazy import 的包 PyInstaller 无法自动探测）──────────────────
hidden_imports = [
    # Excel
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    "openpyxl.workbook",
    "xlrd",
    # Word
    "docx",
    "docx.oxml",
    "docx.shared",
    # PDF
    "fitz",           # PyMuPDF
    # HTML
    "bs4",
    "bs4.builder._lxml",
    "bs4.builder._html5lib",
    # 编码检测
    "chardet",
    # 标准库（部分打包环境需要显式声明）
    "sqlite3",
    "csv",
    "xml.etree.ElementTree",
    "zipfile",
    "io",
    # calamine（try/except 懒加载，静态分析检测不到，需手动声明）
    "python_calamine",
]

# ─── 整包收集（含所有子模块和数据）────────────────────────────────────────
from PyInstaller.utils.hooks import collect_all, collect_data_files

binaries_all = []
datas_all = list(datas)

# python_calamine 是 Rust 扩展，用 collect_all 确保 .so 二进制也被收集
for pkg in ["fitz", "openpyxl", "docx", "python_calamine"]:
    try:
        d, b, h = collect_all(pkg)
        datas_all += d
        binaries_all += b
        hidden_imports += h
    except Exception:
        pass  # 未安装则跳过，工具会自动降级到下一个方案

# ─── 分析 ──────────────────────────────────────────────────────────────────
a = Analysis(
    [ENTRY],
    pathex=[str(HERE)],
    binaries=binaries_all,
    datas=datas_all,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大包，减小体积
        "matplotlib", "numpy", "pandas", "PIL",
        "scipy", "sklearn", "torch", "tensorflow",
        "IPython", "jupyter",
        "PyQt5", "PyQt6", "wx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ─── 平台差异化 ────────────────────────────────────────────────────────────
if sys.platform == "darwin":
    # macOS: 生成 .app bundle
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DataSanitizer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,          # 不显示终端窗口
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="DataSanitizer",
    )
    app = BUNDLE(
        coll,
        name="DataSanitizer.app",
        icon=None,              # None = 使用 PyInstaller 默认图标；替换为 "icon.icns" 可自定义
        bundle_identifier="com.datasanitizer.app",
        info_plist={
            "CFBundleDisplayName": "数据脱敏工具",
            "CFBundleShortVersionString": "1.2.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )

else:
    # Windows: 生成单目录 + 单文件 EXE
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="DataSanitizer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,          # 不显示 cmd 窗口
        disable_windowed_traceback=False,
        argv_emulation=False,
        icon=None,              # 替换为 .ico 文件路径即可加图标
        version=None,
    )
