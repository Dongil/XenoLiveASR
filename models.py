# models.py

import torch
import deepl
import asyncio
import logging
import numpy as np
from abc import ABC, abstractmethod
from faster_whisper import WhisperModel as FasterWhisperModel

# 모듈화된 파일에서 필요한 요소 임포트
from audio_processing import preprocess_audio
from config import MODEL_NAME, TARGET_LANGUAGE, DEEPL_API_KEY

class Translator(ABC):
    @abstractmethod
    async def translate(self, text: str, target_lang: str) -> str: pass

class DeepLTranslator(Translator):
    def __init__(self, api_key: str):
        if not api_key: raise ValueError("DeepL API 키가 설정되지 않았습니다.")
        self.translator = deepl.Translator(api_key)
        self.lang_map = {"en": "EN-US", "ja": "JA", "zh": "ZH", "vi": "VI", "id": "ID", "tr": "TR", "de": "DE", "it": "IT", "pt": "PT-BR", "fr": "FR"}
    
    async def translate(self, text: str, target_lang: str) -> str:
        if not text or target_lang not in self.lang_map: return ""
        deepl_target_lang = self.lang_map[target_lang]
        try:
            result = await asyncio.to_thread(self.translator.translate_text, text, source_lang="KO", target_lang=deepl_target_lang)
            return result.text
        except Exception as e:
            logging.error(f"DeepL 번역 오류 ({target_lang}): {e}")
            return f"[{target_lang} 번역 실패]"

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

# --- 전역 인스턴스 생성 ---
translator_instance = DeepLTranslator(DEEPL_API_KEY) if DEEPL_API_KEY else None
if not translator_instance:
    logging.warning("DEEPL_API_KEY 환경 변수가 없어 번역 기능을 비활성화합니다.")