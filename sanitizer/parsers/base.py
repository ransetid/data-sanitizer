"""
解析器基类
所有文件格式解析器必须继承此抽象类
"""

from abc import ABC, abstractmethod

from sanitizer.engine import SanitizeEngine


class BaseParser(ABC):
    """
    文件解析器抽象基类

    每种文件格式实现一个 Parser，负责：
    1. 判断是否能处理指定文件
    2. 读取文件内容
    3. 调用引擎进行脱敏
    4. 将脱敏后的内容写入输出文件
    """

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """
        判断是否能处理该文件

        Args:
            file_path: 文件路径

        Returns:
            True 如果该 Parser 可以处理此文件
        """
        ...

    @abstractmethod
    def sanitize(self, input_path: str, output_path: str, engine: SanitizeEngine) -> dict:
        """
        对文件进行脱敏处理

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            engine: 脱敏引擎实例

        Returns:
            统计信息字典 {"entities_found": N, "entities_replaced": N}
        """
        ...
