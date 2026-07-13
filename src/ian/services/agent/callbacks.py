#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (c) 2026 NTU AI Club
#
# This file is part of Ian, an open-source AI agent framework developed
# and maintained by NTU AI Club.
#
# Ian is licensed under the GNU General Public License, either version 3
# of the License, or (at your option) any later version.
#
# Ian is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ian. If not, see <https://www.gnu.org/licenses/>.
#

from typing import Any, Dict

from langchain_core.callbacks import BaseCallbackHandler

from ian.services.agent.logging import add_log
from ian.utils.logging import redact_user_content


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
        add_log(
            "TOOL_CALL",
            tool_name=tool_name,
            args=redact_user_content(input_str),
        )

    def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """工具執行完成時"""
        tool_name = kwargs.get("name", "tool")
        add_log(
            "TOOL_RESULT",
            tool_name=tool_name,
            result=redact_user_content(str(output)),
        )
        self.tool_results.append(extract_text_from_output(output))

    def on_tool_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        """工具執行錯誤時"""
        add_log("ERROR", error=type(error).__name__, context="Tool execution")
