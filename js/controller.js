// watch.js

document.addEventListener('DOMContentLoaded', () => {
    // [수정] URL에서 스트림 ID 가져오기
    const pathParts = window.location.pathname.split('/');
    const streamId = pathParts[pathParts.length - 1];
    if (!streamId) {
        document.body.innerHTML = '<h1>잘못된 접근입니다. URL에 스트림 ID가 필요합니다. (예: /liveasr/watch/my_stream)</h1>';
        return;
    }

    // --- UI 요소 ---
    const gridContainer = document.getElementById('grid-container');
    const panels = document.querySelectorAll('.panel');
    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const originalPanel = document.getElementById('panel-original');
    const transPanels = [
        document.getElementById('panel-trans-1'),
        document.getElementById('panel-trans-2'),
        document.getElementById('panel-trans-3')
    ];
    
    // --- 상태 및 설정 ---
    const LANG_NAMES = { "en": "영어", "ja": "일본어", "zh": "중국어", "vi": "베트남어", "id": "인도네시아어", "tr": "터키어", "de": "독일어", "it": "이탈리아어", "pt": "포르투갈어", "fr": "프랑스어" };
    const MAX_LINES = 10;
    let interimElement = null;

    // --- 범용 UI 업데이트 함수 ---
    function updateOutput(container, text, type, id = null) {
        let p;
        if (!container) return;

        if (type === 'interim') {
            p = interimElement;
            if (!p || !container.contains(p)) {
                p = document.createElement('p');
                container.appendChild(p);
                interimElement = p;
            }
            p.className = 'interim-typing';
        } else { // 'final' 또는 'placeholder'
            // ID를 기반으로 기존 <p> 요소를 찾거나 새로 만듦
            if (id) {
                p = container.querySelector(`[data-id="${id}"]`);
            }
            if (!p) {
                p = document.createElement('p');
                container.appendChild(p);
            }
            // 원문 텍스트의 중간 결과는 interimElement를 사용
            if (container === originalPanel.querySelector('.output-div') && type === 'final') {
                if (interimElement) p = interimElement;
            }
            p.className = 'final-result';
            if (container === originalPanel.querySelector('.output-div')) {
                interimElement = null;
            }
        }
        
        p.textContent = `> ${text}`;
        if (id) p.dataset.id = id;
        while (container.childElementCount > MAX_LINES) {
            container.removeChild(container.firstChild);
        }
        container.scrollTop = container.scrollHeight;
    }
    
    // --- WebSocket 연결 및 메시지 처리 ---
    function connectWebSocket() {
        // [수정] WebSocket 주소에 스트림 ID 포함
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/liveasr/watch/${streamId}`;
        const socket = new WebSocket(wsUrl);

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);

            switch (data.type) {
                case 'config':
                    updatePanelHeaders(data.languages || []);
                    break;
                    
                case 'interim_result':
                    updateOutput(originalPanel.querySelector('.output-div'), data.text, 'interim');
                    break;
                    
                case 'final_result':
                    const resultId = data.id;
                    updateOutput(originalPanel.querySelector('.output-div'), data.original, 'final', resultId);
                    
                    // [수정] placeholder 생성 로직 삭제. translation_result에서 직접 처리
                    break;

                case 'translation_result':
                    // [수정] 서버에서 받은 lang 코드로 올바른 패널을 직접 찾음
                    const langCode = data.lang;
                    const transPanel = document.querySelector(`.panel[data-lang="${langCode}"]`);
                    if (transPanel) {
                        const container = transPanel.querySelector('.output-div');
                        updateOutput(container, data.text, 'final', data.original_id);
                    }
                    break;
            }
        };
        socket.onclose = () => setTimeout(connectWebSocket, 5000);
        socket.onerror = (error) => socket.close();
    }

    // --- 패널 및 전체화면 관리 ---
    function updatePanelHeaders(languages) {
        // 모든 번역 패널을 일단 숨김
        transPanels.forEach(panel => panel.style.display = 'none');
		
		gridContainer.classList.remove('grid-container1', 'grid-container2', 'grid-container3');
		
		const langCount = languages.length;
		if (langCount >= 1 && langCount <= 3) {
			gridContainer.classList.add(`grid-container${langCount}`);
		}
		 
        // 설정된 언어에 따라 필요한 패널만 표시
        languages.forEach((langCode, i) => {
            if (i < transPanels.length) {
                const panel = transPanels[i];
                const langName = LANG_NAMES[langCode] || `번역 ${i + 1}`;
                const panelDiv = panel.querySelector('.output-div');

                // 언어 설정이 바뀌면 내용 초기화
                if (panel.dataset.lang !== langCode) {
                    panelDiv.innerHTML = '';
                }
                
                panel.dataset.lang = langCode; // data-lang 속성 설정
                panel.querySelector('h3').textContent = langName;
                panel.style.display = 'flex'; // 패널 보이기
            }
        });
    }
    
    panels.forEach(panel => {
        panel.addEventListener('click', () => {
            if (panel.classList.contains('zoomed-in')) {
                panel.classList.remove('zoomed-in');
                gridContainer.classList.remove('zoomed-view');
            } else {
                if (document.querySelector('.zoomed-in')) return;
                panel.classList.add('zoomed-in');
                gridContainer.classList.add('zoomed-view');
            }
        });
    });
    
    fullscreenBtn.addEventListener('click', () => {
        if (!document.fullscreenElement) document.documentElement.requestFullscreen();
        else if (document.exitFullscreen) document.exitFullscreen();
    });

    // --- 초기 실행 ---
    connectWebSocket();
});