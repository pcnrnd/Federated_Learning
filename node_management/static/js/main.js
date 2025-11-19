/** 애플리케이션 진입점 - 모듈화된 코드 import */
import { showToast as _showToast } from './utils/toast.js';
import { showLoading as _showLoading, hideLoading as _hideLoading } from './utils/loading.js';
import * as nodesAPI from './api/nodes.js';
import * as containersAPI from './api/containers.js';
import { renderGraph, resetGraphLayout, fitGraph } from './components/graph/containerGraph.js';
import { renderServerGraph, resetServerGraphLayout, fitServerGraph } from './components/graph/serverGraph.js';
import { showServerDetailsPanel, closeServerDetailsPanel, setCurrentServersGetter } from './components/server/serverDetails.js';
import { loadServerList, setServerStateGetter, setServerStateSetter } from './components/server/serverList.js';
import * as serverForm from './components/server/serverForm.js';
import { renderContainerCards } from './components/container/containerCards.js';

// 전역 변수 (점진적으로 제거 예정)
let currentContainers = [];
let currentServers = []; // 현재 서버 목록

// 서버 상세 패널에 서버 목록 getter 설정
setCurrentServersGetter(() => currentServers);

// 서버 목록 상태 관리 설정
setServerStateGetter(() => currentServers);
setServerStateSetter((servers) => {
  currentServers = servers;
});

// 전역 함수 래퍼 (HTML onclick 호환성 유지)
function showToast(message, type = 'info') {
  return _showToast(message, type);
}

function showLoading() {
  return _showLoading();
}

function hideLoading() {
  return _hideLoading();
}

// 뷰 전환 함수
function switchView(viewType) {
  const serverView = document.getElementById('serverView');
  const serverGraphView = document.getElementById('serverGraphView');
  const toolbarSection = document.getElementById('toolbarSection');
  const serverBtn = document.getElementById('serverManagerBtn');
  const serverGraphBtn = document.getElementById('serverGraphBtn');

  // 모든 뷰 숨기기
  serverView.style.display = 'none';
  serverGraphView.style.display = 'none';
  
  // 모든 버튼 비활성화
  serverBtn.classList.remove('active');
  serverGraphBtn.classList.remove('active');

  if (viewType === 'server') {
    serverView.style.display = 'block';
    toolbarSection.style.display = 'none';
    serverBtn.classList.add('active');
    
    // 서버 관리 뷰로 전환 시 서버 목록 자동 로드
    loadServerList();
  } else if (viewType === 'serverGraph') {
    serverGraphView.style.display = 'block';
    toolbarSection.style.display = 'none';
    serverGraphBtn.classList.add('active');
    
    // 서버 그래프 뷰로 전환 시 서버 목록 로드 후 그래프 렌더링
    loadServerList().then(() => {
      setTimeout(() => {
        const servers = getCurrentServers();
        if (servers.length > 0) {
          renderServerGraph(servers);
        } else {
          const container = document.getElementById('serverCy');
          if (container) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">서버 데이터를 불러오는 중...</div>';
          }
        }
      }, 100);
    });
  }
}

// 그래프 렌더링 함수는 components/graph/containerGraph.js에서 import
// 서버 그래프 렌더링 함수는 components/graph/serverGraph.js에서 import
// 서버 상세 정보 패널은 components/server/serverDetails.js에서 import

// 카드 렌더링 함수는 components/container/containerCards.js에서 import

// 로딩 함수는 위에서 import된 함수 사용

