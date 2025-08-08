# config.py

import os
from dotenv import load_dotenv

load_dotenv()

# --- Whisper 설정 ---
MODEL_NAME = 'large-v3'
TARGET_LANGUAGE = 'ko'
SAMPLE_RATE = 16000

# --- VAD 설정 ---
VAD_AGGRESSIVENESS = 3
VAD_FRAME_MS = 30
VAD_BYTES_PER_FRAME = (SAMPLE_RATE * VAD_FRAME_MS) // 1000 * 2
SILENCE_THRESHOLD_S = 0.8
MIN_AUDIO_DURATION_S = 1.2

# --- 문장 결합 로직 설정 ---
TRANSLATION_TIMEOUT_S = 1.5
MIN_LENGTH_FOR_TIMEOUT_TRANSLATION = 5

# --- 번역기 기본엔진 설정 ---
TRANSLATION_ENGINE = 'deepl'

# --- API 키 ---
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET=os.getenv("NAVER_CLIENT_SECRET")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# --- 문장 연결 규칙 ---
CONNECTING_WORDS = [
    '그리고', '그래서', '그러나', '하지만', '그런데', '또한', '또는', '즉', '및',
    '대해', '따라', '위해', '통해', '관련', '대한', '관해', '대하여', '비해', '따르면'
]
CONNECTING_ENDINGS = [
    '고', '하며', '면서', '는데', '지만', '하고', '에서', '에게', '한테', '부터', '까지', '으로', '로',
    '인데', '해도', '해서', '했고', '하는', '하던', '거나', '든지', '든가', '으며', '다가',
    '어서', '니까', 'ㄹ수록', '더라도', '어야', '은데', 'ㄴ데', '구요', '고요',
    '를', '을', '가', '이', '는', '은', '의', '와', '과'
]