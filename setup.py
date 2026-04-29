from setuptools import setup, find_packages

setup(
    name="data-sanitizer",
    version="1.0.0",
    description="财务数据脱敏工具 - Financial Data Sanitization Tool",
    author="Daniel Team",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "openpyxl>=3.1.0",
        "xlrd>=2.0.1",
        "python-docx>=1.1.0",
        "PyMuPDF>=1.23.0",
        "beautifulsoup4>=4.12.0",
        "chardet>=5.2.0",
        "spacy>=3.7.0",
    ],
    entry_points={
        "console_scripts": [
            "data-sanitizer=sanitizer.app:main",
        ],
    },
)
