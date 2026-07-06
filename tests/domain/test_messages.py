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

from ian.domain.messages import split_message_chunks


def test_split_message_chunks_returns_short_text_as_single_chunk():
    assert split_message_chunks("hello") == ["hello"]


def test_split_message_chunks_groups_paragraphs_without_exceeding_limit():
    text = "aaa\n\nbbb\n\ncccc"

    assert split_message_chunks(text, max_length=10) == ["aaa\n\nbbb", "cccc"]


def test_split_message_chunks_splits_single_long_paragraph():
    text = "abcdefghij"

    assert split_message_chunks(text, max_length=4) == ["abcd", "efgh", "ij"]


def test_split_message_chunks_limits_max_chunks_and_omits_blank_chunks():
    text = "one\n\n\n\ntwo\n\nthree\n\nfour"

    assert split_message_chunks(text, max_length=5, max_chunks=2) == ["one", "two"]
