from typing import Any, Dict

from langchain_core.callbacks import BaseCallbackHandler

from ian.services.agent.logging import add_log


def extract_text_from_output(output) -> str:
    """從 tool output（通常是 ToolMessage）提取純文字內容。

    避免對 ToolMessage 使用 str()，因為 Pydantic repr 會把 newline
    escape 成 literal \\n，導致 URL regex 提取出帶有垃圾尾巴的 URL。
    """
    if hasattr(output, "content"):
        content = output.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
    return str(output)


class DiscordLogCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler 用於追蹤工具呼叫"""

    def __init__(self):
        super().__init__()
        self.tool_results: list[str] = []

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """工具開始執行時"""
        tool_name = serialized.get("name", "unknown_tool")
        add_log("TOOL_CALL", tool_name=tool_name, args=input_str)

    def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """工具執行完成時"""
        tool_name = kwargs.get("name", "tool")
        add_log("TOOL_RESULT", tool_name=tool_name, result=output)
        self.tool_results.append(extract_text_from_output(output))

    def on_tool_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        """工具執行錯誤時"""
        add_log("ERROR", error=str(error), context="Tool execution")
