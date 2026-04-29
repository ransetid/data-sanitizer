"""
正则规则模块
定义财务场景下的敏感信息匹配规则
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class RuleMatch:
    """正则匹配结果"""
    text: str           # 匹配到的原始文本
    entity_type: str    # 实体类型
    start: int          # 起始位置
    end: int            # 结束位置


@dataclass
class RegexRule:
    """单条正则规则定义"""
    name: str               # 规则名称
    pattern: re.Pattern     # 编译后的正则表达式
    entity_type: str        # 匹配到的实体类型
    validator: Optional[callable] = None  # 可选的验证函数


def _luhn_check(number_str: str) -> bool:
    """Luhn 算法校验（用于信用卡号验证）"""
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _validate_china_id(id_str: str) -> bool:
    """中国身份证号校验"""
    if len(id_str) != 18:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"
    try:
        total = sum(int(id_str[i]) * weights[i] for i in range(17))
        expected = check_codes[total % 11]
        return id_str[-1].upper() == expected
    except (ValueError, IndexError):
        return False


class RegexRules:
    """
    财务场景正则规则集合

    规则按优先级排列，优先匹配更具体的模式
    """

    def __init__(self):
        self.rules = self._build_rules()

    def _build_rules(self) -> list[RegexRule]:
        """构建所有正则规则（按优先级排列，越靠前越优先）"""
        return [
            # =============================================
            #  高确定性规则（结构明确，误匹配率极低）
            # =============================================

            # 中国身份证号（18位，最后一位可能是X）
            RegexRule(
                name="中国身份证",
                pattern=re.compile(
                    r'\b[1-9]\d{5}'             # 地区码
                    r'(?:19|20)\d{2}'           # 出生年
                    r'(?:0[1-9]|1[0-2])'        # 月
                    r'(?:0[1-9]|[12]\d|3[01])'  # 日
                    r'\d{3}'                     # 顺序码
                    r'[\dXx]\b'                  # 校验码
                ),
                entity_type="china_id",
                validator=_validate_china_id,
            ),
            # 香港身份证 (如 A123456(7) 或 AB123456(7))
            RegexRule(
                name="香港身份证",
                pattern=re.compile(
                    r'\b[A-Z]{1,2}\d{6}\(\d\)'
                ),
                entity_type="hk_id",
            ),
            # 信用卡号（13-19位数字，可能有空格或横杠分隔）
            RegexRule(
                name="信用卡号",
                pattern=re.compile(
                    r'\b(?:\d{4}[\s-]?){3,4}\d{1,4}\b'
                ),
                entity_type="credit_card",
                validator=lambda s: _luhn_check(re.sub(r'[\s-]', '', s)),
            ),

            # =============================================
            #  加密货币地址
            # =============================================

            # Bitcoin 地址（Legacy: 1..., SegWit: 3..., Bech32: bc1...）
            RegexRule(
                name="Bitcoin地址",
                pattern=re.compile(
                    r'\b(?:'
                    r'[13][a-km-zA-HJ-NP-Z1-9]{25,34}'   # Legacy / P2SH
                    r'|bc1[a-zA-HJ-NP-Z0-9]{25,62}'      # Bech32
                    r')\b'
                ),
                entity_type="crypto_address",
            ),
            # Ethereum / BSC / Polygon 等 EVM 地址（0x 开头，40 位十六进制）
            RegexRule(
                name="EVM地址",
                pattern=re.compile(
                    r'\b0x[0-9a-fA-F]{40}\b'
                ),
                entity_type="crypto_address",
            ),
            # Tron 地址（T 开头，34 位 Base58）
            RegexRule(
                name="Tron地址",
                pattern=re.compile(
                    r'\bT[a-km-zA-HJ-NP-Z1-9]{33}\b'
                ),
                entity_type="crypto_address",
            ),
            # Bitcoin 交易哈希 / ETH 交易哈希（0x + 64位十六进制 或 纯64位十六进制）
            RegexRule(
                name="交易哈希",
                pattern=re.compile(
                    r'\b(?:0x)?[0-9a-fA-F]{64}\b'
                ),
                entity_type="tx_hash",
            ),

            # =============================================
            #  金融账号与代码
            # =============================================

            # IBAN 国际银行账号（2位国家码 + 2位校验 + 最多30位账号）
            RegexRule(
                name="IBAN账号",
                pattern=re.compile(
                    r'\b[A-Z]{2}\d{2}[\s]?'            # 国家码 + 校验位
                    r'[A-Z0-9]{4}[\s]?'                 # 银行代码
                    r'(?:[A-Z0-9]{4}[\s]?){1,7}'        # 账号主体
                    r'[A-Z0-9]{1,4}\b'                  # 尾部
                ),
                entity_type="iban",
                validator=lambda s: 15 <= len(re.sub(r'\s', '', s)) <= 34,
            ),
            # SWIFT/BIC 代码 (8或11位字母数字)
            RegexRule(
                name="SWIFT代码",
                pattern=re.compile(
                    r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b'
                ),
                entity_type="swift_code",
            ),

            # =============================================
            #  合同编号 / 发票号
            # =============================================

            # 中国增值税发票号码（发票号码/No./票号 + 8-20位数字）
            RegexRule(
                name="发票号码",
                pattern=re.compile(
                    r'(?:发票号[码]?|票号|Invoice[\s]?No\.?|Inv[\s]?[#.])'
                    r'[\s:：#]*'
                    r'([A-Za-z0-9\-]{6,20})',
                    re.IGNORECASE,
                ),
                entity_type="invoice_no",
            ),
            # 合同编号（合同号/Contract No. + 编号）
            RegexRule(
                name="合同编号",
                pattern=re.compile(
                    r'(?:合同[编号]*|Contract[\s]?No\.?|协议[编号]*|Agreement[\s]?No\.?)'
                    r'[\s:：#]*'
                    r'([A-Za-z0-9\-]{4,30})',
                    re.IGNORECASE,
                ),
                entity_type="contract_no",
            ),

            # =============================================
            #  联系方式
            # =============================================

            # 邮箱地址
            RegexRule(
                name="邮箱",
                pattern=re.compile(
                    r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                ),
                entity_type="email",
            ),
            # URL / 网址（http/https/www 开头）
            RegexRule(
                name="URL",
                pattern=re.compile(
                    r'(?:https?://|www\.)'
                    r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?'
                    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)*'
                    r'(?:\.[a-zA-Z]{2,})'
                    r'(?:[/\w\-.~:/?#\[\]@!$&\'()*+,;=%]*)?',
                    re.IGNORECASE,
                ),
                entity_type="url",
            ),
            # 电话号码（国际格式，支持多种写法）
            RegexRule(
                name="电话号码",
                pattern=re.compile(
                    r'(?:\+\d{1,3}[\s.-]?)'     # 国际区号
                    r'(?:\(?\d{1,4}\)?[\s.-]?)*' # 区号
                    r'\d{4,}'                     # 号码主体
                ),
                entity_type="phone",
            ),
            # 中国大陆手机号
            RegexRule(
                name="中国手机号",
                pattern=re.compile(
                    r'\b1[3-9]\d{9}\b'
                ),
                entity_type="phone",
            ),

            # =============================================
            #  工商 / 税务
            # =============================================

            # 统一社会信用代码（营业执照号，18位）
            RegexRule(
                name="统一社会信用代码",
                pattern=re.compile(
                    r'\b[0-9A-HJ-NP-RTUW-Y]{2}\d{6}[0-9A-HJ-NP-RTUW-Y]{10}\b'
                ),
                entity_type="tax_id",
            ),

            # =============================================
            #  兜底规则（放最后，优先级最低）
            # =============================================

            # 银行账号（9-18位连续数字）
            RegexRule(
                name="银行账号",
                pattern=re.compile(
                    r'\b\d{9,18}\b'
                ),
                entity_type="bank_account",
            ),
        ]

    def find_all(self, text: str) -> list[RuleMatch]:
        """
        对文本应用所有正则规则，返回所有匹配结果

        已匹配的文本范围不会被后续规则重复匹配（优先级按规则顺序）
        """
        matches = []
        # 记录已经被匹配覆盖的区间，防止重叠
        covered_spans = []

        for rule in self.rules:
            for m in rule.pattern.finditer(text):
                start, end = m.start(), m.end()
                matched_text = m.group()

                # 检查是否与已有匹配重叠
                if self._overlaps(start, end, covered_spans):
                    continue

                # 如果有验证函数，进行验证
                if rule.validator and not rule.validator(matched_text):
                    continue

                matches.append(RuleMatch(
                    text=matched_text,
                    entity_type=rule.entity_type,
                    start=start,
                    end=end,
                ))
                covered_spans.append((start, end))

        # 按位置排序
        matches.sort(key=lambda m: m.start)
        return matches

    @staticmethod
    def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        """检查区间 [start, end) 是否与已有区间重叠"""
        for s, e in spans:
            if start < e and end > s:
                return True
        return False
