const PBKDF2_ITERATIONS = 250000;
const KEY_SALT_PREFIX = "sharing-board:v2:";
const MAX_FILE_SIZE = 64 * 1024 * 1024;
const FILE_CHUNK_SIZE = 256 * 1024;
const TEXT_SYNC_DELAY_MS = 180;
const ROOM_SYNC_DELAY_MS = 250;

let ws = null;
let sessionKey = null;
let sessionKeyFingerprint = "";
let activeRoom = "";
let keyRefreshVersion = 0;
let textSyncTimer = null;
let roomSyncTimer = null;
let pendingEncryptedMessages = [];
let activeOutgoingTransfer = null;
let outgoingTransferQueue = [];
let qrRefreshTimer = null;
let isPrimaryDevice = false;
let invitePanelManualState = null;

const incomingTransfers = new Map();
const receivedDownloads = new Map();
const transferItems = new Map();
const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const clipboardEl = document.getElementById("clipboard");
const statusEl = document.getElementById("connection-status");
const roomStatusEl = document.getElementById("room-status");
const statusSummaryEl = document.getElementById("status-summary");
const passwordEl = document.getElementById("password");
const togglePasswordBtn = document.getElementById("toggle-password-btn");
const roomEl = document.getElementById("room-id");
const logEl = document.getElementById("log");
const copyBtn = document.getElementById("copy-btn");
const clearBtn = document.getElementById("clear-btn");
const fileInputEl = document.getElementById("file-input");
const uploadBoxEl = fileInputEl.closest(".upload-box");
const fileBottomPanelEl = document.querySelector(".file-bottom-panel");
const receivedFilesEl = document.getElementById("received-files");
const copyInviteBtn = document.getElementById("copy-invite-btn");
const regenInviteBtn = document.getElementById("regen-invite-btn");
const inviteLinkPreviewEl = document.getElementById("invite-link-preview");
const inviteQrEl = document.getElementById("invite-qr");
const invitePanelEl = document.getElementById("invite-panel");
const toggleInvitePanelBtn = document.getElementById("toggle-invite-panel-btn");
const clipboardSyncStatusEl = document.getElementById("clipboard-sync-status");
const clipboardCountEl = document.getElementById("clipboard-count");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const toastEl = document.getElementById("toast");
const mobileTabButtons = Array.from(document.querySelectorAll("[data-mobile-tab]"));

passwordEl.addEventListener("input", () => {
    syncInviteState();
    void refreshSessionKey();
});

roomEl.addEventListener("input", () => {
    const nextRoom = normalizeRoom(roomEl.value);
    if (nextRoom !== activeRoom) {
        activeRoom = "";
        pendingEncryptedMessages = [];
        incomingTransfers.clear();
        activeOutgoingTransfer = null;
        outgoingTransferQueue = [];
        resetSharedState();
        applyInvitePanelState();
        setRoomStatus(nextRoom ? "加入中..." : "未加入房间", "muted");
    }
    syncInviteState();
    scheduleJoin();
    void refreshSessionKey();
});

clipboardEl.addEventListener("input", () => {
    updateControls();
    updateClipboardMeta();
    setClipboardSyncState("syncing", "同步中");
    clearTimeout(textSyncTimer);
    textSyncTimer = setTimeout(() => {
        void sendTextPayload();
    }, TEXT_SYNC_DELAY_MS);
});

copyBtn.addEventListener("click", () => {
    void copyToSystemClipboard();
});

clearBtn.addEventListener("click", () => {
    clipboardEl.value = "";
    updateClipboardMeta();
    setClipboardSyncState("syncing", "同步中");
    void sendTextPayload();
});

clipboardEl.addEventListener("input", () => {
    setClipboardSyncState("syncing", "同步中");
});

clearBtn.addEventListener("click", () => {
    setClipboardSyncState("syncing", "同步中");
});

fileInputEl.addEventListener("change", () => {
    void enqueueSelectedFiles();
});

["dragenter", "dragover"].forEach((eventName) => {
    uploadBoxEl.addEventListener(eventName, (event) => {
        event.preventDefault();
        if (!fileInputEl.disabled) {
            uploadBoxEl.classList.add("drag-active");
        }
    });
});

["dragleave", "dragend", "drop"].forEach((eventName) => {
    uploadBoxEl.addEventListener(eventName, () => {
        uploadBoxEl.classList.remove("drag-active");
    });
});

uploadBoxEl.addEventListener("drop", (event) => {
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length) {
        void enqueueFiles(files);
    }
});

togglePasswordBtn.addEventListener("click", () => {
    const isHidden = passwordEl.type === "password";
    passwordEl.type = isHidden ? "text" : "password";
    togglePasswordBtn.classList.toggle("is-visible", isHidden);
    togglePasswordBtn.setAttribute("aria-label", isHidden ? "隐藏密码" : "显示密码");
    togglePasswordBtn.setAttribute("aria-pressed", String(isHidden));
});

copyInviteBtn.addEventListener("click", () => {
    void copyInviteLink();
});

regenInviteBtn.addEventListener("click", () => {
    resetInviteCredentials();
});

themeToggleBtn.addEventListener("click", () => {
    toggleTheme();
});

toggleInvitePanelBtn.addEventListener("click", () => {
    const isCollapsed = invitePanelEl.classList.contains("collapsed");
    invitePanelManualState = isCollapsed ? "expanded" : "collapsed";
    applyInvitePanelState();
});

mobileTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
        setActiveMobileTab(button.dataset.mobileTab);
    });
});

function initializeInviteCredentials() {
    const inviteParams = new URLSearchParams(window.location.hash.slice(1));
    const hashRoom = normalizeRoom(inviteParams.get("room") || "");
    const hashPassword = inviteParams.get("password") || "";
    isPrimaryDevice = inviteParams.get("host") === "1";

    roomEl.value = hashRoom || generateReadableCode(8);
    passwordEl.value = hashPassword || generateReadableCode(12);
    syncInviteState();
    applyInvitePanelState();
}

function resetInviteCredentials() {
    roomEl.value = generateReadableCode(8);
    passwordEl.value = generateReadableCode(12);
    activeRoom = "";
    pendingEncryptedMessages = [];
    incomingTransfers.clear();
    activeOutgoingTransfer = null;
    outgoingTransferQueue = [];
    invitePanelManualState = null;
    resetSharedState();
    setRoomStatus("加入中...", "muted");
    syncInviteState();
    applyInvitePanelState();
    scheduleJoin();
    void refreshSessionKey();
}

function syncInviteState() {
    const room = normalizeRoom(roomEl.value);
    const password = passwordEl.value.trim();
    const inviteLink = buildInviteLink(room, password);

    inviteLinkPreviewEl.textContent = inviteLink || "邀请链接生成中...";

    updateAddressBar(room, password);
    scheduleQrRefresh(inviteLink);
}

function buildInviteLink(room, password) {
    if (!room || !password) {
        return "";
    }

    const hash = new URLSearchParams({ room, password }).toString();
    return `${window.location.origin}${window.location.pathname}#${hash}`;
}

function updateAddressBar(room, password) {
    const params = new URLSearchParams();
    if (room && password) {
        params.set("room", room);
        params.set("password", password);
    }
    if (isPrimaryDevice) {
        params.set("host", "1");
    }
    const hash = params.toString() ? `#${params.toString()}` : "";
    history.replaceState(null, "", `${window.location.pathname}${hash}`);
}

function applyInvitePanelState() {
    const shouldCollapse = invitePanelManualState === "expanded" ? false : true;

    invitePanelEl.classList.toggle("collapsed", shouldCollapse);
    toggleInvitePanelBtn.textContent = shouldCollapse ? "展开二维码与邀请信息" : "收起二维码与邀请信息";
    toggleInvitePanelBtn.setAttribute("aria-expanded", String(!shouldCollapse));
}

function setActiveMobileTab(tabName) {
    const knownTabs = new Set(["text", "file", "connect"]);
    const nextTab = knownTabs.has(tabName) ? tabName : "file";
    document.body.dataset.mobileTab = nextTab;

    for (const button of mobileTabButtons) {
        const isActive = button.dataset.mobileTab === nextTab;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-current", isActive ? "page" : "false");
    }
}

function scheduleQrRefresh(inviteLink) {
    clearTimeout(qrRefreshTimer);

    if (!inviteLink) {
        inviteQrEl.textContent = "等待邀请码";
        return;
    }

    qrRefreshTimer = setTimeout(() => {
        void renderInviteQr(inviteLink);
    }, 180);
}

async function renderInviteQr(inviteLink) {
    try {
        inviteQrEl.textContent = "二维码生成中...";
        const response = await fetch("/api/qr", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data: inviteLink }),
        });

        if (!response.ok) {
            throw new Error(`QR request failed: ${response.status}`);
        }

        inviteQrEl.innerHTML = await response.text();
    } catch (error) {
        console.error(error);
        inviteQrEl.textContent = "二维码生成失败";
    }
}

async function copyInviteLink() {
    const inviteLink = buildInviteLink(normalizeRoom(roomEl.value), passwordEl.value.trim());
    if (!inviteLink) {
        logEl.textContent = "请先生成有效的房间号和密码";
        return;
    }

    try {
        await navigator.clipboard.writeText(inviteLink);
        showButtonFeedback(copyInviteBtn, "已复制");
        logEl.textContent = "邀请链接已复制";
    } catch (error) {
        console.error(error);
        logEl.textContent = "复制邀请链接失败";
    }
}

function connect() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        statusEl.textContent = "已连接";
        statusSummaryEl.className = "status-summary connected";
        scheduleJoin();
        updateControls();
    };

    ws.onmessage = async (event) => {
        let message;
        try {
            message = JSON.parse(event.data);
        } catch (error) {
            console.error(error);
            logEl.textContent = "收到无法识别的服务器消息";
            return;
        }

        if (message.type === "joined") {
            activeRoom = message.room;
            setRoomStatus(`房间: ${message.room}`, "connected");
            applyInvitePanelState();
            updateControls();
            logEl.textContent =
                message.has_text || message.has_file
                    ? "已加入房间，正在恢复最近同步内容"
                    : "已加入房间，暂无历史内容";
            maybeResumeOutgoingTransfer();
            return;
        }

        if (message.type === "payload" || message.type === "file_manifest" || message.type === "file_chunk") {
            await queueOrProcessEncryptedMessage(message);
            return;
        }

        if (message.type === "file_status") {
            handleFileStatus(message);
            return;
        }

        if (message.type === "file_resume_state") {
            await handleResumeState(message);
            return;
        }

        if (message.type === "error") {
            logEl.textContent = message.message || "服务器返回错误";
        }
    };

    ws.onclose = () => {
        statusEl.textContent = "断开连接";
        statusSummaryEl.className = "status-summary disconnected";
        activeRoom = "";
        pendingEncryptedMessages = [];
        incomingTransfers.clear();
        if (activeOutgoingTransfer && !activeOutgoingTransfer.completed) {
            activeOutgoingTransfer.dispatchToken += 1;
            setTransferInfo(
                activeOutgoingTransfer.metadata.fileName,
                activeOutgoingTransfer.metadata.size,
                "连接中断，等待重连续传"
            );
        }
        updateControls();
        setRoomStatus("连接断开，等待重连", "muted");
        applyInvitePanelState();
        setTimeout(connect, 3000);
    };
}

