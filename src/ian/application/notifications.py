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

from dataclasses import dataclass
from typing import Protocol

from ian.application.members import ReminderRecipient


class NotificationSender(Protocol):
    async def send(self, recipient: ReminderRecipient, message: str) -> bool: ...


@dataclass
class DeliveryReport:
    total_members: int = 0
    total_recipients: int = 0
    discord_ok: int = 0
    discord_fail: int = 0
    fb_ok: int = 0
    fb_fail: int = 0
    line_ok: int = 0
    line_fail: int = 0

    @classmethod
    def for_recipients(cls, recipients: list[ReminderRecipient]) -> "DeliveryReport":
        return cls(
            total_members=len({recipient.user_id for recipient in recipients}),
            total_recipients=len(recipients),
        )

    def record(self, recipient: ReminderRecipient, success: bool) -> None:
        field = f"{recipient.platform.value}_{'ok' if success else 'fail'}"
        setattr(self, field, getattr(self, field) + 1)

    @property
    def sent_count(self) -> int:
        return self.discord_ok + self.fb_ok + self.line_ok

    @property
    def failed_count(self) -> int:
        return self.discord_fail + self.fb_fail + self.line_fail

    @property
    def status(self) -> str:
        return "success" if self.failed_count == 0 else "partial_failure"

async def deliver_message(
    sender: NotificationSender,
    recipients: list[ReminderRecipient],
    message: str,
) -> DeliveryReport:
    report = DeliveryReport.for_recipients(recipients)
    for recipient in recipients:
        try:
            success = await sender.send(recipient, message)
        except Exception:
            success = False
        report.record(recipient, success)
    return report
