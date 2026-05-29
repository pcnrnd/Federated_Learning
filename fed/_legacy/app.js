/**
 * Federated Computing Simulator & Dashboard Orchestrator
 * Pure Vanilla JavaScript Client-Side Engine
 * Multi-Tab & Sidebar Log Filtering Navigation Upgrade (12-Node Scaling)
 */

const SVG_NS = "http://www.w3.org/2000/svg";

class FederatedSimulator {
    constructor() {
        // Tab Navigation Elements
        this.menuBtns = document.querySelectorAll('.menu-btn');
        this.tabPanes = document.querySelectorAll('.tab-pane');
        this.viewTitle = document.getElementById('view-title');
        this.viewDesc = document.getElementById('view-desc');
        
        // Simulation Control Elements
        this.btnStart = document.getElementById('btn-start');
        this.btnPause = document.getElementById('btn-pause');
        this.btnReset = document.getElementById('btn-reset');
        this.btnClearConsole = document.getElementById('btn-clear-console');
        this.logFilterBtns = document.querySelectorAll('.filter-btn');
        
        this.configAlgorithm = document.getElementById('config-algorithm');
        this.configRounds = document.getElementById('config-rounds');
        this.configEpochs = document.getElementById('config-epochs');
        this.configLr = document.getElementById('config-lr');
        
        this.valRounds = document.getElementById('val-rounds');
        this.valEpochs = document.getElementById('val-epochs');
        this.valLr = document.getElementById('val-lr');
        
        this.statRound = document.getElementById('stat-round');
        this.statAccuracy = document.getElementById('stat-accuracy');
        this.statTraffic = document.getElementById('stat-traffic');
        this.consoleOutput = document.getElementById('console-output');
        
        // Simulation Configuration State
        this.isRunning = false;
        this.isPaused = false;
        this.currentRound = 0;
        this.totalRounds = parseInt(this.configRounds.value);
        this.localEpochs = parseInt(this.configEpochs.value);
        this.learningRate = parseFloat(this.configLr.value);
        this.algorithm = this.configAlgorithm.value;
        
        this.globalAccuracy = 28.5; // Starting global accuracy
        this.globalLoss = 2.15;      // Starting global loss
        this.accumulatedTraffic = 0.0;
        
        // Staggered simulation timeout registry
        this.chart = null;
        this.timeoutIds = [];
        
        // Log Filtering Category Configuration
        this.activeLogFilter = 'all';
        
        // Generate 12 Symmetrical Sized Distributed Nodes
        this.nodes = {};
        this.generateTwelveNodes();
        
        // Render SVG and Cards dynamically
        this.renderTopology();
        this.renderNodeCards();
        
        // Bind all event listeners
        this.initEventListeners();
        this.initTabs();
        this.initLogFilters();
        
        // Initialize Chart
        this.initChart();
        
        // Sync configuration sliders values to indicators
        this.syncConfigValues();
    }
    
    // Scale to generate 12 nodes programmatically
    generateTwelveNodes() {
        for (let i = 1; i <= 12; i++) {
            const size = Math.floor(Math.random() * 850) + 450; // Private dataset size: 450 to 1300 rows
            const delay = Math.floor(Math.random() * 110) + 12; // Communication Latency: 12ms to 122ms
            const mult = 0.95 + (Math.random() * 0.1); // Slightly distinct learning capabilities (0.95 - 1.05 multiplier)
            
            this.nodes[i] = {
                id: i,
                name: `노드 ${i}`,
                size: size,
                delay: delay,
                acc: 0,
                loss: 0,
                mult: mult
            };
        }
    }
    
    // Calculate circular coordinates around central server
    getNodeCoords(id) {
        const centerX = 250;
        const centerY = 180;
        const radius = 135; // Perfect radius inside 500x360 SVG
        
        // Symmetrical angular placement for 12 nodes (30 degrees each)
        const angle = (id - 1) * (360 / 12) * (Math.PI / 180);
        
        const x = Math.round(centerX + radius * Math.cos(angle));
        const y = Math.round(centerY + radius * Math.sin(angle));
        return { x, y };
    }
    
