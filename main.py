# 文件名: main.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List

app = FastAPI()

# 挂载静态文件目录 (CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")
# 配置模板目录 (HTML)
templates = Jinja2Templates(directory="templates")

# 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.last_encrypted_message: str = "" 

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # 新用户加入时，同步最后一条消息
        if self.last_encrypted_message:
            await websocket.send_text(self.last_encrypted_message)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str, sender: WebSocket):
        self.last_encrypted_message = message
        for connection in self.active_connections:
            if connection != sender:
                await connection.send_text(message)

manager = ConnectionManager()

# 路由：返回首页
@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 路由：WebSocket 处理
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    # 局域网运行，端口 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)