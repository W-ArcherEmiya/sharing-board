import unittest

from fastapi.testclient import TestClient

import main


class AppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        main.manager.rooms.clear()
        main.manager.connection_rooms.clear()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_index_page_loads(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure Clipboard", response.text)
        self.assertIn("文件传输", response.text)
        self.assertIn("邀请其他设备", response.text)

    def test_qr_api_returns_svg(self) -> None:
        response = self.client.post("/api/qr", json={"data": "https://example.test/#room=a&password=b"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("<svg", response.text)

    def test_room_isolation_and_last_payload_sync(self) -> None:
        payload = {"kind": "text", "iv": "aXY=", "data": "ZGF0YQ=="}

        with self.client.websocket_connect("/ws") as sender, self.client.websocket_connect("/ws") as receiver:
            sender.send_json({"type": "join", "room": "alpha"})
            joined = sender.receive_json()
            self.assertEqual(joined["type"], "joined")
            self.assertFalse(joined["has_text"])
            self.assertFalse(joined["has_file"])

            receiver.send_json({"type": "join", "room": "alpha"})
            joined = receiver.receive_json()
            self.assertEqual(joined["type"], "joined")
            self.assertFalse(joined["has_text"])
            self.assertFalse(joined["has_file"])

            sender.send_json({"type": "payload", "payload": payload})
            broadcast = receiver.receive_json()
            self.assertEqual(broadcast["type"], "payload")
            self.assertEqual(broadcast["payload"], payload)

        with self.client.websocket_connect("/ws") as late_alpha:
            late_alpha.send_json({"type": "join", "room": "alpha"})
            joined = late_alpha.receive_json()
            self.assertTrue(joined["has_text"])
            self.assertFalse(joined["has_file"])
            cached_payload = late_alpha.receive_json()
            self.assertEqual(cached_payload["payload"], payload)

    def test_file_transfer_replay_and_status(self) -> None:
        sender_manifest = {
            "type": "file_manifest",
            "transfer_id": "file-123",
            "upload_token": "upload-abc",
            "total_chunks": 2,
            "total_size": 12,
            "chunk_size": 6,
            "meta_iv": "bWV0YS1pdg==",
            "meta_data": "bWV0YS1kYXRh",
        }
        replay_manifest = {
            "type": "file_manifest",
            "transfer_id": "file-123",
            "total_chunks": 2,
            "total_size": 12,
            "chunk_size": 6,
            "meta_iv": "bWV0YS1pdg==",
            "meta_data": "bWV0YS1kYXRh",
        }
        chunk_one = {
            "type": "file_chunk",
            "transfer_id": "file-123",
            "upload_token": "upload-abc",
            "index": 0,
            "iv": "aXYtMA==",
            "data": "Y2h1bmstMA==",
        }
        replay_chunk_one = {
            "type": "file_chunk",
            "transfer_id": "file-123",
            "index": 0,
            "iv": "aXYtMA==",
            "data": "Y2h1bmstMA==",
        }
        chunk_two = {
            "type": "file_chunk",
            "transfer_id": "file-123",
            "upload_token": "upload-abc",
            "index": 1,
            "iv": "aXYtMQ==",
            "data": "Y2h1bmstMQ==",
        }
        replay_chunk_two = {
            "type": "file_chunk",
            "transfer_id": "file-123",
            "index": 1,
            "iv": "aXYtMQ==",
            "data": "Y2h1bmstMQ==",
        }

        with self.client.websocket_connect("/ws") as sender, self.client.websocket_connect("/ws") as receiver:
            sender.send_json({"type": "join", "room": "files"})
            sender.receive_json()

            receiver.send_json({"type": "join", "room": "files"})
            receiver.receive_json()

            sender.send_json(sender_manifest)
            self.assertEqual(receiver.receive_json(), replay_manifest)
            status = receiver.receive_json()
            self.assertEqual(status["type"], "file_status")
            self.assertEqual(status["status"], "uploading")
            self.assertEqual(status["received_chunks"], 0)

            sender.send_json(chunk_one)
            self.assertEqual(receiver.receive_json(), replay_chunk_one)
            status = receiver.receive_json()
            self.assertEqual(status["status"], "uploading")
            self.assertEqual(status["received_chunks"], 1)

            sender.send_json(chunk_two)
            self.assertEqual(receiver.receive_json(), replay_chunk_two)
            status = receiver.receive_json()
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["received_chunks"], 2)

        with self.client.websocket_connect("/ws") as late_joiner:
            late_joiner.send_json({"type": "join", "room": "files"})
            joined = late_joiner.receive_json()
            self.assertFalse(joined["has_text"])
            self.assertTrue(joined["has_file"])
            self.assertEqual(late_joiner.receive_json(), replay_manifest)
            self.assertEqual(late_joiner.receive_json(), replay_chunk_one)
            self.assertEqual(late_joiner.receive_json(), replay_chunk_two)
            replayed_status = late_joiner.receive_json()
            self.assertEqual(replayed_status["type"], "file_status")
            self.assertEqual(replayed_status["status"], "completed")

    def test_file_resume_state_after_disconnect(self) -> None:
        manifest = {
            "type": "file_manifest",
            "transfer_id": "file-456",
            "upload_token": "resume-token",
            "total_chunks": 3,
            "total_size": 18,
            "chunk_size": 6,
            "meta_iv": "bWV0YS1pdg==",
            "meta_data": "bWV0YS1kYXRh",
        }
        chunk_zero = {
            "type": "file_chunk",
            "transfer_id": "file-456",
            "upload_token": "resume-token",
            "index": 0,
            "iv": "aXYtMA==",
            "data": "Y2h1bmstMA==",
        }
        chunk_one = {
            "type": "file_chunk",
            "transfer_id": "file-456",
            "upload_token": "resume-token",
            "index": 1,
            "iv": "aXYtMQ==",
            "data": "Y2h1bmstMQ==",
        }

        sender = self.client.websocket_connect("/ws")
        receiver = self.client.websocket_connect("/ws")
        sender.__enter__()
        receiver.__enter__()
        try:
            sender.send_json({"type": "join", "room": "resume-room"})
            sender.receive_json()

            receiver.send_json({"type": "join", "room": "resume-room"})
            receiver.receive_json()

            sender.send_json(manifest)
            receiver.receive_json()
            receiver.receive_json()

            sender.send_json(chunk_zero)
            receiver.receive_json()
            receiver.receive_json()

            sender.__exit__(None, None, None)
            interrupted = receiver.receive_json()
            self.assertEqual(interrupted["type"], "file_status")
            self.assertEqual(interrupted["status"], "interrupted")

            with self.client.websocket_connect("/ws") as resumed_sender:
                resumed_sender.send_json({"type": "join", "room": "resume-room"})
                joined = resumed_sender.receive_json()
                self.assertTrue(joined["has_file"])
                self.assertEqual(resumed_sender.receive_json()["type"], "file_manifest")
                self.assertEqual(resumed_sender.receive_json()["type"], "file_chunk")
                replay_status = resumed_sender.receive_json()
                self.assertEqual(replay_status["status"], "interrupted")

                resumed_sender.send_json(
                    {
                        "type": "file_resume_request",
                        "transfer_id": "file-456",
                        "upload_token": "resume-token",
                    }
                )
                resumed_sender_status = resumed_sender.receive_json()
                self.assertEqual(resumed_sender_status["type"], "file_status")
                self.assertEqual(resumed_sender_status["status"], "resuming")

                resume_state = resumed_sender.receive_json()
                self.assertEqual(resume_state["type"], "file_resume_state")
                self.assertEqual(resume_state["missing_indexes"], [1, 2])

                resume_notice = receiver.receive_json()
                self.assertEqual(resume_notice["type"], "file_status")
                self.assertEqual(resume_notice["status"], "resuming")

                resumed_sender.send_json(chunk_one)
                self.assertEqual(receiver.receive_json()["type"], "file_chunk")
                progress_status = receiver.receive_json()
                self.assertEqual(progress_status["type"], "file_status")
                self.assertEqual(progress_status["status"], "uploading")
        finally:
            receiver.__exit__(None, None, None)

    def test_payload_requires_join(self) -> None:
        with self.client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "payload",
                    "payload": {"kind": "text", "iv": "aXY=", "data": "ZGF0YQ=="},
                }
            )
            response = websocket.receive_json()
            self.assertEqual(response["type"], "error")
            self.assertTrue(response["message"])


if __name__ == "__main__":
    unittest.main()
