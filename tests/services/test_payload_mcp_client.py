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

from ian.services.payload_mcp_client import (
    PayloadMcpConfigurationError,
    PayloadMcpSchemaError,
    StreamableHttpMcpToolCaller,
    parse_payload_documents,
)


def test_parse_payload_documents_extracts_fenced_json_and_empty_results():
    assert parse_payload_documents('```json\n{"id": 1}\n```') == [{"id": 1}]
    assert parse_payload_documents('Found 0 documents') == []


@pytest.mark.parametrize("text", ["not JSON", "```json\ninvalid\n```"])
def test_parse_payload_documents_rejects_invalid_text_contract(text):
    with pytest.raises(PayloadMcpSchemaError):
        parse_payload_documents(text)


def test_streamable_caller_requires_complete_shared_configuration():
    with pytest.raises(PayloadMcpConfigurationError):
        StreamableHttpMcpToolCaller("", "", 20)._require_config()
