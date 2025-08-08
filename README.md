# 프로젝트 구성
XenoLiveASR/  
│  
├── main.py              # FastAPI 앱 실행 및 라우팅만 담당  
│  
├── stream_manager.py    # StreamManager와 StreamSession 클래스 담당  
│  
├── audio_processing.py  # VAD, FFmpeg, 오디오 전처리 로직 담당  
│  
├── models.py            # WhisperModel, Translator 등 AI/API 모델 클래스 담당  
│  
├── config.py            # 모든 설정값(VAD, Whisper 모델명 등) 담당  
│  
├── setting.ini          # 서버 환경 설정  
│  
├── css/  
│    └──  css 파일 경로   
├── js/  
│   ├── controller.js       # 프론트앤드 javascript  
│   └── watch.js   
│  
├── templates/  
│    ├── index.html          # speak controller UI/UX   
│    └── watch.html          # 결과 viewer  


# 가상환경 설정


# 번역엔진
1. DeepL  
2. Papago  
3. Google  

# Whisper 파라메터 정보

{
  "beam_size": 3, // 문장 탐색 범위(낮춰서 지연 감소)
  "log_prob_threshold": -1, // 음성인식 확률 임계값(-1=무시)
  "no_speech_threshold": 0.6, // 무음 감지 기준
  "compute_type": "float16", // 연산 정밀도(GPU 권장)
  "best_of": 1, // 샘플링 후보 수(실시간은 1로 지연 최소화)
  "patience": 0.8, // 빔 탐색 인내도(약간만 대기)
  "condition_on_previous_text": false, // 이전 문장 미사용(반복/환각 억제)
  "prompt_reset_on_temperature": 0.5, // 비정상 출력시 프롬프트 초기화 기준
  "initial_prompt": "", // 초기 힌트 문장(도메인 키워드 있으면 넣기)
  "temperature": 0, // 무작위성 0(안정적)
  "compression_ratio_threshold": 2.0, // 반복/군더더기 감지 조금 더 엄격
  "length_penalty": 1, // 길이 패널티 기본
  "repetition_penalty": 1.05, // 반복 토큰 약하게 감점
  "no_repeat_ngram_size": 3, // n-그램 반복 방지
  "prefix": "", // 첫 윈도우 접두어
  "suppress_blank": true, // 시작 공백 억제
  "suppress_tokens": [-1], // 토큰 억제 기본셋
  "max_initial_timestamp": 1, // 초기 타임스탬프 최대
  "word_timestamps": true, // 단어 단위 타임스탬프
  "prepend_punctuations": "'“¿([{-", // 앞쪽에 붙일 문장부호
  "append_punctuations": "'.。,，!！?？:：”)]}、", // 뒤쪽에 붙일 문장부호
  "max_new_tokens": 0, // 생성 토큰 제한(0=제한없음 구현多)
  "chunk_length": 20, // 청크 길이(짧게해서 반응성↑)
  "hallucination_silence_threshold": 3, // 무음 3초 이상이면 스킵(환각 억제)
  "hotwords": [], // 주요 단어(고유명사/약어 넣으면 효과↑)
  "language_detection_threshold": 0.5, // 언어 감지 기준
  "language_detection_segments": 1, // 언어 감지용 조각 수
  "offload_model": true // 처리 후 메모리 해제
}

