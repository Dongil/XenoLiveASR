# models.py

import torch
import deepl
import asyncio
import logging
import numpy as np
import aiohttp  # [추가] Papago 비동기 요청용
import html # [추가] HTML 엔티티 디코딩을 위한 표준 라이브러리
from abc import ABC, abstractmethod
from faster_whisper import WhisperModel as FasterWhisperModel

from google.cloud import translate_v2 as translate # 구글 번역

# 모듈화된 파일에서 필요한 요소 임포트
from audio_processing import preprocess_audio
from config import (
    MODEL_NAME, TARGET_LANGUAGE, DEEPL_API_KEY, 
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, GOOGLE_APPLICATION_CREDENTIALS
)

class Translator(ABC):
    @abstractmethod
    async def translate(self, text: str, target_lang: str) -> str: pass

class DeepLTranslator(Translator):
    def __init__(self, api_key: str):
        if not api_key: raise ValueError("DeepL API 키가 설정되지 않았습니다.")
        self.translator = deepl.Translator(api_key)
        self.lang_map = {"en": "EN-US", "ja": "JA", "zh": "ZH", "vi": "VI", "id": "ID", "tr": "TR", "de": "DE", "it": "IT", "fr": "FR", "es" : "ES", "ru": "RU", "pt": "PT"}

    async def translate(self, text: str, target_lang: str) -> str:
        if not text or target_lang not in self.lang_map: return ""
        deepl_target_lang = self.lang_map[target_lang]
        try:
            result = await asyncio.to_thread(self.translator.translate_text, text, source_lang="KO", target_lang=deepl_target_lang)
            return result.text
        except Exception as e:
            logging.error(f"DeepL 번역 오류 ({target_lang}): {e}")
            return f"[{target_lang} 번역 실패]"

class PapagoTranslator(Translator):
    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise ValueError("Papago Client ID 또는 Secret이 설정되지 않았습니다.")
        
        self.url = "https://papago.apigw.ntruss.com/nmt/v1/translation"
        # __init__에서 헤더를 한 번만 생성
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
        }
        self.lang_map = {"en": "en", "ja": "ja", "zh": "zh-CN", "vi": "vi", "id": "id", "th": "th", "de": "de", "it": "it", "fr": "fr", "es" : "es", "ru": "ru"}

    async def translate(self, text: str, target_lang: str) -> str:
        if not text or target_lang not in self.lang_map: return ""
        papago_target_lang = self.lang_map[target_lang]
        
        # __init__에서 만든 self.headers를 사용하도록 수정
        data = {
            "source": "ko",
            "target": papago_target_lang,
            "text": text
        }
        try:
            async with aiohttp.ClientSession() as session:
                # 헤더를 self.headers로 전달
                async with session.post(self.url, headers=self.headers, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result['message']['result']['translatedText']
                    else:
                        error_text = await response.text()
                        logging.error(f"Papago API 오류 ({response.status}): {error_text}")
                        return f"[Papago {target_lang} 번역 실패]"
        except Exception as e:
            logging.error(f"Papago 번역 오류 ({target_lang}): {e}")
            return f"[Papago {target_lang} 번역 실패]"

class GoogleTranslator(Translator):
    def __init__(self):
        try:
            self.client = translate.Client()
        except Exception as e:
            raise ValueError(f"Google Translate 클라이언트 초기화 실패: {e}. GOOGLE_APPLICATION_CREDENTIALS 환경변수를 확인하세요.")
        self.lang_map = {"en": "en", "ja": "ja", "zh": "zh-CN", "vi": "vi", "id": "id", "th": "th", "mn": "mn", "uz": "uz", "tr": "tr", "de": "de", "it": "it", "fr": "fr", "es": "es", "ru": "ru", "pt": "pt"}
        
    async def translate(self, text: str, target_lang: str) -> str:
        if not text or target_lang not in self.lang_map: return ""
        google_target_lang = self.lang_map[target_lang]
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.client.translate(text, target_language=google_target_lang, source_language='ko')
            )
           
           # [핵심 수정] 번역된 텍스트의 HTML 엔티티를 일반 문자로 디코딩
            translated_text = result['translatedText']
            return html.unescape(translated_text)
        
        except Exception as e:
            logging.error(f"Google 번역 오류 ({target_lang}): {e}")
            return f"[{target_lang} Google 번역 실패]"
        
class WhisperModel:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if self.device == "cuda" else "int8"
        logging.info(f"Whisper 모델 로드 중 ({MODEL_NAME}, Device: {self.device}, Compute Type: {compute_type})...")
        self.model = FasterWhisperModel(MODEL_NAME, device=self.device, compute_type=compute_type)
        logging.info("모델 로드 완료.")
        
    async def transcribe(self, audio_buffer: np.ndarray, previous_text: str = None) -> str:
        try:
            processed_audio = preprocess_audio(audio_buffer)
            segments, _ = await asyncio.to_thread(
                self.model.transcribe,
                processed_audio,
                beam_size=5,
                language=TARGET_LANGUAGE,
                initial_prompt=previous_text,
                condition_on_previous_text=bool(previous_text)
            )
            full_text = "".join(segment.text for segment in segments).strip()
            if full_text:
                hallucination_blacklist = ["감사합니다", "시청해주셔서 감사합니다", "한국어 음성 대화", "다음 영상에서 만나요."]
                is_hallucination = any(word in full_text and len(full_text) < len(word) + 5 for word in hallucination_blacklist)
                if not is_hallucination:
                    return full_text
                else:
                    logging.warning(f"환각 의심 결과 필터링됨: '{full_text}'")
        except Exception as e:
            logging.error(f"인식 오류: {e}")
        return ""

# [핵심 수정] 번역 엔진들을 딕셔너리로 관리 (팩토리 패턴)
TRANSLATORS = {}
try:
    if DEEPL_API_KEY:
        TRANSLATORS['deepl'] = DeepLTranslator(DEEPL_API_KEY)
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        TRANSLATORS['papago'] = PapagoTranslator(NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)
    if GOOGLE_APPLICATION_CREDENTIALS:
        TRANSLATORS['google'] = GoogleTranslator()
except ValueError as e:
    logging.warning(f"번역기 초기화 중 오류: {e}")

if not TRANSLATORS:
    logging.error("사용 가능한 번역 엔진이 하나도 없습니다. API 키를 확인하세요.")