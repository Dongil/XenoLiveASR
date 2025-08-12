# stream_manager.py

import asyncio
import logging
import json
import time
import os
from typing import List, Dict, Optional
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect

from models import WhisperModel, TRANSLATORS
from audio_processing import create_ffmpeg_process, pcm_processing_task
from config import (
    CONNECTING_WORDS, CONNECTING_ENDINGS, TRANSLATION_TIMEOUT_S, 
    MIN_LENGTH_FOR_TIMEOUT_TRANSLATION, SILENCE_THRESHOLD_S, TRANSLATION_ENGINE
)

class StreamSession:
    def __init__(self, stream_id: str, manager: 'StreamManager'):
        self.stream_id = stream_id; 
        self.manager = manager; 
        self.controller: Optional[WebSocket] = None
        self.viewers: List[WebSocket] = []; 
        self.background_tasks: List[asyncio.Task] = []
         # [수정] 세션별 설정값 저장 변수 추가 및 기본값으로 초기화
        self.silence_threshold = SILENCE_THRESHOLD_S
        self.translation_engine = TRANSLATION_ENGINE
        
        # [추가] Whisper 파라미터 저장을 위한 딕셔너리
        self.whisper_options: Dict = {}
        self.options_lock = asyncio.Lock()  # 옵션 딕셔너리 접근을 위한 잠금

        # [수정] 누락된 self.lock 추가
        self.lock = asyncio.Lock() # 텍스트 버퍼 및 번역 로직 보호를 위한 잠금
        
        self.config_data: Dict = {'type': 'config', 'languages': []} 
        self.cache: deque = deque(maxlen=8); 
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.pcm_queue: Optional[asyncio.Queue] = None

        logging.info(f"[{stream_id}] 새로운 스트림 세션 생성됨.")
    
    # [수정] 비동기 함수로 변경하여 I/O 블로킹 방지
    async def _load_options_from_file(self):
        async with self.options_lock:
            options_path = f"uploads/{self.stream_id}.json"
            if os.path.exists(options_path):
                try:
                    with open(options_path, 'r', encoding='utf-8') as f:
                        self.whisper_options = json.load(f)
                    logging.info(f"[{self.stream_id}] 저장된 파라미터를 로드했습니다: {options_path}")
                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f"[{self.stream_id}] 파라미터 파일 로드 실패: {e}, 기본값을 사용합니다.")
                    self.whisper_options = {}
            else:
                logging.info(f"[{self.stream_id}] 저장된 파라미터 파일이 없습니다. 기본값을 사용합니다.")

    # [수정] 비동기 함수로 변경하고 잠금 사용
    async def _save_options_to_file(self):
        async with self.options_lock:
            options_path = f"uploads/{self.stream_id}.json"
            try:
                # 비동기 파일 쓰기 (더 안전하지만, 여기서는 동기식으로도 충분)
                # import aiofiles
                # async with aiofiles.open(options_path, 'w', encoding='utf-8') as f:
                #     await f.write(json.dumps(self.whisper_options, ensure_ascii=False, indent=2))
                with open(options_path, 'w', encoding='utf-8') as f:
                    json.dump(self.whisper_options, f, ensure_ascii=False, indent=2)
                logging.info(f"[{self.stream_id}] 파라미터를 파일에 저장했습니다: {options_path}")
            except IOError as e:
                logging.error(f"[{self.stream_id}] 파라미터 파일 저장 실패: {e}")

    async def add_viewer(self, websocket: WebSocket):
        await websocket.accept(); 
        self.viewers.append(websocket)
        logging.info(f"[{self.stream_id}] 뷰어 연결됨. (총 {len(self.viewers)}명)")
        await websocket.send_json(self.config_data)
        for result in list(self.cache): 
            await websocket.send_json(result)

    def remove_viewer(self, websocket: WebSocket):
        self.viewers.remove(websocket)
        logging.info(f"[{self.stream_id}] 뷰어 연결 끊김. (남은 뷰어: {len(self.viewers)}명)")

    async def broadcast_to_viewers_and_cache(self, data: dict):
        broadcast_data = data  # 기본적으로는 받은 데이터 그대로 브로드캐스트
        if data.get('type') == 'config':
            self.config_data['languages'] = data.get('languages', [])
            self.cache.clear()
            # 뷰어에게는 언어 설정만 포함된 config_data를 보냄
            broadcast_data = self.config_data
        elif data.get('type') in ['final_result', 'translation_result']:
            self.cache.append(data)

        if self.viewers:
            # [핵심 수정] data -> broadcast_data 로 변경하여 올바른 데이터를 전송
            await asyncio.gather(*[ws.send_json(broadcast_data) for ws in self.viewers], return_exceptions=False)
            
    async def _reset_processing_tasks(self, whisper_model: WhisperModel):
        logging.info(f"[{self.stream_id}] FFmpeg 및 처리 태스크를 초기화/재설정합니다...")
        for task in self.background_tasks:
            if not task.done(): 
                task.cancel()
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.background_tasks.clear()

        if self.proc and self.proc.returncode is None:
            if self.proc.stdin and not self.proc.stdin.is_closing(): 
                self.proc.stdin.close()
            await self.proc.wait()
        
        self.pcm_queue = asyncio.Queue(); 
        text_queue = asyncio.Queue(); 
        text_buffer_ref = {'buffer': ""}
        self.proc = await create_ffmpeg_process(self.stream_id)

        # [중요 수정] pcm_processing_task에 self.whisper_options 딕셔너리 자체를 전달
        # 이렇게 하면 pcm_processing_task 내부에서 항상 최신 값을 참조할 수 있습니다.
        tasks = [
            pcm_processing_task(self.stream_id, self.pcm_queue, text_queue, text_buffer_ref, whisper_model, self.silence_threshold, self.whisper_options, self.options_lock),
            self._text_processing_task(text_queue, text_buffer_ref),
            self._read_stdout(self.proc, self.pcm_queue),
            self._read_stderr(self.proc)
        ]
        self.background_tasks = [asyncio.create_task(t) for t in tasks]
        logging.info(f"[{self.stream_id}] {len(self.background_tasks)}개의 새로운 백그라운드 태스크 시작 완료.")
    
    async def set_controller(self, websocket: WebSocket, whisper_model: WhisperModel):
        self.controller = websocket

        # [수정] 컨트롤러 연결 시점에 파일에서 최신 옵션 로드
        await self._load_options_from_file()
        
        # 파일에서 로드한 옵션이 없다면 (비어있다면) 모델의 기본값으로 채움
        async with self.options_lock:
            if not self.whisper_options:
                self.whisper_options = whisper_model.transcribe_options.copy()
                logging.info(f"[{self.stream_id}] Whisper 기본 파라미터를 적용합니다.")
        
        try:
            initial_settings = {
                "type": "session_init",
                "settings": {
                    "silence_threshold": self.silence_threshold,
                    "translation_engine": self.translation_engine,
                    "whisper_params": self.whisper_options
                }
            }
            await websocket.send_json(initial_settings)
            logging.info(f"[{self.stream_id}] 컨트롤러에게 초기 설정 전송 완료.")
        except WebSocketDisconnect:
            logging.warning(f"[{self.stream_id}] 초기 설정 전송 중 컨트롤러 연결 끊김.")
            self.controller = None
            return
        
        try:
            logging.info(f"[{self.stream_id}] 컨트롤러 루프 시작. 메시지 대기 중...")
            while True:
                message = await websocket.receive()
                if 'text' in message:
                    data = json.loads(message['text'])
                    logging.info(f"[{self.stream_id}] 컨트롤러로부터 텍스트 메시지 수신: {data}")
                    
                    if data.get('type') == 'stream_start':
                        logging.info(f"[{self.stream_id}] 컨트롤러로부터 스트림 시작 요청 수신.")
                        await self._reset_processing_tasks(whisper_model)
                    elif data.get('type') == 'tuning':   # 'tuning' 타입 메시지 처리 로직
                        params_to_update = data.get('params', {})
                        # [수정] 잠금을 사용하여 안전하게 업데이트
                        async with self.options_lock:
                            self.whisper_options.update(params_to_update)
                        logging.info(f"[{self.stream_id}] Whisper 파라미터 업데이트됨: {params_to_update}")
                        await self._save_options_to_file() # 변경된 내용을 파일에 저장
                        await self.controller.send_json({"type": "tuning_ack", "status": "success", "message": "파라미터가 적용 및 저장되었습니다."})
                    elif data.get('type') == 'config':
                        # 세션의 설정 값을 클라이언트가 보낸 값으로 업데이트
                        self.silence_threshold = data.get('silence_threshold', self.silence_threshold)
                        self.translation_engine = data.get('translation_engine', self.translation_engine)

                        # 번역 언어 설정은 기존 로직대로 처리하여 뷰어에게 브로드캐스팅
                        lang_config_data = {'type': 'config', 'languages': data.get('languages', [])}
                        
                        logging.info(f"[{self.stream_id}] 컨트롤러 설정 변경: 언어={lang_config_data['languages']}, 침묵={self.silence_threshold}s, 엔진='{self.translation_engine}'")
                        await self.broadcast_to_viewers_and_cache(lang_config_data)
                elif 'bytes' in message:
                    logging.debug(f"[{self.stream_id}] 컨트롤러로부터 {len(message['bytes'])} 바이트 수신.")
                    if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
                        self.proc.stdin.write(message['bytes']); 
                        await self.proc.stdin.drain()
                    else:
                        logging.warning(f"[{self.stream_id}] FFmpeg 프로세스가 준비되지 않아 오디오 데이터를 무시합니다.")

        except (WebSocketDisconnect, RuntimeError):
            logging.info(f"[{self.stream_id}] 컨트롤러 연결이 정상적으로 종료되었습니다.")
        except Exception as e:
            logging.error(f"[{self.stream_id}] 컨트롤러 루프에서 예상치 못한 오류 발생:", exc_info=True)
        finally:
            await self._cleanup()

    # [핵심 수정] _cleanup 메소드가 proc을 인자로 받지 않도록 수정
    async def _cleanup(self):
        logging.info(f"[{self.stream_id}] 세션 정리 시작...")
        for task in self.background_tasks:
            if not task.done(): task.cancel()
        
        if self.proc and self.proc.returncode is None:
            if self.proc.stdin and not self.proc.stdin.is_closing():
                self.proc.stdin.close()
            await self.proc.wait()
        
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.controller = None
        self.manager.remove_session_if_empty(self.stream_id)
        logging.info(f"[{self.stream_id}] 세션 정리 완료.")

    async def _text_processing_task(self, text_queue: asyncio.Queue, text_buffer_ref: Dict):
        logging.info(f"[{self.stream_id}] 텍스트 처리 태스크 시작됨.")
        try:
            loop = asyncio.get_event_loop()
            text_buffer = ""
            last_text_received_time = None
            
            async def trigger_translation_if_needed(force_reason: str = ""):
                nonlocal text_buffer, last_text_received_time
                async with self.lock:
                    current_buffer = text_buffer.strip()
                    if not current_buffer: 
                        return
                    should_translate = False
                    last_word = current_buffer.split()[-1] if current_buffer else ""
                    is_semantically_incomplete = any(last_word.endswith(e) for e in CONNECTING_ENDINGS) or last_word in CONNECTING_WORDS
                    if force_reason == 'punctuation':
                        should_translate = True
                    elif not force_reason:
                        current_time = loop.time()
                        is_timeout = last_text_received_time and (current_time - last_text_received_time > TRANSLATION_TIMEOUT_S)
                        is_long_enough = len(current_buffer) >= MIN_LENGTH_FOR_TIMEOUT_TRANSLATION
                        if is_timeout and is_long_enough and not is_semantically_incomplete:
                            should_translate = True
                    
                    if should_translate:
                        final_original_text = text_buffer.strip()
                        text_buffer = ""
                        text_buffer_ref['buffer'] = ""
                        last_text_received_time = None
                        result_id = str(time.time())
                        log_reason = f"(강제: {force_reason})" if force_reason else "(타임아웃)"
                        logging.info(f"[{self.stream_id}] 번역 시작 {log_reason}: '{final_original_text}'")
                        final_payload = {'type': 'final_result', 'original': final_original_text, 'id': result_id}
                        if self.controller:
                            await self.controller.send_json(final_payload)
                        await self.broadcast_to_viewers_and_cache(final_payload)
                        
                         # --- [핵심 수정] 번역기 선택 로직 ---
                        active_languages = self.config_data.get('languages', [])
                        # 1. 세션에 설정된 엔진 이름으로 사용 가능한 번역기 인스턴스를 가져옴
                        translator = TRANSLATORS.get(self.translation_engine)

                        # 2. 번역할 언어가 있고, 선택된 번역기가 사용 가능한 상태일 때만 번역 수행
                        if active_languages and translator:
                            logging.info(f"[{self.stream_id}] '{self.translation_engine}' 엔진으로 번역을 수행합니다.")
                            translations_dict = {}
                            translation_tasks = []
                            for lang in active_languages:
                                async def translate_and_store(l):
                                    # 3. 가져온 translator 인스턴스의 translate 메서드 호출
                                    translations_dict[l] = await translator.translate(final_original_text, l)
                                translation_tasks.append(translate_and_store(lang))
                            await asyncio.gather(*translation_tasks)

                            for lang_code, translated_text in translations_dict.items():
                                trans_payload = {'type': 'translation_result', 'original_id': result_id, 'lang': lang_code, 'text': translated_text}
                                if self.controller:
                                    await self.controller.send_json(trans_payload)
                                await self.broadcast_to_viewers_and_cache(trans_payload)
                        elif active_languages:
                            logging.warning(f"[{self.stream_id}] '{self.translation_engine}' 번역기가 선택되었으나, 서버에서 사용할 수 없습니다. (API 키 확인 필요)")
            
            async def text_consumer():
                nonlocal text_buffer, last_text_received_time
                while True:
                    transcribed_text = await text_queue.get()
                    logging.debug(f"[{self.stream_id}] 텍스트 큐에서 수신: '{transcribed_text}'")
                    if text_buffer.strip() and transcribed_text:
                        text_buffer += " "
                    text_buffer += transcribed_text
                    text_buffer_ref['buffer'] = text_buffer.strip()
                    last_text_received_time = loop.time()
                    interim_payload = {'type': 'interim_result', 'text': text_buffer.strip()}
                    if self.controller:
                        await self.controller.send_json(interim_payload)
                    await self.broadcast_to_viewers_and_cache(interim_payload)
                    cleaned_text = text_buffer.strip()
                    if cleaned_text.endswith(('습니다.', '니다.', '까요?', '이죠?', '데요!', '하죠.', '시오.')):
                        await asyncio.sleep(0.3)
                        if last_text_received_time and (loop.time() - last_text_received_time >= 0.3):
                            await trigger_translation_if_needed(force_reason='punctuation')
            
            async def timeout_watcher():
                while True:
                    await asyncio.sleep(0.5)
                    await trigger_translation_if_needed()
            
            await asyncio.gather(text_consumer(), timeout_watcher())

        except asyncio.CancelledError:
            logging.info(f"[{self.stream_id}] 텍스트 처리 태스크 취소됨.")
        except Exception as e:
            logging.error(f"[{self.stream_id}] 텍스트 처리 태스크에서 오류 발생:", exc_info=True)

    async def _read_stdout(self, proc, pcm_queue):
        logging.info(f"[{self.stream_id}] FFmpeg stdout 읽기 태스크 시작됨.")
        try:
            while True:
                pcm_chunk = await proc.stdout.read(4096)
                if not pcm_chunk:
                    logging.info(f"[{self.stream_id}] FFmpeg stdout 스트림 종료됨.")
                    break
                logging.debug(f"[{self.stream_id}] FFmpeg stdout에서 {len(pcm_chunk)} 바이트 읽음.")
                await pcm_queue.put(pcm_chunk)
        except asyncio.CancelledError:
            logging.info(f"[{self.stream_id}] FFmpeg stdout 읽기 태스크 취소됨.")
        except Exception as e:
            logging.error(f"[{self.stream_id}] FFmpeg stdout 읽기 태스크에서 오류 발생:", exc_info=True)

    async def _read_stderr(self, proc):
        logging.info(f"[{self.stream_id}] FFmpeg stderr 읽기 태스크 시작됨.")
        try:
            buffer = b''
            while True:
                chunk = await proc.stderr.read(128)
                if not chunk:
                    logging.info(f"[{self.stream_id}] FFmpeg stderr 스트림 종료됨.")
                    break
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    logging.warning(f"[{self.stream_id}] FFmpeg: {line.decode(errors='ignore').strip()}")
        except asyncio.CancelledError:
            logging.info(f"[{self.stream_id}] FFmpeg stderr 읽기 태스크 취소됨.")
        except Exception as e:
            logging.error(f"[{self.stream_id}] FFmpeg stderr 읽기 태스크에서 오류 발생:", exc_info=True)


class StreamManager:
    def __init__(self):
        self.streams: Dict[str, StreamSession] = {}
        self.lock = asyncio.Lock()
    
    async def get_or_create_session(self, stream_id: str) -> StreamSession:
        async with self.lock:
            if stream_id not in self.streams:
                self.streams[stream_id] = StreamSession(stream_id, self)
            return self.streams[stream_id]

    def remove_session_if_empty(self, stream_id: str):
        if stream_id in self.streams:
            session = self.streams[stream_id]
            if not session.controller and not session.viewers:
                del self.streams[stream_id]
                logging.info(f"[{stream_id}] 컨트롤러와 뷰어가 모두 없어 세션을 제거합니다.")

stream_manager = StreamManager()