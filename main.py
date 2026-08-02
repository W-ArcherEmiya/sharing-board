import asyncio
import base64
import binascii
import json
import secrets
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

MAX_ROOM_ID_LENGTH = 64
MAX_IDENTIFIER_LENGTH = 128
MAX_FILE_SIZE = 128 * 1024 * 1024
MAX_FILE_CHUNK_SIZE = 256 * 1024
MAX_FILE_CHUNKS = 512
MAX_WEBSOCKET_MESSAGE_SIZE = 512 * 1024
MAX_TEXT_BASE64_LENGTH = 128 * 1024
MAX_METADATA_BASE64_LENGTH = 256 * 1024
MAX_CHUNK_BASE64_LENGTH = 4 * ((MAX_FILE_CHUNK_SIZE + 16 + 2) // 3)
MAX_IV_BASE64_LENGTH = 64
MAX_SERVER_CACHE_BYTES = 256 * 1024 * 1024
MAX_ROOMS = 64
MAX_CONNECTIONS = 128
MAX_ROOM_CONNECTIONS = 16
ROOM_CACHE_TTL_SECONDS = 30 * 60
ROOM_CLEANUP_INTERVAL_SECONDS = 60
APP_VERSION = "1.6.1"
ASSET_VERSION = str(int(time.time()))
BASE_DIR = Path(__file__).resolve().parent


async def cleanup_expired_rooms() -> None:
    while True:
        await asyncio.sleep(ROOM_CLEANUP_INTERVAL_SECONDS)
        manager.prune_expired_rooms()


@asynccontextmanager
async def lifespan(_: FastAPI):
    cleanup_task = asyncio.create_task(cleanup_expired_rooms())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="Sharing Board", version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' ws: wss:"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
    cached_bytes: int = 0


@dataclass
class RoomState:
    connections: List[WebSocket] = field(default_factory=list)
    last_text_payload: Optional[str] = None
    text_cached_bytes: int = 0
    file_transfer: Optional[FileTransferState] = None
    last_activity: float = field(default_factory=time.monotonic)


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

        self.prune_expired_rooms()
        if len(self.connection_rooms) >= MAX_CONNECTIONS:
            raise ValueError("connection_limit")

        room = self.rooms.get(room_id)
        if room is None:
            if len(self.rooms) >= MAX_ROOMS:
                raise ValueError("room_limit")
            room = RoomState()
            self.rooms[room_id] = room
        if len(room.connections) >= MAX_ROOM_CONNECTIONS:
            raise ValueError("room_connection_limit")

        if websocket not in room.connections:
            room.connections.append(websocket)
        self.connection_rooms[id(websocket)] = room_id
        self._touch(room)

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
        self._touch(room)

        file_transfer = room.file_transfer
        if (
            file_transfer is not None
            and file_transfer.sender_connection_id == id(websocket)
            and not file_transfer.completed
        ):
            file_transfer.sender_connection_id = None
            self._set_file_status(file_transfer, "interrupted")
            await self.broadcast_to_room(room, file_transfer.status_message, exclude=websocket)

        if not room.connections and room.last_text_payload is None and room.file_transfer is None:
            self.rooms.pop(room_id, None)

    def get_room_id(self, websocket: WebSocket) -> Optional[str]:
        return self.connection_rooms.get(id(websocket))

    async def store_text_and_broadcast(self, websocket: WebSocket, payload_message: str) -> None:
        room = self._require_room_for(websocket)
        payload_size = encoded_message_size(payload_message)
        projected_size = self.cached_payload_bytes() - room.text_cached_bytes + payload_size
        self._ensure_cache_capacity(projected_size)
        room.last_text_payload = payload_message
        room.text_cached_bytes = payload_size
        self._touch(room)
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
        file_transfer.cached_bytes = encoded_message_size(
            manifest_message
        ) + encoded_message_size(file_transfer.status_message)
        previous_cached_bytes = room.file_transfer.cached_bytes if room.file_transfer else 0
        projected_size = self.cached_payload_bytes() - previous_cached_bytes + file_transfer.cached_bytes
        self._ensure_cache_capacity(projected_size)
        room.file_transfer = file_transfer
        self._touch(room)

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
        if index >= file_transfer.total_chunks:
            raise ValueError("chunk_index")

        if file_transfer.sender_connection_id != id(websocket):
            file_transfer.sender_connection_id = id(websocket)
            self._set_file_status(file_transfer, "resuming")
            await self.broadcast_to_room(room, file_transfer.status_message, exclude=websocket)

        if index not in file_transfer.received_indexes:
            chunk_cached_bytes = encoded_message_size(chunk_message)
            self._ensure_cache_capacity(self.cached_payload_bytes() + chunk_cached_bytes)
            file_transfer.received_indexes.add(index)
            file_transfer.chunk_messages[index] = chunk_message
            file_transfer.cached_bytes += chunk_cached_bytes
            await self.broadcast_to_room(room, chunk_message, exclude=websocket)

        if len(file_transfer.received_indexes) >= file_transfer.total_chunks:
            file_transfer.completed = True
            self._set_file_status(file_transfer, "completed")
        else:
            self._set_file_status(file_transfer, "uploading")

        self._touch(room)
        await self.broadcast_to_room(room, file_transfer.status_message)

    async def send_resume_state(
        self, websocket: WebSocket, transfer_id: str, upload_token: str
    ) -> None:
        room = self._require_room_for(websocket)
        file_transfer = self._require_matching_transfer(room, transfer_id, upload_token)

        if file_transfer.sender_connection_id != id(websocket):
            file_transfer.sender_connection_id = id(websocket)
            if not file_transfer.completed:
                self._set_file_status(file_transfer, "resuming")
                await self.broadcast_to_room(room, file_transfer.status_message)

        missing_indexes = [
            index for index in range(file_transfer.total_chunks) if index not in file_transfer.received_indexes
        ]
        self._touch(room)
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
            not secrets.compare_digest(file_transfer.transfer_id, transfer_id)
            or not secrets.compare_digest(file_transfer.upload_token, upload_token)
        ):
            raise ValueError("transfer_mismatch")
        return file_transfer

    def cached_payload_bytes(self) -> int:
        return sum(
            room.text_cached_bytes
            + (room.file_transfer.cached_bytes if room.file_transfer is not None else 0)
            for room in self.rooms.values()
        )

    def prune_expired_rooms(self, now: Optional[float] = None) -> List[str]:
        current_time = time.monotonic() if now is None else now
        expired_room_ids = [
            room_id
            for room_id, room in self.rooms.items()
            if not room.connections
            and current_time - room.last_activity >= ROOM_CACHE_TTL_SECONDS
        ]
        for room_id in expired_room_ids:
            self.rooms.pop(room_id, None)
        return expired_room_ids

    def _ensure_cache_capacity(self, projected_size: int) -> None:
        if projected_size > MAX_SERVER_CACHE_BYTES:
            raise ValueError("cache_limit")

    def _set_file_status(self, file_transfer: FileTransferState, status: str) -> None:
        previous_size = encoded_message_size(file_transfer.status_message)
        file_transfer.status_message = self._build_file_status_message(file_transfer, status)
        size_delta = encoded_message_size(file_transfer.status_message) - previous_size
        self._ensure_cache_capacity(self.cached_payload_bytes() + max(0, size_delta))
        file_transfer.cached_bytes += size_delta

    @staticmethod
    def _touch(room: RoomState) -> None:
        room.last_activity = time.monotonic()

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


