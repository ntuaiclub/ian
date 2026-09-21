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

from datetime import date

import pytest

from ian.application.members import ReminderRecipient
from ian.application.reminders import DailyReminderService, ReminderLoadError
from ian.domain.events import Event
from ian.domain.members import MemberTier, Platform


def event(event_id: int, tier: int = 0) -> Event:
    return Event.model_validate(
        {
            "id": event_id,
            "title": f"Event {event_id}",
            "startDate": "2026-07-12T19:00:00+08:00",
            "endDate": "2026-07-12T21:00:00+08:00",
            "minimumTier": tier,
            "slug": f"event-{event_id}",
            "_status": "published",
        }
    )


def recipient(
    account_id: str,
    tier: MemberTier,
    platform: Platform = Platform.DISCORD,
) -> ReminderRecipient:
    return ReminderRecipient(
        user_id=int(account_id[-1]),
        platform=platform,
        account_id=account_id,
        tier=tier,
    )


class EventsStub:
    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error

    async def list_events_on_date(self, _target_date, viewer_tier):
        assert viewer_tier == 3
        if self.error:
            raise self.error
        return self.events

    @staticmethod
    def can_access(item, viewer_tier):
        return viewer_tier >= item.required_tier

    @staticmethod
    def format_events(events):
        return "|".join(item.title for item in events)


class MembersStub:
    def __init__(self, recipients=None, error=None):
        self.recipients = recipients or []
        self.error = error
        self.calls = 0

    async def list_reminder_recipients(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.recipients


class SenderStub:
    def __init__(self, outcomes=None):
        self.outcomes = iter(outcomes or [])
        self.calls = []

    async def send(self, target, message):
        self.calls.append((target, message))
        outcome = next(self.outcomes, True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_no_events_skips_member_lookup():
    members = MembersStub()
    service = DailyReminderService(EventsStub(), members, SenderStub())

    result = await service.run(date(2026, 7, 12))

    assert result.status == "no_events"
    assert members.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "members", "stage"),
    [
        (EventsStub(error=RuntimeError("events")), MembersStub(), "load_events"),
        (
            EventsStub([event(1)]),
            MembersStub(error=RuntimeError("members")),
            "load_members",
        ),
    ],
)
async def test_dependency_failure_identifies_stage(events, members, stage):
    service = DailyReminderService(events, members, SenderStub())

    with pytest.raises(ReminderLoadError) as captured:
        await service.run(date(2026, 7, 12))

    assert captured.value.stage == stage


@pytest.mark.asyncio
async def test_dry_run_never_calls_sender():
    service = DailyReminderService(
        EventsStub([event(1)]),
        MembersStub([recipient("account-1", MemberTier.LECTURE_EXPLORATION)]),
        SenderStub([AssertionError("must not send")]),
    )

    result = await service.run(date(2026, 7, 12), dry=True)

    assert result.status == "dry_run"
    assert result.recipient_count == 1


@pytest.mark.asyncio
async def test_filters_events_per_recipient_and_aggregates_delivery():
    sender = SenderStub([True, False])
    tier_one = recipient("account-1", MemberTier.LECTURE_EXPLORATION)
    tier_two = recipient("account-2", MemberTier.HANDS_ON, Platform.LINE)
    service = DailyReminderService(
        EventsStub([event(1), event(2, tier=2)]),
        MembersStub([tier_one, tier_two]),
        sender,
    )

    result = await service.run(date(2026, 7, 12))

    assert result.status == "completed"
    assert sender.calls == [
        (tier_one, "Event 1"),
        (tier_two, "Event 1|Event 2"),
    ]
    assert result.delivery is not None
    assert result.delivery.discord_ok == 1
    assert result.delivery.line_fail == 1
    assert result.delivery.status == "partial_failure"


@pytest.mark.asyncio
async def test_skips_recipient_without_visible_events():
    sender = SenderStub()
    service = DailyReminderService(
        EventsStub([event(1, tier=3)]),
        MembersStub([recipient("account-1", MemberTier.LECTURE_EXPLORATION)]),
        sender,
    )

    result = await service.run(date(2026, 7, 12))

    assert sender.calls == []
    assert result.delivery is not None
    assert result.recipient_count == 0
    assert result.delivery.total_members == 0
    assert result.delivery.total_recipients == 0
    assert result.delivery.sent_count == 0
