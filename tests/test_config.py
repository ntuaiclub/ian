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

import importlib.util
import os
import shutil


def test_config_loads_project_dotenv_before_reading_environment(monkeypatch, tmp_path):
    source = os.path.join(os.path.dirname(__file__), "..", "src", "ian", "config.py")
    project = tmp_path
    package_dir = project / "src" / "ian"
    package_dir.mkdir(parents=True)
    config_file = package_dir / "config.py"
    shutil.copyfile(source, config_file)

    dotenv_file = project / ".env"
    dotenv_file.write_text(
        "\n".join(
            [
                "DISCORD_BOT_TOKEN=token-from-dotenv",
                "DISCORD_LOG_CHANNEL_ID=789",
                "STAFF_NOTIFICATION_CHANNEL_ID=999",
                "MCP_PORT=6001",
                "DISCORD_ALLOWED_CHANNELS=123, 456",
                "GOOGLE_API_KEY=google-key",
                "PAGE_ACCESS_TOKEN=page-token",
                "FB_VERIFY_TOKEN=verify-token",
                "LINE_CHANNEL_ACCESS_TOKEN=line-token",
                "LINE_CHANNEL_SECRET=line-secret",
                "LINE_ALLOWED_GROUPS=group-a, group-b",
            ]
        ),
        encoding="utf-8",
    )

    for key in [
        "DISCORD_BOT_TOKEN",
        "DISCORD_LOG_CHANNEL_ID",
        "STAFF_NOTIFICATION_CHANNEL_ID",
        "MCP_PORT",
        "DISCORD_ALLOWED_CHANNELS",
        "GOOGLE_API_KEY",
        "PAGE_ACCESS_TOKEN",
        "FB_VERIFY_TOKEN",
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET",
        "LINE_ALLOWED_GROUPS",
    ]:
        monkeypatch.delenv(key, raising=False)

    spec = importlib.util.spec_from_file_location("isolated_ian_config", config_file)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PROJECT_ROOT == project
    assert module.DISCORD_BOT_TOKEN == "token-from-dotenv"
    assert module.DISCORD_LOG_CHANNEL_ID == "789"
    assert module.DISCORD_LOG_CHANNEL_ID_INT == 789
    assert module.STAFF_NOTIFICATION_CHANNEL_ID == "999"
    assert module.MCP_PORT == 6001
    assert module.ALLOWED_DISCORD_CHANNELS == ["123", "456"]
    assert module.GOOGLE_API_KEY == "google-key"
    assert module.PAGE_ACCESS_TOKEN == "page-token"
    assert module.FB_VERIFY_TOKEN == "verify-token"
    assert module.LINE_CHANNEL_ACCESS_TOKEN == "line-token"
    assert module.LINE_CHANNEL_SECRET == "line-secret"
    assert module.LINE_ALLOWED_GROUPS == ["group-a", "group-b"]
    assert module.ALLOWED_CHANNELS == ["123", "456", "group-a", "group-b"]
