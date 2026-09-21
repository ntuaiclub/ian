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

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import ian.bootstrap as bootstrap
from ian.bootstrap import build_application
from ian.infrastructure.payload_mcp.event_repository import (
    PayloadMcpEventRepository,
)
from ian.infrastructure.payload_mcp.member_repository import (
    PayloadMcpMemberRepository,
)
from ian.infrastructure.rag.adapter import HybridRagAdapter


class FakeCaller:
    async def call_tool(self, name, arguments):
        raise AssertionError("composition must not call MCP")


class FakeSender:
    async def send(self, recipient, message):
        raise AssertionError("composition must not send notifications")


class FakeOperationalNotifier:
    async def send_channel(self, channel_id, message):
        raise AssertionError("composition must not send operational messages")

    async def send_log(self, message):
        raise AssertionError("composition must not send operational logs")


class FakeAgentAdapter:
    async def generate(self, request):
        raise AssertionError("composition must not invoke the agent")

    async def clear(self, session_id):
        raise AssertionError("composition must not clear sessions")

    async def startup(self):
        raise AssertionError("composition must not start agent threads")


class FakeChatHistoryWriter:
    def append(self, entry):
        raise AssertionError("composition must not persist chat history")


def test_build_application_composes_dependencies_without_io():
    operational = FakeOperationalNotifier()
    agent = FakeAgentAdapter()
    chat_history = FakeChatHistoryWriter()
    application = build_application(
        FakeCaller(),
        FakeSender(),
        operational,
        agent,
        chat_history_writer=chat_history,
    )

    assert isinstance(application.events.repository, PayloadMcpEventRepository)
    assert isinstance(application.members.repository, PayloadMcpMemberRepository)
    assert application.checkins.members is application.members
    assert application.reminders.events is application.events
    assert application.reminders.members is application.members
    assert application.member_notifications.events is application.events
    assert application.member_notifications.members is application.members
    assert application.operational_notifications is operational
    assert application.agent.adapter is agent
    assert application.chat_history.writer is chat_history
    assert isinstance(application.rag.adapter, HybridRagAdapter)


def test_get_application_builds_default_graph_once(monkeypatch):
    application = SimpleNamespace()
    calls = []
    monkeypatch.setattr(bootstrap, "_default_application", None)
    monkeypatch.setattr(
        bootstrap,
        "build_application",
        lambda: calls.append(True) or application,
    )

    assert bootstrap.get_application() is application
    assert bootstrap.get_application() is application
    assert calls == [True]


def test_default_composition_keeps_agent_runtime_lazy():
    project_root = Path(__file__).resolve().parents[1]
    src_root = project_root / "src"
    script = """
import json
import sys
import threading
import socket

def fail_network(*args, **kwargs):
    raise AssertionError("bootstrap must not perform network I/O")

socket.create_connection = fail_network

modules_before = set(sys.modules)
threads_before = {thread.ident for thread in threading.enumerate()}

import ian.bootstrap as bootstrap

application = bootstrap.get_application()
modules_after = set(sys.modules)
heavy_prefixes = (
    "langchain",
    "langchain_core",
    "langchain_google_genai",
    "langchain_mcp_adapters",
    "langgraph",
)
payload = {
    "adapter_type": type(application.agent.adapter).__name__,
    "chat_history_writer_type": type(application.chat_history.writer).__name__,
    "rag_adapter_type": type(application.rag.adapter).__name__,
    "heavy_modules": sorted(
        module
        for module in modules_after - modules_before
        if module in heavy_prefixes or module.startswith(
            tuple(f"{prefix}." for prefix in heavy_prefixes)
        )
    ),
    "eager_agent_modules": sorted(
        module
        for module in (
            "ian.infrastructure.agent.logging",
            "ian.infrastructure.agent.runtime",
            "ian.infrastructure.agent.sessions",
        )
        if module in modules_after
    ),
    "eager_rag_runtime": "ian.infrastructure.rag.runtime" in modules_after,
    "new_threads": sorted(
        thread.name
        for thread in threading.enumerate()
        if thread.ident not in threads_before
    ),
}
print(json.dumps(payload))
"""
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(src_root), existing_pythonpath) if part
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload == {
        "adapter_type": "LangGraphAgentAdapter",
        "chat_history_writer_type": "JsonlChatHistoryWriter",
        "rag_adapter_type": "HybridRagAdapter",
        "heavy_modules": [],
        "eager_agent_modules": [],
        "eager_rag_runtime": False,
        "new_threads": [],
    }
