/**
 * FCP PoC Premium Dashboard Client Logic Script
 * (REST API 비동기 연동 및 인터랙티브 UI 상태 제어)
 */

const API_BASE = "http://localhost:8085";
let selectedNodeId = "silo_1";

// DOM 참조 포인터
const nodeListContainer = document.getElementById("node-list");
const containerListContainer = document.getElementById("container-list");
const selectedNodeDisplay = document.getElementById("selected-node-display");
const consoleLogs = document.getElementById("console-logs");

// KPI 엘리먼트
const kpiTime = document.getElementById("kpi-time");
const kpiCleaning = document.getElementById("kpi-cleaning");
const kpiDrift = document.getElementById("kpi-drift");
const kpiDriftBadge = document.getElementById("kpi-drift-badge");
const kpiOverhead = document.getElementById("kpi-overhead");
const driftCard = document.getElementById("drift-card");

// 입력 엘리먼트
const nodeLabelInput = document.getElementById("node-label-input");
const nodeUrlInput = document.getElementById("node-url-input");
const cleanRecipeSelect = document.getElementById("clean-recipe-select");
const roundNumInput = document.getElementById("round-num-input");

// 1. 라이브 로그 출력 유틸리티
function appendLog(message, type = "INFO") {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [${type}] `;
    consoleLogs.innerHTML += `<br>${prefix}${message}`;
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

// 2. 전체 연합 노드 조회 및 렌더링 (HTTP GET)
async function fetchNodes() {
    try {
        const response = await fetch(`${API_BASE}/api/nodes`);
        if (!response.ok) throw new Error("노드 정보 응답 에러");
        
        const nodes = await response.json();
        nodeListContainer.innerHTML = "";
        
        if (nodes.length === 0) {
            nodeListContainer.innerHTML = `<div style="text-align: center; color: var(--text-secondary); font-size: 0.8rem; padding: 1.5rem 0;">등록된 노드가 없습니다.</div>`;
            return;
        }

        nodes.forEach(node => {
            const card = document.createElement("div");
            card.className = `node-card ${node.node_id === selectedNodeId ? "pulse-border" : ""}`;
            card.style.cursor = "pointer";
            
            // 카드 클릭 시 타겟 선택 노드 스위칭
            card.onclick = () => {
                selectedNodeId = node.node_id;
                selectedNodeDisplay.innerText = `선택 노드: ${node.node_id} (${node.label})`;
                appendLog(`대상을 전환했습니다: ${node.label} (${node.node_id})`);
                
                // 이전 액티브 표시 제거 후 펄스 보더 적용
                document.querySelectorAll(".node-card").forEach(c => c.classList.remove("pulse-border"));
                card.classList.add("pulse-border");
                
                fetchContainers();
            };

            card.innerHTML = `
                <div class="node-header">
                    <span class="node-label">${node.label}</span>
                    <span class="node-status ${node.status === 'connected' ? 'status-connected' : 'status-disconnected'}"></span>
                </div>
                <div class="node-details">${node.base_url}</div>
                <div style="display:flex; justify-content: space-between; align-items:center; font-size: 0.65rem; color: var(--text-secondary); margin-top: 0.25rem;">
                    <span>역할: ${node.role} (${node.type})</span>
                    <span style="color: ${node.status === 'connected' ? 'var(--color-success)' : 'var(--color-danger)'}">${node.status === 'connected' ? '연결됨' : '연결 해제'}</span>
                </div>
            `;
            nodeListContainer.appendChild(card);
        });

        appendLog("원격 사일로 노드 리스트 동적 갱신 성공.");
    } catch (err) {
        appendLog(`노드 조회 실패: ${err.message}`, "ERROR");
    }
}

// 3. 신규 노드 등록 (HTTP POST)
async function registerNode() {
    const label = nodeLabelInput.value.trim();
    const url = nodeUrlInput.value.trim();
    
    if (!label || !url) {
        alert("모든 필드를 입력해 주세요.");
        return;
    }

    try {
        appendLog(`신규 사일로 가입 요청 발송: ${label}`);
        const response = await fetch(`${API_BASE}/api/nodes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ base_url: url, label: label, tls: false })
        });

        if (!response.ok) throw new Error("서버 등록 거부");
        const result = await response.json();
        
        appendLog(`사일로 가입 완료. 할당된 ID: ${result.node_id}`, "SUCCESS");
        nodeLabelInput.value = "";
        nodeUrlInput.value = "";
        
        await fetchNodes();
    } catch (err) {
        appendLog(`노드 가입 실패: ${err.message}`, "ERROR");
    }
}

