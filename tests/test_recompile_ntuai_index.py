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
import json
from pathlib import Path
import sys

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "recompile_ntuai_index.py"
SPEC = importlib.util.spec_from_file_location("recompile_ntuai_index", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


SAMPLE_MARKDOWN = """# 關於 NTU AI

### 社團介紹

我們一起學習 AI。

## 加入社團

### 社費資訊（社員方案）

| 項目 | 探索者 $2,000 | 終身 VIP $50,000 |
| --- | --- | --- |
| 社員身份有效期 | 一個學期 | 終身 |
| 演講 | ● | ● |

#### 退費

30 天內可申請退費。

#### 付款方式

- 郵局／銀行轉帳
- 帳號：0001 2345
- 郵局代號（Bank ID）：700

## 聯絡資訊與社群

- Email: club@example.test
- Website: https://example.test

## 常見問答

### 社員加入

**Q:** 如何加入？
**A:** 請填寫表單。

- 等待 Email 通知

## 社課與活動

### 時間

星期四晚上 7 點到 9 點。
"""


def test_compile_markdown_extracts_paragraphs_faqs_and_entities():
    records = compiler.compile_markdown(SAMPLE_MARKDOWN, "knowledge.md")

    paragraphs = [record for record in records if record["type"] == "paragraph"]
    faqs = [record for record in records if record["type"] == "faq"]
    entities = {
        record["entity_type"]: record
        for record in records
        if record["type"] == "entity"
    }

    assert paragraphs[0] == {
        "id": "para_0001",
        "type": "paragraph",
        "text": "我們一起學習 AI。",
        "path": "關於 NTU AI > 社團介紹",
        "source_file": "knowledge.md",
        "lang": "zh",
    }
    assert faqs == [
        {
            "id": "faq_0001",
            "type": "faq",
            "question": "如何加入？",
            "answer": "請填寫表單。\n\n- 等待 Email 通知",
            "path": "關於 NTU AI > 常見問答 > 社員加入",
            "tags": ["關於 NTU AI", "常見問答", "社員加入"],
            "source_file": "knowledge.md",
            "lang": "zh",
        }
    ]
    assert entities["membership_fee"]["plans"]["探索者"] == {
        "amount": 2000,
        "duration": "一個學期",
        "benefits": ["演講"],
    }
    assert entities["membership_fee"]["payment"] == {
        "bank_account": "00012345",
        "bank_id": "700",
        "method": "郵局／銀行轉帳",
    }
    assert entities["contact"]["emails"] == ["club@example.test"]
    assert entities["contact"]["urls"] == ["https://example.test"]
    assert entities["course_schedule"]["schedule"] == "星期四晚上 7 點到 9 點。"


@pytest.mark.parametrize(
    "markdown",
    [
        "# FAQ\n\n**Q:** 沒有答案？",
        "# FAQ\n\n**A:** 沒有問題。",
    ],
)
def test_compile_markdown_rejects_malformed_faqs(markdown):
    with pytest.raises(compiler.CompileError):
        compiler.compile_markdown(markdown, "knowledge.md")


def test_main_writes_atomically_and_check_detects_stale_output(tmp_path):
    source = tmp_path / "knowledge.md"
    output = tmp_path / "index.jsonl"
    source.write_text("# 介紹\n\n內容。\n", encoding="utf-8")

    assert compiler.main(["--input", str(source), "--output", str(output)]) == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["para_0001"]
    assert (
        compiler.main(["--input", str(source), "--output", str(output), "--check"]) == 0
    )

    output.write_text("stale\n", encoding="utf-8")
    assert (
        compiler.main(["--input", str(source), "--output", str(output), "--check"]) == 1
    )
