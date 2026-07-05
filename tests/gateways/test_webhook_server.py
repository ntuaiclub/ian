from ian.gateways import facebook_webhook, line_webhook, webhook_server
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


def test_facebook_webhook_route_can_be_disabled(monkeypatch):
    calls = []

    def fake_handle_facebook_messages(data):
        calls.append(data)

    monkeypatch.setattr(facebook_webhook, "handle_facebook_messages", fake_handle_facebook_messages)
    webhook_server.configure_platforms("line")

    try:
        client = webhook_server.app.test_client()
        response = client.post("/", json={"object": "page", "entry": []})

        assert response.status_code == 404
        assert calls == []
    finally:
        webhook_server.configure_platforms("all")


def test_line_webhook_route_can_be_disabled(monkeypatch):
    calls = []

    def fake_handle(body, signature):
        calls.append({"body": body, "signature": signature})

    monkeypatch.setattr(line_webhook.line_handler, "handle", fake_handle)
    webhook_server.configure_platforms("fb")

    try:
        client = webhook_server.app.test_client()
        response = client.post(
            "/line/callback",
            data="{}",
            headers={"X-Line-Signature": "signature"},
        )

        assert response.status_code == 404
        assert calls == []
    finally:
        webhook_server.configure_platforms("all")


def test_webhook_status_reports_enabled_platforms():
    webhook_server.configure_platforms("line")

    try:
        client = webhook_server.app.test_client()
        response = client.get("/status")

        assert response.status_code == 200
        assert response.json["platforms"] == ["LINE"]
    finally:
        webhook_server.configure_platforms("all")

def test_facebook_member_mapping_path_comes_from_config():
    assert facebook_webhook.MAPPING_FILE_PATH == MEMBER_MAPPING_FILE
    assert MEMBER_MAPPING_FILE.name == "member_mapping.csv"
    assert MEMBER_MAPPING_FILE.parent.name == "data"
