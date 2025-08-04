# audio_processing.py

import asyncio
import logging
import numpy as np
import webrtcvad
import subprocess
from scipy.signal import butter, lfilter
import noisereduce as nr
from typing import Dict

from config import (
    VAD_AGGRESSIVENESS, VAD_FRAME_MS, VAD_BYTES_PER_FRAME, SILENCE_THRESHOLD_S,
    MIN_AUDIO_DURATION_S, SAMPLE_RATE
)

# --- 오디오 전처리 함수 ---
def band_pass_filter(data, lowcut=300, highcut=3400, sr=SAMPLE_RATE, order=5):
    nyquist = 0.5 * sr
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype='band')
    y = lfilter(b, a, data)
    return y

def preprocess_audio(audio_np: np.ndarray) -> np.ndarray:
    audio_float32 = audio_np.astype(np.float32) / 32768.0
    try:
        reduced_noise_audio = nr.reduce_noise(y=audio_float32, sr=SAMPLE_RATE)
        filtered_audio = band_pass_filter(reduced_noise_audio, sr=SAMPLE_RATE)
        return filtered_audio.astype(np.float32)
    except Exception as e:
        logging.error(f"오디오 전처리 중 오류 발생: {e}, 원본 오디오 사용")
        return audio_float32

# --- FFmpeg 관련 함수 ---
async def create_ffmpeg_process(stream_id: str):
    command = ["ffmpeg", "-f", "webm", "-i", "-", "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    logging.info(f"[{stream_id}] FFmpeg 프로세스 생성됨 (PID: {proc.pid}).")
    return proc

# --- VAD 기반 PCM 처리 태스크 ---
# [핵심 수정] 이 함수는 이제 WhisperModel 객체를 직접 받으므로, 타입 힌팅이 필요 없음
async def pcm_processing_task(stream_id: str, pcm_queue: asyncio.Queue, text_queue: asyncio.Queue, text_buffer_ref: Dict, whisper_model):
    logging.info(f"[{stream_id}] PCM 처리 태스크 시작됨.")
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    pcm_buffer, speech_buffer = bytearray(), bytearray()
    is_speaking, silence_frames_count = False, 0
    max_silence_frames = int(SILENCE_THRESHOLD_S * 1000 / VAD_FRAME_MS)
    min_audio_bytes = int(MIN_AUDIO_DURATION_S * SAMPLE_RATE * 2)

    try:
        while True:
            pcm_chunk = await pcm_queue.get()
            pcm_buffer.extend(pcm_chunk)
            while len(pcm_buffer) >= VAD_BYTES_PER_FRAME:
                frame = pcm_buffer[:VAD_BYTES_PER_FRAME]; pcm_buffer = pcm_buffer[VAD_BYTES_PER_FRAME:]
                is_speech = vad.is_speech(frame, SAMPLE_RATE)
                if is_speaking:
                    speech_buffer.extend(frame)
                    if not is_speech:
                        silence_frames_count += 1
                        if silence_frames_count > max_silence_frames:
                            is_speaking = False
                            if len(speech_buffer) > min_audio_bytes:
                                audio_np = np.frombuffer(speech_buffer, dtype=np.int16).copy()
                                original = await whisper_model.transcribe(audio_np, previous_text=text_buffer_ref['buffer'])
                                if original: await text_queue.put(original)
                            speech_buffer.clear()
                    else: silence_frames_count = 0
                elif is_speech: is_speaking, silence_frames_count = True, 0; speech_buffer.extend(frame)
    except asyncio.CancelledError: logging.info(f"[{stream_id}] PCM 처리 태스크 취소됨.")
    except Exception as e: logging.error(f"[{stream_id}] PCM 처리 태스크에서 치명적 오류 발생:", exc_info=True)