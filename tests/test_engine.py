"""
脱敏引擎测试
测试正则规则、实体映射、文本处理和数值缩放
"""

import os
import sqlite3
import tempfile
import unittest

from sanitizer.engine import SanitizeEngine
from sanitizer.entity_map import EntityMap
from sanitizer.rules import RegexRules


class TestRegexRules(unittest.TestCase):
    """测试正则规则匹配"""

    def setUp(self):
        self.rules = RegexRules()

    def test_match_bank_account(self):
        """银行账号匹配（9-18位数字）"""
        text = "收款账号为 622202123456789"
        matches = self.rules.find_all(text)
        # 应匹配到银行账号
        bank_matches = [m for m in matches if m.entity_type == "bank_account"]
        self.assertTrue(len(bank_matches) > 0, "应匹配到银行账号")

    def test_match_email(self):
        """邮箱地址匹配"""
        text = "请发送到 finance@company.com 和 admin@example.org"
        matches = self.rules.find_all(text)
        email_matches = [m for m in matches if m.entity_type == "email"]
        self.assertEqual(len(email_matches), 2, "应匹配到2个邮箱地址")

    def test_match_china_phone(self):
        """中国手机号匹配"""
        text = "联系电话 13812345678"
        matches = self.rules.find_all(text)
        phone_matches = [m for m in matches if m.entity_type == "phone"]
        self.assertTrue(len(phone_matches) > 0, "应匹配到手机号")

    def test_match_international_phone(self):
        """国际电话号码匹配"""
        text = "海外联系 +852 9123 4567"
        matches = self.rules.find_all(text)
        phone_matches = [m for m in matches if m.entity_type == "phone"]
        self.assertTrue(len(phone_matches) > 0, "应匹配到国际电话号码")

    def test_match_swift_code(self):
        """SWIFT 代码匹配"""
        text = "SWIFT: BKCHCNBJ110"
        matches = self.rules.find_all(text)
        swift_matches = [m for m in matches if m.entity_type == "swift_code"]
        self.assertTrue(len(swift_matches) > 0, "应匹配到 SWIFT 代码")

    def test_match_hk_id(self):
        """香港身份证匹配"""
        text = "持证人 A123456(7)"
        matches = self.rules.find_all(text)
        hk_matches = [m for m in matches if m.entity_type == "hk_id"]
        self.assertEqual(len(hk_matches), 1, "应匹配到1个香港身份证")

    def test_no_overlap(self):
        """验证规则不会重叠匹配"""
        text = "邮箱 test@domain.com 电话 13900001111"
        matches = self.rules.find_all(text)
        # 检查没有重叠
        for i in range(len(matches)):
            for j in range(i + 1, len(matches)):
                self.assertFalse(
                    matches[i].start < matches[j].end and matches[j].start < matches[i].end,
                    f"匹配结果不应重叠: {matches[i]} 和 {matches[j]}",
                )


