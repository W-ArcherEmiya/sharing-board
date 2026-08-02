import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

MAX_ROOM_ID_LENGTH = 64
APP_VERSION = "1.5.27"
ASSET_VERSION = str(int(time.time()))

app = FastAPI(title="Sharing Board", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@dataclass
class FileTransferState:
    transfer_id: str
    upload_token: str
    manifest_message: str
    total_chunks: int
    total_size: int
    chunk_size: int
    chunk_messages: Dict[int, str] = field(default_factory=dict)
    received_indexes: Set[int] = field(default_factory=set)
    status_message: Optional[str] = None
    sender_connection_id: Optional[int] = None
    completed: bool = False


@dataclass
class RoomState:
    connections: List[WebSocket] = field(default_factory=list)
    last_text_payload: Optional[str] = None
    file_transfer: Optional[FileTransferState] = None


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, RoomState] = {}
        self.connection_rooms: Dict[int, str] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def disconnect(self, websocket: WebSocket) -> None:
        await self.leave_room(websocket)

    async def join_room(self, websocket: WebSocket, room_id: str) -> None:
        await self.leave_room(websocket)

        room = self.rooms.setdefault(room_id, RoomState())
        if websocket not in room.connections:
            room.connections.append(websocket)
        self.connection_rooms[id(websocket)] = room_id

        await websocket.send_json(
            {
                "type": "joined",
                "room": room_id,
                "has_text": room.last_text_payload is not None,
                "has_file": room.file_transfer is not None,
            }
        )

        if room.last_text_payload is not None:
            await websocket.send_text(room.last_text_payload)

        if room.file_transfer is not None:
            await websocket.send_text(room.file_transfer.manifest_message)
            for index in sorted(room.file_transfer.chunk_messages):
                await websocket.send_text(room.file_transfer.chunk_messages[index])
            if room.file_transfer.status_message is not None:
                await websocket.send_text(room.file_transfer.status_message)

    async def leave_room(self, websocket: WebSocket) -> None:
        room_id = self.connection_rooms.pop(id(websocket), None)
        if room_id is None:
            return

        room = self.rooms.get(room_id)
        if room is None:
            return

        if websocket in room.connections:
            room.connections.remove(websocket)

        file_transfer = room.file_transfer
        if (
            file_transfer is not None
            and file_transfer.sender_connection_id == id(websocket)
            and not file_transfer.completed
        ):
            file_transfer.sender_connection_id = None
            file_transfer.status_message = self._build_file_status_message(
                file_transfer, "interrupted"
            )
            await self.broadcast_to_room(room, file_transfer.status_message, exclude=websocket)

        if not room.connections and room.last_text_payload is None and room.file_transfer is None:
            self.rooms.pop(room_id, None)

    def get_room_id(self, websocket: WebSocket) -> Optional[str]:
        return self.connection_rooms.get(id(websocket))

    async def store_text_and_broadcast(self, websocket: WebSocket, payload_message: str) -> None:
        room = self._require_room_for(websocket)
        room.last_text_payload = payload_message
        await self.broadcast_to_room(room, payload_message, exclude=websocket)

    async def start_file_transfer(
        self,
        websocket: WebSocket,
        transfer_id: str,
        upload_token: str,
        manifest_message: str,
        total_chunks: int,
        total_size: int,
        chunk_size: int,
    ) -> None:
        room = self._require_room_for(websocket)
        file_transfer = FileTransferState(
            transfer_id=transfer_id,
            upload_token=upload_token,
            manifest_message=manifest_message,
            total_chunks=total_chunks,
            total_size=total_size,
            chunk_size=chunk_size,
            sender_connection_id=id(websocket),
        )
        file_transfer.status_message = self._build_file_status_message(file_transfer, "uploading")
        room.file_transfer = file_transfer

        await self.broadcast_to_room(room, manifest_message, exclude=websocket)
        await self.broadcast_to_room(room, file_transfer.status_message)

    async def append_file_chunk(
        self,
        websocket: WebSocket,
        transfer_id: str,
        upload_token: str,
        index: int,
        chunk_message: str,
    ) -> None:
        room = self._require_room_for(websocket)
        file_transfer = self._require_matching_transfer(room, transfer_id, upload_token)

        if file_transfer.sender_connection_id != id(websocket):
            file_transfer.sender_connection_id = id(websocket)
            file_transfer.status_message = self._build_file_status_message(file_transfer, "resuming")
            await self.broadcast_to_room(room, file_transfer.status_message, exclude=websocket)

        if index not in file_transfer.received_indexes:
            file_transfer.received_indexes.add(index)
            file_transfer.chunk_messages[index] = chunk_message
            await self.broadcast_to_room(room, chunk_message, exclude=websocket)

        if len(file_transfer.received_indexes) >= file_transfer.total_chunks:
            file_transfer.completed = True
            file_transfer.status_message = self._build_file_status_message(file_transfer, "completed")
        else:
            file_transfer.status_message = self._build_file_status_message(file_transfer, "uploading")

        await self.broadcast_to_room(room, file_transfer.status_message)

    async def send_resume_state(
        self, websocket: WebSocket, transfer_id: str, upload_token: str
    ) -> None:
        room = self._require_room_for(websocket)
        file_transfer = self._require_matching_transfer(room, transfer_id, upload_token)

        if file_transfer.sender_connection_id != id(websocket):
            file_transfer.sender_connection_id = id(websocket)
            if not file_transfer.completed:
                file_transfer.status_message = self._build_file_status_message(file_transfer, "resuming")
                await self.broadcast_to_room(room, file_transfer.status_message)

        missing_indexes = [
            index for index in range(file_transfer.total_chunks) if index not in file_transfer.received_indexes
        ]
        await websocket.send_json(
            {
                "type": "file_resume_state",
                "transfer_id": file_transfer.transfer_id,
                "missing_indexes": missing_indexes,
                "received_chunks": len(file_transfer.received_indexes),
                "total_chunks": file_transfer.total_chunks,
                "completed": file_transfer.completed,
            }
        )

    async def broadcast_to_room(
        self, room: RoomState, message: str, exclude: Optional[WebSocket] = None
    ) -> None:
        disconnected: List[WebSocket] = []
        for connection in room.connections:
            if exclude is not None and connection == exclude:
                continue
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            await self.disconnect(connection)

    def _require_room_for(self, websocket: WebSocket) -> RoomState:
        room_id = self.get_room_id(websocket)
        if room_id is None:
            raise ValueError("join_required")
        return self.rooms[room_id]

    def _require_matching_transfer(
        self, room: RoomState, transfer_id: str, upload_token: str
    ) -> FileTransferState:
        file_transfer = room.file_transfer
        if file_transfer is None:
            raise ValueError("missing_manifest")
        if (
            file_transfer.transfer_id != transfer_id
            or file_transfer.upload_token != upload_token
        ):
            raise ValueError("transfer_mismatch")
        return file_transfer

    def _build_file_status_message(self, file_transfer: FileTransferState, status: str) -> str:
        return json.dumps(
            {
                "type": "file_status",
                "transfer_id": file_transfer.transfer_id,
                "status": status,
                "received_chunks": len(file_transfer.received_indexes),
                "total_chunks": file_transfer.total_chunks,
                "total_size": file_transfer.total_size,
                "chunk_size": file_transfer.chunk_size,
            }
        )


