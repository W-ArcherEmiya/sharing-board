import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicReadinessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        main.manager.rooms.clear()
        main.manager.connection_rooms.clear()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_http_responses_include_security_headers(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertIn("style-src 'self' 'unsafe-inline'", response.headers["content-security-policy"])
        self.assertIn("connect-src 'self' ws: wss:", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")

    def test_websocket_origin_must_match_request_host(self) -> None:
        same_origin = SimpleNamespace(
            headers={"origin": "https://192.168.1.20:8000", "host": "192.168.1.20:8000"}
        )
        foreign_origin = SimpleNamespace(
            headers={"origin": "https://attacker.example", "host": "192.168.1.20:8000"}
        )
        non_browser_client = SimpleNamespace(headers={"host": "192.168.1.20:8000"})
        self.assertTrue(main.is_allowed_websocket_origin(same_origin))
        self.assertFalse(main.is_allowed_websocket_origin(foreign_origin))
        self.assertTrue(main.is_allowed_websocket_origin(non_browser_client))

    def test_file_manifest_boundaries_are_enforced_server_side(self) -> None:
        valid = {
            "transfer_id": "transfer",
            "upload_token": "token",
            "total_chunks": 1,
            "total_size": main.MAX_FILE_CHUNK_SIZE,
            "chunk_size": main.MAX_FILE_CHUNK_SIZE,
            "meta_iv": "aXY=",
            "meta_data": "bWV0YQ==",
        }
        self.assertTrue(main.validate_file_manifest(valid))

        oversized = dict(valid, total_size=main.MAX_FILE_SIZE + 1)
        mismatched_chunks = dict(valid, total_chunks=2)
        oversized_chunk = dict(valid, chunk_size=main.MAX_FILE_CHUNK_SIZE + 1)
        self.assertFalse(main.validate_file_manifest(oversized))
        self.assertFalse(main.validate_file_manifest(mismatched_chunks))
        self.assertFalse(main.validate_file_manifest(oversized_chunk))

    def test_chunk_index_cannot_exceed_manifest(self) -> None:
        manifest = {
            "type": "file_manifest",
            "transfer_id": "bounded-file",
            "upload_token": "bounded-token",
            "total_chunks": 1,
            "total_size": 6,
            "chunk_size": 6,
            "meta_iv": "aXY=",
            "meta_data": "bWV0YQ==",
        }
        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "join", "room": "bounded-room"})
            self.assertEqual(websocket.receive_json()["type"], "joined")
            websocket.send_json(manifest)
            self.assertEqual(websocket.receive_json()["status"], "uploading")
            websocket.send_json(
                {
                    "type": "file_chunk",
                    "transfer_id": "bounded-file",
                    "upload_token": "bounded-token",
                    "index": 1,
                    "iv": "aXY=",
                    "data": "Y2h1bms=",
                }
            )
            error = websocket.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertIn("索引", error["message"])

    def test_text_payload_is_bounded_and_unknown_fields_are_removed(self) -> None:
        payload = {
            "kind": "text",
            "iv": "aXY=",
            "data": "dGV4dA==",
            "unexpected": "not-forwarded",
        }
        self.assertEqual(
            main.sanitize_text_payload(payload),
            {"kind": "text", "iv": "aXY=", "data": "dGV4dA=="},
        )
        self.assertIsNone(main.sanitize_text_payload(dict(payload, data="not-base64")))

    def test_inactive_room_cache_expires_but_active_room_is_kept(self) -> None:
        main.manager.rooms["expired"] = main.RoomState(last_activity=1.0)
        main.manager.rooms["active"] = main.RoomState(
            connections=[object()],
            last_activity=1.0,
        )
        removed = main.manager.prune_expired_rooms(now=main.ROOM_CACHE_TTL_SECONDS + 2.0)
        self.assertEqual(removed, ["expired"])
        self.assertNotIn("expired", main.manager.rooms)
        self.assertIn("active", main.manager.rooms)

    def test_public_repository_files_and_runtime_limits_exist(self) -> None:
        for relative_path in (
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "THIRD_PARTY_NOTICES.md",
            ".github/workflows/tests.yml",
            ".github/dependabot.yml",
        ):
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)

        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        launcher = (PROJECT_ROOT / "Run.bat").read_text(encoding="utf-8")
        self.assertIn("server.*.log", gitignore)
        self.assertIn("tmp/", gitignore)
        self.assertIn("--ws-max-size 524288", launcher)
        self.assertEqual(main.APP_VERSION, "1.6.1")

    def test_browser_script_has_no_duplicate_function_declarations(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        declarations = re.findall(
            r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
            script,
            flags=re.MULTILINE,
        )
        duplicates = sorted(
            name for name in set(declarations) if declarations.count(name) > 1
        )
        self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main()