    // Dynamically draw network paths and nodes inside SVG
    renderTopology() {
        const pathsContainer = document.getElementById('paths-container');
        const clientsContainer = document.getElementById('clients-container');
        
        pathsContainer.innerHTML = '';
        clientsContainer.innerHTML = '';
        
        Object.keys(this.nodes).forEach(id => {
            const coords = this.getNodeCoords(id);
            
            // 1. Create connecting lines (paths)
            const path = document.createElementNS(SVG_NS, "path");
            path.setAttribute("id", `path-node-${id}`);
            path.setAttribute("class", "network-path");
            path.setAttribute("d", `M ${coords.x} ${coords.y} L 250 180`);
            pathsContainer.appendChild(path);
            
            // 2. Create client node visual groups
            const group = document.createElementNS(SVG_NS, "g");
            group.setAttribute("class", "client-node");
            group.setAttribute("id", `node-${id}-visual`);
            group.setAttribute("transform", `translate(${coords.x}, ${coords.y})`);
            
            // Node Outer Glow Ring
            const outer = document.createElementNS(SVG_NS, "circle");
            outer.setAttribute("class", "node-outer");
            outer.setAttribute("r", "16"); // Compact size to fit 12 nodes beautifully
            
            // Node Inner Circle
            const inner = document.createElementNS(SVG_NS, "circle");
            inner.setAttribute("class", "node-inner");
            inner.setAttribute("r", "11");
            
            // FontAwesome Icon Center Label
            const textIcon = document.createElementNS(SVG_NS, "text");
            textIcon.setAttribute("class", "node-label");
            textIcon.setAttribute("y", "3");
            textIcon.setAttribute("text-anchor", "middle");
            
            const tspan = document.createElementNS(SVG_NS, "tspan");
            tspan.setAttribute("font-family", "FontAwesome");
            tspan.setAttribute("font-size", "8");
            tspan.setAttribute("fill", "#ffffff");
            tspan.textContent = "\uf109"; // terminal icon
            
            textIcon.appendChild(tspan);
            
            // Text Label below Node
            const textName = document.createElementNS(SVG_NS, "text");
            textName.setAttribute("class", "node-name");
            textName.setAttribute("y", "26");
            textName.setAttribute("text-anchor", "middle");
            textName.textContent = `노드 ${id}`;
            
            group.appendChild(outer);
            group.appendChild(inner);
            group.appendChild(textIcon);
            group.appendChild(textName);
            
            clientsContainer.appendChild(group);
        });
    }
    
