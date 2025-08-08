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


# UI


# 번역엔진
1. DeepL  
2. Papago  
3. Google  