function scheduleJoin() {
    clearTimeout(roomSyncTimer);
    roomSyncTimer = setTimeout(() => {
        sendJoinMessage();
    }, ROOM_SYNC_DELAY_MS);
}

function sendJoinMessage() {
    const room = normalizeRoom(roomEl.value);
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        updateControls();
        return;
    }

    if (!room) {
        activeRoom = "";
        applyInvitePanelState();
        setRoomStatus("未加入房间", "muted");
        updateControls();
        return;
    }

    if (!hasSessionKeyFor(room, passwordEl.value)) {
        setRoomStatus("正在准备会话密钥...", "muted");
        updateControls();
        return;
    }

    if (activeRoom === room) {
        updateControls();
        return;
    }

    ws.send(JSON.stringify({ type: "join", room }));
    setRoomStatus("加入中...", "muted");
    updateControls();
}

async function refreshSessionKey() {
    const version = ++keyRefreshVersion;
    const password = passwordEl.value;
    const room = normalizeRoom(roomEl.value);
    sessionKey = null;
    sessionKeyFingerprint = "";

    if (!password || !room) {
        updateControls();
        return;
    }

    try {
        logEl.textContent = "正在生成会话密钥...";
        const keyMaterial = await crypto.subtle.importKey(
            "raw",
            textEncoder.encode(password),
            "PBKDF2",
            false,
            ["deriveKey"]
        );
        setClipboardSyncState("synced", "已同步");

        const derivedKey = await crypto.subtle.deriveKey(
            {
                name: "PBKDF2",
                salt: textEncoder.encode(`${KEY_SALT_PREFIX}${room}`),
                iterations: PBKDF2_ITERATIONS,
                hash: "SHA-256",
            },
            keyMaterial,
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"]
        );

        if (version !== keyRefreshVersion) {
            return;
        }

        sessionKey = derivedKey;
        sessionKeyFingerprint = createSessionKeyFingerprint(room, password);
        logEl.textContent = "会话密钥已就绪";
        updateControls();
        await flushPendingEncryptedMessages();
        scheduleJoin();
        maybeResumeOutgoingTransfer();
    } catch (error) {
        console.error(error);
        setClipboardSyncState("error", "同步失败");
        if (version === keyRefreshVersion) {
            sessionKey = null;
            sessionKeyFingerprint = "";
            logEl.textContent = "会话密钥生成失败";
            updateControls();
        }
    }
}

async function sendTextPayload() {
    if (!canSync()) {
        return;
    }

    try {
        const encrypted = await encryptBytes(textEncoder.encode(clipboardEl.value));
        ws.send(
            JSON.stringify({
                type: "payload",
                payload: {
                    kind: "text",
                    iv: bytesToBase64(encrypted.iv),
                    data: bytesToBase64(encrypted.data),
                },
            })
        );
        logEl.textContent = "文字已加密并同步";
    } catch (error) {
        console.error(error);
        logEl.textContent = "文字同步失败";
    }
}

async function enqueueSelectedFiles() {
    const files = Array.from(fileInputEl.files || []);
    fileInputEl.value = "";
    await enqueueFiles(files);
}

async function enqueueFiles(files) {
    if (!files.length) {
        return;
    }

    if (!canSync()) {
        logEl.textContent = "请先连接服务器、加入房间并输入密码";
        return;
    }

    const validFiles = [];
    let skippedCount = 0;
    const room = normalizeRoom(roomEl.value);

    for (const file of files) {
        if (file.size > MAX_FILE_SIZE) {
            skippedCount += 1;
            continue;
        }

        validFiles.push(createOutgoingTransfer(file, room));
    }

    if (!validFiles.length) {
        logEl.textContent = `所选文件均超过 ${formatBytes(MAX_FILE_SIZE)}，未加入队列`;
        return;
    }

    validFiles.forEach((transfer) => {
        updateTransferItemProgress(transfer.transferId, transfer.metadata.fileName, transfer.metadata.size, 0);
    });
    outgoingTransferQueue = outgoingTransferQueue.concat(validFiles);

    if (skippedCount) {
        logEl.textContent = `${validFiles.length} 个文件已加入队列，${skippedCount} 个因过大被跳过`;
    } else {
        logEl.textContent = `${validFiles.length} 个文件已加入传输队列`;
    }

    if (!activeOutgoingTransfer) {
        await startNextQueuedTransfer();
        return;
    }

    updateTransferQueueHint(activeOutgoingTransfer);
}

function createOutgoingTransfer(file, room) {
    return {
        file,
        room,
        transferId: createTransferId(),
        uploadToken: createTransferToken(),
        metadata: {
            fileName: file.name,
            mimeType: file.type || "application/octet-stream",
            size: file.size,
        },
        totalChunks: Math.max(1, Math.ceil(file.size / FILE_CHUNK_SIZE)),
        started: false,
        completed: false,
        dispatchToken: 0,
    };
}

