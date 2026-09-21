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
from types import SimpleNamespace

import pytest

from ian.application.agent import AgentResult
from ian.domain.members import Platform
from ian.gateways import discord_bot


def _interaction(sent_messages):
    async def defer():
        return None

    async def send(message):
        sent_messages.append(message)

    return SimpleNamespace(
        id="private-interaction",
        user=SimpleNamespace(
            id=123456,
            name="private-account-name",
            display_name="Private Display Name",
        ),
        channel_id="private-channel",
        response=SimpleNamespace(defer=defer),
        followup=SimpleNamespace(send=send),
    )


@pytest.mark.parametrize("history_outcome", [True, False])
def test_ask_records_successful_reply_without_changing_delivery(
    monkeypatch, capsys, history_outcome
):
    sent_messages = []
    history_calls = []

    async def find_member(*_args):
        return None

    async def handle_agent(_request):
        return AgentResult(text="private answer", should_reply=True)

    def record_history(**kwargs):
        history_calls.append(kwargs)
        return history_outcome

    monkeypatch.setattr(
        discord_bot,
        "member_service",
        SimpleNamespace(find_user_by_platform=find_member),
    )
    monkeypatch.setattr(
        discord_bot,
        "agent_service",
        SimpleNamespace(handle=handle_agent),
    )
    monkeypatch.setattr(
        discord_bot,
        "chat_history_service",
        SimpleNamespace(record=record_history),
    )

    asyncio.run(
        discord_bot.ask.callback(
            _interaction(sent_messages),
            "private question",
        )
    )

    assert sent_messages == ["private answer"]
    assert history_calls == [
        {
            "platform": Platform.DISCORD,
            "sender_id": "123456",
            "user_name": "Private Display Name",
            "user_message": "private question",
            "bot_response": "private answer",
        }
    ]
    raw_logs = capsys.readouterr().err
    entries = [json.loads(line) for line in raw_logs.splitlines()]
    assert entries[-1]["event"] == "reply_sent"
    for private_value in (
        "private-interaction",
        "private-account-name",
        "Private Display Name",
        "private-channel",
        "private question",
        "private answer",
        "123456",
    ):
        assert private_value not in raw_logs


def test_ask_does_not_record_no_response(monkeypatch, capsys):
    sent_messages = []

    async def find_member(*_args):
        return None

    async def handle_agent(_request):
        return AgentResult(
            text="[NO_RESPONSE]🙏",
            should_reply=False,
            reaction_emoji="🙏",
        )

    monkeypatch.setattr(
        discord_bot,
        "member_service",
        SimpleNamespace(find_user_by_platform=find_member),
    )
    monkeypatch.setattr(
        discord_bot,
        "agent_service",
        SimpleNamespace(handle=handle_agent),
    )
    monkeypatch.setattr(
        discord_bot,
        "chat_history_service",
        SimpleNamespace(
            record=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("no-response should not be persisted")
            )
        ),
    )

    asyncio.run(
        discord_bot.ask.callback(
            _interaction(sent_messages),
            "private question",
        )
    )

    assert sent_messages == ["🙏"]
    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[-1]["event"] == "no_response"
