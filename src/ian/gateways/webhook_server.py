from flask import Flask, abort, request
from linebot.exceptions import InvalidSignatureError

from ian.config import FB_VERIFY_TOKEN
from ian.gateways import facebook_webhook, line_webhook
from ian.gateways.messaging_common import get_current_time
from ian.services.member_store import init as init_member_db
from ian.utils.console import eprint

app = Flask(__name__)

VERIFY_TOKEN = FB_VERIFY_TOKEN

# Initialize member database
try:
    init_member_db()
    eprint("社員資料庫已初始化 (webhook_server)")
except Exception as e:
    eprint(f"社員資料庫初始化失敗: {e}")


@app.route('/', methods=['GET'])
async def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args["hub.challenge"], 200
        return "驗證失敗", 403
    return "Hello World", 200

@app.route('/', methods=['POST'])
async def webhook():
    data = request.get_json()
    try:
        if data.get('object') == 'page':
            facebook_webhook.handle_facebook_messages(data)
    except Exception as e:
        print(f"Webhook 處理過程中發生未知錯誤: {e}")
    return "ok", 200


@app.route('/line/callback', methods=['POST'])
def line_callback():
    """LINE webhook 接收端點。"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        line_webhook.line_handler.handle(body, signature)
    except InvalidSignatureError:
        eprint("LINE: Invalid signature")
        abort(400)
    except Exception as e:
        eprint(f"LINE CALLBACK: handler.handle() 發生例外: {e}")

    return "OK", 200


@app.route('/status', methods=['GET'])
def status():
    return {
        "status": "running",
        "timestamp": get_current_time()["nowdatetime"],
        "platforms": ["Facebook", "LINE"]
    }, 200

def main():
    print("啟動 Flask 伺服器...")
    app.run(host='0.0.0.0', port=5190, debug=False)


if __name__ == '__main__':
    main()