async function startNextQueuedTransfer() {
    if (activeOutgoingTransfer || !outgoingTransferQueue.length) {
        return;
    }

    activeOutgoingTransfer = outgoingTransferQueue.shift();
    setTransferInfo(
        activeOutgoingTransfer.metadata.fileName,
        activeOutgoingTransfer.metadata.size,
        "准备加密并启动传输"
    );
    updateTransferQueueHint(activeOutgoingTransfer);
    await startOrResumeOutgoingTransfer(activeOutgoingTransfer);
}

async function startOrResumeOutgoingTransfer(transfer) {
    if (activeOutgoingTransfer !== transfer || transfer.completed) {
        return;
    }

    if (!canSync() || normalizeRoom(roomEl.value) !== transfer.room) {
        setTransferInfo(
            transfer.metadata.fileName,
            transfer.metadata.size,
            "连接未就绪，等待自动续传"
        );
        updateTransferQueueHint(transfer);
        return;
    }

    try {
        if (!transfer.started) {
            const encryptedMetadata = await encryptBytes(
                textEncoder.encode(JSON.stringify(transfer.metadata))
            );
            ws.send(
                JSON.stringify({
                    type: "file_manifest",
                    transfer_id: transfer.transferId,
                    upload_token: transfer.uploadToken,
                    total_chunks: transfer.totalChunks,
                    total_size: transfer.metadata.size,
                    chunk_size: FILE_CHUNK_SIZE,
                    meta_iv: bytesToBase64(encryptedMetadata.iv),
                    meta_data: bytesToBase64(encryptedMetadata.data),
                })
            );
            transfer.started = true;
            setTransferInfo(
                transfer.metadata.fileName,
                transfer.metadata.size,
                "文件描述已发送，正在确认续传位置"
            );
            updateTransferQueueHint(transfer);
        }

        requestResumeState(transfer);
    } catch (error) {
        console.error(error);
        setTransferInfo(transfer.metadata.fileName, transfer.metadata.size, "文件初始化失败");
    }
}

function requestResumeState(transfer) {
    if (activeOutgoingTransfer !== transfer || transfer.completed || !canSync()) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "file_resume_request",
            transfer_id: transfer.transferId,
            upload_token: transfer.uploadToken,
        })
    );
}

function maybeResumeOutgoingTransfer() {
    if (
        activeOutgoingTransfer &&
        !activeOutgoingTransfer.completed &&
        activeOutgoingTransfer.room === normalizeRoom(roomEl.value) &&
        canSync()
    ) {
        void startOrResumeOutgoingTransfer(activeOutgoingTransfer);
        return;
    }

    if (!activeOutgoingTransfer && outgoingTransferQueue.length && canSync()) {
        void startNextQueuedTransfer();
    }
}

async function handleResumeState(message) {
    const transfer = activeOutgoingTransfer;
    if (!transfer || transfer.transferId !== message.transfer_id || transfer.completed) {
        return;
    }

    if (message.completed || message.missing_indexes.length === 0) {
        await markOutgoingTransferComplete(transfer);
        return;
    }

    const receivedProgress = Math.round((message.received_chunks / message.total_chunks) * 100);
    setTransferInfo(
        transfer.metadata.fileName,
        transfer.metadata.size,
        `服务器已接收 ${receivedProgress}% ，继续补传`
    );
    updateTransferQueueHint(transfer);
    await sendMissingChunks(transfer, message.missing_indexes, message.received_chunks);
}

async function sendMissingChunks(transfer, missingIndexes, initialReceivedCount) {
    const runToken = ++transfer.dispatchToken;
    let completedInRun = initialReceivedCount;

    for (let position = 0; position < missingIndexes.length; position += 1) {
        if (
            activeOutgoingTransfer !== transfer ||
            transfer.completed ||
            transfer.dispatchToken !== runToken
        ) {
            return;
        }

        if (!canSync() || activeRoom !== transfer.room) {
            setTransferInfo(
                transfer.metadata.fileName,
                transfer.metadata.size,
                "连接中断，等待重连续传"
            );
            updateTransferQueueHint(transfer);
            return;
        }

        const index = missingIndexes[position];
        const start = index * FILE_CHUNK_SIZE;
        const end = Math.min(transfer.metadata.size, start + FILE_CHUNK_SIZE);
        const chunkBytes = new Uint8Array(await transfer.file.slice(start, end).arrayBuffer());
        const encryptedChunk = await encryptBytes(chunkBytes);

        ws.send(
            JSON.stringify({
                type: "file_chunk",
                transfer_id: transfer.transferId,
                upload_token: transfer.uploadToken,
                index,
                iv: bytesToBase64(encryptedChunk.iv),
                data: bytesToBase64(encryptedChunk.data),
            })
        );

        completedInRun += 1;
        const progress = Math.round((completedInRun / transfer.totalChunks) * 100);
        setTransferInfo(
            transfer.metadata.fileName,
            transfer.metadata.size,
            `正在发送分片 ${index + 1}/${transfer.totalChunks} · ${progress}%`
        );
        updateTransferQueueHint(transfer);

        if (position % 4 === 3) {
            await nextFrame();
        }
    }

    setTransferInfo(transfer.metadata.fileName, transfer.metadata.size, "分片已发送，等待房间确认");
    updateTransferQueueHint(transfer);
}

