import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_cancel_releases_request_and_allows_next_turn(tmp_path):
    started = threading.Event()
    released = threading.Event()

    class Agent:
        busy = False

        async def run(self, state, body):
            assert not self.busy
            self.busy = True
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.busy = False
                released.set()

    app = create_app(Settings(_env_file=None, registry_database_path=tmp_path / "test.sqlite3"))
    app.state.agent = Agent()
    body = {"client_id": "pc-a", "request_token": "a" * 32,
            "messages": [{"role": "user", "content": "test"}]}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, "/api/v1/agent/chat", json=body)
        assert started.wait(3)
        # A different token must not cancel the active request.
        client.post("/api/v1/agent/cancel", json={"client_id": "pc-a", "request_token": "b" * 32}).raise_for_status()
        assert not released.is_set()
        duplicate = client.post("/api/v1/agent/chat", json=body)
        assert duplicate.status_code == 409
        response = client.post("/api/v1/agent/cancel", json={"client_id": "pc-a", "request_token": "a" * 32})
        assert response.json()["status"] == "cancelled"
        assert released.is_set() and not app.state.agent.busy
        assert pending.result(timeout=3).json()["detail"]["code"] == "request_cancelled"
        assert not app.state.agent_requests.active
        # Cancellation may arrive before the original chat POST.
        body["request_token"] = "b" * 32
        assert client.post("/api/v1/agent/chat", json=body).json()["detail"]["code"] == "request_cancelled"
        started.clear()
        released.clear()
        body["request_token"] = "c" * 32
        pending = pool.submit(client.post, "/api/v1/agent/chat", json=body)
        assert started.wait(3)
        client.post("/api/v1/agent/cancel", json={"client_id": "pc-a", "request_token": "c" * 32}).raise_for_status()
        assert pending.result(timeout=3).status_code == 409
        assert released.is_set()
