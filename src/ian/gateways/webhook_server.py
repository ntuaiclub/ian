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

from flask import Flask, abort, request
from linebot.exceptions import InvalidSignatureError

from ian.config import FB_VERIFY_TOKEN
from ian.gateways import facebook_webhook, line_webhook
from ian.gateways.messaging_common import get_current_time
from ian.utils.logging import log_event

app = Flask(__name__)

VERIFY_TOKEN = FB_VERIFY_TOKEN
PLATFORM_ALIASES = {
    "all": {"Facebook", "LINE"},
    "fb": {"Facebook"},
    "line": {"LINE"},
}
ENABLED_WEBHOOK_PLATFORMS = PLATFORM_ALIASES["all"].copy()


def configure_platforms(platform: str = "all") -> set[str]:
    selected = PLATFORM_ALIASES.get(platform)
    if selected is None:
        raise ValueError(f"Unsupported webhook platform: {platform}")

    global ENABLED_WEBHOOK_PLATFORMS
    ENABLED_WEBHOOK_PLATFORMS = selected.copy()
    return ENABLED_WEBHOOK_PLATFORMS


def initialize_dependencies() -> None:
    """Webhook dependencies are initialized lazily by their SDK clients."""


@app.route("/", methods=["GET"])
async def verify():
    if "Facebook" not in ENABLED_WEBHOOK_PLATFORMS:
        abort(404)
    if request.args.get("hub.mode") == "subscribe" and request.args.get(
        "hub.challenge"
    ):
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args["hub.challenge"], 200
        return "驗證失敗", 403
    return "Hello World", 200


@app.route("/", methods=["POST"])
async def webhook():
    if "Facebook" not in ENABLED_WEBHOOK_PLATFORMS:
        abort(404)
    data = request.get_json()
    try:
        if data.get("object") == "page":
            facebook_webhook.handle_facebook_messages(data)
    except Exception as e:
        log_event(
            "request_failed",
            "webhook_server",
            level="error",
            platform="Facebook",
            status="error",
            operation="handle_webhook",
            error=e,
        )
    return "ok", 200


@app.route("/line/callback", methods=["POST"])
def line_callback():
    """LINE webhook 接收端點。"""
    if "LINE" not in ENABLED_WEBHOOK_PLATFORMS:
        abort(404)

    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        line_webhook.line_handler.handle(body, signature)
    except InvalidSignatureError:
        log_event(
            "request_rejected",
            "webhook_server",
            level="warning",
            platform="LINE",
            status="invalid_signature",
            reason="signature_verification_failed",
        )
        abort(400)
    except Exception as e:
        log_event(
            "request_failed",
            "webhook_server",
            level="error",
            platform="LINE",
            status="error",
            operation="handle_webhook",
            error=e,
        )

    return "OK", 200


@app.route("/status", methods=["GET"])
def status():
    return {
        "status": "running",
        "timestamp": get_current_time()["nowdatetime"],
        "platforms": sorted(ENABLED_WEBHOOK_PLATFORMS),
    }, 200


def entrypoint(platform: str = "all"):
    initialize_dependencies()
    enabled = configure_platforms(platform)
    log_event(
        "service_started",
        "webhook_server",
        status="running",
        service="webhook_server",
        host="0.0.0.0",
        port=5190,
        enabled_platforms=sorted(enabled),
    )
    app.run(host="0.0.0.0", port=5190, debug=False)
