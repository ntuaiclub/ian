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

import pytest

from ian.application.member_notifications import (
    EventNotFoundError,
    MemberNotificationService,
    StaffPermissionError,
)
from ian.application.members import ReminderRecipient
from ian.domain.events import Event
from ian.domain.members import MemberTier, Platform


def event(tier=0):
    return Event.model_validate(
        {
            "id": 42,
            "title": "Agent Evaluation",
            "startDate": "2026-08-01T19:00:00+08:00",
            "endDate": "2026-08-01T21:00:00+08:00",
            "minimumTier": tier,
            "slug": "agent-evaluation",
            "_status": "published",
        }
    )


def recipient(user_id, tier):
    return ReminderRecipient(
        user_id=user_id,
        platform=Platform.DISCORD,
        account_id=f"discord-{user_id}",
        tier=tier,
    )


class EventsStub:
    def __init__(self, selected=None):
        self.selected = selected
        self.calls = 0

    async def get_published_event_for_staff(self, _event_id):
        self.calls += 1
        return self.selected

    async def list_upcoming_events(self, viewer_tier, limit):
        self.calls += 1
        assert viewer_tier == 3
        return [self.selected][:limit] if self.selected else []

    @staticmethod
    def can_access(item, viewer_tier):
        return viewer_tier >= item.required_tier

    @staticmethod
    def format_event(item):
        return item.title


class MembersStub:
    def __init__(self, recipients=None, *, staff=True):
        self.recipients = recipients or []
        self.staff = staff
        self.calls = 0

    async def is_staff(self, platform, account_id):
        self.calls += 1
        assert platform in {"Discord", "FB", "LINE"}
        assert account_id
        return self.staff

    async def list_reminder_recipients(self):
        self.calls += 1
        return self.recipients


class SenderStub:
    def __init__(self, outcomes=None):
        self.outcomes = iter(outcomes or [])
        self.calls = []

    async def send(self, target, message):
        self.calls.append((target, message))
        return next(self.outcomes, True)


@pytest.mark.asyncio
async def test_non_staff_is_rejected_before_event_dependencies():
    events = EventsStub(event())
    members = MembersStub(staff=False)
    service = MemberNotificationService(events, members, SenderStub())

    with pytest.raises(StaffPermissionError):
        await service.list_upcoming("Discord", "account-1")

    assert events.calls == 0
    assert members.calls == 1


@pytest.mark.asyncio
async def test_missing_event_does_not_load_recipients():
    members = MembersStub()
    service = MemberNotificationService(EventsStub(), members, SenderStub())

    with pytest.raises(EventNotFoundError):
        await service.notify_event("Discord", "account-1", 42)

    assert members.calls == 1


@pytest.mark.asyncio
async def test_event_notification_filters_recipients_by_tier_and_appends_note():
    sender = SenderStub([True])
    service = MemberNotificationService(
        EventsStub(event(tier=2)),
        MembersStub(
            [
                recipient(1, MemberTier.LECTURE_EXPLORATION),
                recipient(2, MemberTier.HANDS_ON),
            ]
        ),
        sender,
    )

    result = await service.notify_event("Discord", "account-1", 42, " reminder ")

    assert len(sender.calls) == 1
    assert sender.calls[0][0].tier is MemberTier.HANDS_ON
    assert sender.calls[0][1] == "Agent Evaluation\n\n附註：reminder"
    assert result.delivery.total_members == 1
    assert result.delivery.discord_ok == 1


@pytest.mark.asyncio
async def test_custom_notification_aggregates_delivery():
    sender = SenderStub([True, False])
    service = MemberNotificationService(
        EventsStub(),
        MembersStub(
            [
                recipient(1, MemberTier.LECTURE_EXPLORATION),
                recipient(2, MemberTier.HANDS_ON),
            ]
        ),
        sender,
    )

    report = await service.notify_custom(
        "Discord",
        "account-1",
        "  Custom alert  ",
    )

    assert [message for _target, message in sender.calls] == [
        "NTUAI 通知\n\nCustom alert",
        "NTUAI 通知\n\nCustom alert",
    ]
    assert report.discord_ok == 1
    assert report.discord_fail == 1
    assert report.status == "partial_failure"
