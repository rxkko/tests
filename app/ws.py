from typing import Optional

from fastapi import WebSocket


class ConnectionManager:
    """Хранит активные WebSocket-соединения по комнатам (тестам)."""

    def __init__(self):
        # test_id -> list of {"kind": "teacher"|"student", "participant_id": int|None, "ws": WebSocket}
        self._rooms: dict = {}

    async def connect(
        self,
        test_id: int,
        kind: str,
        participant_id: Optional[int],
        ws: WebSocket,
    ) -> None:
        await ws.accept()
        self._rooms.setdefault(test_id, []).append(
            {"kind": kind, "participant_id": participant_id, "ws": ws}
        )

    def disconnect(self, test_id: int, ws: WebSocket) -> None:
        self._rooms[test_id] = [
            c for c in self._rooms.get(test_id, []) if c["ws"] is not ws
        ]

    async def _send(self, connections, message: dict) -> None:
        for c in connections:
            try:
                await c["ws"].send_json(message)
            except Exception:
                pass

    async def send_to_students(self, test_id: int, message: dict) -> None:
        await self._send(
            [c for c in self._rooms.get(test_id, []) if c["kind"] == "student"],
            message,
        )

    async def send_to_student(
        self, test_id: int, participant_id: int, message: dict
    ) -> None:
        await self._send(
            [
                c
                for c in self._rooms.get(test_id, [])
                if c["kind"] == "student"
                and c["participant_id"] == participant_id
            ],
            message,
        )

    async def send_to_teachers(self, test_id: int, message: dict) -> None:
        await self._send(
            [c for c in self._rooms.get(test_id, []) if c["kind"] == "teacher"],
            message,
        )

    async def broadcast(self, test_id: int, message: dict) -> None:
        await self._send(self._rooms.get(test_id, []), message)


manager = ConnectionManager()