def is_bounded_non_empty_string(value: object, max_length: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= max_length


def is_bounded_base64_string(value: object, max_length: int) -> bool:
    if not is_bounded_non_empty_string(value, max_length):
        return False
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


def encoded_message_size(message: Optional[str]) -> int:
    return len(message.encode("utf-8")) if message is not None else 0


def sanitize_text_payload(payload: dict) -> Optional[dict]:
    if (
        payload.get("kind") != "text"
        or not is_bounded_base64_string(payload.get("iv"), MAX_IV_BASE64_LENGTH)
        or not is_bounded_base64_string(payload.get("data"), MAX_TEXT_BASE64_LENGTH)
    ):
        return None

    sanitized = {
        "kind": "text",
        "iv": payload["iv"],
        "data": payload["data"],
    }
    sender_iv = payload.get("sender_iv")
    sender_data = payload.get("sender_data")
    if sender_iv is None and sender_data is None:
        return sanitized
    if not (
        is_bounded_base64_string(sender_iv, MAX_IV_BASE64_LENGTH)
        and is_bounded_base64_string(sender_data, MAX_METADATA_BASE64_LENGTH)
    ):
        return None
    sanitized["sender_iv"] = sender_iv
    sanitized["sender_data"] = sender_data
    return sanitized


def validate_text_payload(payload: dict) -> bool:
    return sanitize_text_payload(payload) is not None


def validate_file_manifest(message: dict) -> bool:
    if not (
        is_bounded_non_empty_string(message.get("transfer_id"), MAX_IDENTIFIER_LENGTH)
        and is_bounded_non_empty_string(message.get("upload_token"), MAX_IDENTIFIER_LENGTH)
        and isinstance(message.get("total_chunks"), int)
        and 1 <= message["total_chunks"] <= MAX_FILE_CHUNKS
        and isinstance(message.get("total_size"), int)
        and 0 <= message["total_size"] <= MAX_FILE_SIZE
        and isinstance(message.get("chunk_size"), int)
        and 1 <= message["chunk_size"] <= MAX_FILE_CHUNK_SIZE
        and is_bounded_base64_string(message.get("meta_iv"), MAX_IV_BASE64_LENGTH)
        and is_bounded_base64_string(message.get("meta_data"), MAX_METADATA_BASE64_LENGTH)
    ):
        return False
    expected_chunks = max(
        1,
        (message["total_size"] + message["chunk_size"] - 1) // message["chunk_size"],
    )
    return message["total_chunks"] == expected_chunks


def validate_file_chunk(message: dict) -> bool:
    return (
        is_bounded_non_empty_string(message.get("transfer_id"), MAX_IDENTIFIER_LENGTH)
        and is_bounded_non_empty_string(message.get("upload_token"), MAX_IDENTIFIER_LENGTH)
        and isinstance(message.get("index"), int)
        and 0 <= message["index"] < MAX_FILE_CHUNKS
        and is_bounded_base64_string(message.get("iv"), MAX_IV_BASE64_LENGTH)
        and is_bounded_base64_string(message.get("data"), MAX_CHUNK_BASE64_LENGTH)
    )


def validate_resume_request(message: dict) -> bool:
    return (
        is_bounded_non_empty_string(message.get("transfer_id"), MAX_IDENTIFIER_LENGTH)
        and is_bounded_non_empty_string(message.get("upload_token"), MAX_IDENTIFIER_LENGTH)
    )


def is_allowed_websocket_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    parsed_origin = urlsplit(origin)
    request_host = websocket.headers.get("host", "").lower()
    return parsed_origin.scheme in {"http", "https"} and parsed_origin.netloc.lower() == request_host


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
    if not is_allowed_websocket_origin(websocket):
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        while True:
            raw_message = await websocket.receive_text()
            if encoded_message_size(raw_message) > MAX_WEBSOCKET_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "message": "消息超过允许大小"})
                await websocket.close(code=1009)
                break
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
                try:
                    await manager.join_room(websocket, room_id)
                except ValueError as error:
                    await websocket.send_json(
                        {"type": "error", "message": resolve_transfer_error_message(error)}
                    )
                continue

            if message_type == "payload":
                payload = message.get("payload")
                sanitized_payload = sanitize_text_payload(payload) if isinstance(payload, dict) else None
                if sanitized_payload is None:
                    await websocket.send_json({"type": "error", "message": "同步内容格式无效"})
                    continue

                payload_message = json.dumps({"type": "payload", "payload": sanitized_payload})
                try:
                    await manager.store_text_and_broadcast(websocket, payload_message)
                except ValueError as error:
                    await websocket.send_json(
                        {"type": "error", "message": resolve_transfer_error_message(error)}
                    )
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
                except ValueError as error:
                    await websocket.send_json(
                        {"type": "error", "message": resolve_transfer_error_message(error)}
                    )
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
        pass
    finally:
        await manager.disconnect(websocket)


def resolve_transfer_error_message(error: ValueError) -> str:
    error_code = str(error)
    if error_code == "join_required":
        return "请先加入房间"
    if error_code == "missing_manifest":
        return "请先发送文件描述"
    if error_code == "cache_limit":
        return "服务器临时缓存已满，请稍后重试"
    if error_code in {"connection_limit", "room_limit", "room_connection_limit"}:
        return "当前连接数量已达安全上限"
    if error_code == "chunk_index":
        return "文件分片索引超出范围"
    return "传输状态已变化，请重新选择文件"


if __name__ == "__main__":
    uvicorn.run(
        app,
        # Listening on the LAN is the application's documented purpose.
        host="0.0.0.0",  # nosec B104
        port=8000,
        ws_max_size=MAX_WEBSOCKET_MESSAGE_SIZE,
    )
