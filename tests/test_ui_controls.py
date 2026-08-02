import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UIControlsTestCase(unittest.TestCase):
    def test_brand_preferences_use_sharing_board_storage_keys(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('const THEME_STORAGE_KEY = "sharing-board-theme";', script)
        self.assertIn('const ACCENT_STORAGE_KEY = "sharing-board-accent";', script)
        self.assertIn("readMigratedPreference(THEME_STORAGE_KEY", script)
        self.assertIn("localStorage.removeItem(legacyKey);", script)

    def test_single_file_limit_is_128_mb_with_256_kb_chunks(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("const MAX_FILE_SIZE = 128 * 1024 * 1024;", script)
        self.assertIn("const FILE_CHUNK_SIZE = 256 * 1024;", script)
        self.assertIn("单文件大小上限为 `128 MB`", readme)

    def test_password_toggle_updates_visible_label_and_accessible_name(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('const nextLabel = isHidden ? "隐藏" : "显示";', script)
        self.assertIn("togglePasswordBtn.textContent = nextLabel;", script)
        self.assertIn('togglePasswordBtn.setAttribute("aria-label", `${nextLabel}密码`);', script)
        self.assertIn('aria-controls="password"', template)

    def test_password_toggle_has_stable_touch_target(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        toggle_rule = styles.split(".password-toggle {", 1)[1].split("}", 1)[0]
        active_rule = styles.split(".password-toggle:active:not(:disabled) {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 58px;", toggle_rule)
        self.assertIn("min-height: 100%;", toggle_rule)
        self.assertIn("touch-action: manipulation;", toggle_rule)
        self.assertIn("transform: none;", toggle_rule)
        self.assertIn("transform: none;", active_rule)

    def test_share_panel_does_not_render_redundant_invite_link_preview(self) -> None:
        template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertNotIn("invite-link-preview", template)
        self.assertNotIn("inviteLinkPreviewEl", script)
        self.assertIn('id="copy-invite-btn"', template)

    def test_share_panel_uses_compact_icon_only_header(self) -> None:
        template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("邀请其他设备", template)
        self.assertNotIn("<h3>分享此房间</h3>", template)
        self.assertIn('class="invite-panel-head icon-only"', template)
        self.assertIn('aria-label="分享房间"', template)

    def test_device_count_uses_interconnection_wording(self) -> None:
        template = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn("设备已安全互联", template)
        self.assertIn("台设备已安全互联", script)
        self.assertNotIn("台设备已安全连接", script)

    def test_new_device_toast_only_runs_when_peer_count_increases(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn("peers > previousPeerCount", script)
        self.assertIn('document.body.dataset.stage !== "chat"', script)
        self.assertIn("presenceRefreshInFlight", script)
        self.assertIn("previousPeerCount = peers;", script)

    def test_encrypted_messages_are_processed_in_websocket_arrival_order(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn("let encryptedMessagePipeline = Promise.resolve();", script)
        self.assertIn("encryptedMessagePipeline = encryptedMessagePipeline", script)
        self.assertIn("await processEncryptedMessage(message);", script)
        self.assertIn(
            "pending.map((message) => queueOrProcessEncryptedMessage(message))",
            script,
        )

    def test_message_order_and_text_sender_identity(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("messageListEl.append(item);", script)
        self.assertIn("messageListEl.append(row);", script)
        self.assertNotIn("receivedFilesEl.prepend(item);", script)
        self.assertNotIn("messageListEl.insertBefore(row, fileBottomPanelEl);", script)
        outgoing_text_rule = styles.rsplit(".message-row.outgoing {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-direction: row-reverse;", outgoing_text_rule)
        self.assertIn("justify-content: flex-start;", outgoing_text_rule)
        self.assertIn("sender_iv: bytesToBase64(encryptedSender.iv)", script)
        self.assertIn("sender_data: bytesToBase64(encryptedSender.data)", script)
        self.assertIn('appendChatText(messageText, "outgoing", senderProfile);', script)
        self.assertIn('appendChatText(nextText, "incoming", senderProfile);', script)

    def test_file_metadata_uses_direction_specific_compact_format(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('[formatBytes(size), "已发送"]', script)
        self.assertIn('[formatBytes(size)]', script)
        self.assertNotIn("entry.createdAt", script)
        self.assertIn('entry.meta.textContent = parts.join(" ");', script)
        self.assertNotIn("发送至另一台设备", script)
        self.assertNotIn("`来自 ${normalized.nickname}`", script)
        self.assertNotIn("`${formatBytes(size)} · 未下载`", script)
        self.assertNotIn("`${formatBytes(size)} · 已下载`", script)

    def test_long_text_bubbles_use_compact_reading_width(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("max-width: min(58%, 480px);", styles)
        self.assertIn("max-width: calc(78% - 40px);", styles)

    def test_composer_avoids_mobile_focus_zoom(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        composer_rules = styles.split(".composer-shell #clipboard {")
        composer_rule = composer_rules[1].split("}", 1)[0]
        self.assertIn("font-size: 16px;", composer_rule)
        self.assertIn("touch-action: manipulation;", composer_rule)
        self.assertIn("-webkit-text-size-adjust: 100%;", styles)

    def test_text_message_footer_has_time_and_svg_copy_action(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn('footer.className = "message-bubble-footer";', script)
        self.assertIn('copyMessageButton.className = "message-copy-button";', script)
        self.assertIn('copyMessageButton.setAttribute("aria-label", "复制这条文字");', script)
        self.assertIn('<svg viewBox="0 0 24 24"', script)
        self.assertIn('<path d="M9 7V5.5A1.5 1.5', script)
        self.assertIn('<rect x="4" y="8" width="11" height="11" rx="2">', script)
        self.assertNotIn('<rect x="9" y="3"', script)
        self.assertIn("footer.append(copyMessageButton);", script)
        self.assertIn("await navigator.clipboard.writeText(text);", script)
        self.assertNotIn(".message-bubble-footer time {", styles)
        self.assertIn(".message-copy-button svg {", styles)
        self.assertIn("width: 14px;", styles)
        self.assertIn("align-items: center;", styles)

    def test_messages_share_minute_level_timeline_dividers(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn('let lastTimelineMinuteKey = "";', script)
        self.assertGreaterEqual(script.count("appendTimelineTimeDivider();"), 2)
        self.assertIn('divider.className = "conversation-time-divider";', script)
        self.assertIn('minute: "2-digit"', script)
        self.assertIn("minuteKey === lastTimelineMinuteKey", script)
        self.assertIn(".conversation-time-divider::before", styles)
        self.assertIn(".conversation-time-divider::after", styles)

    def test_file_picker_focus_does_not_draw_selection_box(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        focus_rule = styles.split(".composer-shell .upload-box:focus-within {", 1)[1].split("}", 1)[0]
        self.assertIn("outline: none !important;", focus_rule)
        self.assertIn("box-shadow: none !important;", focus_rule)
        self.assertIn("color: var(--accent);", focus_rule)

    def test_file_picker_and_text_caret_share_left_alignment(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        upload_rule = styles.split(".composer-shell .upload-box {", 1)[1].split("}", 1)[0]
        clipboard_rule = styles.split(".composer-shell #clipboard {", 1)[1].split("}", 1)[0]
        folder_rule = styles.split(".composer-shell .folder-icon {", 1)[1].split("}", 1)[0]
        self.assertIn("padding: 0 0 0 2px;", upload_rule)
        self.assertIn("justify-items: start;", upload_rule)
        self.assertIn("padding: 36px 2px 40px;", clipboard_rule)
        self.assertIn("transform: translateX(-3px);", folder_rule)

    def test_avatar_picker_uses_regular_text_weight(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        final_avatar_rule = styles.rsplit(".avatar-upload-button {", 1)[1].split("}", 1)[0]
        self.assertIn("font-weight: 400;", final_avatar_rule)

    def test_profile_save_button_uses_regular_text_weight(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        save_rule = styles.split(".profile-panel .primary-wide {", 1)[1].split("}", 1)[0]
        self.assertIn("font-weight: 400;", save_rule)

    def test_copy_invite_button_uses_regular_text_weight(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        copy_rule = styles.split("#copy-invite-btn {", 1)[1].split("}", 1)[0]
        self.assertIn("font-weight: 400;", copy_rule)

    def test_send_button_uses_regular_text_weight(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        send_rules = styles.split(".composer-shell .send-button {")
        send_rule = send_rules[1].split("}", 1)[0]
        self.assertIn("font-weight: 400;", send_rule)

    def test_device_profiles_have_stable_encrypted_short_codes(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";', script)
        self.assertIn("localStorage.setItem(\"sharing-board-device-profile\", JSON.stringify(deviceProfile));", script)
        self.assertIn("deviceId: deviceProfile?.deviceId", script)
        self.assertIn('`${profile.nickname} · ${profile.deviceId}`', script)
        self.assertIn("entry.senderName.textContent = formatSenderDisplayName(normalized);", script)
        self.assertIn("senderName.textContent = formatSenderDisplayName(normalizedSender);", script)

    def test_file_sizes_do_not_separate_numbers_and_units(self) -> None:
        script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
        self.assertIn('return "0B";', script)
        self.assertIn(')}${units[unitIndex]}`;', script)
        self.assertNotIn(')} ${units[unitIndex]}`;', script)

    def test_rounded_rectangles_share_one_radius(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("--radius-unified: 8px;", styles)
        self.assertIn("--radius-card: var(--radius-unified);", styles)
        self.assertIn("--radius-control: var(--radius-unified);", styles)
        self.assertIn("--radius-small: var(--radius-unified);", styles)
        self.assertIn(
            "border-radius: var(--radius-unified) var(--radius-unified) 0 0;",
            styles,
        )

    def test_document_file_icon_has_no_folded_corner(self) -> None:
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".file-kind-icon.document {", styles)
        self.assertNotIn(".file-kind-icon.document::after", styles)


if __name__ == "__main__":
    unittest.main()