class TestEntityMap(unittest.TestCase):
    """测试实体映射表"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "_mapping.db")
        self.entity_map = EntityMap(self.db_path)

    def tearDown(self):
        # 清理临时文件
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_get_or_create_consistency(self):
        """同一实体多次查询应返回相同的替换值"""
        r1 = self.entity_map.get_or_create("ABC公司", "company", "test.xlsx")
        r2 = self.entity_map.get_or_create("ABC公司", "company", "other.xlsx")
        self.assertEqual(r1, r2, "同一实体应返回相同的替换值")

    def test_different_entities_different_replacements(self):
        """不同实体应返回不同的替换值"""
        r1 = self.entity_map.get_or_create("ABC公司", "company")
        r2 = self.entity_map.get_or_create("XYZ公司", "company")
        self.assertNotEqual(r1, r2, "不同实体应返回不同的替换值")

    def test_company_format(self):
        """公司名替换格式应为 Company_X"""
        r = self.entity_map.get_or_create("某某科技有限公司", "company")
        self.assertTrue(r.startswith("Company_"), f"公司名替换格式不正确: {r}")

    def test_person_format(self):
        """人名替换格式应为 Person_XX"""
        r = self.entity_map.get_or_create("张三", "person")
        self.assertTrue(r.startswith("Person_"), f"人名替换格式不正确: {r}")

    def test_email_format(self):
        """邮箱替换格式应为 user_XX@example.com"""
        r = self.entity_map.get_or_create("test@company.com", "email")
        self.assertIn("@example.com", r, f"邮箱替换格式不正确: {r}")

    def test_bank_account_length_preserved(self):
        """银行账号替换应保留位数"""
        original = "6222021234567890"
        r = self.entity_map.get_or_create(original, "bank_account")
        self.assertEqual(len(r), len(original), "银行账号替换应保留位数")
        self.assertTrue(r.isdigit(), "银行账号替换应全是数字")

    def test_persistence(self):
        """关闭后重新打开映射表应保留数据"""
        self.entity_map.get_or_create("持久化公司", "company")

        # 创建新的 EntityMap 实例（模拟重新打开）
        new_map = EntityMap(self.db_path)
        r = new_map.get_or_create("持久化公司", "company")
        self.assertTrue(r.startswith("Company_"), "重新加载后应返回已有的替换值")

    def test_scale_factor_consistency(self):
        """同一 seed 的缩放系数应一致"""
        f1 = self.entity_map.get_number_scale_factor("sheet1")
        f2 = self.entity_map.get_number_scale_factor("sheet1")
        self.assertEqual(f1, f2, "同一 seed 的缩放系数应一致")

    def test_scale_factor_range(self):
        """缩放系数应在 0.7-1.3 范围内"""
        for i in range(20):
            factor = self.entity_map.get_number_scale_factor(f"test_seed_{i}")
            self.assertGreaterEqual(factor, 0.7, "缩放系数不应小于 0.7")
            self.assertLessEqual(factor, 1.3, "缩放系数不应大于 1.3")


class TestSanitizeEngine(unittest.TestCase):
    """测试脱敏引擎"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "_mapping.db")
        self.entity_map = EntityMap(self.db_path)
        # 禁用 Ollama 进行纯单元测试
        self.engine = SanitizeEngine(self.entity_map, use_ollama=False)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_process_text_replaces_email(self):
        """process_text 应替换文本中的邮箱"""
        text = "请联系 finance@company.com 获取报告"
        result = self.engine.process_text(text)
        self.assertNotIn("finance@company.com", result, "原始邮箱不应保留")
        self.assertIn("@example.com", result, "应替换为脱敏邮箱格式")

    def test_process_text_replaces_phone(self):
        """process_text 应替换文本中的手机号"""
        text = "财务部电话 13912345678"
        result = self.engine.process_text(text)
        self.assertNotIn("13912345678", result, "原始手机号不应保留")

    def test_process_text_empty(self):
        """空文本应直接返回"""
        self.assertEqual(self.engine.process_text(""), "")
        self.assertEqual(self.engine.process_text("   "), "   ")

    def test_process_text_no_sensitive_data(self):
        """没有敏感信息的文本应原样返回"""
        text = "这是一段普通的财务描述"
        result = self.engine.process_text(text)
        self.assertEqual(result, text, "无敏感信息的文本应原样返回")

    def test_scale_number_consistency(self):
        """同一 seed 的数值缩放应一致"""
        v1 = self.engine.scale_number(1000.0, "sheet1")
        v2 = self.engine.scale_number(1000.0, "sheet1")
        self.assertEqual(v1, v2, "同 seed 同值的缩放结果应一致")

    def test_scale_number_proportional(self):
        """数值缩放应保持等比关系"""
        seed = "test_sheet"
        v1 = self.engine.scale_number(1000.0, seed)
        v2 = self.engine.scale_number(2000.0, seed)
        # 比例应与原始相同
        self.assertAlmostEqual(v2 / v1, 2.0, places=1, msg="缩放应保持等比关系")

    def test_scale_number_zero(self):
        """零值缩放应返回零"""
        result = self.engine.scale_number(0.0, "any_seed")
        self.assertEqual(result, 0.0, "零值缩放应返回零")

    def test_scale_number_integer_preserved(self):
        """整数缩放后应仍为整数（浮点表示）"""
        result = self.engine.scale_number(1000, "test")
        self.assertEqual(result, float(int(result)), "整数缩放结果应为整数")

    def test_stats_tracking(self):
        """统计信息应正确跟踪"""
        self.engine.reset_stats()
        self.engine.process_text("邮箱 test@company.com")
        self.assertGreater(
            self.engine.stats["entities_found"], 0,
            "应记录发现的实体数"
        )


class TestOllamaResponseParsing(unittest.TestCase):
    """测试 Ollama 响应解析"""

    def test_parse_clean_json(self):
        """解析干净的 JSON 数组"""
        response = '[{"text": "华为", "type": "company"}]'
        result = SanitizeEngine._parse_llm_response(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "华为")

    def test_parse_json_in_markdown(self):
        """解析 markdown 代码块中的 JSON"""
        response = '```json\n[{"text": "张三", "type": "person"}]\n```'
        result = SanitizeEngine._parse_llm_response(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "person")

    def test_parse_empty_array(self):
        """解析空数组"""
        result = SanitizeEngine._parse_llm_response("[]")
        self.assertEqual(result, [])

    def test_parse_garbage(self):
        """无法解析的内容返回空列表"""
        result = SanitizeEngine._parse_llm_response("这不是JSON")
        self.assertEqual(result, [])

    def test_parse_json_with_surrounding_text(self):
        """解析带有前后文字的 JSON"""
        response = '以下是识别结果：\n[{"text": "腾讯", "type": "company"}]\n以上是全部实体。'
        result = SanitizeEngine._parse_llm_response(response)
        self.assertEqual(len(result), 1)

    def test_parse_with_think_tags(self):
        """解析带有 <think> 标签的响应（qwen3 等模型）"""
        response = '<think>\n让我分析一下这段文本...\n这里有一个公司名。\n</think>\n[{"text": "阿里巴巴", "type": "company"}]'
        result = SanitizeEngine._parse_llm_response(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "阿里巴巴")


if __name__ == "__main__":
    unittest.main()
