
//controller.js

document.addEventListener('DOMContentLoaded', () => {
    // --- [핵심 수정] URL에서 스트림 ID 가져오기 (더 유연한 방식으로) ---
    const pathParts = window.location.pathname.split('/');
    const streamId = pathParts.filter(part => part).pop(); // 경로의 마지막 부분을 ID로 사용

    if (!streamId) {
        document.body.innerHTML = '<h1>잘못된 접근입니다. URL 끝에 스트림 ID가 필요합니다. (예: /liveasr/my_stream)</h1>';
        return;
    }

    // --- [핵심 수정] 언어 및 엔진 지원 데이터 ---
    // 표 순서대로 모든 언어를 정의
    const ALL_LANGUAGES = [
        { code: "en", name: "영어" },
        { code: "ja", name: "일본어" },
        { code: "zh", name: "중국어" },
        { code: "vi", name: "베트남어" },
        { code: "id", name: "인도네시아어" },
        { code: "th", name: "태국어" },
        { code: "mn", name: "몽골어" },
        { code: "uz", name: "우즈벡어" },
        { code: "tr", name: "터키어" },
        { code: "de", name: "독일어" },
        { code: "it", name: "이탈리아어" },
        { code: "fr", name: "프랑스어" },
        { code: "es", name: "스페인어" },
        { code: "ru", name: "러시아어" },
        { code: "pt", name: "포르투갈어" }
    ];

    // 기존 LANGUAGES 객체를 대체할 이름 조회용 맵 (모든 언어 포함)
    const LANGUAGE_NAMES = {
        "none": "사용안함",
        ...Object.fromEntries(ALL_LANGUAGES.map(lang => [lang.code, lang.name]))
    };

    // 엔진별 지원 언어 코드
    const SUPPORTED_LANGUAGES_BY_ENGINE = {
        'deepl': ['en', 'ja', 'zh', 'vi', 'id', 'tr', 'de', 'it', 'fr', 'es', 'ru', 'pt'],
        'papago': ['en', 'ja', 'zh', 'vi', 'id', 'th', 'de', 'it', 'fr', 'es', 'ru'],
        'google': ['en', 'ja', 'zh', 'vi', 'id', 'th', 'mn', 'uz', 'tr', 'de', 'it', 'fr', 'es', 'ru', 'pt']
    };

    // --- UI 요소 및 상태 변수 ---
    const rejectionOverlay = document.getElementById('rejection-overlay');
    document.querySelector('h1').textContent += ` (${streamId})`;
    const statusElem = document.getElementById('status');
    const outputElem = document.getElementById('transcription-output');
    const translationOutputs = [document.getElementById('translation-output-1'), document.getElementById('translation-output-2'), document.getElementById('translation-output-3')];
    const langSelects = [document.getElementById('lang-select-1'), document.getElementById('lang-select-2'), document.getElementById('lang-select-3')];
    const micControlArea = document.getElementById('mic-control-area');
    const micSelect = document.getElementById('mic-select');
    const recordBtn = document.getElementById('record-btn');
    const tabAudioBtn = document.getElementById('tab-audio-btn');
    const fileControlArea = document.getElementById('file-control-area');
    const fileInput = document.getElementById('file-input');
    const playPauseBtn = document.getElementById('play-pause-btn');
    const restartBtn = document.getElementById('restart-btn');
    const waveformCanvas = document.getElementById('waveform-canvas');
    const canvasCtx = waveformCanvas.getContext('2d');
    const TIMESLICE = 500;    
    const silenceThresholdSlider = document.getElementById('silence-threshold-slider');
    const silenceThresholdValue = document.getElementById('silence-threshold-value');
    const translationEngineSelect = document.getElementById('translation-engine-select');
    const openViewerLink = document.getElementById('open-viewer-link');
    // [추가] 튜닝 관련 UI 요소
    const tuningText = document.getElementById('tuning-text');
    const tuningBtn = document.getElementById('tuning-btn');
    // --- [추가] 모달 관련 UI 요소 ---
    const helpIcon = document.getElementById('help-icon');
    const helpModal = document.getElementById('help-modal');
    const closeModalBtn = helpModal.querySelector('.close-btn');
    // --- [추가] 토글 버튼 관련 UI 요소 ---
    const paramToggleBtn = document.getElementById('param-toggle-btn');
    const paramControlArea = document.getElementById('param-control-area');
    const iconExpand = paramToggleBtn.querySelector('.icon-expand');
    const iconCollapse = paramToggleBtn.querySelector('.icon-collapse');
    let socket, mediaRecorder, mediaStream, animationFrameId;
    let isStreaming = false;
    let currentMode = null;
    let audioContext = null; 
    let audioElement, audioSourceNode, analyserNode;
    let interimElement = null;
    let isConnectionRejected = false;
    const LANGUAGES = { "none": "사용안함", "en": "영어", "ja": "일본어", "zh": "중국어", "vi": "베트남어", "id": "인도네시아어", "tr": "터키어", "de": "독일어", "it": "이탈리아어", "pt": "포르투갈어", "fr": "프랑스어" };

    // [추가] 뷰어 링크 설정
    if (openViewerLink) {
        const watchUrl = window.location.href.replace('/liveasr/', '/liveasr/watch/');
        openViewerLink.href = watchUrl;
    }

    // --- 초기화 ---
    connectWebSocket();
    getMicrophones();
    populateLanguageSelects();

    // --- 이벤트 리스너 ---
    recordBtn.addEventListener('click', handleMicStream);
    tabAudioBtn.addEventListener('click', handleTabAudioStream);
    fileInput.addEventListener('change', handleFileSelect);
    playPauseBtn.addEventListener('click', handleFilePlayPause);
    restartBtn.addEventListener('click', () => {
        if (audioElement) {
            audioElement.currentTime = 0;
            if (!isStreaming && currentMode === 'file') {
                handleFilePlayPause();
            }
        }
    });
    
    // [수정] 'change' 이벤트는 마우스를 놓았을 때 발생. 실시간 전송을 위해 'change' 사용
    silenceThresholdSlider.addEventListener('input', () => {
        const value = parseFloat(silenceThresholdSlider.value);
        silenceThresholdValue.textContent = `${value.toFixed(1)}s`;
    });

    silenceThresholdSlider.addEventListener('change', () => {
        updateSettingsOnServer();
    });

    translationEngineSelect.addEventListener('change', () => {
        updateSettingsOnServer();
    });
    
    // [핵심 수정] 엔진 변경 시 언어 목록 업데이트 및 서버 전송
    translationEngineSelect.addEventListener('change', () => {
        const engine = translationEngineSelect.value;
        populateLanguageSelects(engine); // 언어 목록 다시 그리기
        updateSettingsOnServer(); // 변경된 설정(언어 선택 포함)을 서버로 전송
    });

    // 언어 선택 변경 시에도 서버로 설정 전송
    langSelects.forEach(select => {
        select.addEventListener('change', updateSettingsOnServer);
    });
    
    // [추가] 'JSON으로 서버 전송' 버튼 클릭 이벤트 리스너
    tuningBtn.addEventListener('click', () => {
        try {
            // textarea의 텍스트를 JSON 객체로 파싱
            const params = JSON.parse(tuningText.value);
            
            if (socket && socket.readyState === WebSocket.OPEN) {
                const message = {
                    type: 'tuning',
                    params: params
                };
                socket.send(JSON.stringify(message));
                console.log("서버로 튜닝 파라미터 전송:", message);
                // 사용자에게 피드백을 주기 위해 버튼 텍스트 잠시 변경
                const originalText = tuningBtn.textContent;
                tuningBtn.textContent = '전송 완료!';
                tuningBtn.style.backgroundColor = '#4CAF50';
                setTimeout(() => {
                    tuningBtn.textContent = originalText;
                    tuningBtn.style.backgroundColor = '';
                }, 2000);
            }
        } catch (e) {
            alert('JSON 형식이 올바르지 않습니다. 코드를 다시 확인해주세요.\n오류: ' + e.message);
            console.error("JSON 파싱 오류:", e);
        }
    });

    // --- 오디오 컨텍스트 관리 ---
    function getAudioContext() {
        if (!audioContext) {
            try { 
                audioContext = new (window.AudioContext || window.webkitAudioContext)(); 
            } catch (e) { 
                alert('Web Audio API is not supported in this browser'); 
                console.error(e); 
            }
        }
        return audioContext;
    }

    // --- 마이크 및 탭오디오 처리 ---
    async function getMicrophones() {
        try {
            await navigator.mediaDevices.getUserMedia({ audio: true });
            const devices = await navigator.mediaDevices.enumerateDevices();
            micSelect.innerHTML = '';
            devices.filter(d => d.kind === 'audioinput').forEach(d => {
                const o = document.createElement('option'); o.value = d.deviceId; o.text = d.label || `마이크 ${micSelect.options.length + 1}`; micSelect.appendChild(o);
            });
            if (!isConnectionRejected) { recordBtn.disabled = false; }
        } catch (err) { 
            statusElem.textContent = '마이크 접근 불가'; 
            recordBtn.disabled = true; 
            tabAudioBtn.disabled = true; 
        }
    }
    
    function setMode(mode){
        currentMode = mode;
        micControlArea.classList.toggle("disabled", mode !== "mic" && mode !== null && mode !== "tab");
        fileControlArea.classList.toggle("disabled", mode !== "file" && mode !== null);
    }

    async function handleMicStream(){
        if(isStreaming) {
            stopStreaming();
        } else {
            setMode("mic");
            try {
                const deviceId = micSelect.value;
                mediaStream = await navigator.mediaDevices.getUserMedia({audio:{deviceId: deviceId ? {exact: deviceId} : undefined }});
                startStreaming(mediaStream,"mic");
            } catch(e){
                console.error("마이크 접근 오류:", e);
                statusElem.textContent="마이크 접근 불가";
                setMode(null);
            }
        }
    }

    async function handleTabAudioStream(){
        if(isStreaming) {
            stopStreaming();
        } else {
            try {
                const displayStream = await navigator.mediaDevices.getDisplayMedia({video:true, audio:true});
                if (displayStream.getAudioTracks().length > 0) {
                    setMode("tab");
                    mediaStream = new MediaStream(displayStream.getAudioTracks());
                    startStreaming(mediaStream,"tab");
                    displayStream.getVideoTracks()[0].onended = () => {
                        if (isStreaming && currentMode === "tab") stopStreaming();
                    };
                } else {
                    alert("오디오가 포함된 탭을 선택하지 않았거나, 오디오 공유 옵션을 체크하지 않았습니다.");
                }
            } catch(e){
                console.error("탭 오디오 캡처 오류:", e);
                if (e.name !== "NotAllowedError") {
                    alert("탭 오디오를 캡처할 수 없습니다. 브라우저가 이 기능을 지원하는지 확인하세요.");
                }
            }
        }
    }
    
    // --- 파일 처리 ---
    function handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;
        setMode('file');
        if (isStreaming) stopStreaming();
        if (audioElement) { audioElement.pause(); audioElement.srcObject = null; audioElement.src = ''; }
        if (audioSourceNode) { audioSourceNode.disconnect(); audioSourceNode = null; }
        audioElement = new Audio(URL.createObjectURL(file));
        playPauseBtn.disabled = false; restartBtn.disabled = false;
        statusElem.textContent = "파일 준비 완료. 재생 버튼을 누르세요.";
        audioElement.onended = () => { if (isStreaming) stopStreaming(); };
    }

    function setupAudioContextForFile(){
        const context = getAudioContext();
        if (!context) return false;
        if (context.state === "suspended") context.resume();
        if (!audioSourceNode || audioSourceNode.mediaElement !== audioElement) {
            try {
                audioSourceNode = context.createMediaElementSource(audioElement);
                analyserNode = context.createAnalyser();
                analyserNode.fftSize = 2048;
                const destinationNode = context.createMediaStreamDestination();
                mediaStream = destinationNode.stream;
                audioSourceNode.connect(analyserNode);
                audioSourceNode.connect(context.destination);
                analyserNode.connect(destinationNode);
            } catch(e) {
                console.error("Error setting up audio context nodes:", e);
                if (audioSourceNode) audioSourceNode.disconnect();
                return false;
            }
        }
        return true;
    }
    
    function handleFilePlayPause() {
        if (isStreaming) { 
            audioElement.pause(); 
            stopStreaming(); 
        } else {
            if (audioElement.ended) { audioElement.currentTime = 0; }
            if (setupAudioContextForFile()) {
                audioElement.play();
                startStreaming(mediaStream, 'file');
            } else { 
                statusElem.textContent = "오디오 컨텍스트를 시작할 수 없습니다."; 
            }
        }
    }

    // --- 공통 스트리밍 및 UI ---
    function startStreaming(stream, mode) {
        if (isStreaming) return;

        // [핵심 수정] 새로운 스트림을 시작하기 전에 서버에 신호를 보냄
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'stream_start' }));
        }

        isStreaming = true;
        mediaStream = stream; // 현재 활성 스트림을 저장

        if (mode !== 'file') {
            [outputElem, ...translationOutputs].forEach(el => el.innerHTML = '');
            interimElement = null;
        }

        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

        // ondataavailable 핸들러: 데이터가 생성될 때마다 서버로 전송
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
                socket.send(event.data);
            }
        };

        mediaRecorder.start(TIMESLICE);
        statusElem.textContent = '스트리밍 중...';

        if (mode === 'mic' || mode === 'tab') {
            recordBtn.textContent = '전송 중지'; 
            recordBtn.classList.add('recording');
            tabAudioBtn.textContent = '전송 중지'; 
            tabAudioBtn.classList.add('recording');
        } else if (mode === 'file') {
            playPauseBtn.textContent = '⏸️'; 
            playPauseBtn.classList.add('playing');
            drawWaveform();
        }
    }
    
    function stopStreaming() {
        if (!isStreaming) return;
        isStreaming = false;

        // 1. MediaRecorder 중지 및 이벤트 리스너 제거
        if (mediaRecorder) {
            if (mediaRecorder.state === "recording") {
                mediaRecorder.stop();
            }
            mediaRecorder.ondataavailable = null; // 이벤트 리스너 제거가 핵심!
        }
        
        // 2. MediaStream의 모든 트랙 중지 (마이크/탭오디오의 경우)
        if (currentMode !== 'file' && mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
        }

        if (animationFrameId) cancelAnimationFrame(animationFrameId);

        // 3. UI 업데이트
        if (currentMode === 'file') {
            clearWaveform();
            playPauseBtn.textContent = '▶️';
            playPauseBtn.classList.remove('playing');
            if (audioElement && audioElement.ended) {
                statusElem.textContent = '재생 완료. 다시 재생하거나 새 파일을 선택하세요.';
            } else {
                statusElem.textContent = '일시 중지. 다시 재생하려면 재생 버튼을 누르세요.';
            }
        } else {
            clearWaveform();
            statusElem.textContent = '대기 중';
            recordBtn.textContent = '전송 시작'; recordBtn.classList.remove('recording');
            tabAudioBtn.textContent = '탭 오디오 캡처'; tabAudioBtn.classList.remove('recording');
            setMode(null);
        }
    }

    function drawWaveform(){
        animationFrameId = requestAnimationFrame(drawWaveform);
        const bufferLength = analyserNode.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        analyserNode.getByteTimeDomainData(dataArray);
        canvasCtx.fillStyle="#2c2c2c"; canvasCtx.fillRect(0, 0, waveformCanvas.width, waveformCanvas.height);
        canvasCtx.lineWidth=2; canvasCtx.strokeStyle="#bb86fc"; canvasCtx.beginPath();
        const sliceWidth = waveformCanvas.width * 1.0 / bufferLength; let x = 0;
        for (let i = 0; i < bufferLength; i++) {
            const v = dataArray[i] / 128.0, y = v * waveformCanvas.height / 2;
            if (i === 0) canvasCtx.moveTo(x, y); else canvasCtx.lineTo(x, y);
            x += sliceWidth;
        }
        canvasCtx.lineTo(waveformCanvas.width, waveformCanvas.height / 2); canvasCtx.stroke();
    }
    function clearWaveform(){ canvasCtx.fillStyle="#2c2c2c"; canvasCtx.fillRect(0, 0, waveformCanvas.width, waveformCanvas.height); }
    
    function updateOutput(container, text, type, id = null){
        let p; const maxLines = 4;
        if (type === "interim") {
            p = interimElement;
            if (!p || !container.contains(p)) { 
                p = document.createElement("p"); 
                container.appendChild(p); 
                interimElement = p; 
            }
            p.className = "interim-typing";
        } else {
            if (container === outputElem) { 
                p = interimElement; 
            } else { 
                p = container.querySelector(`[data-id="${id}"]`); 
            }
            if (!p) { 
                p = document.createElement("p"); 
                container.appendChild(p); 
            }
            p.className = "final-result";
            if (container === outputElem) { 
                interimElement = null; 
            }
        }
        p.textContent = `> ${text}`;
        if (id) p.dataset.id = id;
        while (container.childElementCount > maxLines) { 
            container.removeChild(container.firstChild); 
        }
        container.scrollTop = container.scrollHeight;
    }
    
    // --- WebSocket 및 언어 설정 ---
    function connectWebSocket(){
        const wsUrl=`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/liveasr/control/${streamId}`;
        socket = new WebSocket(wsUrl);
        
        socket.onopen = () => { 
            statusElem.textContent = "서버에 연결됨"; 
        };

        socket.onmessage = event => {
            const data = JSON.parse(event.data);
            switch (data.type) {
                // [추가] 서버로부터 세션 초기화 메시지를 받아 UI에 적용
                case "session_init":
                    console.log("서버로부터 초기 설정값 수신:", data.settings);
                    if (data.settings.silence_threshold) {
                        const initialValue = data.settings.silence_threshold;
                        silenceThresholdSlider.value = initialValue;
                        silenceThresholdValue.textContent = `${parseFloat(initialValue).toFixed(1)}s`;
                    }

                    if (data.settings.translation_engine) {
                        const engine = data.settings.translation_engine;
                        translationEngineSelect.value = engine;
                        // [핵심 수정] 서버에서 받은 엔진 정보로 언어 목록 업데이트
                        populateLanguageSelects(engine);
                    }

                    // [추가] Whisper 파라미터를 textarea에 표시
                    if (data.settings.whisper_params) {
                        // JSON.stringify의 세 번째 인자(2)는 들여쓰기 칸 수를 의미
                        tuningText.value = JSON.stringify(data.settings.whisper_params, null, 2);
                    }
                    break;
                case "tuning_ack":  // [추가] 튜닝 성공/실패에 대한 피드백 처리
                    console.log("서버로부터 튜닝 확인 메시지 수신:", data);
                    // alert(data.message); // 필요하다면 alert로 알림
                    break;
                case "interim_result":
                    updateOutput(outputElem, data.text, "interim");
                    break;
                case "final_result":
                    const resultId = data.id;
                    updateOutput(outputElem, data.original, "final", resultId);
                    langSelects.forEach((select) => {
                        if (select.value !== "none") {
                            const container = translationOutputs[langSelects.indexOf(select)];
                            const p = document.createElement("p");
                            p.dataset.id = resultId;
                            // [핵심 수정] LANGUAGE_NAMES 사용
                            p.textContent = `> [${LANGUAGE_NAMES[select.value]} 번역 대기중...]`;
                            p.style.color = "#888";
                            container.appendChild(p);
                            while (container.childElementCount > 4) { container.removeChild(container.firstChild); }
                            container.scrollTop = container.scrollHeight;
                        }
                    });
                    break;
                case "translation_result":
                    const originalId = data.original_id;
                    const langCode = data.lang;
                    const translatedText = data.text;
                    langSelects.forEach((select, index) => {
                        if (select.value === langCode) {
                            const container = translationOutputs[index];
                            const p = container.querySelector(`[data-id="${originalId}"]`);
                            if (p) {
                                p.textContent = `> ${translatedText}`;
                                p.style.color = "";
                                p.className = "final-result";
                            }
                        }
                    });
            }
        };

        socket.onclose = event => {
            if (!event.wasClean) {
                isConnectionRejected = true;
                if (rejectionOverlay) rejectionOverlay.style.display = "flex";
                document.querySelectorAll("button, input, select").forEach(el => { el.disabled = true });
                statusElem.textContent = "연결 거부됨 (다른 컨트롤러 활성 중)";
            } else {
                statusElem.textContent = "연결 끊김, 재연결 시도...";
                if (isStreaming) stopStreaming();
                setTimeout(connectWebSocket, 5000);
            }
        };
    }

    // --- [핵심 수정] 언어 선택 드롭다운을 동적으로 채우는 함수 ---
    function populateLanguageSelects(engine) {
        const supportedCodes = SUPPORTED_LANGUAGES_BY_ENGINE[engine] || [];

        // 현재 선택된 값들을 저장
        const currentSelections = langSelects.map(select => select.value);

        langSelects.forEach((select, index) => {
            select.innerHTML = ""; // 기존 옵션 모두 제거

            // '사용안함' 옵션 추가
            const noneOption = document.createElement("option");
            noneOption.value = "none";
            noneOption.textContent = "사용안함";
            select.appendChild(noneOption);

            // 지원하는 언어만 순서대로 추가
            ALL_LANGUAGES.forEach(lang => {
                if (supportedCodes.includes(lang.code)) {
                    const option = document.createElement("option");
                    option.value = lang.code;
                    option.textContent = lang.name;
                    select.appendChild(option);
                }
            });

            // 이전 선택 값으로 복원 시도
            const previousValue = currentSelections[index];
            if (supportedCodes.includes(previousValue)) {
                select.value = previousValue;
            } else {
                select.value = "none"; // 지원하지 않으면 '사용안함'으로
            }
        });
    }

    // [수정] 모든 설정을 한 번에 모아서 서버로 전송하는 함수
    function updateSettingsOnServer() {
        if (socket && socket.readyState === WebSocket.OPEN) {
            // 현재 UI의 모든 설정 값을 읽어옴
            const activeLanguages = langSelects.map(s => s.value).filter(v => v !== 'none');
            const languages = [...new Set(activeLanguages)];
            const silenceThreshold = parseFloat(silenceThresholdSlider.value);
            const translationEngine = translationEngineSelect.value;

            // 하나의 config 메시지로 통합하여 전송
            const configMessage = {
                type: 'config',
                languages: languages,
                silence_threshold: silenceThreshold,
                translation_engine: translationEngine
            };
            
            console.log("서버로 설정 전송:", configMessage);
            socket.send(JSON.stringify(configMessage));
        }
    }

    // --- [추가] 파라미터 영역 토글 이벤트 리스너 ---
    paramToggleBtn.addEventListener('click', () => {
        // 현재 파라미터 영역이 보이는지 여부를 확인
        const isVisible = paramControlArea.style.display === 'block';

        if (isVisible) {
            // 영역 숨기기
            paramControlArea.classList.add('slide-up');
            paramControlArea.classList.remove('slide-down');
            // 애니메이션이 끝난 후 display를 none으로 변경
            setTimeout(() => {
                paramControlArea.style.display = 'none';
            }, 400); // CSS의 transition 시간과 일치시킴

            // 아이콘 변경: 축소 -> 확대
            iconCollapse.style.display = 'none';
            iconExpand.style.display = 'inline-block';
            paramToggleBtn.title = '파라미터 설정 펼치기';
        } else {
            // 영역 보이기
            paramControlArea.style.display = 'block';
            // display가 block으로 바뀐 후, 클래스를 추가하여 애니메이션 트리거
            setTimeout(() => {
                paramControlArea.classList.add('slide-down');
                paramControlArea.classList.remove('slide-up');
            }, 10); // 아주 짧은 딜레이

            // 아이콘 변경: 확대 -> 축소
            iconExpand.style.display = 'none';
            iconCollapse.style.display = 'inline-block';
            paramToggleBtn.title = '파라미터 설정 접기';
        }
    });

    // --- [추가] 모달 이벤트 리스너 ---
    // 도움말 아이콘 클릭 시 모달 열기
    helpIcon.addEventListener('click', () => {
        helpModal.style.display = 'block';
    });

    // 닫기(X) 버튼 클릭 시 모달 닫기
    closeModalBtn.addEventListener('click', () => {
        helpModal.style.display = 'none';
    });

    // 모달 바깥 영역 클릭 시 모달 닫기
    window.addEventListener('click', (event) => {
        if (event.target === helpModal) {
            helpModal.style.display = 'none';
        }
    });

    // ESC 키 눌렀을 때 모달 닫기
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && helpModal.style.display === 'block') {
            helpModal.style.display = 'none';
        }
    });
});