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

import subprocess
from pathlib import Path


HASH_HEADER = """#
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
"""

MARKDOWN_HEADER = """<!--
SPDX-License-Identifier: GPL-3.0-or-later

Copyright (c) 2026 NTU AI Club

This file is part of Ian, an open-source AI agent framework developed
and maintained by NTU AI Club.

Ian is licensed under the GNU General Public License, either version 3
of the License, or (at your option) any later version.

Ian is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Ian. If not, see <https://www.gnu.org/licenses/>.
-->
"""


def test_tracked_files_have_license_metadata():
    result = subprocess.run(
        ["uv", "run", "python", "scripts/add_license_headers.py", "--check"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_python_files_use_full_hash_license_header():
    text = Path("src/ian/domain/urls.py").read_text(encoding="utf-8")

    assert text.startswith(HASH_HEADER)


def test_markdown_files_use_full_comment_license_header():
    text = Path("README.md").read_text(encoding="utf-8")

    assert text.startswith(MARKDOWN_HEADER)