async function queueOrProcessEncryptedMessage(message) {
    if (!sessionKey) {
        pendingEncryptedMessages.push(message);
        logEl.textContent = "收到密文，请输入正确房间号和密码";
        return;
    }

    await processEncryptedMessage(message);
}

async function flushPendingEncryptedMessages() {
    if (!sessionKey || pendingEncryptedMessages.length === 0) {
        return;
    }

    const pending = pendingEncryptedMessages;
    pendingEncryptedMessages = [];

    for (const message of pending) {
        await processEncryptedMessage(message);
    }
}

async function processEncryptedMessage(message) {
    if (message.type === "payload") {
        await handleTextPayload(message.payload);
        return;
    }

    if (message.type === "file_manifest") {
        await handleFileManifest(message);
        return;
    }

    if (message.type === "file_chunk") {
        await handleFileChunk(message);
    }
}

async function handleTextPayload(payload) {
    if (!payload || typeof payload !== "object") {
        logEl.textContent = "收到无效文字内容";
        return;
    }

    try {
        const decryptedBytes = await decryptBase64Envelope(payload.iv, payload.data);
        const nextText = textDecoder.decode(decryptedBytes);
        if (clipboardEl.value !== nextText) {
            clipboardEl.value = nextText;
        }
        updateClipboardMeta();
        setClipboardSyncState("synced", "已同步");
        logEl.textContent = "文字已解密并更新";
        updateControls();
    } catch (error) {
        console.error(error);
        pendingEncryptedMessages = [messageEnvelope("payload", payload)];
        setClipboardSyncState("error", "解密失败");
        logEl.textContent = "文字解密失败，请检查房间号和密码";
    }
}

async function handleFileManifest(message) {
    if (activeOutgoingTransfer && activeOutgoingTransfer.transferId === message.transfer_id) {
        return;
    }

    try {
        const decryptedMetadataBytes = await decryptBase64Envelope(
            message.meta_iv,
            message.meta_data
        );
        const metadata = JSON.parse(textDecoder.decode(decryptedMetadataBytes));

        incomingTransfers.set(message.transfer_id, {
            metadata,
            totalChunks: message.total_chunks,
            totalSize: message.total_size,
            receivedChunks: 0,
            chunks: new Array(message.total_chunks),
            completed: false,
        });

        updateTransferItemProgress(message.transfer_id, metadata.fileName, metadata.size, 0);
    } catch (error) {
        console.error(error);
        pendingEncryptedMessages.push(message);
        logEl.textContent = "文件描述解密失败，请检查房间号和密码";
    }
}

async function handleFileChunk(message) {
    if (activeOutgoingTransfer && activeOutgoingTransfer.transferId === message.transfer_id) {
        return;
    }

    const transfer = incomingTransfers.get(message.transfer_id);
    if (!transfer) {
        pendingEncryptedMessages.push(message);
        return;
    }

    if (message.index < 0 || message.index >= transfer.totalChunks) {
        logEl.textContent = "收到非法文件分片";
        return;
    }

    if (transfer.chunks[message.index]) {
        return;
    }

    try {
        transfer.chunks[message.index] = await decryptBase64Envelope(message.iv, message.data);
        transfer.receivedChunks += 1;
        const progress = Math.round((transfer.receivedChunks / transfer.totalChunks) * 100);
        updateTransferItemProgress(message.transfer_id, transfer.metadata.fileName, transfer.totalSize, progress);

        if (transfer.receivedChunks === transfer.totalChunks) {
            const blob = new Blob(transfer.chunks, {
                type: transfer.metadata.mimeType || "application/octet-stream",
            });
            transfer.completed = true;
            transfer.chunks = [];
            addDownloadableFile(message.transfer_id, transfer.metadata.fileName, blob, transfer.totalSize);
            hideTransferSummary();
            logEl.textContent = "文件已解密并组装完成";
        }
    } catch (error) {
        console.error(error);
        incomingTransfers.delete(message.transfer_id);
        pendingEncryptedMessages.push(message);
        logEl.textContent = "文件分片解密失败，请检查房间号和密码";
    }
}

function handleFileStatus(message) {
    const statusText = describeTransferStatus(message.status, message.received_chunks, message.total_chunks);

    if (activeOutgoingTransfer && activeOutgoingTransfer.transferId === message.transfer_id) {
        if (message.status === "completed") {
            void markOutgoingTransferComplete(activeOutgoingTransfer);
            return;
        }
        const progress = message.total_chunks > 0
            ? Math.round((message.received_chunks / message.total_chunks) * 100)
            : 0;
        updateTransferItemProgress(
            activeOutgoingTransfer.transferId,
            activeOutgoingTransfer.metadata.fileName,
            activeOutgoingTransfer.metadata.size,
            progress
        );
        updateTransferQueueHint(activeOutgoingTransfer);
        return;
    }

    const transfer = incomingTransfers.get(message.transfer_id);
    if (transfer) {
        if (message.status === "completed") {
            hideTransferSummary();
            return;
        }
        const progress = message.total_chunks > 0
            ? Math.round((message.received_chunks / message.total_chunks) * 100)
            : 0;
        updateTransferItemProgress(message.transfer_id, transfer.metadata.fileName, transfer.totalSize, progress);
        return;
    }

    if (message.status === "completed") {
        hideTransferSummary();
        return;
    }

    logEl.textContent = "收到文件状态，等待文件描述解密";
}

