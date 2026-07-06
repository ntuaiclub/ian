# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

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
