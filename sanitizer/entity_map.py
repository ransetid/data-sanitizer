"""
全局实体映射表模块
使用 SQLite 存储原始值与脱敏替换值的映射关系，保证一致性
"""

import hashlib
import random
import re
import sqlite3
import string
from datetime import datetime
from pathlib import Path
from typing import Optional


class EntityMap:
    """
    实体映射表

    使用 SQLite 持久化存储，确保：
    1. 同一个实体在所有文件中始终替换为同一个值
    2. 不同实体替换为不同的值
    3. 替换值的格式与原始值类似（如银行账号保持位数）
    """

    def __init__(self, db_path: str):
        """
        初始化映射表

        Args:
            db_path: SQLite 数据库文件路径（通常放在输出目录下的 _mapping.db）
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # 各类型计数器（从数据库中恢复）
        self._counters = {}
        self._load_counters()

        # 随机盐（用于缩放系数生成）
        # DB 已存在则复用之前的盐，保证同一个 DB 内一致
        # 删掉 DB 重跑 → 新盐 → 新系数
        self._salt = self._load_or_create_salt()

    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_mapping (
                original TEXT NOT NULL,
                replacement TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                first_seen_file TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (original, entity_type)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_type
            ON entity_mapping(entity_type)
        """)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def _load_counters(self):
        """从数据库中恢复各类型的计数器"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT entity_type, COUNT(*) FROM entity_mapping GROUP BY entity_type"
        )
        for entity_type, count in cursor.fetchall():
            self._counters[entity_type] = count
        conn.close()

    def _load_or_create_salt(self) -> str:
        """
        加载或创建随机盐

        盐存储在 entity_mapping 表中（entity_type='_meta', original='salt'）。
        DB 已存在则复用，新 DB 则生成新盐。
        删掉 DB 重跑 → 新盐 → 所有缩放系数都会变。
        """
        import uuid
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT replacement FROM entity_mapping WHERE original = ? AND entity_type = ?",
            ("__salt__", "_meta"),
        )
        row = cursor.fetchone()

        if row:
            conn.close()
            return row[0]

        # 生成新盐
        salt = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO entity_mapping (original, replacement, entity_type, first_seen_file, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("__salt__", salt, "_meta", None, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        return salt

    def _next_counter(self, entity_type: str) -> int:
        """获取指定类型的下一个编号"""
        current = self._counters.get(entity_type, 0)
        self._counters[entity_type] = current + 1
        return current + 1

    def get_or_create(
        self,
        original: str,
        entity_type: str,
        source_file: Optional[str] = None,
    ) -> str:
        """
        获取或创建替换值

        如果该实体已有映射，返回已有的替换值；
        否则生成新的替换值并存储

        Args:
            original: 原始敏感文本
            entity_type: 实体类型
            source_file: 首次发现该实体的文件路径

        Returns:
            替换后的脱敏文本
        """
        conn = self._get_conn()

        # 先查找是否已存在
        cursor = conn.execute(
            "SELECT replacement FROM entity_mapping WHERE original = ? AND entity_type = ?",
            (original, entity_type),
        )
        row = cursor.fetchone()

        if row:
            conn.close()
            return row[0]

        # 生成新的替换值
        replacement = self._generate_replacement(original, entity_type)

        # 存储映射
        conn.execute(
            "INSERT INTO entity_mapping (original, replacement, entity_type, first_seen_file, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (original, replacement, entity_type, source_file, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        return replacement

    def _generate_replacement(self, original: str, entity_type: str) -> str:
        """
        根据实体类型生成合适的替换值

        策略：
        - 公司名 -> Company_A, Company_B, ...
        - 人名 -> Person_01, Person_02, ...
        - 银行名 -> Bank_01, Bank_02, ...
        - 银行账号 -> 保留位数的随机数字
        - IBAN -> 保留格式的随机值
        - 邮箱 -> user_01@example.com
        - URL -> https://www.example-01.com
        - 电话 -> 保留格式的随机数字
        - 身份证 -> 保留位数的随机值
        - 信用卡 -> 保留格式的随机值
        - SWIFT -> 随机字母组合
        - 税务号 -> 随机值
        - 加密货币地址 -> 保留前缀的随机值
        - 交易哈希 -> 随机十六进制
        - 合同编号 -> CONTRACT-001, CONTRACT-002, ...
        - 发票号码 -> INV-001, INV-002, ...
        - 地址 -> Address_01, Address_02, ...
        """
        counter = self._next_counter(entity_type)

        if entity_type == "company":
            # 使用字母编号：A, B, C, ..., Z, AA, AB, ...
            label = self._number_to_alpha(counter)
            return f"Company_{label}"

        elif entity_type == "person":
            return f"Person_{counter:02d}"

        elif entity_type == "bank_name":
            return f"Bank_{counter:02d}"

        elif entity_type == "address":
            return f"Address_{counter:02d}"

        elif entity_type == "bank_account":
            # 保留位数，生成随机数字
            length = len(original)
            rng = self._seeded_random(original)
            digits = "".join(str(rng.randint(0, 9)) for _ in range(length))
            # 确保第一位不为 0
            if digits[0] == "0":
                digits = str(rng.randint(1, 9)) + digits[1:]
            return digits

        elif entity_type == "iban":
            # 保留国家码，替换其余部分
            rng = self._seeded_random(original)
            clean = re.sub(r'\s', '', original)
            country = clean[:2]  # 保留国家码
            rest_len = len(clean) - 2
            digits = "".join(str(rng.randint(0, 9)) for _ in range(rest_len))
            return f"{country}{digits}"

        elif entity_type == "email":
            return f"user_{counter:02d}@example.com"

        elif entity_type == "url":
            return f"https://www.example-{counter:02d}.com"

        elif entity_type == "phone":
            # 保留原始格式（空格、横杠等），替换数字部分
            rng = self._seeded_random(original)
            result = []
            for ch in original:
                if ch.isdigit():
                    result.append(str(rng.randint(0, 9)))
                else:
                    result.append(ch)
            return "".join(result)

        elif entity_type == "china_id":
            # 生成假的身份证号（不通过校验也没关系，只需格式一致）
            rng = self._seeded_random(original)
            return "".join(str(rng.randint(0, 9)) for _ in range(17)) + str(rng.randint(0, 9))

        elif entity_type == "hk_id":
            # 保留格式：X123456(7)
            rng = self._seeded_random(original)
            prefix = original[0]  # 保留第一个字母
            digits = "".join(str(rng.randint(0, 9)) for _ in range(6))
            check = str(rng.randint(0, 9))
            return f"{prefix}{digits}({check})"

        elif entity_type == "credit_card":
            # 保留格式（空格/横杠），替换数字
            rng = self._seeded_random(original)
            result = []
            for ch in original:
                if ch.isdigit():
                    result.append(str(rng.randint(0, 9)))
                else:
                    result.append(ch)
            return "".join(result)

        elif entity_type == "swift_code":
            # 生成随机 SWIFT 格式代码
            rng = self._seeded_random(original)
            length = len(original)
            letters = string.ascii_uppercase
            bank = "".join(rng.choice(letters) for _ in range(4))
            country = "".join(rng.choice(letters) for _ in range(2))
            location = "".join(rng.choice(letters + string.digits) for _ in range(2))
            if length == 11:
                branch = "".join(rng.choice(letters + string.digits) for _ in range(3))
                return f"{bank}{country}{location}{branch}"
            return f"{bank}{country}{location}"

        elif entity_type == "tax_id":
            # 保留位数，生成随机字母数字
            rng = self._seeded_random(original)
            chars = string.ascii_uppercase + string.digits
            return "".join(rng.choice(chars) for _ in range(len(original)))

        elif entity_type == "crypto_address":
            # 保留前缀特征，替换主体
            rng = self._seeded_random(original)
            hex_chars = "0123456789abcdef"
            b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

            if original.startswith("0x"):
                # EVM 地址: 0x + 40位十六进制
                body = "".join(rng.choice(hex_chars) for _ in range(40))
                return f"0x{body}"
            elif original.startswith("bc1"):
                # Bitcoin Bech32
                bech32_chars = "023456789acdefghjklmnpqrstuvwxyz"
                body = "".join(rng.choice(bech32_chars) for _ in range(len(original) - 3))
                return f"bc1{body}"
            elif original.startswith("T"):
                # Tron
                body = "".join(rng.choice(b58_chars) for _ in range(len(original) - 1))
                return f"T{body}"
            else:
                # Bitcoin Legacy / P2SH
                prefix = original[0]
                body = "".join(rng.choice(b58_chars) for _ in range(len(original) - 1))
                return f"{prefix}{body}"

        elif entity_type == "tx_hash":
            # 交易哈希：保留 0x 前缀（如有），替换主体
            rng = self._seeded_random(original)
            hex_chars = "0123456789abcdef"
            if original.startswith("0x"):
                body = "".join(rng.choice(hex_chars) for _ in range(64))
                return f"0x{body}"
            else:
                return "".join(rng.choice(hex_chars) for _ in range(64))

        elif entity_type == "contract_no":
            return f"CONTRACT-{counter:03d}"

        elif entity_type == "invoice_no":
            return f"INV-{counter:03d}"

        else:
            # 通用替换
            return f"[REDACTED_{entity_type}_{counter:03d}]"

    @staticmethod
    def _seeded_random(seed_str: str) -> random.Random:
        """
        基于字符串生成确定性随机数生成器

        确保同一个原始值每次生成的替换值一致
        """
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % (2**32)
        return random.Random(seed)

    @staticmethod
    def _number_to_alpha(n: int) -> str:
        """
        将数字转换为字母编号

        1 -> A, 2 -> B, ..., 26 -> Z, 27 -> AA, 28 -> AB, ...
        """
        result = []
        while n > 0:
            n -= 1
            result.append(chr(65 + n % 26))
            n //= 26
        return "".join(reversed(result))

    def get_number_scale_factor(
        self, seed: str, scale_min: float = 0.01, scale_max: float = 100.0
    ) -> float:
        """
        获取数值缩放系数

        对同一个 seed，返回一致的缩放系数。
        范围由 scale_min / scale_max 控制（默认 0.01 ~ 100）。

        注意：同一个 seed 在同一个 DB 内只生成一次系数并缓存。
        如需改变范围，需删除 _mapping.db 重新生成。
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT replacement FROM entity_mapping WHERE original = ? AND entity_type = ?",
            (f"__scale__{seed}", "scale_factor"),
        )
        row = cursor.fetchone()

        if row:
            conn.close()
            return float(row[0])

        # 生成新的缩放系数（seed + 随机盐，确保每轮 DB 不同）
        rng = self._seeded_random(f"{seed}::{self._salt}")
        lo, hi = min(scale_min, scale_max), max(scale_min, scale_max)
        factor = rng.uniform(lo, hi)
        factor = round(factor, 6)

        conn.execute(
            "INSERT INTO entity_mapping (original, replacement, entity_type, first_seen_file, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"__scale__{seed}", str(factor), "scale_factor", None, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        return factor

    def get_stats(self) -> dict:
        """获取映射表统计信息"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT entity_type, COUNT(*) FROM entity_mapping "
            "WHERE entity_type != 'scale_factor' GROUP BY entity_type"
        )
        stats = dict(cursor.fetchall())
        cursor = conn.execute(
            "SELECT COUNT(*) FROM entity_mapping WHERE entity_type != 'scale_factor'"
        )
        total = cursor.fetchone()[0]
        conn.close()
        return {"total": total, "by_type": stats}

    def export_report(self, output_path: str):
        """
        导出可读的映射报告（CSV 格式）

        包含两部分：
        1. 实体映射表：原始值 → 替换值
        2. 数值缩放系数：文件/Sheet → 缩放倍数
        """
        import csv

        conn = self._get_conn()

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            # === 第一部分：实体映射 ===
            writer.writerow(["=== 实体映射表 ==="])
            writer.writerow(["类型", "原始值", "替换值", "首次出现文件", "创建时间"])

            cursor = conn.execute(
                "SELECT entity_type, original, replacement, first_seen_file, created_at "
                "FROM entity_mapping WHERE entity_type != 'scale_factor' "
                "ORDER BY entity_type, created_at"
            )
            for row in cursor.fetchall():
                writer.writerow(row)

            # 空行分隔
            writer.writerow([])

            # === 第二部分：缩放系数 ===
            writer.writerow(["=== 数值缩放系数 ==="])
            writer.writerow(["文件 / Sheet", "缩放倍数", "说明"])

            cursor = conn.execute(
                "SELECT original, replacement FROM entity_mapping "
                "WHERE entity_type = 'scale_factor' ORDER BY original"
            )
            for row in cursor.fetchall():
                seed = row[0].replace("__scale__", "")
                factor = float(row[1])
                note = f"所有数值 × {factor}（原值的 {factor*100:.1f}%）"
                writer.writerow([seed, factor, note])

        conn.close()

    # ── 增量模式：关键词快照 ────────────────────────────────────────────

    def save_keywords_snapshot(self, keywords: set[str]):
        """
        保存本次使用的关键词集合到 DB

        用于增量模式：下次运行时对比，找出新增的关键词。
        存储格式：每个关键词一行，排序后存为纯文本。
        """
        text = "\n".join(sorted(keywords))
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO entity_mapping "
            "(original, replacement, entity_type, first_seen_file, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("__keywords__", text, "_meta", None, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def load_keywords_snapshot(self) -> set[str]:
        """
        从 DB 加载上次运行的关键词集合

        返回空集合表示没有历史记录（首次运行）。
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT replacement FROM entity_mapping "
            "WHERE original = ? AND entity_type = ?",
            ("__keywords__", "_meta"),
        )
        row = cursor.fetchone()
        conn.close()

        if not row or not row[0]:
            return set()
        return set(row[0].split("\n"))

    def has_real_mappings(self) -> bool:
        """
        检查 DB 中是否存在真实的实体映射（排除 _meta 类型）

        用于增量模式：判断 DB 是否来自之前的全量运行（有映射但没有关键词快照）。
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM entity_mapping WHERE entity_type != ?",
            ("_meta",),
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
