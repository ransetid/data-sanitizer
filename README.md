# 财务数据脱敏工具 DataSanitizer

将文件夹中的财务文件进行批量脱敏处理，自动识别并替换敏感信息（公司名、人名、银行账号、电话等），输出到指定目录。

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

## 支持的文件格式

| 格式 | 扩展名 | 处理方式 |
| --- | --- | --- |
| Excel | `.xlsx`, `.xls` | openpyxl / xlrd / calamine，保留样式和 Sheet 结构 |
| CSV | `.csv`, `.tsv` | csv 模块，自动检测编码 |
| Word | `.docx` | python-docx，保留格式 |
| PDF | `.pdf` | PyMuPDF redaction |
| 文本 | `.txt` | 全文替换 |
| HTML | `.html`, `.htm` | BeautifulSoup，保留 DOM 结构 |

## 脱敏策略

**三层检测架构：**

```
文本输入
  │
  ▼
┌────────────────────────────────────┐
│ L0 - 自定义关键词匹配（最高优先级）│  ← 用户维护的关键词库
│ 按长度从长到短匹配，避免短词截断长词 │
└────────────────────────────────────┘
  │
  ▼
┌────────────────────────────────────┐
│ L1 - 正则匹配                      │  ← 银行账号、SWIFT、邮箱、
│ 预定义规则匹配结构化数据             │     电话、身份证、信用卡、税务号
└────────────────────────────────────┘
  │
  ▼
┌────────────────────────────────────┐
│ L2 - 本地 LLM NER（可选兜底）      │  ← 识别 L0/L1 漏掉的实体
│ 支持 Ollama / OMLX / LM Studio    │     可关闭，仅用正则
└────────────────────────────────────┘
```

**替换规则：**

| 实体类型 | 替换格式 | 示例 |
| --- | --- | --- |
| 公司名 | `Company_A`, `Company_B` | ABC科技 → Company_A |
| 人名 | `Person_01`, `Person_02` | 张三 → Person_01 |
| 邮箱 | `user_01@example.com` | test@co.com → user_01@example.com |
| 银行账号 | 等位随机数字 | 6222... → 3847... |
| 电话 | 保留格式随机数字 | +852 9123 4567 → +341 7856 2039 |
| 数值 | 等比缩放（同一 DB 系数一致） | 1,000,000 → 732,000 |

所有映射存储在输出目录下的 `_mapping.db`（SQLite），保证同一实体在所有文件中替换一致。

## 功能特性

- **自定义关键词库**：在 GUI 中直接编辑，支持前缀标记（`[人名]`、`[银行]`、`[地址]`、`[签字]`）
- **长词优先匹配**：`CLEARY GOTTLIEB STEEN` 优先于 `CLEARY`，不会残留明文
- **自定义输出目录**：默认 `{源文件夹}_脱敏`，可手动指定
- **增量脱敏模式**：新增关键词后只重新处理包含新词的文件，避免全量重跑
- **映射一致性**：同一 `_mapping.db` 内，相同实体始终替换为相同值，数值缩放系数一致
- **Excel 兼容性**：openpyxl → xlrd → LibreOffice + calamine 多级 fallback，兼容 Excel 2003 XML
- **本地 LLM NER**：支持 Ollama / OMLX / LM Studio 等本地模型，可关闭仅用正则

## 安装

```bash
pip install -r requirements.txt
```

### 可选依赖

- **本地 LLM**：安装 [Ollama](https://ollama.com) 并拉取模型（如 `ollama pull qwen3:8b`），用于 NER 兜底识别
- **LibreOffice**：处理 Excel 2003 XML 格式时需要，[下载地址](https://www.libreoffice.org)
- **python-calamine**：`pip install python-calamine`，高性能 Excel 读取备选方案

## 使用

```bash
python run.py
```

启动 GUI 后：

1. （可选）配置 LLM 地址和模型，点击「测试连接」
2. 编辑关键词库，添加需要脱敏的公司名、人名等
3. 点击「选择文件夹」选择源数据目录
4. 确认或修改输出目录
5. 点击「开始脱敏」
6. 新增关键词后可勾选「增量模式」只处理相关文件

## 打包

### macOS（生成 .dmg）

```bash
bash build_mac.sh
# 产物：dist/DataSanitizer-x.x.x-mac.dmg
```

### Windows（生成 .exe）

```bash
build_win.bat
# 产物：dist/DataSanitizer/DataSanitizer.exe
```

## 项目结构

```
data-sanitizer/
├── run.py                  # 启动入口
├── keywords.txt            # 脱敏关键词库
├── sanitizer/
│   ├── app.py              # tkinter GUI
│   ├── engine.py           # 脱敏引擎（关键词 + 正则 + LLM NER）
│   ├── entity_map.py       # SQLite 实体映射表
│   ├── rules.py            # 正则规则定义
│   ├── utils.py            # 工具函数
│   └── parsers/
│       ├── base.py         # BaseParser 抽象类
│       ├── excel_parser.py # xlsx/xls/csv
│       ├── word_parser.py  # docx
│       ├── pdf_parser.py   # PDF
│       ├── text_parser.py  # txt
│       └── html_parser.py  # html
├── tests/
│   └── test_engine.py      # 单元测试
├── DataSanitizer.spec      # PyInstaller 打包配置
├── build_mac.sh            # macOS 打包脚本
└── build_win.bat           # Windows 打包脚本
```

## 测试

```bash
python -m pytest tests/ -v
```

## License

MIT
