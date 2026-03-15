// 文件名: static/script.js
let ws;
let cryptoKey = null;
const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();
const clipboardEl = document.getElementById("clipboard");
const statusEl = document.getElementById("connection-status");
const passwordEl = document.getElementById("password");
const logEl = document.getElementById("log");

// 1. 监听密码输入，生成密钥
passwordEl.addEventListener('input', async (e) => {
    const password = e.target.value;
    if (password.length > 0) {
        await generateKey(password);
        clipboardEl.disabled = false;
        logEl.innerText = "密钥已生成，准备传输";
        // 如果已经连上且有数据，尝试解密
        if (ws && ws.readyState === WebSocket.OPEN) {
             // 这里的逻辑通常需要服务器重发最后一条消息，或者本地缓存密文重试
             // 为简化，建议用户输完密码后刷新或等待新消息
        }
    } else {
        clipboardEl.disabled = true;
        cryptoKey = null;
    }
});

// 2. 监听文本框输入 -> 加密 -> 发送
clipboardEl.addEventListener('input', async () => {
    if (!ws || !cryptoKey) return;
    const text = clipboardEl.value;
    const encryptedData = await encryptMessage(text);
    ws.send(JSON.stringify(encryptedData));
    logEl.innerText = "已加密并同步";
});

// 3. WebSocket 连接管理
function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        statusEl.innerText = "已连接";
        statusEl.className = "status connected";
    };

    ws.onmessage = async (event) => {
        if (!cryptoKey) {
            logEl.innerText = "收到数据，但未设置密码，无法解密";
            return;
        }
        try {
            const data = JSON.parse(event.data);
            const decryptedText = await decryptMessage(data);
            // 只有当内容不同时才更新，防止光标跳动
            if (clipboardEl.value !== decryptedText) {
                clipboardEl.value = decryptedText;
                logEl.innerText = "收到并解密更新";
            }
        } catch (e) {
            console.error(e);
            logEl.innerText = "解密失败：密码可能错误";
        }
    };

    ws.onclose = () => {
        statusEl.innerText = "断开连接";
        statusEl.className = "status disconnected";
        setTimeout(connect, 3000); // 3秒后重连
    };
}

// 4. 加密工具函数 (AES-GCM)
async function generateKey(password) {
    const msgBuffer = textEncoder.encode(password);
    const hash = await crypto.subtle.digest('SHA-256', msgBuffer);
    cryptoKey = await crypto.subtle.importKey(
        'raw', hash, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']
    );
}

async function encryptMessage(text) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = textEncoder.encode(text);
    const ciphertext = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv }, cryptoKey, encoded
    );
    return {
        iv: Array.from(iv),
        data: Array.from(new Uint8Array(ciphertext))
    };
}

async function decryptMessage(bundle) {
    const iv = new Uint8Array(bundle.iv);
    const data = new Uint8Array(bundle.data);
    const decrypted = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: iv }, cryptoKey, data
    );
    return textDecoder.decode(decrypted);
}

// 5. 辅助功能
function copyToSystem() {
    clipboardEl.select();
    clipboardEl.setSelectionRange(0, 99999); // 适配移动端
    
    // 现代浏览器标准 API
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(clipboardEl.value).then(() => {
            logEl.innerText = "已复制到系统剪贴板！";
        });
    } else {
        // 降级方案
        document.execCommand('copy');
        logEl.innerText = "已复制 (旧版API)";
    }
}

function clearBoard() {
    clipboardEl.value = "";
    clipboardEl.dispatchEvent(new Event('input')); // 触发发送空消息
}

// 启动
connect();