// 4. 컨테이너 실시간 상태 모니터링 (HTTP GET)
async function fetchContainers() {
    containerListContainer.innerHTML = `<div style="text-align: center; color: var(--text-secondary); font-size: 0.75rem; padding: 1rem 0;">컨테이너 스캔 중...</div>`;
    try {
        const response = await fetch(`${API_BASE}/api/nodes/${selectedNodeId}/containers`);
        if (!response.ok) throw new Error("컨테이너 상태 로드 실패");
        
        const containers = await response.json();
        containerListContainer.innerHTML = "";

        if (containers.length === 0) {
            containerListContainer.innerHTML = `<div style="text-align: center; color: var(--text-secondary); font-size: 0.75rem; padding: 1rem 0;">수집된 컨테이너가 없거나 연결이 끊겼습니다.</div>`;
            return;
        }

        containers.forEach(c => {
            const item = document.createElement("div");
            item.className = "container-item";
            
            const isRunning = c.status.toLowerCase().includes("up") || c.status.toLowerCase().includes("running");
            const statusClass = isRunning ? "status-running" : "status-stopped";
            const statusText = isRunning ? "Running" : "Exited";
            const actionText = isRunning ? "정지" : "시작";
            const targetAction = isRunning ? "stop" : "start";

            item.innerHTML = `
                <div style="display:flex; flex-direction:column; gap:0.15rem;">
                    <span class="container-name">${c.name}</span>
                    <span style="font-size:0.65rem; color:var(--text-secondary);">${c.image}</span>
                </div>
                <div style="display:flex; gap:0.5rem; align-items:center;">
                    <span class="container-status-badge ${statusClass}">${statusText}</span>
                    <button class="btn btn-secondary" style="font-size: 0.65rem; padding: 0.15rem 0.4rem; border-color: rgba(255,255,255,0.1);" onclick="controlContainer('${c.container_id}', '${targetAction}')">
                        ${actionText}
                    </button>
                </div>
            `;
            containerListContainer.appendChild(item);
        });

        appendLog(`${selectedNodeId} 노드의 컨테이너 상태 스캔 완료.`);
    } catch (err) {
        containerListContainer.innerHTML = `<div style="text-align: center; color: var(--color-danger); font-size: 0.75rem; padding: 1rem 0;">연결에 실패했습니다.</div>`;
        appendLog(`컨테이너 조회 실패: ${err.message}`, "ERROR");
    }
}

// 5. 컨테이너 원격 제어 (HTTP POST)
async function controlContainer(containerId, action) {
    try {
        appendLog(`컨테이너 제어 명령 전송: ${selectedNodeId} ➡️ ${containerId} (${action})`);
        const response = await fetch(`${API_BASE}/api/nodes/${selectedNodeId}/containers/${containerId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: action })
        });

        if (!response.ok) throw new Error("제어 실패");
        appendLog(`제어 명령 전달 성공: ${action.toUpperCase()}`, "SUCCESS");
        
        // 1초 뒤 상태 새로고침
        setTimeout(fetchContainers, 1000);
    } catch (err) {
        appendLog(`컨테이너 제어 실패: ${err.message}`, "ERROR");
    }
}

// 6. 원격 데이터 정제 시뮬레이션 기동
async function runCleaningJob() {
    const recipeName = cleanRecipeSelect.value;
    appendLog(`데이터 정제 배치 Job 가동 요청 배포: ${recipeName}`);
    
    try {
        const response = await fetch(`${API_BASE}/api/cleaning-jobs?recipe_name=${encodeURIComponent(recipeName)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(["silo_1", "silo_2"])
        });
        
        if (!response.ok) throw new Error("정제 배포 에러");
        const result = await response.json();
        
        appendLog(`정제 완료. Job ID: ${result.job_id}`, "SUCCESS");
        appendLog(`정제 지표 수합: 결측치 ${result.cleaning_metrics.resolved_errors}건 보간 성공.`, "METRIC");
        
        // KPI 2 카드 동적 업데이트
        kpiCleaning.innerText = "100.0%";
        kpiCleaning.style.color = "var(--color-success)";
    } catch (err) {
        appendLog(`정제 잡 실행 실패: ${err.message}`, "ERROR");
    }
}

