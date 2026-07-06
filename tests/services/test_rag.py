# SPDX-FileCopyrightText: 2026 NTU AI Club
# SPDX-License-Identifier: GPL-3.0-or-later

from ian.services.rag import SimpleBM25


def test_simple_bm25_scores_matching_document_higher():
    bm25 = SimpleBM25([["ai", "course"], ["member", "fee"]])

    scores = bm25.get_scores(["ai"])

    assert scores[0] > scores[1]
