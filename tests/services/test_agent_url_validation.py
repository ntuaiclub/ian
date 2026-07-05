from ian.domain.urls import URL_PLACEHOLDER
from ian.services.agent.runtime import _validate_agent_response_urls


def test_agent_runtime_allows_prompt_and_tool_result_urls():
    response = (
        "社員申請看 https://bit.ly/ntuai-1142-member ，"
        "講義看 https://docs.example/slides 。"
    )

    cleaned = _validate_agent_response_urls(
        response,
        tool_results=["講義連結：https://docs.example/slides"],
    )

    assert "https://bit.ly/ntuai-1142-member" in cleaned
    assert "https://docs.example/slides" in cleaned


def test_agent_runtime_replaces_hallucinated_urls_without_prompt_wrappers():
    cleaned = _validate_agent_response_urls(
        "社團網站 https://linktr.ee/ntuai ，假連結 https://fake.example/path",
        tool_results=[],
    )

    assert "https://linktr.ee/ntuai" in cleaned
    assert "https://fake.example/path" not in cleaned
    assert URL_PLACEHOLDER in cleaned
