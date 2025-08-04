# stream_manager.py

import asyncio
import logging
import json
import time
from typing import List, Dict, Optional
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect

from models import WhisperModel, translator_instance
from audio_processing import create_ffmpeg_process, pcm_processing_task
from config import (
    CONNECTING_WORDS, CONNECTING_ENDINGS, TRANSLATION_TIMEOUT_S, 
    MIN_LENGTH_FOR_TIMEOUT_TRANSLATION
)

class StreamSession:
    def __init__(self, stream_id: str, manager: 'StreamManager'):
        self.stream_id = stream_id; self.manager = manager; self.controller: Optional[WebSocket] = None
        self.viewers: List[WebSocket] = []; self.background_tasks: List[asyncio.Task] = []
        self.config: Dict = {'type': 'config', 'languages': []}; self.cache: deque = deque(maxlen=8); self.lock = asyncio.Lock()
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.pcm_queue: Optional[asyncio.Queue] = None
        logging.info(f"[{stream_id}] 새로운 스트림 세션 생성됨.")

    async def add_viewer(self, websocket: WebSocket):
        await websocket.accept(); self.viewers.append(websocket)
        logging.info(f"[{self.stream_id}] 뷰어 연결됨. (총 {len(self.viewers)}명)")
        await websocket.send_json(self.config)
        for result in list(self.cache): await websocket.send_json(result)

    def remove_viewer(self, websocket: WebSocket):
        self.viewers.remove(websocket)
        logging.info(f"[{self.stream_id}] 뷰어 연결 끊김. (남은 뷰어: {len(self.viewers)}명)")

    async def broadcast_to_viewers_and_cache(self, data: dict):
        if data.get('type') == 'config': self.config = data; self.cache.clear()
        elif data.get('type') in ['final_result', 'translation_result']: self.cache.append(data)
        if self.viewers: await asyncio.gather(*[ws.send_json(data) for ws in self.viewers], return_exceptions=False)
            
    async def _reset_processing_tasks(self, whisper_model: WhisperModel):
        logging.info(f"[{self.stream_id}] FFmpeg 및 처리 태스크를 초기화/재설정합니다...")
        for task in self.background_tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.background_tasks.clear()

        if self.proc and self.proc.returncode is None:
            if self.proc.stdin and not self.proc.stdin.is_closing(): self.proc.stdin.close()
            await self.proc.wait()
        
        self.pcm_queue = asyncio.Queue(); text_queue = asyncio.Queue(); text_buffer_ref = {'buffer': ""}
        self.proc = await create_ffmpeg_process(self.stream_id)

        # [핵심 수정] 외부 함수를 직접 태스크로 생성. 더 이상 _pcm_processing_task 메소드는 없음.
        tasks = [
            pcm_processing_task(self.stream_id, self.pcm_queue, text_queue, text_buffer_ref, whisper_model),
            self._text_processing_task(text_queue, text_buffer_ref),
            self._read_stdout(self.proc, self.pcm_queue),
            self._read_stderr(self.proc)
        ]
        self.background_tasks = [asyncio.create_task(t) for t in tasks]
        logging.info(f"[{self.stream_id}] {len(self.background_tasks)}개의 새로운 백그라운드 태스크 시작 완료.")

    async def set_controller(self, websocket: WebSocket, whisper_model: WhisperModel):
        self.controller = websocket
        try:
            logging.info(f"[{self.stream_id}] 컨트롤러 루프 시작. 메시지 대기 중...")
            while True:
                message = await websocket.receive()
                if 'text' in message:
                    data = json.loads(message['text'])
                    logging.info(f"[{self.stream_id}] 컨트롤러로부터 텍스트 메시지 수신: {data}")
                    if data.get('type') == 'stream_start':
                        await self._reset_processing_tasks(whisper_model)
                    elif data.get('type') == 'config':
                        config_data = {'type': 'config', 'languages': data.get('languages', [])}
                        logging.info(f"[{self.stream_id}] 컨트롤러 번역 언어 설정: {config_data['languages']}")
                        await self.broadcast_to_viewers_and_cache(config_data)
                elif 'bytes' in message:
                    logging.debug(f"[{self.stream_id}] 컨트롤러로부터 {len(message['bytes'])} 바이트 수신.")
                    if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
                        self.proc.stdin.write(message['bytes']); await self.proc.stdin.drain()
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
                    if not current_buffer: return
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
                        
                        active_languages = self.config.get('languages', [])
                        if active_languages and translator_instance:
                            translations_dict = {}
                            translation_tasks = []
                            for lang in active_languages:
                                async def translate_and_store(l):
                                    translations_dict[l] = await translator_instance.translate(final_original_text, l)
                                translation_tasks.append(translate_and_store(lang))
                            await asyncio.gather(*translation_tasks)
                            for lang_code, translated_text in translations_dict.items():
                                trans_payload = {'type': 'translation_result', 'original_id': result_id, 'lang': lang_code, 'text': translated_text}
                                if self.controller:
                                    await self.controller.send_json(trans_payload)
                                await self.broadcast_to_viewers_and_cache(trans_payload)
            
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