async function markOutgoingTransferComplete(transfer) {
    if (activeOutgoingTransfer !== transfer) {
        return;
    }

    transfer.completed = true;
    transfer.dispatchToken += 1;
    logEl.textContent = `${transfer.metadata.fileName} 传输完成`;
    markTransferItemSent(transfer.transferId, transfer.metadata.fileName, transfer.metadata.size);
    activeOutgoingTransfer = null;

    if (outgoingTransferQueue.length) {
        await startNextQueuedTransfer();
        return;
    }

    hideTransferSummary();
}

async function encryptBytes(bytes) {
    if (!sessionKey) {
        throw new Error("missing session key");
    }

    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, sessionKey, bytes);

    return {
        iv,
        data: new Uint8Array(ciphertext),
    };
}

async function decryptBase64Envelope(ivBase64, dataBase64) {
    if (!sessionKey) {
        throw new Error("missing session key");
    }

    const iv = base64ToBytes(ivBase64);
    const data = base64ToBytes(dataBase64);
    const plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, sessionKey, data);
    return new Uint8Array(plaintext);
}

async function copyToSystemClipboard() {
    try {
        await navigator.clipboard.writeText(clipboardEl.value);
        showButtonFeedback(copyBtn, "已复制");
        logEl.textContent = "文本已复制到系统剪贴板";
    } catch (error) {
        console.error(error);
        clipboardEl.select();
        document.execCommand("copy");
        showButtonFeedback(copyBtn, "已复制");
        logEl.textContent = "文本已复制";
    }
}

function showButtonFeedback(button, text) {
    const originalText = button.dataset.originalText || button.textContent;
    button.dataset.originalText = originalText;
    button.textContent = text;
    clearTimeout(Number(button.dataset.resetTimer || 0));
    const timer = window.setTimeout(() => {
        button.textContent = originalText;
    }, 1600);
    button.dataset.resetTimer = String(timer);
}