    // Dynamically draw Node Cards in Node Management Tab
    renderNodeCards() {
        const container = document.getElementById('nodes-card-container');
        container.innerHTML = '';
        
        Object.keys(this.nodes).forEach(id => {
            const node = this.nodes[id];
            
            const card = document.createElement('div');
            card.className = 'glass-panel node-card';
            card.id = `card-node-${id}`;
            
            // Randomly simulate distinct label distributions
            const normalPct = Math.floor(Math.random() * 20) + 48; // 48% to 68%
            const abnormalPct = 100 - normalPct;
            
            card.innerHTML = `
                <div class="node-card-header">
                    <span class="node-badge status-idle" id="badge-node-${id}">IDLE</span>
                    <h3>노드 ${id} (분산 데이터 노드)</h3>
                </div>
                <div class="node-card-body">
                    <div class="node-stat-row">
                        <span class="label">로컬 데이터</span>
                        <span class="val font-semibold">${node.size.toLocaleString()} 건 (레코드)</span>
                    </div>
                    <div class="node-stat-row">
                        <span class="label">연결 지연</span>
                        <span class="val ${node.delay > 70 ? 'text-yellow' : 'text-green'}">${node.delay} ms</span>
                    </div>
                    <div class="node-stat-row">
                        <span class="label">프로세서 부하</span>
                        <div class="progress-bar-wrapper">
                            <div class="progress-bar" id="cpu-node-${id}" style="width: 0%;"></div>
                        </div>
                        <span class="val progress-text" id="cpu-text-node-${id}">0%</span>
                    </div>
                    <div class="node-divider"></div>
                    <div class="node-stat-row font-medium">
                        <span class="label">로컬 정확도</span>
                        <span class="val text-cyan" id="acc-node-${id}">0.00%</span>
                    </div>
                    <div class="node-stat-row font-medium">
                        <span class="label">로컬 오차율 (Loss)</span>
                        <span class="val text-red" id="loss-node-${id}">0.0000</span>
                    </div>
                </div>
                <div class="node-card-footer">
                    <div class="class-distribution">
                        <span class="label">레이블 데이터 분포 비율 (정상 / 비정상):</span>
                        <div class="dist-bar">
                            <div class="dist-segment seg-1" style="width: ${normalPct}%;" title="정상 비율: ${normalPct}%"></div>
                            <div class="dist-segment seg-2" style="width: ${abnormalPct}%;" title="비정상 비율: ${abnormalPct}%"></div>
                        </div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }
    
    // Tab Navigation switching logic
    initTabs() {
        const tabInfo = {
            'tab-dashboard': {
                title: '메인 대시보드',
                desc: '연합컴퓨팅 시스템의 토폴로지와 학습 사이클을 시뮬레이션하고 통제합니다.'
            },
            'tab-nodes': {
                title: '분산 노드 관리',
                desc: '각 개별 원격 연계 클라이언트의 로컬 프라이버시 데이터셋 크기, 하드웨어 부하 지표 및 성능을 감시합니다.'
            },
            'tab-analytics': {
                title: '성능 분석 차트',
                desc: '다수의 학습 연합 라운드에 따른 손실값 감소 수렴 추이 및 글로벌 모델 정확도의 진화를 심도 있게 추적합니다.'
            },
            'tab-logs': {
                title: '실시간 시스템 로그',
                desc: '중앙 오케스트레이터의 동적 지휘 및 전송 채널 패킷 통신 내역을 전수 모니터링합니다.'
            }
        };
        
        this.menuBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTab = btn.getAttribute('data-tab');
                
                this.menuBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                this.tabPanes.forEach(pane => {
                    pane.classList.remove('active');
                    if (pane.id === targetTab) {
                        pane.classList.add('active');
                    }
                });
                
                const info = tabInfo[targetTab];
                if (info) {
                    this.viewTitle.textContent = info.title;
                    this.viewDesc.textContent = info.desc;
                }
                
                // Recalculate Chart.js sizing upon full analytics tab focus
                if (targetTab === 'tab-analytics' && this.chart) {
                    this.chart.resize();
                }
            });
        });
    }
    
    // Operational logs filter menu
    initLogFilters() {
        this.logFilterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                this.logFilterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                const filter = btn.getAttribute('data-filter');
                this.activeLogFilter = filter;
                this.applyLogFilter();
            });
        });
    }
    
    applyLogFilter() {
        const logEntries = this.consoleOutput.querySelectorAll('.log-entry');
        logEntries.forEach(entry => {
            entry.classList.remove('hidden-log');
            
            if (this.activeLogFilter === 'all') return;
            
            if (this.activeLogFilter === 'system') {
                if (!entry.classList.contains('system')) entry.classList.add('hidden-log');
            } else if (this.activeLogFilter === 'server') {
                const isServerLog = entry.classList.contains('server') || 
                                    entry.classList.contains('success') || 
                                    entry.classList.contains('error');
                if (!isServerLog) entry.classList.add('hidden-log');
            } else if (this.activeLogFilter === 'nodes') {
                const isNodeLog = entry.className.includes('node-'); // matches node-1, node-2...
                if (!isNodeLog) entry.classList.add('hidden-log');
            }
        });
        this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
    }
    
    initEventListeners() {
        this.btnStart.addEventListener('click', () => this.startSimulation());
        this.btnPause.addEventListener('click', () => this.pauseSimulation());
        this.btnReset.addEventListener('click', () => this.resetSimulation());
        this.btnClearConsole.addEventListener('click', () => this.clearConsole());
        
        this.configRounds.addEventListener('input', (e) => {
            this.valRounds.textContent = e.target.value;
            this.totalRounds = parseInt(e.target.value);
            this.updateRoundStats();
        });
        
        this.configEpochs.addEventListener('input', (e) => {
            this.valEpochs.textContent = e.target.value;
            this.localEpochs = parseInt(e.target.value);
        });
        
        this.configLr.addEventListener('input', (e) => {
            this.valLr.textContent = parseFloat(e.target.value).toFixed(3);
            this.learningRate = parseFloat(e.target.value);
        });
        
        this.configAlgorithm.addEventListener('change', (e) => {
            this.algorithm = e.target.value;
            this.log('system', `합산 알고리즘 구성 변동 -> ${this.getAlgName(this.algorithm)}`);
        });
    }
    
    syncConfigValues() {
        this.valRounds.textContent = this.configRounds.value;
        this.valEpochs.textContent = this.configEpochs.value;
        this.valLr.textContent = parseFloat(this.configLr.value).toFixed(3);
        this.updateRoundStats();
    }
    
    updateRoundStats() {
        this.statRound.textContent = `${this.currentRound} / ${this.totalRounds}`;
    }
    
    updateNodeCardsInitial() {
        Object.keys(this.nodes).forEach(id => {
            const accEl = document.getElementById(`acc-node-${id}`);
            const lossEl = document.getElementById(`loss-node-${id}`);
            const cpuEl = document.getElementById(`cpu-node-${id}`);
            const cpuTxt = document.getElementById(`cpu-text-node-${id}`);
            
            if (accEl) accEl.textContent = '0.00%';
            if (lossEl) lossEl.textContent = '0.0000';
            if (cpuEl) cpuEl.style.width = '0%';
            if (cpuTxt) cpuTxt.textContent = '0%';
        });
    }
    
    getAlgName(alg) {
        if (alg === 'fedavg') return 'FedAvg (연합 가중 평균)';
        if (alg === 'fedmedian') return 'Federated Median (이상치 견고)';
        if (alg === 'secagg') return 'Secure Aggregation (암호 보안 합산)';
        return alg;
    }
    
    log(sender, message) {
        const time = new Date().toLocaleTimeString('ko-KR', { hour12: false });
        const entry = document.createElement('div');
        entry.className = `log-entry ${sender}`;
        
        const timeSpan = document.createElement('span');
        timeSpan.className = 'time';
        timeSpan.textContent = `[${time}]`;
        
        const tagSpan = document.createElement('span');
        tagSpan.className = 'tag';
        
        let tagText = '[SYSTEM]';
        if (sender === 'server') tagText = '[SERVER]';
        else if (sender === 'success') tagText = '[SUCCESS]';
        else if (sender === 'error') tagText = '[ERROR]';
        else if (sender.startsWith('node-')) {
            tagText = `[NODE ${sender.split('-')[1]}]`;
        }
        tagSpan.textContent = tagText;
        
        const msgSpan = document.createElement('span');
        msgSpan.className = 'msg';
        msgSpan.textContent = message;
        
        entry.appendChild(timeSpan);
        entry.appendChild(tagSpan);
        entry.appendChild(msgSpan);
        
        // Apply logging visibility filter rule on-the-fly
        if (this.activeLogFilter !== 'all') {
            if (this.activeLogFilter === 'system' && sender !== 'system') {
                entry.classList.add('hidden-log');
            } else if (this.activeLogFilter === 'server' && sender !== 'server' && sender !== 'success' && sender !== 'error') {
                entry.classList.add('hidden-log');
            } else if (this.activeLogFilter === 'nodes' && !sender.startsWith('node-')) {
                entry.classList.add('hidden-log');
            }
        }
        
        this.consoleOutput.appendChild(entry);
        this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
    }
    
    clearConsole() {
        this.consoleOutput.innerHTML = '';
        this.log('system', '오케스트레이터 로그 콘솔이 비워졌습니다.');
    }
    
    initChart() {
        const ctx = document.getElementById('performance-chart').getContext('2d');
        
        Chart.defaults.color = '#9ca3af';
        Chart.defaults.font.family = 'Inter, sans-serif';
        
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [0],
                datasets: [
                    {
                        label: '글로벌 모델 정확도 (%)',
                        data: [this.globalAccuracy],
                        borderColor: '#06b6d4',
                        backgroundColor: 'rgba(6, 182, 212, 0.08)',
                        borderWidth: 2,
                        tension: 0.3,
                        pointBackgroundColor: '#06b6d4',
                        pointBorderColor: 'rgba(255, 255, 255, 0.2)',
                        pointHoverRadius: 6,
                        yAxisID: 'yAccuracy'
                    },
                    {
                        label: '글로벌 Loss',
                        data: [this.globalLoss],
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.04)',
                        borderWidth: 2,
                        tension: 0.3,
                        pointBackgroundColor: '#ef4444',
                        pointBorderColor: 'rgba(255, 255, 255, 0.2)',
                        pointHoverRadius: 6,
                        yAxisID: 'yLoss'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            font: { size: 11 },
                            color: '#e5e7eb'
                        }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: '#111827',
                        titleColor: '#ffffff',
                        bodyColor: '#e5e7eb',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.03)' },
                        title: {
                            display: true,
                            text: '연합 학습 라운드 (Global Rounds)',
                            font: { size: 11 }
                        }
                    },
                    yAccuracy: {
                        type: 'linear',
                        position: 'left',
                        min: 0,
                        max: 100,
                        grid: { color: 'rgba(255, 255, 255, 0.03)' },
                        title: {
                            display: true,
                            text: '모델 정확도 (%)',
                            font: { size: 11 }
                        }
                    },
                    yLoss: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 2.5,
                        grid: { drawOnChartArea: false },
                        title: {
                            display: true,
                            text: '오차값 (Loss)',
                            font: { size: 11 }
                        }
                    }
                }
            }
        });
    }
    
    updateChart(round, acc, loss) {
        this.chart.data.labels.push(round);
        this.chart.data.datasets[0].data.push(acc);
        this.chart.data.datasets[1].data.push(loss);
        this.chart.update();
    }
    
    // Coordinate animated flowing packet particles across 12 nodes
    animatePackets(direction, callback) {
        const container = document.getElementById('packet-container');
        if (!container) return;
        
        container.innerHTML = '';
        
        const nodeIds = Object.keys(this.nodes);
        const packetColor = direction === 'download' ? '#06b6d4' : '#a855f7';
        
        nodeIds.forEach(id => {
            // Create particle circle
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("r", "4");
            circle.setAttribute("fill", packetColor);
            circle.setAttribute("filter", "url(#small-glow)");
            
            const animateMotion = document.createElementNS(SVG_NS, "animateMotion");
            
            // Stagger slightly using duration variation for rich aesthetics
            const dur = (1.2 + Math.random() * 0.4).toFixed(2); 
            animateMotion.setAttribute("dur", `${dur}s`);
            animateMotion.setAttribute("repeatCount", "1");
            animateMotion.setAttribute("fill", "freeze");
            animateMotion.setAttribute("calcMode", "linear");
            
            if (direction === 'download') {
                animateMotion.setAttribute("keyPoints", "1;0");
                animateMotion.setAttribute("keyTimes", "0;1");
            } else {
                animateMotion.setAttribute("keyPoints", "0;1");
                animateMotion.setAttribute("keyTimes", "0;1");
            }
            
            const mpath = document.createElementNS(SVG_NS, "mpath");
            mpath.setAttribute("href", `#path-node-${id}`);
            
            animateMotion.appendChild(mpath);
            circle.appendChild(animateMotion);
            container.appendChild(circle);
        });
        
        // Active visual toggles for paths and nodes
        nodeIds.forEach(id => {
            const path = document.getElementById(`path-node-${id}`);
            const visualNode = document.getElementById(`node-${id}-visual`);
            
            if (path) path.className.baseVal = 'network-path';
            if (visualNode) visualNode.className.baseVal = 'client-node';
            
            if (path && visualNode) {
                if (direction === 'download') {
                    path.classList.add('active-download');
                    visualNode.classList.add('active-sync');
                } else {
                    path.classList.add('active-upload');
                    visualNode.classList.add('active-upload');
                }
            }
        });
        
        const timerId = setTimeout(() => {
            nodeIds.forEach(id => {
                const path = document.getElementById(`path-node-${id}`);
                if (path) path.className.baseVal = 'network-path';
            });
            container.innerHTML = '';
            if (callback) callback();
        }, 1600);
        
        this.timeoutIds.push(timerId);
    }
    