def normalize_room_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None

    room_id = value.strip()
    if not room_id or len(room_id) > MAX_ROOM_ID_LENGTH:
        return None

    return room_id


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_base64_string(value: object) -> bool:
    return is_non_empty_string(value)


def validate_text_payload(payload: dict) -> bool:
    return (
        payload.get("kind") == "text"
        and is_base64_string(payload.get("iv"))
        and is_base64_string(payload.get("data"))
    )


def validate_file_manifest(message: dict) -> bool:
    return (
        is_non_empty_string(message.get("transfer_id"))
        and is_non_empty_string(message.get("upload_token"))
        and isinstance(message.get("total_chunks"), int)
        and message["total_chunks"] > 0
        and isinstance(message.get("total_size"), int)
        and message["total_size"] >= 0
        and isinstance(message.get("chunk_size"), int)
        and message["chunk_size"] > 0
        and is_base64_string(message.get("meta_iv"))
        and is_base64_string(message.get("meta_data"))
    )


def validate_file_chunk(message: dict) -> bool:
    return (
        is_non_empty_string(message.get("transfer_id"))
        and is_non_empty_string(message.get("upload_token"))
        and isinstance(message.get("index"), int)
        and message["index"] >= 0
        and is_base64_string(message.get("iv"))
        and is_base64_string(message.get("data"))
    )