function addDownloadableFile(transferId, fileName, blob, size) {
    removeDownloadableFile(transferId);

    const url = URL.createObjectURL(blob);
    const entry = ensureTransferItem(transferId, fileName, size);
    entry.element.classList.add("download-ready");
    entry.meta.textContent = formatBytes(size);
    entry.actions.replaceChildren();

    const link = document.createElement("a");
    link.className = "download-link";
    link.href = url;
    link.download = fileName;
    link.setAttribute("aria-label", `下载 ${fileName}`);
    link.title = "下载";
    link.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M12 3v14"></path>
            <path d="m6 11 6 6 6-6"></path>
        </svg>
    `;
    link.addEventListener("click", () => {
        entry.element.classList.add("downloaded");
        entry.meta.textContent = `${formatBytes(size)} · 已下载`;
        hideTransferSummary();
        logEl.textContent = `${fileName} 已下载`;
    });

    entry.actions.append(link);
    receivedDownloads.set(transferId, { url, element: entry.element });
    updateReceivedFilesVisibility();
}

function removeDownloadableFile(transferId) {
    const existing = receivedDownloads.get(transferId);
    if (!existing) {
        return;
    }

    URL.revokeObjectURL(existing.url);
    receivedDownloads.delete(transferId);
    removeTransferItem(transferId);
}

function ensureTransferItem(transferId, fileName, size) {
    const existing = transferItems.get(transferId);
    if (existing) {
        existing.title.textContent = fileName;
        existing.meta.textContent = formatBytes(size);
        return existing;
    }

    const item = document.createElement("div");
    item.className = "received-file transfer-item";

    const main = document.createElement("div");
    main.className = "received-file-main";

    const info = document.createElement("div");
    info.className = "received-file-info";
    const title = document.createElement("strong");
    title.textContent = fileName;
    const meta = document.createElement("span");
    meta.textContent = formatBytes(size);
    info.append(title, meta);

    const actions = document.createElement("div");
    actions.className = "received-file-actions";
    main.append(info, actions);

    const progress = document.createElement("div");
    progress.className = "file-item-progress";
    const progressTrack = document.createElement("div");
    progressTrack.className = "file-item-progress-track";
    const progressBar = document.createElement("div");
    progressBar.className = "file-item-progress-bar";
    progressTrack.append(progressBar);
    const progressText = document.createElement("span");
    progressText.className = "file-item-progress-text";
    progressText.textContent = "0%";
    progress.append(progressTrack, progressText);

    item.append(main, progress);
    receivedFilesEl.prepend(item);

    const entry = { element: item, title, meta, actions, progressBar, progressText };
    transferItems.set(transferId, entry);
    updateReceivedFilesVisibility();
    return entry;
}

function updateTransferItemProgress(transferId, fileName, size, progress) {
    const entry = ensureTransferItem(transferId, fileName, size);
    const nextProgress = Math.max(0, Math.min(100, Math.round(progress)));
    entry.progressBar.style.width = `${nextProgress}%`;
    entry.progressText.textContent = `${nextProgress}%`;
    entry.element.classList.toggle("complete", nextProgress >= 100);
}

function updateMatchingTransferItem(fileName, size, progress) {
    for (const [transferId, entry] of transferItems.entries()) {
        if (entry.title.textContent === fileName && entry.meta.textContent === formatBytes(size)) {
            updateTransferItemProgress(transferId, fileName, size, progress);
            return true;
        }
    }

    return false;
}

function markTransferItemSent(transferId, fileName, size) {
    const entry = ensureTransferItem(transferId, fileName, size);
    updateTransferItemProgress(transferId, fileName, size, 100);
    entry.element.classList.add("sent");
    entry.actions.replaceChildren();
    updateReceivedFilesVisibility();
}

function removeTransferItem(transferId) {
    const existing = transferItems.get(transferId);
    if (!existing) {
        return;
    }

    existing.element.remove();
    transferItems.delete(transferId);
    updateReceivedFilesVisibility();
}

function resetSharedState() {
    clipboardEl.value = "";
    setTransferActivity(false);
    incomingTransfers.clear();

    for (const { url, element } of receivedDownloads.values()) {
        URL.revokeObjectURL(url);
        element.remove();
    }
    receivedDownloads.clear();
    for (const { element } of transferItems.values()) {
        element.remove();
    }
    transferItems.clear();
    updateReceivedFilesVisibility();

    setClipboardSyncState("idle", "等待同步");
    updateClipboardMeta();
    updateControls();
}

function updateControls() {
    const ready = canSync();
    clipboardEl.disabled = !ready;
    fileInputEl.disabled = !ready;
    uploadBoxEl.classList.toggle("disabled", !ready);
    copyBtn.disabled = !clipboardEl.value;
    clearBtn.disabled = !ready;
    updateClipboardMeta();
}

function canSync() {
    const room = normalizeRoom(roomEl.value);
    return Boolean(
        ws &&
            ws.readyState === WebSocket.OPEN &&
            room &&
            activeRoom === room &&
            hasSessionKeyFor(room, passwordEl.value)
    );
}

function createSessionKeyFingerprint(room, password) {
    return `${room}\n${password}`;
}

function hasSessionKeyFor(room, password) {
    return Boolean(
        sessionKey &&
            room &&
            password &&
            sessionKeyFingerprint === createSessionKeyFingerprint(room, password)
    );
}

function setClipboardSyncState(state, text) {
    clipboardSyncStatusEl.textContent = text;
    clipboardSyncStatusEl.className = `sync-pill ${state}`;
}

function updateClipboardMeta() {
    clipboardCountEl.textContent = `${clipboardEl.value.length} 字`;
}

function setRoomStatus(text, state) {
    roomStatusEl.textContent = text;
    statusSummaryEl.className = `status-summary ${state}`;
}

function setTransferInfo(fileName, size, statusText) {
    const progress = inferTransferProgress(statusText);
    if (progress === null) {
        return;
    }

    if (activeOutgoingTransfer) {
        updateTransferItemProgress(
            activeOutgoingTransfer.transferId,
            activeOutgoingTransfer.metadata.fileName,
            activeOutgoingTransfer.metadata.size,
            progress
        );
        return;
    }

    updateMatchingTransferItem(fileName, size, progress);
}

function setTransferActivity(active) {
    fileBottomPanelEl.classList.toggle("has-transfer", active);
}

function updateReceivedFilesVisibility() {
    fileBottomPanelEl.classList.toggle("has-received-files", transferItems.size > 0);
}

function hideTransferSummary() {
    setTransferActivity(false);
}

function updateTransferQueueHint(transfer) {
    return transfer;
}

function describeTransferStatus(status, receivedChunks, totalChunks) {
    const progress = totalChunks > 0 ? Math.round((receivedChunks / totalChunks) * 100) : 0;

    if (status === "uploading") {
        return `房间已接收 ${progress}%`;
    }
    if (status === "resuming") {
        return `检测到断点，正在续传 ${progress}%`;
    }
    if (status === "interrupted") {
        return "传输已中断，等待原发送端重连续传";
    }
    if (status === "completed") {
        return "传输完成";
    }
    return "等待传输";
}

function normalizeRoom(value) {
    const room = value.trim();
    return room ? room.slice(0, 64) : "";
}

function generateReadableCode(length) {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz";
    const bytes = crypto.getRandomValues(new Uint8Array(length));
    let output = "";

    for (let index = 0; index < length; index += 1) {
        output += alphabet[bytes[index] % alphabet.length];
    }

    return output;
}

function createTransferId() {
    if (crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return `transfer-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createTransferToken() {
    if (crypto.randomUUID) {
        return `token-${crypto.randomUUID()}`;
    }
    return `token-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function bytesToBase64(bytes) {
    let binary = "";
    const chunkSize = 0x8000;

    for (let index = 0; index < bytes.length; index += chunkSize) {
        const chunk = bytes.subarray(index, index + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }

    return btoa(binary);
}

function base64ToBytes(base64Value) {
    const binary = atob(base64Value);
    const bytes = new Uint8Array(binary.length);

    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
    }

    return bytes;
}

function formatBytes(size) {
    if (!Number.isFinite(size) || size <= 0) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    const unitIndex = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
    const value = size / 1024 ** unitIndex;
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function nextFrame() {
    return new Promise((resolve) => {
        requestAnimationFrame(() => resolve());
    });
}

function messageEnvelope(type, payload) {
    return { type, payload };
}

function initializeTheme() {
    const savedTheme = localStorage.getItem("secure-clipboard-theme");
    document.body.classList.toggle("theme-dark", savedTheme === "dark");
    updateThemeToggleButton();
}

function toggleTheme() {
    const nextDark = !document.body.classList.contains("theme-dark");
    document.body.classList.toggle("theme-dark", nextDark);
    localStorage.setItem("secure-clipboard-theme", nextDark ? "dark" : "light");
    updateThemeToggleButton();
}

function updateThemeToggleButton() {
    const isDark = document.body.classList.contains("theme-dark");
    themeToggleBtn.setAttribute("aria-pressed", String(isDark));
    themeToggleBtn.querySelector(".theme-switch-label").textContent = isDark ? "深色模式" : "浅色模式";
}

function applyInvitePanelState() {
    const shouldCollapse = invitePanelManualState === "expanded" ? false : true;
    invitePanelEl.classList.toggle("collapsed", shouldCollapse);
    toggleInvitePanelBtn.textContent = shouldCollapse ? "展开二维码与邀请信息" : "收起二维码与邀请信息";
    toggleInvitePanelBtn.setAttribute("aria-expanded", String(!shouldCollapse));
}

function setClipboardSyncState(state, text) {
    clipboardSyncStatusEl.textContent = text;
    clipboardSyncStatusEl.className = `sync-pill ${state}`;
}

function inferTransferProgress(statusText) {
    const matchedProgress = /(\d{1,3})%/.exec(statusText);
    if (matchedProgress) {
        return Math.max(0, Math.min(100, Number(matchedProgress[1])));
    }
    if (/完成|下载|可立即/.test(statusText)) {
        return 100;
    }
    return null;
}

function updateTransferProgress(progress) {
    if (!activeOutgoingTransfer) {
        return;
    }

    updateTransferItemProgress(
        activeOutgoingTransfer.transferId,
        activeOutgoingTransfer.metadata.fileName,
        activeOutgoingTransfer.metadata.size,
        progress
    );
}

function setTransferInfo(fileName, size, statusText) {
    const inferredProgress = inferTransferProgress(statusText);
    if (inferredProgress === null) {
        return;
    }

    if (activeOutgoingTransfer) {
        updateTransferItemProgress(
            activeOutgoingTransfer.transferId,
            activeOutgoingTransfer.metadata.fileName,
            activeOutgoingTransfer.metadata.size,
            inferredProgress
        );
        return;
    }

    updateMatchingTransferItem(fileName, size, inferredProgress);
}

function setRoomStatus(text, state) {
    roomStatusEl.textContent = text;
    statusSummaryEl.className = `status-summary ${state}`;
}

function showToast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("visible");
    clearTimeout(Number(toastEl.dataset.timer || 0));
    const timer = window.setTimeout(() => {
        toastEl.classList.remove("visible");
    }, 1600);
    toastEl.dataset.timer = String(timer);
}

const originalShowButtonFeedback = showButtonFeedback;
showButtonFeedback = function showButtonFeedbackWithToast(button, text) {
    originalShowButtonFeedback(button, text);
    showToast(text);
};

async function sendTextPayload() {
    if (!canSync()) {
        return;
    }

    try {
        const encrypted = await encryptBytes(textEncoder.encode(clipboardEl.value));
        ws.send(
            JSON.stringify({
                type: "payload",
                payload: {
                    kind: "text",
                    iv: bytesToBase64(encrypted.iv),
                    data: bytesToBase64(encrypted.data),
                },
            })
        );
        setClipboardSyncState("synced", "已同步");
        logEl.textContent = "文字已加密并同步";
    } catch (error) {
        console.error(error);
        setClipboardSyncState("error", "同步失败");
        logEl.textContent = "文字同步失败";
    }
}

async function handleTextPayload(payload) {
    if (!payload || typeof payload !== "object") {
        logEl.textContent = "收到无效文字内容";
        return;
    }

    try {
        const decryptedBytes = await decryptBase64Envelope(payload.iv, payload.data);
        const nextText = textDecoder.decode(decryptedBytes);
        if (clipboardEl.value !== nextText) {
            clipboardEl.value = nextText;
        }
        updateClipboardMeta();
        setClipboardSyncState("synced", "已同步");
        logEl.textContent = "文字已更新";
        updateControls();
    } catch (error) {
        console.error(error);
        pendingEncryptedMessages = [messageEnvelope("payload", payload)];
        setClipboardSyncState("error", "解密失败");
        logEl.textContent = "文字解密失败，请检查房间号和密码";
    }
}

function handleFileStatus(message) {
    const statusText = describeTransferStatus(message.status, message.received_chunks, message.total_chunks);

    if (activeOutgoingTransfer && activeOutgoingTransfer.transferId === message.transfer_id) {
        if (message.status === "completed") {
            void markOutgoingTransferComplete(activeOutgoingTransfer);
            return;
        }
        const progress = message.total_chunks > 0
            ? Math.round((message.received_chunks / message.total_chunks) * 100)
            : 0;
        updateTransferItemProgress(
            activeOutgoingTransfer.transferId,
            activeOutgoingTransfer.metadata.fileName,
            activeOutgoingTransfer.metadata.size,
            progress
        );
        updateTransferQueueHint(activeOutgoingTransfer);
        return;
    }

    const transfer = incomingTransfers.get(message.transfer_id);
    if (transfer) {
        if (message.status === "completed") {
            hideTransferSummary();
            return;
        }
        const progress = message.total_chunks > 0
            ? Math.round((message.received_chunks / message.total_chunks) * 100)
            : 0;
        updateTransferItemProgress(message.transfer_id, transfer.metadata.fileName, transfer.totalSize, progress);
        return;
    }

    if (message.status === "completed") {
        hideTransferSummary();
        return;
    }

    logEl.textContent = "收到文件状态，等待文件描述解密";
}

initializeInviteCredentials();
initializeTheme();
updateClipboardMeta();
setClipboardSyncState("idle", "等待同步");
setActiveMobileTab("file");
connect();
void refreshSessionKey();
setClipboardSyncState("idle", "等待同步");
