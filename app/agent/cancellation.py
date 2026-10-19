"""Per-request cancellation; early cancellations also cover HTTP arrival races."""
import asyncio
import time
from collections import OrderedDict

from app.execution.connections import ExecutionError


class AgentRequests:
    def __init__(self):
        self.active = {}
        self.cancelled = OrderedDict()

    def _prune(self):
        now = time.monotonic()
        for key, deadline in list(self.cancelled.items()):
            if deadline <= now:
                self.cancelled.pop(key, None)
        while len(self.cancelled) > 1024:
            self.cancelled.popitem(last=False)

    async def run(self, state, body):
        if body.request_token is None:
            return await state.agent.run(state, body)
        self._prune()
        key = (body.client_id, body.request_token)
        if key in self.cancelled:
            raise ExecutionError(409, "request_cancelled", "중지된 요청입니다.")
        if key in self.active:
            raise ExecutionError(409, "duplicate_request", "이미 처리 중인 요청입니다.")
        task = asyncio.create_task(state.agent.run(state, body))
        self.active[key] = task
        try:
            return await task
        except asyncio.CancelledError:
            if key in self.cancelled:
                raise ExecutionError(409, "request_cancelled", "요청을 중지했습니다.") from None
            raise
        finally:
            self.active.pop(key, None)

    async def cancel(self, client_id, token):
        self._prune()
        key = (client_id, token)
        self.cancelled[key] = time.monotonic() + 660
        self.cancelled.move_to_end(key)
        self._prune()
        task = self.active.get(key)
        if task is not None and not task.done():
            task.cancel()
            # Wait for runner finally blocks to release the client's busy flag.
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        return {"status": "cancelled", "message": "추가 AI 처리를 중지했습니다. 이미 시작된 프로그램 작업은 계속될 수 있습니다."}
