
//controller.js

document.addEventListener('DOMContentLoaded', () => {
    // --- [핵심 수정] URL에서 스트림 ID 가져오기 (더 유연한 방식으로) ---
    const pathParts = window.location.pathname.split('/');
    const streamId = pathParts.filter(part => part).pop(); // 경로의 마지막 부분을 ID로 사용

    if (!streamId) {
        document.body.innerHTML = '<h1>잘못된 접근입니다. URL 끝에 스트림 ID가 필요합니다. (예: /liveasr/my_stream)</h1>';
        return;
    }

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
    let socket, mediaRecorder, mediaStream, animationFrameId;
    let isStreaming = false;
    let currentMode = null;
    let audioContext = null; 
    let audioElement, audioSourceNode, analyserNode;
    let interimElement = null;
    let isConnectionRejected = false;
    const LANGUAGES = { "none": "사용안함", "en": "영어", "ja": "일본어", "zh": "중국어", "vi": "베트남어", "id": "인도네시아어", "tr": "터키어", "de": "독일어", "it": "이탈리아어", "pt": "포르투갈어", "fr": "프랑스어" };

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
            recordBtn.textContent = '전송 중지'; recordBtn.classList.add('recording');
            tabAudioBtn.textContent = '전송 중지'; tabAudioBtn.classList.add('recording');
        } else if (mode === 'file') {
            playPauseBtn.textContent = '⏸️'; playPauseBtn.classList.add('playing');
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
        socket.onopen = () => { statusElem.textContent = "서버에 연결됨"; updateLanguagesOnServer(); };
        socket.onmessage = event => {
            const data = JSON.parse(event.data);
            switch (data.type) {
                case "interim_result":
                    updateOutput(outputElem, data.text, "interim");
                    break;
                case "final_result":
                    const resultId = data.id;
                    updateOutput(outputElem, data.original, "final", resultId);
                    langSelects.forEach((select, index) => {
                        if (select.value !== "none") {
                            const container = translationOutputs[index];
                            const p = document.createElement("p");
                            p.dataset.id = resultId;
                            p.textContent = `> [${LANGUAGES[select.value]} 번역 대기중...]`;
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

    function populateLanguageSelects(){
        langSelects.forEach(select => {
            select.innerHTML = "";
            for (const [code, name] of Object.entries(LANGUAGES)) {
                const option = document.createElement("option");
                option.value = code; option.textContent = name;
                select.appendChild(option);
            }
            select.value = "none";
            select.addEventListener("change", handleLanguageChange);
        });
    }

    function handleLanguageChange(){
        updateLanguagesOnServer();
    }

    function updateLanguagesOnServer(){
        const activeLanguages = langSelects.map(s => s.value).filter(v => v !== "none");
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({type: "config", languages: [...new Set(activeLanguages)] }));
        }
    }
});