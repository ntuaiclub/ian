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

import asyncio
import json

import pytest

from ian.domain.urls import URL_PLACEHOLDER
from ian.domain.injection import INJECTION_REJECTION_MSG
from ian.services.agent import runtime
from ian.services.agent.runtime import _validate_agent_response_urls


def test_agent_runtime_allows_prompt_and_tool_result_urls():
    response = (
        "社員申請看 https://bit.ly/ntuai-1142-member ，"
        "講義看 https://docs.example/slides 。"
    )

    cleaned = _validate_agent_response_urls(
        response,
        tool_results=["講義連結：https://docs.example/slides"],
    )

    assert "https://bit.ly/ntuai-1142-member" in cleaned
    assert "https://docs.example/slides" in cleaned


def test_agent_runtime_replaces_hallucinated_urls_without_prompt_wrappers():
    cleaned = _validate_agent_response_urls(
        "社團網站 https://linktr.ee/ntuai ，假連結 https://fake.example/path",
        tool_results=[],
    )

    assert "https://linktr.ee/ntuai" in cleaned
    assert "https://fake.example/path" not in cleaned
    assert URL_PLACEHOLDER in cleaned


def test_chat_with_agent_logs_blocked_request_without_private_content(
    monkeypatch, capsys
):
    monkeypatch.setattr(runtime, "lookup_member_by_platform", lambda *_args: None)
    monkeypatch.setattr(runtime, "detect_prompt_injection", lambda _question: True)
    monkeypatch.setattr(runtime, "add_log", lambda *_args, **_kwargs: None)

    result = asyncio.run(
        runtime.chat_with_agent(
            "session-1",
            "Private Name",
            "private malicious prompt",
            "member",
            0.0,
            "channel-1",
            platform="LINE",
            account_id="account-1",
        )
    )

    assert result == INJECTION_REJECTION_MSG
    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == "request_rejected"
    assert entry["reason"] == "prompt_injection"
    for sensitive in ("session-1", "account-1", "Private Name", "private malicious prompt"):
        assert sensitive not in json.dumps(entry)


@pytest.mark.parametrize(
    ("usage_allowed", "expected_event", "expected_status"),
    [
        pytest.param(False, "no_response", "rate_limited", id="usage-limit"),
        pytest.param(True, "agent_invoked", "queued", id="queued"),
    ],
)
def test_chat_with_agent_logs_usage_and_queue_outcomes(
    monkeypatch, capsys, usage_allowed, expected_event, expected_status
):
    queued = []

    async def resolve_future(_future):
        return "agent result"

    monkeypatch.setattr(runtime, "lookup_member_by_platform", lambda *_args: None)
    monkeypatch.setattr(runtime, "detect_prompt_injection", lambda _question: False)
    monkeypatch.setattr(
        runtime, "check_and_update_usage", lambda _session_id: usage_allowed
    )
    monkeypatch.setattr(runtime.request_queue, "put", queued.append)
    monkeypatch.setattr(runtime.asyncio, "wrap_future", resolve_future)

    asyncio.run(
        runtime.chat_with_agent(
            "session-1",
            "Private Name",
            "private question",
            "member",
            0.0,
            "channel-1",
            platform="Discord",
            account_id="account-1",
        )
    )

    entry = json.loads(capsys.readouterr().err)
    assert entry["event"] == expected_event
    assert entry["status"] == expected_status
    assert len(queued) == int(usage_allowed)
    assert "private question" not in json.dumps(entry)
