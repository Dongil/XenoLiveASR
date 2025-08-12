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

    # [추가] 서버 시작 시 'uploads' 폴더 생성
    uploads_dir = "uploads"
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)
        logging.info(f"'{uploads_dir}' 폴더를 생성했습니다.")

    whisper_model_instance = WhisperModel()
    app_ready.set() # [핵심 추가] 모델 로드가 끝나면, 앱이 준비되었음을 알림
    yield
    logging.info("서버 종료.")

# --- FastAPI 앱 설정 ---
app = FastAPI(lifespan=lifespan)
# static 폴더 경로를 명확하게 지정
app.mount("/js", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "js")), name="js")
app.mount("/css", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "css")), name="css")
templates_path = os.path.join(os.path.dirname(__file__), "templates")

# --- 라우팅 ---
@app.get("/liveasr/watch/{stream_id}")
async def get_watch_page(stream_id: str):
    return FileResponse(os.path.join(templates_path, "watch.html"))

@app.get("/liveasr/{stream_id}")
async def get_control_page(stream_id: str):
    return FileResponse(os.path.join(templates_path, "index.html"))

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

# --- 서버 실행 부분 (최종 수정본) ---
if __name__ == '__main__':
    import configparser
    import os

    # 1. 설정 파일 파서 생성 및 파일 읽기
    config_parser = configparser.ConfigParser()
    config_parser.read('settings.ini', encoding='utf-8')

    # 2. 실행 환경 결정
    app_env = os.environ.get('APP_ENV', 'development').lower()

    if app_env not in config_parser.sections():
        print(f"\033[91m[ERROR] Unknown environment '{app_env}' in settings.ini. Falling back to 'development'.\033[0m")
        app_env = 'development'

    # 3. 해당 환경의 설정 값 로드 (일반 딕셔너리로 변환)
    try:
        settings = {**config_parser['default'], **config_parser[app_env]}
        
        # [수정] 일반 딕셔너리이므로, 타입 변환을 직접 수행합니다.
        HOST = settings.get('host')
        PORT = int(settings.get('port'))  # getint -> int()로 직접 변환
        PROTOCOL = settings.get('protocol')
        SSL_KEYFILE = settings.get('ssl_keyfile') or None
        SSL_CERTFILE = settings.get('ssl_certfile') or None
        
        # getboolean을 직접 구현 (문자열 'true', 'false' 등을 bool로 변환)
        reload_str = settings.get('reload', 'false').lower()
        RELOAD = reload_str in ('true', '1', 't', 'y', 'yes')

    except (KeyError, ValueError, configparser.NoSectionError) as e:
        print(f"\033[91m[ERROR] Could not load settings for '{app_env}'. Please check settings.ini. Details: {e}\033[0m")
        exit(1)

    # 4. DeepL API 키 경고
    if not config.DEEPL_API_KEY:
         print("\n\033[93m경고: DEEPL_API_KEY 환경 변수가 없어 번역 기능이 비활성화됩니다.\033[0m")

    # 5. uvicorn 실행 옵션 동적 구성
    run_options = {
        "app": "main:app",  # uvicorn.run의 첫 번째 인자는 딕셔너리에 포함시키는 것이 더 일관적입니다.
        "host": HOST,
        "port": PORT,
        "reload": RELOAD
    }

    print("="*50)
    print(f"  Starting server in [\033[96m{app_env.upper()}\033[0m] mode.")
    print(f"  Environment: {PROTOCOL}://{HOST}:{PORT}")
    print("="*50)

    if PROTOCOL == 'https':
        if SSL_KEYFILE and SSL_CERTFILE:
            print(f"  SSL Key: {SSL_KEYFILE}")
            print(f"  SSL Cert: {SSL_CERTFILE}")
            run_options["ssl_keyfile"] = SSL_KEYFILE
            run_options["ssl_certfile"] = SSL_CERTFILE
        else:
            print("\033[91m[ERROR] Protocol is 'https' but SSL certificate files are not configured in settings.ini.\033[0m")
            exit(1)

    print("\n사용 예시:")
    print(f"  - 컨트롤러: {PROTOCOL}://127.0.0.1:{PORT}/liveasr/my_stream_1")
    print(f"  - 뷰어: {PROTOCOL}://127.0.0.1:{PORT}/liveasr/watch/my_stream_1")
    print("\n서버를 중지하려면 CTRL+C를 누르세요.")
    
    # [수정] uvicorn.run() 호출 방식을 딕셔너리 unpacking으로 통일합니다.
    uvicorn.run(**run_options)