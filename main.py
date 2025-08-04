# main.py

import uvicorn
import os
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# --- 모듈화된 파일 임포트 ---
import config
from models import WhisperModel
from stream_manager import stream_manager

# --- 로깅 설정 ---
#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- FastAPI 생명주기 이벤트 ---
whisper_model_instance: Optional[WhisperModel] = None
app_ready = asyncio.Event() # [핵심 추가] 앱 준비 상태를 알리는 이벤트 플래그

@asynccontextmanager
async def lifespan(app: FastAPI):
    global whisper_model_instance
    whisper_model_instance = WhisperModel()
    app_ready.set() # [핵심 추가] 모델 로드가 끝나면, 앱이 준비되었음을 알림
    yield
    logging.info("서버 종료.")

# --- FastAPI 앱 설정 ---
app = FastAPI(lifespan=lifespan)
# static 폴더 경로를 명확하게 지정
app.mount("/js", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "js")), name="js")
templates_path = os.path.join(os.path.dirname(__file__), "templates")

# --- 라우팅 ---
@app.get("/liveasr/{stream_id}")
async def get_control_page(stream_id: str):
    return FileResponse(os.path.join(templates_path, "index.html"))

@app.get("/liveasr/watch/{stream_id}")
async def get_watch_page(stream_id: str):
    return FileResponse(os.path.join(templates_path, "watch.html"))

@app.websocket("/ws/liveasr/control/{stream_id}")
async def websocket_control_endpoint(websocket: WebSocket, stream_id: str):
    await app_ready.wait() # 앱이 완전히 준비될 때까지 여기서 대기
    
    session = await stream_manager.get_or_create_session(stream_id)
    if session.controller:
        logging.warning(f"[{stream_id}] 이미 컨트롤러가 연결되어 있어 새 연결을 거부합니다.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    await session.set_controller(websocket, whisper_model_instance)

@app.websocket("/ws/liveasr/watch/{stream_id}")
async def websocket_watch_endpoint(websocket: WebSocket, stream_id: str):
    await app_ready.wait() # 앱이 완전히 준비될 때까지 여기서 대기

    session = await stream_manager.get_or_create_session(stream_id)
    try:
        await session.add_viewer(websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        session.remove_viewer(websocket)
        stream_manager.remove_session_if_empty(stream_id)

# --- http 서버 실행 ---
if __name__ == '__main__':
    HOST = '0.0.0.0'
    PORT = 65432
    if not config.DEEPL_API_KEY:
        print("\n\033[93m경고: DEEPL_API_KEY 환경 변수가 없어 번역 기능이 비활성화됩니다.\033[0m")
    
    print(f"FastAPI 서버 시작 (http://{HOST}:{PORT})")
    print("사용 예시:")
    print(f"  - 컨트롤러: http://127.0.0.1:{PORT}/liveasr/my_stream_1")
    print(f"  - 뷰어: http://127.0.0.1:{PORT}/liveasr/watch/my_stream_1")
    
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)

# --- https 서버 실행 ---
# if __name__ == '__main__':
#     HOST = '0.0.0.0'
#     PORT = 8448  # 일반적으로 HTTPS는 443 포트 사용
#     if not config.DEEPL_API_KEY:
#          print("\n\033[93m경고: DEEPL_API_KEY 환경 변수가 없어 번역 기능이 비활성화됩니다.\033[0m")

#     print(f"FastAPI 서버 시작 (http://{HOST}:{PORT})")
#     print("사용 예시:")
#     print(f"  - 컨트롤러: http://127.0.0.1:{PORT}/liveasr/my_stream_1")
#     print(f"  - 뷰어: http://127.0.0.1:{PORT}/liveasr/watch/my_stream_1")
    
#     uvicorn.run(
#         app,
#         host=HOST,
#         port=PORT,
#         ssl_keyfile="D:/AutoSet9/server/conf/newkey.pem",         # 개인 키 파일
#         ssl_certfile="D:/AutoSet9/server/conf/xenoglobal.co.kr-fullchain.pem",    # 인증서 파일
#     )