"""T10 集成：WS 订阅协议 / 推送 / 非法 topic / 事件通道。"""

import threading

from starlette.testclient import TestClient

from tests.harness import make_app


def _test_app():
    app, ctx = make_app()
    return app, ctx


class TestWebSocket:
    def test_sub_ack_and_quotes_push(self):
        app, ctx = _test_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"op": "sub", "topics": ["quotes"]})
                ack = ws.receive_json()
                assert ack["topic"] == "ack"
                assert ack["data"]["topics"] == ["quotes"]
                # 总线发布 → 订阅者收到推送帧
                ctx.bus.publish("quotes", {"source": "tencent", "quotes": []})
                frame = ws.receive_json()
                assert frame["topic"] == "quotes"
                assert frame["data"]["source"] == "tencent"

    def test_trader_topic_and_unsub(self):
        app, ctx = _test_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"op": "sub", "topics": ["trader:1", "events"]})
                ws.receive_json()  # ack
                ctx.bus.publish("trader:1", {"e": "account", "equity": 100})
                frame = ws.receive_json()
                assert frame["topic"] == "trader:1"
                ws.send_json({"op": "unsub", "topics": ["trader:1"]})
                ack = ws.receive_json()
                assert "trader:1" not in ack["data"]["topics"]
                # 退订后不再收到
                ctx.bus.publish("trader:1", {"e": "account"})
                ctx.bus.publish("events", {"e": "trader_created"})
                frame = ws.receive_json()
                assert frame["topic"] == "events"

    def test_invalid_topic_rejected(self):
        app, ctx = _test_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"op": "sub", "topics": ["nope", "trader:abc"]})
                ack = ws.receive_json()
                assert ack["data"]["topics"] == []
                ws.send_json({"op": "bad-op", "topics": []})
                err = ws.receive_json()
                assert err["topic"] == "error"

    def test_key_handshake(self):
        import secrets

        key = secrets.token_urlsafe(16)
        app, ctx = make_app(qtv_api_key=key)
        with TestClient(app) as client:
            # 无 key：握手被拒
            try:
                with client.websocket_connect("/ws") as ws:
                    ws.send_json({"op": "sub", "topics": ["quotes"]})
                    ws.receive_json()
                rejected = False
            except Exception:
                rejected = True
            assert rejected
            # ?key= 握手通过
            with client.websocket_connect(f"/ws?key={key}") as ws:
                ws.send_json({"op": "sub", "topics": ["quotes"]})
                assert ws.receive_json()["topic"] == "ack"