    startSimulation() {
        if (this.isRunning && !this.isPaused) return;
        
        if (this.currentRound >= this.totalRounds) {
            this.resetSimulation();
            setTimeout(() => this.startSimulation(), 500);
            return;
        }
        
        this.isRunning = true;
        this.isPaused = false;
        this.toggleInputs(true);
        
        this.btnStart.disabled = true;
        this.btnStart.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 실시간 학습 중...`;
        this.btnPause.disabled = false;
        
        this.log('system', `연합 오케스트레이터 기동 시작 (학습 구성 -> 알고리즘: ${this.getAlgName(this.algorithm)}, 총 라운드: ${this.totalRounds})`);
        
        this.runNextRound();
    }
    
    pauseSimulation() {
        if (!this.isRunning || this.isPaused) return;
        
        this.isPaused = true;
        this.btnStart.disabled = false;
        this.btnStart.innerHTML = `<i class="fa-solid fa-play"></i> 학습 재개`;
        this.btnPause.disabled = true;
        
        this.log('system', `오케스트레이터 일시정지 명령 수신 (현재 라운드: ${this.currentRound})`);
        this.clearAllTimers();
        
        Object.keys(this.nodes).forEach(id => {
            const badge = document.getElementById(`badge-node-${id}`);
            if (badge) {
                badge.className = 'node-badge status-idle';
                badge.textContent = 'IDLE';
            }
            const visualNode = document.getElementById(`node-${id}-visual`);
            if (visualNode) visualNode.className.baseVal = 'client-node';
        });
    }
    
    resetSimulation() {
        this.clearAllTimers();
        
        this.isRunning = false;
        this.isPaused = false;
        this.currentRound = 0;
        this.globalAccuracy = 28.5;
        this.globalLoss = 2.15;
        this.accumulatedTraffic = 0.0;
        
        // Sync values from selectors
        this.totalRounds = parseInt(this.configRounds.value);
        this.localEpochs = parseInt(this.configEpochs.value);
        this.learningRate = parseFloat(this.configLr.value);
        this.algorithm = this.configAlgorithm.value;
        
        this.toggleInputs(false);
        
        this.btnStart.disabled = false;
        this.btnStart.innerHTML = `<i class="fa-solid fa-play"></i> 학습 시작`;
        this.btnPause.disabled = true;
        
        this.statAccuracy.textContent = '0.00%';
        this.statTraffic.textContent = '0.00 MB';
        this.updateRoundStats();
        
        // Clear SVG packet visualizer
        const container = document.getElementById('packet-container');
        if (container) container.innerHTML = '';
        
        // Regenerate Symmetrical Nodes and cards
        this.generateTwelveNodes();
        this.renderTopology();
        this.renderNodeCards();
        
        // Reset Chart
        this.chart.destroy();
        this.initChart();
        
        this.log('system', '연합 학습 대시보드 리셋 완료. 새로운 오케스트레이션 세션 대기 중.');
    }
    
    toggleInputs(disable) {
        this.configAlgorithm.disabled = disable;
        this.configRounds.disabled = disable;
        this.configEpochs.disabled = disable;
        this.configLr.disabled = disable;
    }
    
    clearAllTimers() {
        this.timeoutIds.forEach(id => clearTimeout(id));
        this.timeoutIds = [];
    }
    
    runNextRound() {
        if (this.currentRound >= this.totalRounds || this.isPaused) {
            if (this.currentRound >= this.totalRounds) {
                this.log('success', `[학습 세션 완료] 총 ${this.totalRounds} 라운드 통합 연합 학습이 성공적으로 종료되었습니다.`);
                this.log('success', `최종 정확도: ${this.globalAccuracy.toFixed(2)}%, 최저 글로벌 오차(Loss): ${this.globalLoss.toFixed(4)}`);
                
                this.btnStart.disabled = false;
                this.btnStart.innerHTML = `<i class="fa-solid fa-play"></i> 학습 재시작`;
                this.btnPause.disabled = true;
            }
            return;
        }
        
        this.currentRound++;
        this.updateRoundStats();
        
        this.log('server', `[ROUND ${this.currentRound}] 글로벌 가중치 파라미터 12개 분산 노드로 브로드캐스트 전송...`);
        
        // Download animation (Server -> 12 Nodes)
        this.animatePackets('download', () => {
            if (this.isPaused) return;
            
            // Nodes state to Syncing
            Object.keys(this.nodes).forEach(id => {
                const badge = document.getElementById(`badge-node-${id}`);
                if (badge) {
                    badge.textContent = 'SYNCING';
                    badge.className = 'node-badge status-syncing';
                }
            });
            
            const timer1 = setTimeout(() => {
                if (this.isPaused) return;
                this.log('server', '12개 분산 데이터 노드 전체 글로벌 매개변수 수신 및 복호화 완료.');
                this.runLocalTraining();
            }, 800);
            
            this.timeoutIds.push(timer1);
        });
    }
    
    runLocalTraining() {
        if (this.isPaused) return;
        
        // Transition client cards states to TRAINING
        Object.keys(this.nodes).forEach(id => {
            const badge = document.getElementById(`badge-node-${id}`);
            if (badge) {
                badge.textContent = 'TRAINING';
                badge.className = 'node-badge status-training';
            }
            
            const visualNode = document.getElementById(`node-${id}-visual`);
            if (visualNode) visualNode.className.baseVal = 'client-node active-local';
            
            // Sim CPU Spike
            const cpu = Math.floor(Math.random() * 15) + 80;
            const cpuBar = document.getElementById(`cpu-node-${id}`);
            const cpuText = document.getElementById(`cpu-text-node-${id}`);
            if (cpuBar) cpuBar.style.width = `${cpu}%`;
            if (cpuText) cpuText.textContent = `${cpu}%`;
        });
        
        this.log('system', `12개 모든 원격 노드 로컬 데이터 연합 학습 시작 (반복: ${this.localEpochs} Epochs, 속도: ${this.learningRate})`);
        
        // Print status metrics details for some nodes randomly to keep terminal organic and highly readable
        const selectedLogNodes = [1, Math.floor(Math.random() * 3) + 2, Math.floor(Math.random() * 4) + 6, 12];
        selectedLogNodes.forEach(id => {
            const node = this.nodes[id];
            this.log(`node-${id}`, `로컬 연계 프라이버시 데이터(${node.size.toLocaleString()}건) 최적화 연산 가속화 개시.`);
        });
        
        let localEpoch = 0;
        const trainInterval = setInterval(() => {
            if (this.isPaused) {
                clearInterval(trainInterval);
                return;
            }
            
            localEpoch++;
            if (localEpoch <= this.localEpochs) {
                // Incrementally update nodes metrics
                Object.keys(this.nodes).forEach(id => {
                    const node = this.nodes[id];
                    const roundProgress = this.currentRound / this.totalRounds;
                    const epochProgress = localEpoch / this.localEpochs;
                    
                    const finalTargetNodeAcc = 45 + (42 * Math.pow(roundProgress, 0.5) * node.mult);
                    const currentRoundStartAcc = this.currentRound === 1 ? 28 : (45 + (42 * Math.pow((this.currentRound - 1) / this.totalRounds, 0.5) * node.mult));
                    
                    const stepAcc = currentRoundStartAcc + (finalTargetNodeAcc - currentRoundStartAcc) * epochProgress;
                    const randomGitter = (Math.random() - 0.5) * 1.5;
                    node.acc = Math.min(98.5, Math.max(20.0, stepAcc + randomGitter));
                    
                    const finalTargetNodeLoss = 0.15 + (1.9 * (1 - Math.pow(roundProgress, 0.6)) / node.mult);
                    const currentRoundStartLoss = this.currentRound === 1 ? 2.1 : (0.15 + (1.9 * (1 - Math.pow((this.currentRound - 1) / this.totalRounds, 0.6)) / node.mult));
                    
                    const stepLoss = currentRoundStartLoss + (finalTargetNodeLoss - currentRoundStartLoss) * epochProgress;
                    node.loss = Math.max(0.02, stepLoss + (Math.random() - 0.5) * 0.05);
                    
                    const accEl = document.getElementById(`acc-node-${id}`);
                    const lossEl = document.getElementById(`loss-node-${id}`);
                    if (accEl) accEl.textContent = `${node.acc.toFixed(2)}%`;
                    if (lossEl) lossEl.textContent = node.loss.toFixed(4);
                });
            } else {
                clearInterval(trainInterval);
                this.log('system', '12개 노드 분산 로컬 학습 완료. 로컬 가중치 업데이트 전송 준비.');
                this.uploadLocalWeights();
            }
        }, 2200 / this.localEpochs);
    }
    
    uploadLocalWeights() {
        if (this.isPaused) return;
        
        // Transition badges to UPLOADING
        Object.keys(this.nodes).forEach(id => {
            const badge = document.getElementById(`badge-node-${id}`);
            if (badge) {
                badge.textContent = 'UPLOADING';
                badge.className = 'node-badge status-uploading';
            }
            
            // Release CPU
            const cpu = Math.floor(Math.random() * 8) + 3;
            const cpuBar = document.getElementById(`cpu-node-${id}`);
            const cpuText = document.getElementById(`cpu-text-node-${id}`);
            if (cpuBar) cpuBar.style.width = `${cpu}%`;
            if (cpuText) cpuText.textContent = `${cpu}%`;
        });
        
        // Trigger Upload Animations (12 Nodes -> Server)
        this.animatePackets('upload', () => {
            if (this.isPaused) return;
            
            // Traffic Calculation for 12 nodes
            let nodeTraffic = 1.15; // 1.15MB base local weights upload size
            if (this.algorithm === 'secagg') {
                nodeTraffic = 2.25; // Secure aggregation has crypto-masking overhead
            }
            
            const roundTraffic = nodeTraffic * 12; // multiplied by 12 Symmetrical Nodes!
            this.accumulatedTraffic += roundTraffic;
            this.statTraffic.textContent = `${this.accumulatedTraffic.toFixed(2)} MB`;
            
            // Log uploads staggeredly or selectively
            const selectedLogNodes = [1, Math.floor(Math.random() * 4) + 4, 12];
            selectedLogNodes.forEach(id => {
                const node = this.nodes[id];
                this.log(
                    `node-${id}`, 
                    `로컬 파라미터 업데이트 암호화 전송 완료 (크기: ${nodeTraffic.toFixed(2)} MB, 지연시간: ${node.delay} ms)`
                );
            });
            this.log('server', '12개 전 노드 개별 연합 가중치 획득 성공. 통합 집계 단계 진입.');
            
            const timer2 = setTimeout(() => {
                if (this.isPaused) return;
                this.aggregateGlobalModel();
            }, 800);
            
            this.timeoutIds.push(timer2);
        });
    }
    
    aggregateGlobalModel() {
        if (this.isPaused) return;
        
        // Reset topology visual nodes back to IDLE
        Object.keys(this.nodes).forEach(id => {
            const visualNode = document.getElementById(`node-${id}-visual`);
            if (visualNode) visualNode.className.baseVal = 'client-node';
            
            const badge = document.getElementById(`badge-node-${id}`);
            if (badge) {
                badge.className = 'node-badge status-idle';
                badge.textContent = 'IDLE';
            }
        });
        
        this.log('server', `[가중치 합산] ${this.getAlgName(this.algorithm)} 연산 기동 중...`);
        
        const timer3 = setTimeout(() => {
            if (this.isPaused) return;
            
            let sumAcc = 0;
            let sumLoss = 0;
            let totalWeight = 0;
            
            Object.keys(this.nodes).forEach(id => {
                const node = this.nodes[id];
                sumAcc += node.acc * node.size;
                sumLoss += node.loss * node.size;
                totalWeight += node.size;
            });
            
            let rawAcc = sumAcc / totalWeight;
            let rawLoss = sumLoss / totalWeight;
            
            if (this.algorithm === 'fedmedian') {
                rawAcc = rawAcc - 0.65 + (Math.random() * 0.4);
                rawLoss = rawLoss + 0.015 + (Math.random() * 0.01);
            } else if (this.algorithm === 'secagg') {
                this.log('server', '[보안 암호화 해독] 가해식 난수화 마스킹 소거 완료. 글로벌 모델 가중치 병합 성공.');
            }
            
            this.globalAccuracy = Math.min(99.4, rawAcc);
            this.globalLoss = Math.max(0.012, rawLoss);
            
            this.statAccuracy.textContent = `${this.globalAccuracy.toFixed(2)}%`;
            
            this.log('success', `[ROUND ${this.currentRound} 완료] 글로벌 파라미터 업데이트 성공. (검증 정확도: ${this.globalAccuracy.toFixed(2)}%, 글로벌 Loss: ${this.globalLoss.toFixed(4)})`);
            
            // Append data to Chart
            this.updateChart(this.currentRound, this.globalAccuracy, this.globalLoss);
            
            // Wait 2 seconds before executing next round
            const timer4 = setTimeout(() => {
                this.runNextRound();
            }, 2000);
            
            this.timeoutIds.push(timer4);
        }, 1200);
        
        this.timeoutIds.push(timer3);
    }
}

// Instantiate once DOM fully loads
window.addEventListener('DOMContentLoaded', () => {
    window.simulator = new FederatedSimulator();
});