// 7. FedAvg 연합학습 및 파라미터 수합 시연
async function runFederatedLearning() {
    const roundVal = roundNumInput.value;
    const roundId = `rd_${roundVal.padStart(2, '0')}`;
    
    appendLog(`--- 연합학습 파라미터 수합 및 FedAvg 실행 (${roundId}) ---`);
    
    // 3개 가상 사일로 가중치 임시 탑재
    const siloPayloads = [
        {
            node_id: "silo_1",
            sample_size: 1500,
            weights: { "fc1.weight": 0.5124, "fc1.bias": -0.1250, "fc2.weight": 0.9102 }
        },
        {
            node_id: "silo_2",
            sample_size: 1200,
            weights: { "fc1.weight": 0.4850, "fc1.bias": -0.0950, "fc2.weight": 0.8750 }
        },
        {
            node_id: "silo_3",
            sample_size: 1800,
            weights: { "fc1.weight": 0.5310, "fc1.bias": -0.1120, "fc2.weight": 0.9420 }
        }
    ];

    try {
        // 1단계: 3개 사일로 가중치 개별 제출 시뮬레이션
        for (const payload of siloPayloads) {
            appendLog(`[가중치 수합] ${payload.node_id} 데이터 제출 중... (샘플 크기: ${payload.sample_size})`);
            const res = await fetch(`${API_BASE}/api/rounds/${roundId}/parameters`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error(`${payload.node_id} 가중치 제출 에러`);
        }
        
        appendLog(`가중치 취합 Barrier 대기 완료 (3/3). FedAvg 공식 집계 트리거.`, "PROCESS");
        
        // 2단계: 중앙 FCP 집계 트리거 호출
        const aggRes = await fetch(`${API_BASE}/api/rounds/${roundId}/aggregate`, {
            method: "POST"
        });
        if (!aggRes.ok) throw new Error("FedAvg 가중 평균 연산 실패");
        const aggResult = await aggRes.json();
        
        appendLog(`FedAvg 글로벌 가중치 갱신 성공!`, "SUCCESS");
        appendLog(`산출된 글로벌 파라미터: ${JSON.stringify(aggResult.global_weights)}`, "WEIGHT");
        
        // KPI 수치 라이브 갱신 시뮬레이션
        kpiTime.innerText = `${(10.5 + Math.random() * 5).toFixed(1)}s`;
        kpiOverhead.innerText = `${(10.2 + Math.random() * 4).toFixed(1)} KB`;
        
        const nextDrift = (0.05 + Math.random() * 0.08).toFixed(3);
        kpiDrift.innerText = nextDrift;
        if (parseFloat(nextDrift) > 0.12) {
            kpiDriftBadge.innerText = "경고";
            kpiDriftBadge.style.color = "var(--color-danger)";
            driftCard.style.borderColor = "var(--color-danger)";
        } else {
            kpiDriftBadge.innerText = "안정";
            kpiDriftBadge.style.color = "var(--color-success)";
            driftCard.style.borderColor = "var(--border-color)";
        }
        
    } catch (err) {
        appendLog(`연합학습 실행 실패: ${err.message}`, "ERROR");
    }
}

// 8. 이벤트 바인딩 및 주기 갱신
document.getElementById("add-node-btn").onclick = registerNode;
document.getElementById("scan-containers-btn").onclick = fetchContainers;
document.getElementById("run-clean-btn").onclick = runCleaningJob;
document.getElementById("run-fl-btn").onclick = runFederatedLearning;

// 초기 로딩 프로세스
window.onload = async () => {
    appendLog("FCP PoC 프론트엔드가 백엔드 API 연결을 수립합니다.");
    await fetchNodes();
    await fetchContainers();
};
