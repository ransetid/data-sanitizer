#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# macOS 打包脚本
# 产物：dist/DataSanitizer-1.0.0-mac.dmg
#
# 用法：
#   cd tools/data-sanitizer
#   bash build_mac.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

APP_NAME="DataSanitizer"
VERSION="1.2.0"
DMG_NAME="${APP_NAME}-${VERSION}-mac.dmg"

echo "══════════════════════════════════════════"
echo "  数据脱敏工具 macOS 打包"
echo "  产物：dist/${DMG_NAME}"
echo "══════════════════════════════════════════"

# ── 1. 检查依赖 ────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "[提示] 正在安装 PyInstaller..."
    pip3 install pyinstaller
fi

# ── 1.5 修复 conda 环境下 PyInstaller 缺少默认图标的问题 ───────
PYINSTALLER_IMAGES=$(python3 -c "
import PyInstaller, os
print(os.path.join(os.path.dirname(PyInstaller.__file__), 'bootloader', 'images'))
")
MISSING_ICON="${PYINSTALLER_IMAGES}/icon-windowed.icns"

if [ ! -f "${MISSING_ICON}" ]; then
    echo "[修复] PyInstaller 缺少默认图标，正在生成..."

    # 用 Python 生成一个 128x128 的 PNG（无需任何第三方库）
    python3 - <<'PYEOF'
import struct, zlib

def png_chunk(name, data):
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + name + data + struct.pack('>I', crc)

w, h = 128, 128
sig  = b'\x89PNG\r\n\x1a\n'
ihdr = png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))  # RGBA

raw = b''
for y in range(h):
    raw += b'\x00'   # filter: None
    for x in range(w):
        raw += bytes([70, 130, 180, 255])   # 蓝灰色填充

idat = png_chunk(b'IDAT', zlib.compress(raw, 9))
iend = png_chunk(b'IEND', b'')

with open('/tmp/_ds_src.png', 'wb') as f:
    f.write(sig + ihdr + idat + iend)
PYEOF

    # 用 sips + iconutil（macOS 内置）生成标准 icns
    ICONSET="/tmp/_ds_app.iconset"
    rm -rf "${ICONSET}"
    mkdir -p "${ICONSET}"

    for size in 16 32 64 128 256 512; do
        sips -z ${size} ${size} /tmp/_ds_src.png \
             --out "${ICONSET}/icon_${size}x${size}.png" &>/dev/null
    done
    for size in 16 32 128 256; do
        double=$((size * 2))
        sips -z ${double} ${double} /tmp/_ds_src.png \
             --out "${ICONSET}/icon_${size}x${size}@2x.png" &>/dev/null
    done

    mkdir -p "${PYINSTALLER_IMAGES}"
    iconutil -c icns "${ICONSET}" -o "${MISSING_ICON}" 2>/dev/null
    rm -rf "${ICONSET}" /tmp/_ds_src.png

    if [ -f "${MISSING_ICON}" ]; then
        echo "[修复] 图标已生成：${MISSING_ICON}"
    else
        echo "[警告] 图标生成失败，继续尝试打包..."
    fi
fi

# ── 2. 安装项目依赖 ────────────────────────────────────────────
echo "[1/4] 安装 Python 依赖..."
pip3 install -r requirements.txt --quiet

# ── 3. 清理上次构建产物 ────────────────────────────────────────
echo "[2/4] 清理旧构建..."
rm -rf dist __pycache__
# build/ 目录保留（PyInstaller 缓存，重试时加速分析阶段）
# 如需完全干净构建，手动 rm -rf build

# ── 4. PyInstaller 打包 ────────────────────────────────────────
echo "[3/4] PyInstaller 打包中（可能需要 1-3 分钟）..."
python3 -m PyInstaller DataSanitizer.spec --noconfirm

if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "[错误] 打包失败，未找到 dist/${APP_NAME}.app"
    exit 1
fi

# ── 5. 创建 DMG ────────────────────────────────────────────────
echo "[4/4] 创建 DMG..."
DMG_STAGING="dist/dmg_staging"
rm -rf "${DMG_STAGING}" "dist/${DMG_NAME}"

mkdir -p "${DMG_STAGING}"
cp -R "dist/${APP_NAME}.app" "${DMG_STAGING}/"

# 创建 /Applications 快捷方式（拖拽安装体验）
ln -sf /Applications "${DMG_STAGING}/Applications"

# 用 hdiutil 打包（macOS 内置，无需额外安装）
hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "${DMG_STAGING}" \
    -ov \
    -format UDZO \
    "dist/${DMG_NAME}"

rm -rf "${DMG_STAGING}"

echo ""
echo "✅ 打包完成！"
echo "   DMG：dist/${DMG_NAME}"
echo ""
echo "安装方式：双击 DMG → 将 DataSanitizer.app 拖入 Applications 文件夹"
echo "词库文件：~/Library/Application Support/DataSanitizer/keywords.txt"