def validate_resume_request(message: dict) -> bool:
    return (
        is_non_empty_string(message.get("transfer_id"))
        and is_non_empty_string(message.get("upload_token"))
    )


manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "asset_version": ASSET_VERSION,
            "app_version": APP_VERSION,
        },
    )


@app.get("/api/rooms/{room_id}/presence")
async def get_room_presence(room_id: str) -> dict:
    normalized_room = normalize_room_id(room_id)
    if normalized_room is None:
        return {"room": "", "peers": 0}

    room = manager.rooms.get(normalized_room)
    return {
        "room": normalized_room,
        "peers": len(room.connections) if room is not None else 0,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "消息格式无效"})
                continue

            if not isinstance(message, dict):
                await websocket.send_json({"type": "error", "message": "消息必须为 JSON 对象"})
                continue

            message_type = message.get("type")
            if message_type == "join":
                room_id = normalize_room_id(message.get("room"))
                if room_id is None:
                    await websocket.send_json({"type": "error", "message": "房间号不能为空且长度不能超过 64"})
                    continue
                await manager.join_room(websocket, room_id)
                continue

            if message_type == "payload":
                payload = message.get("payload")
                if not isinstance(payload, dict) or not validate_text_payload(payload):
                    await websocket.send_json({"type": "error", "message": "同步内容格式无效"})
                    continue

                payload_message = json.dumps({"type": "payload", "payload": payload})
                try:
                    await manager.store_text_and_broadcast(websocket, payload_message)
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "请先加入房间"})
                continue

            if message_type == "file_manifest":
                if not validate_file_manifest(message):
                    await websocket.send_json({"type": "error", "message": "文件描述格式无效"})
                    continue

                manifest_message = json.dumps(
                    {
                        "type": "file_manifest",
                        "transfer_id": message["transfer_id"],
                        "total_chunks": message["total_chunks"],
                        "total_size": message["total_size"],
                        "chunk_size": message["chunk_size"],
                        "meta_iv": message["meta_iv"],
                        "meta_data": message["meta_data"],
                    }
                )
                try:
                    await manager.start_file_transfer(
                        websocket,
                        transfer_id=message["transfer_id"],
                        upload_token=message["upload_token"],
                        manifest_message=manifest_message,
                        total_chunks=message["total_chunks"],
                        total_size=message["total_size"],
                        chunk_size=message["chunk_size"],
                    )
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "请先加入房间"})
                continue

            if message_type == "file_chunk":
                if not validate_file_chunk(message):
                    await websocket.send_json({"type": "error", "message": "文件分片格式无效"})
                    continue

                chunk_message = json.dumps(
                    {
                        "type": "file_chunk",
                        "transfer_id": message["transfer_id"],
                        "index": message["index"],
                        "iv": message["iv"],
                        "data": message["data"],
                    }
                )
                try:
                    await manager.append_file_chunk(
                        websocket,
                        transfer_id=message["transfer_id"],
                        upload_token=message["upload_token"],
                        index=message["index"],
                        chunk_message=chunk_message,
                    )
                except ValueError as error:
                    await websocket.send_json(
                        {"type": "error", "message": resolve_transfer_error_message(error)}
                    )
                continue

            if message_type == "file_resume_request":
                if not validate_resume_request(message):
                    await websocket.send_json({"type": "error", "message": "续传请求格式无效"})
                    continue

                try:
                    await manager.send_resume_state(
                        websocket,
                        transfer_id=message["transfer_id"],
                        upload_token=message["upload_token"],
                    )
                except ValueError as error:
                    await websocket.send_json(
                        {"type": "error", "message": resolve_transfer_error_message(error)}
                    )
                continue

            await websocket.send_json({"type": "error", "message": "不支持的消息类型"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


def resolve_transfer_error_message(error: ValueError) -> str:
    if str(error) == "join_required":
        return "请先加入房间"
    if str(error) == "missing_manifest":
        return "请先发送文件描述"
    return "传输状态已变化，请重新选择文件"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
