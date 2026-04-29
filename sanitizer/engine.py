"""
脱敏引擎核心模块
三层处理架构：正则匹配 -> 本地 LLM NER -> 文本替换
支持 Ollama 原生 API 和 OpenAI 兼容 API（OMLX / LM Studio / vLLM 等）
"""

import json
import logging
import math
import re
from typing import Optional

import requests as http_client

from sanitizer.entity_map import EntityMap
from sanitizer.rules import RegexRules

logger = logging.getLogger(__name__)

# NER 提示词（系统消息）
NER_SYSTEM_PROMPT = """你是一个命名实体识别（NER）专家。你的任务是从文本中提取敏感实体。

只提取以下类型：
- company: 公司名、机构名、组织名
- person: 人名

不要提取：金额数字、日期、货币代码、财务术语（如 Revenue、EBITDA）、会计科目名称。

请严格以 JSON 数组格式返回，每个元素包含 text 和 type 两个字段。
如果没有找到任何实体，返回空数组 []。

示例输出：
[{"text": "张三", "type": "person"}, {"text": "华为技术有限公司", "type": "company"}]"""

NER_USER_PROMPT_PREFIX = "请从以下文本中提取所有敏感实体：\n\n"


class SanitizeEngine:
    """
    脱敏引擎

    处理流程：
    1. L1 - 正则匹配：使用预定义的正则规则匹配银行账号、邮箱、电话等结构化数据
    2. L2 - 本地 LLM NER：使用本地模型识别公司名、人名等非结构化实体
    3. 对每个匹配到的实体，从 entity_map 获取或创建一致的替换值
    """

    # API 类型常量
    API_OLLAMA = "ollama"
    API_OPENAI = "openai"

    def __init__(
        self,
        entity_map: EntityMap,
        ollama_url: str = "http://127.0.0.1:16578",
        ollama_model: str = "qwen3:8b",
        api_key: str = "",
        use_ollama: bool = True,
        custom_entities: Optional[dict] = None,
        unified_scale: bool = True,
        scale_min: float = 0.01,
        scale_max: float = 100.0,
    ):
        self.entity_map = entity_map
        self.regex_rules = RegexRules()

        # 自定义实体词典（L0 层 — 最高优先级）
        # 格式: {"company": ["Acme Corp", "Global Trading", ...], "person": ["张三", ...]}
        self.custom_entities: dict[str, list[str]] = custom_entities or {}

        # 数值缩放模式
        # True = 所有文件/Sheet 用同一个系数（保持跨表加和关系）
        # False = 每个文件/Sheet 各自独立系数
        self.unified_scale = unified_scale
        self.scale_min = scale_min
        self.scale_max = scale_max

        # LLM 配置 — 自动处理 URL 格式
        url = ollama_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        self.llm_url = url
        self.llm_model = ollama_model
        self.api_key = api_key.strip() if api_key else ""
        self.use_llm = use_ollama
        self._llm_available: Optional[bool] = None
        self._api_type: Optional[str] = None

        # 处理统计
        self.stats = {
            "files": 0,
            "entities_found": 0,
            "entities_replaced": 0,
        }

        # 当前正在处理的文件路径（用于 entity_map 记录来源）
        self._current_file: Optional[str] = None

        # 文本处理结果缓存
        # 财务文件中同一公司名/账号会出现数百上千次，缓存避免重复跑正则和 LLM
        # key: 原始文本, value: 脱敏后文本
        # 最多缓存 5000 条，超出后清空（简单策略，足够应对单次处理）
        self._text_cache: dict[str, str] = {}
        self._TEXT_CACHE_MAX = 5000

    def set_current_file(self, file_path: str):
        """设置当前处理的文件路径"""
        self._current_file = file_path

    def _build_headers(self) -> dict:
        """构建 HTTP 请求头，包含 API Key（如果设置了）"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_ollama(self) -> bool:
        """
        检测本地 LLM 服务是否可用
        自动识别 API 类型：Ollama 原生 或 OpenAI 兼容

        Returns:
            True 如果可用，False 如果不可用
        """
        if self._llm_available is not None:
            return self._llm_available

        if not self.use_llm:
            self._llm_available = False
            return False

        headers = self._build_headers()

        # === 尝试 1: Ollama 原生 API ===
        try:
            resp = http_client.get(f"{self.llm_url}/api/tags", headers=headers, timeout=3)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                base_model = self.llm_model.split(":")[0]
                if any(base_model in name for name in model_names):
                    self._api_type = self.API_OLLAMA
                    self._llm_available = True
                    logger.info(f"Ollama API 已连接，使用模型: {self.llm_model}")
                    return True
                else:
                    logger.info(
                        f"Ollama 已连接但未找到模型 {self.llm_model}，"
                        f"可用模型: {model_names}"
                    )
        except Exception:
            pass

        # === 尝试 2: OpenAI 兼容 API (/v1/models) ===
        try:
            resp = http_client.get(f"{self.llm_url}/v1/models", headers=headers, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_ids = [m.get("id", "") for m in models]
                base_model = self.llm_model.split(":")[0]

                if model_ids and (
                    any(base_model in mid for mid in model_ids)
                    or len(model_ids) > 0  # 有模型就行，用户指定的名字发请求时再验证
                ):
                    self._api_type = self.API_OPENAI
                    self._llm_available = True
                    found = model_ids[0] if model_ids else self.llm_model
                    logger.info(f"OpenAI 兼容 API 已连接，模型: {found}")
                    return True
        except Exception:
            pass

        # === 尝试 3: 直接尝试 /v1/chat/completions（有些服务不暴露 /v1/models）===
        try:
            resp = http_client.post(
                f"{self.llm_url}/v1/chat/completions",
                headers=headers,
                json={
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                self._api_type = self.API_OPENAI
                self._llm_available = True
                logger.info(f"OpenAI 兼容 API 已连接（直接测试成功），模型: {self.llm_model}")
                return True
        except Exception:
            pass

        logger.warning(
            f"无法连接本地 LLM ({self.llm_url})，已尝试 Ollama 和 OpenAI 兼容 API。"
            "NER 层将被跳过，仅使用正则规则。"
        )
        self._llm_available = False
        return False

    def get_api_type(self) -> Optional[str]:
        """返回检测到的 API 类型"""
        return self._api_type

    def process_text(self, text: str) -> str:
        """
        对一段文本进行脱敏处理

        Args:
            text: 待脱敏的原始文本

        Returns:
            脱敏后的文本
        """
        if not text or not text.strip():
            return text

        # 命中缓存直接返回（财务文件中同一实体会大量重复出现）
        if text in self._text_cache:
            return self._text_cache[text]

        # 收集所有需要替换的片段：(start, end, entity_type, original_text)
        replacements = []

        # === L0: 自定义词典匹配（最高优先级）===
        if self.custom_entities:
            dict_replacements = self._match_custom_entities(text)
            replacements.extend(dict_replacements)

        # === L1: 正则匹配 ===
        regex_matches = self.regex_rules.find_all(text)
        for match in regex_matches:
            replacements.append((match.start, match.end, match.entity_type, match.text))

        # === L2: 本地 LLM NER ===
        if self.check_ollama():
            ner_replacements = self._run_llm_ner(text, replacements)
            replacements.extend(ner_replacements)

        if not replacements:
            return text

        # 按位置排序，从后往前替换（避免位置偏移）
        replacements.sort(key=lambda r: r[0], reverse=True)

        # 去重：去掉重叠的替换（保留先出现的，即优先级更高的）
        replacements = self._deduplicate_replacements(replacements)

        # 执行替换
        result = text
        for start, end, entity_type, original_text in replacements:
            replacement = self.entity_map.get_or_create(
                original_text, entity_type, self._current_file
            )
            result = result[:start] + replacement + result[end:]
            self.stats["entities_found"] += 1
            self.stats["entities_replaced"] += 1

        # 写入缓存（缓存满时清空，避免内存无限增长）
        if len(self._text_cache) >= self._TEXT_CACHE_MAX:
            self._text_cache.clear()
        self._text_cache[text] = result

        return result

    def _match_custom_entities(self, text: str) -> list:
        """
        L0 层：使用自定义词典匹配实体

        遍历用户提供的实体列表，在文本中查找每个实体的所有出现位置。
        大小写不敏感匹配。
        """
        results = []
        covered = set()

        # 按关键词长度从长到短排序，确保 "CLEARY GOTTLIEB STEEN" 优先于 "CLEARY"
        # 避免短词先占位导致长词被截断、残留部分明文
        all_entries = []
        for entity_type, entity_list in self.custom_entities.items():
            for entity_name in entity_list:
                if entity_name and len(entity_name) >= 2:
                    all_entries.append((entity_type, entity_name))
        all_entries.sort(key=lambda x: len(x[1]), reverse=True)

        for entity_type, entity_name in all_entries:
            # 大小写不敏感查找
            text_lower = text.lower()
            name_lower = entity_name.lower()
            start = 0

            while True:
                idx = text_lower.find(name_lower, start)
                if idx == -1:
                    break

                end_idx = idx + len(entity_name)

                # 检查是否已覆盖
                if not any(i in covered for i in range(idx, end_idx)):
                    # 使用原文中的实际文本（保留原始大小写）
                    original_text = text[idx:end_idx]
                    results.append((idx, end_idx, entity_type, original_text))
                    for i in range(idx, end_idx):
                        covered.add(i)

                start = end_idx

        return results

    def _run_llm_ner(self, text: str, existing_replacements: list) -> list:
        """
        使用本地 LLM 进行命名实体识别
        自动使用正确的 API 格式（Ollama 或 OpenAI 兼容）
        """
        # 已有替换的覆盖范围
        covered = set()
        for start, end, _, _ in existing_replacements:
            for i in range(start, end):
                covered.add(i)

        # 限制文本长度
        truncated = text[:4000] if len(text) > 4000 else text

        try:
            if self._api_type == self.API_OLLAMA:
                response_text = self._call_ollama_api(truncated)
            else:
                response_text = self._call_openai_api(truncated)

            entities = self._parse_llm_response(response_text)

        except http_client.exceptions.Timeout:
            logger.warning("LLM 请求超时")
            return []
        except Exception as e:
            logger.warning(f"LLM NER 出错: {e}")
            return []

        # 在原文中定位每个实体
        results = []
        for entity in entities:
            entity_text = entity.get("text", "").strip()
            entity_type = entity.get("type", "")

            if not entity_text or len(entity_text) < 2:
                continue

            if entity_type not in ("company", "person"):
                continue

            # 在原文中查找所有出现位置
            start = 0
            while True:
                idx = text.find(entity_text, start)
                if idx == -1:
                    break

                end_idx = idx + len(entity_text)

                # 检查是否与已有替换重叠
                if not any(i in covered for i in range(idx, end_idx)):
                    results.append((idx, end_idx, entity_type, entity_text))
                    for i in range(idx, end_idx):
                        covered.add(i)

                start = end_idx

        return results

    def _call_ollama_api(self, text: str) -> str:
        """调用 Ollama 原生 /api/generate 接口"""
        resp = http_client.post(
            f"{self.llm_url}/api/generate",
            headers=self._build_headers(),
            json={
                "model": self.llm_model,
                "prompt": NER_SYSTEM_PROMPT + "\n\n" + NER_USER_PROMPT_PREFIX + text,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 1024,
                },
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"Ollama 请求失败 (HTTP {resp.status_code})")
            return "[]"
        return resp.json().get("response", "[]")

    def _call_openai_api(self, text: str) -> str:
        """调用 OpenAI 兼容 /v1/chat/completions 接口"""
        resp = http_client.post(
            f"{self.llm_url}/v1/chat/completions",
            headers=self._build_headers(),
            json={
                "model": self.llm_model,
                "messages": [
                    {"role": "system", "content": NER_SYSTEM_PROMPT},
                    {"role": "user", "content": NER_USER_PROMPT_PREFIX + text},
                ],
                "temperature": 0,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"OpenAI API 请求失败 (HTTP {resp.status_code})")
            return "[]"

        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "[]")
        return "[]"

    @staticmethod
    def _parse_llm_response(response_text: str) -> list:
        """
        解析 LLM 返回的 JSON 实体列表

        兼容各种可能的返回格式（带 markdown 代码块、多余文字、think 标签等）
        """
        text = response_text.strip()

        # 先去掉 <think>...</think> 标签（某些模型如 qwen3 会加思考过程）
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        # 尝试直接解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        json_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 [ 和最后一个 ] 之间的内容
        bracket_match = re.search(r'\[.*\]', text, re.DOTALL)
        if bracket_match:
            try:
                result = json.loads(bracket_match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        logger.debug(f"无法解析 LLM 响应: {text[:200]}")
        return []

    @staticmethod
    def _deduplicate_replacements(replacements: list) -> list:
        """
        去重重叠的替换区间

        输入已按 start 降序排列，保留较早（位置靠前）的替换
        """
        if not replacements:
            return []

        sorted_reps = sorted(replacements, key=lambda r: r[0])
        result = [sorted_reps[0]]

        for rep in sorted_reps[1:]:
            last = result[-1]
            if rep[0] >= last[1]:
                result.append(rep)

        result.sort(key=lambda r: r[0], reverse=True)
        return result

    def scale_number(self, value: float, seed: str) -> float:
        """
        对数值进行等比缩放

        Args:
            value: 原始数值
            seed: 缩放种子（通常是文件名+sheet名），相同 seed 使用相同系数
                  unified_scale=True 时忽略此参数，全局使用同一个系数

        Returns:
            缩放后的数值
        """
        if value == 0:
            return 0.0

        # 统一缩放模式：所有文件/Sheet 用同一个系数
        actual_seed = "__global__" if self.unified_scale else seed
        factor = self.entity_map.get_number_scale_factor(
            actual_seed, self.scale_min, self.scale_max
        )
        scaled = value * factor

        if isinstance(value, int) or (isinstance(value, float) and value == int(value)):
            return float(round(scaled))
        else:
            if value != 0:
                decimal_places = max(0, -int(math.floor(math.log10(abs(value)))) + 2)
                decimal_places = min(decimal_places, 4)
            else:
                decimal_places = 2
            return round(scaled, decimal_places)

    def scale_numbers_in_text(self, text: str, seed: str) -> str:
        """
        对文本中嵌入的数值进行等比缩放（用于 Word / HTML / TXT 等格式）

        匹配规则：
        - 支持带千分符的数字：1,234,567 或 1,234,567.89
        - 支持普通数字：1234567 或 1234567.89
        - 可带货币符号前缀：$、¥、€、£、HK$、USD 等
        - 跳过年份（2000-2099）
        - 跳过小数值（绝对值 < 1000，避免缩放页码、数量等无意义数字）
        - 保留原始格式（千分符、小数位数、货币符号）
        """
        # 匹配可选货币符号 + 数字（带千分符或普通）
        NUMBER_PATTERN = re.compile(
            r'(?<![.\d])'                          # 左侧不能紧跟数字或小数点
            r'((?:HK\$|USD|CNY|EUR|GBP|SGD|JPY|[¥$€£₩₿])\s*)?'  # 可选货币符号
            r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?'      # 带千分符的数字
            r'|\d{4,}(?:\.\d+)?'                   # ≥4位纯数字（或带小数）
            r'|\d+\.\d{2,})'                       # 带至少2位小数的数字
            r'(?![.\d])'                           # 右侧不能紧跟数字或小数点
        )

        def replace_number(m):
            currency = m.group(1) or ""
            num_str = m.group(2)

            # 解析数值
            try:
                clean = num_str.replace(",", "")
                value = float(clean)
            except ValueError:
                return m.group(0)

            # 跳过年份
            if 2000 <= value <= 2099:
                return m.group(0)

            # 跳过小数值（绝对值 < 1000）
            if abs(value) < 1000:
                return m.group(0)

            # 缩放
            scaled = self.scale_number(value, seed)

            # 重新格式化，保持原始格式风格
            has_comma = "," in num_str
            if "." in num_str:
                decimal_places = len(num_str.split(".")[-1])
                if has_comma:
                    formatted = f"{scaled:,.{decimal_places}f}"
                else:
                    formatted = f"{scaled:.{decimal_places}f}"
            else:
                int_scaled = int(round(scaled))
                if has_comma:
                    formatted = f"{int_scaled:,}"
                else:
                    formatted = str(int_scaled)

            return currency + formatted

        return NUMBER_PATTERN.sub(replace_number, text)

    def reset_stats(self):
        """重置处理统计"""
        self.stats = {
            "files": 0,
            "entities_found": 0,
            "entities_replaced": 0,
        }