async function reloadContainers() {
  const nodeSelect = document.getElementById("nodeSelect");
  const nodeId = nodeSelect.value;
  const containerGrid = document.getElementById("containerGrid");
  const statusText = document.getElementById("statusText");

  showLoading();
  containerGrid.innerHTML = '';
  statusText.textContent = "";

  try {
    const data = await containersAPI.getContainers(nodeId, true);

    if (!Array.isArray(data)) {
      containerGrid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <i class="fas fa-exclamation-triangle"></i>
          <h3>데이터 형식 오류</h3>
          <p>서버에서 올바른 형식의 데이터를 받지 못했습니다.</p>
        </div>
      `;
      hideLoading();
      return;
    }

    // 전역 변수에 저장 (그래프에서 사용)
    currentContainers = data;

    // 카드 렌더링
    renderContainerCards(data, nodeId);

    // 그래프 뷰가 활성화되어 있으면 그래프도 업데이트
    if (document.getElementById('graphView').style.display !== 'none') {
      renderGraph(data);
    }

    const now = new Date();
    statusText.textContent = `노드: ${nodeId} · 컨테이너 ${data.length}개 · 갱신: ${now.toLocaleTimeString()}`;
    
    hideLoading();
  } catch (e) {
    console.error(e);
    containerGrid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <i class="fas fa-exclamation-circle"></i>
        <h3>불러오기 실패</h3>
        <p>컨테이너 정보를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    `;
    statusText.textContent = "에러 발생 (콘솔 로그 참조)";
    hideLoading();
  }
}

async function doAction(action, nodeId, containerId) {
  const actionNames = {
    'start': '시작',
    'stop': '중지',
    'restart': '재시작'
  };
  
  if (!confirm(`${containerId} 컨테이너를 ${actionNames[action]} 하시겠습니까?`)) return;

  showLoading();

  try {
    let result;
    if (action === 'start') {
      result = await containersAPI.startContainer(nodeId, containerId);
    } else if (action === 'stop') {
      result = await containersAPI.stopContainer(nodeId, containerId);
    } else if (action === 'restart') {
      result = await containersAPI.restartContainer(nodeId, containerId);
    }

    if (result && result.ok !== false) {
      await reloadContainers();
      showToast(`${actionNames[action]} 요청이 완료되었습니다.`, 'success');
    } else {
      hideLoading();
      showToast(`${actionNames[action]} 요청이 실패했습니다.`, 'error');
    }
  } catch (e) {
    console.error(e);
    hideLoading();
    showToast('요청 중 오류가 발생했습니다.', 'error');
  }
}

// 토스트 함수는 위에서 import된 함수 사용

// 전역 함수로 export (HTML onclick 호환성)
window.switchView = switchView;
window.loadServerList = loadServerList;
window.renderGraph = renderGraph;
window.resetGraphLayout = resetGraphLayout;
window.fitGraph = fitGraph;
window.renderServerGraph = renderServerGraph;
window.resetServerGraphLayout = resetServerGraphLayout;
window.showServerDetailsPanel = showServerDetailsPanel;
window.closeServerDetailsPanel = closeServerDetailsPanel;
window.fitServerGraph = fitServerGraph;
window.reloadContainers = reloadContainers;
window.doAction = doAction;
window.openServerManager = openServerManager;
window.showAddServerForm = showAddServerForm;
window.closeServerFormModal = closeServerFormModal;
window.editServer = editServer;
window.saveServer = saveServer;
window.deleteServer = deleteServer;
window.testServerConnection = testServerConnection;
window.testServerConnectionById = testServerConnectionById;
window.cancelServerForm = cancelServerForm;
window.updateNodeSelect = updateNodeSelect;

// 헬퍼 함수 (내부 사용)
function getCurrentServers() {
  return currentServers;
}

// 페이지 로드 시 기본 뷰를 서버 그래프로 설정
window.addEventListener("load", function() {
  switchView('serverGraph');
});

// ============================================
// 서버 관리 함수
// ============================================

let currentEditingServerId = null;

// 서버 관리 뷰 열기 (switchView로 대체됨, 호환성을 위해 유지)
async function openServerManager() {
  switchView('server');
}

// 서버 목록 로드는 components/server/serverList.js에서 import

// 서버 폼 관련 함수는 components/server/serverForm.js에서 import
async function saveServer(event) {
  await serverForm.saveServer(event, async () => {
    // 서버 목록 새로고침
    await loadServerList();
    // 노드 선택 드롭다운 업데이트
    await updateNodeSelect();
  });
}

async function editServer(serverId) {
  await serverForm.editServer(serverId);
}

function showAddServerForm() {
  serverForm.showAddServerForm();
}

function closeServerFormModal() {
  serverForm.closeServerFormModal();
}

function testServerConnection() {
  serverForm.testServerConnection();
}

function cancelServerForm() {
  serverForm.cancelServerForm();
}

// 서버 삭제
async function deleteServer(serverId) {
  if (serverId === 'main') {
    showToast('중앙 서버는 삭제할 수 없습니다.', 'error');
    return;
  }
  
  if (!confirm('정말 이 서버를 삭제하시겠습니까?')) {
    return;
  }
  
  // 삭제 전에 해당 서버 아이템 찾기 (더 확실한 방법)
  const serverList = document.getElementById('serverList');
  let serverItemToRemove = null;
  if (serverList) {
    const items = serverList.querySelectorAll('.server-item');
    items.forEach(item => {
      // 서버 ID로 직접 찾기 (더 확실한 방법)
      const serverDetails = item.querySelector('.server-details');
      if (serverDetails) {
        // 첫 번째 span에 서버 ID가 있음: <span><i class="fas fa-server"></i> ${server.id}</span>
        const serverIdSpan = serverDetails.querySelector('span');
        if (serverIdSpan) {
          // 아이콘을 제외한 텍스트만 확인
          const textContent = serverIdSpan.textContent.trim();
          // 서버 ID가 정확히 일치하는지 확인 (공백 제거 후 비교)
          if (textContent === serverId || textContent.includes(serverId)) {
            serverItemToRemove = item;
          }
        }
      }
      // 백업: onclick 속성으로 찾기
      if (!serverItemToRemove) {
        const deleteBtn = item.querySelector(`button[onclick*="deleteServer('${serverId}')"]`);
        if (deleteBtn) {
          serverItemToRemove = item;
        }
      }
    });
  }
  
  try {
    console.log('서버 삭제 요청 시작:', serverId);
    
    const result = await nodesAPI.deleteNode(serverId);
    console.log('서버 삭제 성공:', result);
    
    // 즉시 DOM에서 제거 (목록 새로고침 전에 제거하여 깜빡임 방지)
    if (serverItemToRemove) {
      serverItemToRemove.remove(); // 즉시 제거
    }
    
    showToast(result.message || '서버가 삭제되었습니다.', 'success');
    
    // 서버 목록 새로고침 (재시도 로직 추가)
    let retryCount = 0;
    const maxRetries = 3;
    let loadSuccess = false;
    
    while (retryCount < maxRetries && !loadSuccess) {
      try {
        await loadServerList();
        loadSuccess = true;
        console.log('서버 목록 새로고침 성공');
      } catch (loadError) {
        retryCount++;
        console.error(`서버 목록 새로고침 실패 (시도 ${retryCount}/${maxRetries}):`, loadError);
        
        if (retryCount < maxRetries) {
          // 재시도 전 대기
          await new Promise(resolve => setTimeout(resolve, 500));
        } else {
          // 최종 실패 시 사용자에게 알림
          showToast('서버 목록을 새로고침하지 못했습니다. 페이지를 새로고침해주세요.', 'error');
          console.error('서버 목록 새로고침 최종 실패:', loadError);
        }
      }
    }
    
    // 서버 그래프가 활성화되어 있으면 다시 렌더링
    const serverGraphView = document.getElementById('serverGraphView');
    if (serverGraphView && serverGraphView.style.display !== 'none') {
      setTimeout(() => {
        // currentServers는 loadServerList()에서 이미 업데이트됨
        // 빈 배열이어도 renderServerGraph가 빈 상태를 처리함
        renderServerGraph(currentServers);
      }, 100);
    }
    
    // 노드 선택 드롭다운 업데이트
    try {
      await updateNodeSelect();
    } catch (updateError) {
      console.error('노드 선택 드롭다운 업데이트 실패:', updateError);
    }
    
    // 현재 선택된 노드가 삭제된 경우 기본 노드로 변경
    const nodeSelect = document.getElementById('nodeSelect');
    if (nodeSelect && nodeSelect.value === serverId) {
      nodeSelect.value = 'main';
      try {
        await reloadContainers();
      } catch (reloadError) {
        console.error('컨테이너 새로고침 실패:', reloadError);
      }
    }
  } catch (error) {
    // 네트워크 오류와 기타 오류 구분
    if (error instanceof TypeError && error.message.includes('fetch')) {
      console.error('네트워크 오류:', error);
      showToast('서버에 연결할 수 없습니다. 네트워크 연결을 확인해주세요.', 'error');
    } else if (error.name === 'AbortError') {
      console.error('요청 취소됨:', error);
      showToast('요청이 취소되었습니다.', 'error');
    } else {
      console.error('서버 삭제 오류:', error);
      console.error('오류 상세:', {
        name: error.name,
        message: error.message,
        stack: error.stack
      });
      showToast(error.message || '서버 삭제 중 오류가 발생했습니다.', 'error');
    }
    
    // 에러 발생 시 제거 취소 (이미 제거되지 않았으므로 복구 불필요)
    // 하지만 혹시 모를 경우를 대비해 목록 새로고침 시도
    try {
      await loadServerList();
    } catch (loadError) {
      console.error('에러 후 목록 새로고침 실패:', loadError);
    }
  }
}

// 서버 연결 테스트 (폼에서)는 components/server/serverForm.js에서 import

// 서버 연결 테스트 (목록에서)
async function testServerConnectionById(serverId) {
  try {
    showToast('연결 테스트 중...', 'info');
    
    const result = await nodesAPI.testConnection(serverId);
    
    if (result.ok) {
      showToast(`연결 성공! Docker ${result.version}`, 'success');
    } else {
      showToast(`연결 실패: ${result.error}`, 'error');
    }
    
    // 서버 목록 새로고침
    await loadServerList();
  } catch (error) {
    console.error('연결 테스트 오류:', error);
    showToast('연결 테스트 중 오류가 발생했습니다.', 'error');
  }
}

// 서버 폼 취소는 위에서 처리됨

// 노드 선택 드롭다운 업데이트
async function updateNodeSelect() {
  try {
    const nodes = await nodesAPI.getNodes();
    
    const nodeSelect = document.getElementById('nodeSelect');
    const currentValue = nodeSelect.value;
    
    nodeSelect.innerHTML = '';
    nodes.forEach(node => {
      const option = document.createElement('option');
      option.value = node.id;
      option.textContent = `${node.label} (${node.id})`;
      nodeSelect.appendChild(option);
    });
    
    // 현재 선택값 유지 (존재하는 경우)
    if (currentValue && nodes.find(n => n.id === currentValue)) {
      nodeSelect.value = currentValue;
    } else if (nodes.length > 0) {
      nodeSelect.value = nodes[0].id;
    }
  } catch (error) {
    console.error('노드 목록 업데이트 오류:', error);
  }
}

