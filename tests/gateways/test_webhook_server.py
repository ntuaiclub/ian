from ian.gateways import facebook_webhook, line_webhook, messaging_common, webhook_server
from ian.config import MEMBER_MAPPING_FILE


def test_webhook_post_delegates_facebook_messages(monkeypatch):
    calls = []

    def fake_handle_facebook_messages(data):
        calls.append(data)

    monkeypatch.setattr(facebook_webhook, "handle_facebook_messages", fake_handle_facebook_messages)

    client = webhook_server.app.test_client()
    response = client.post("/", json={"object": "page", "entry": []})

    assert response.status_code == 200
    assert response.text == "ok"
    assert calls == [{"object": "page", "entry": []}]


def test_webhook_routes_use_split_gateway_modules():
    assert hasattr(facebook_webhook, "handle_facebook_messages")
    assert hasattr(line_webhook, "line_handler")
    assert hasattr(line_webhook, "handle_line_message")
    assert hasattr(messaging_common, "get_current_time")
    assert hasattr(messaging_common, "save_chat_history")


def test_gateway_helpers_avoid_unneeded_public_wrappers():
    assert not hasattr(messaging_common, "ensure_upload_dir")
    assert not hasattr(messaging_common, "run_async_in_thread")


def test_facebook_member_mapping_path_comes_from_config():
    assert facebook_webhook.MAPPING_FILE_PATH == MEMBER_MAPPING_FILE
    assert MEMBER_MAPPING_FILE.name == "member_mapping.csv"
    assert MEMBER_MAPPING_FILE.parent.name == "data"
