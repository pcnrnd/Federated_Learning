/** 서버 상세 정보 패널 컴포넌트 */

// 전역 변수에서 서버 목록 가져오기 (임시 - 나중에 상태 관리로 개선)
let getCurrentServers = () => [];

export function setCurrentServersGetter(getter) {
  getCurrentServers = getter;
}

export function showServerDetailsPanel(serverData) {
  const panel = document.getElementById('serverDetailsPanel');
  const content = document.getElementById('serverDetailsContent');
  
  if (!panel || !content) return;
  
  // 서버 정보 가져오기 (base_url 등 추가 정보)
  const servers = getCurrentServers();
  const server = servers.find(s => s.id === serverData.fullId) || serverData;
  
  const statusText = serverData.status === 'online' ? '온라인' : '오프라인';
  const roleText = serverData.role === 'central' ? '중앙 서버' : '클라이언트 서버';
  
  content.innerHTML = `
    <div class="detail-section">
      <h4><i class="fas fa-server"></i> 기본 정보</h4>
      <div class="detail-item">
        <span class="detail-label">서버 ID:</span>
        <span class="detail-value">${serverData.fullId}</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">서버 이름:</span>
        <span class="detail-value">${serverData.label}</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">상태:</span>
        <span class="detail-value status-${serverData.status}">
          <i class="fas ${serverData.status === 'online' ? 'fa-check-circle' : 'fa-times-circle'}"></i>
          ${statusText}
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">역할:</span>
        <span class="detail-value role-${serverData.role}">
          <i class="fas ${serverData.role === 'central' ? 'fa-crown' : 'fa-desktop'}"></i>
          ${roleText}
        </span>
      </div>
    </div>
    <div class="detail-section">
      <h4><i class="fas fa-network-wired"></i> 연결 정보</h4>
      <div class="detail-item">
        <span class="detail-label">URL:</span>
        <span class="detail-value">${server.base_url || serverData.base_url || 'N/A'}</span>
      </div>
    </div>
  `;
  
  panel.style.display = 'block';
}

export function closeServerDetailsPanel() {
  const panel = document.getElementById('serverDetailsPanel');
  if (panel) {
    panel.style.display = 'none';
  }
}

