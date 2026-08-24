/** 서버 목록 컴포넌트 */
import * as nodesAPI from '../../api/nodes.js';
import { showToast } from '../../utils/toast.js';
import { renderServerGraph } from '../graph/serverGraph.js';

// 전역 변수에서 서버 목록 가져오기/설정하기 (임시 - 나중에 상태 관리로 개선)
let getCurrentServers = () => [];
let setCurrentServers = null;

export function setServerStateGetter(getter) {
  getCurrentServers = getter;
}

export function setServerStateSetter(setter) {
  setCurrentServers = setter;
}

export async function loadServerList() {
  try {
    const servers = await nodesAPI.getNodesStatus();
    
    // 응답이 배열인지 확인
    if (!Array.isArray(servers)) {
      throw new Error('서버 목록 형식이 올바르지 않습니다');
    }
    
    // 전역 변수에 저장 (그래프에서 사용)
    if (setCurrentServers) {
      setCurrentServers(servers);
    }
    
    const serverList = document.getElementById('serverList');
    if (!serverList) {
      // serverList가 없어도 그래프는 업데이트 가능
      // 서버 그래프 뷰가 활성화되어 있으면 그래프 업데이트
      if (document.getElementById('serverGraphView') && document.getElementById('serverGraphView').style.display !== 'none') {
        if (servers.length > 0) {
          renderServerGraph(servers);
        } else {
          const container = document.getElementById('serverCy');
          if (container) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">등록된 서버가 없습니다.</div>';
          }
        }
      }
      return;
    }
    
    serverList.innerHTML = '';
    
    if (servers.length === 0) {
      serverList.innerHTML = '<div class="empty-state"><p>등록된 서버가 없습니다.</p></div>';
      // 서버 그래프 뷰가 활성화되어 있으면 그래프도 업데이트
      if (document.getElementById('serverGraphView') && document.getElementById('serverGraphView').style.display !== 'none') {
        renderServerGraph([]);
      }
      return;
    }
    
    servers.forEach(server => {
      const serverItem = document.createElement('div');
      serverItem.className = 'server-item';
      
      const statusClass = server.status === 'online' ? 'online' : 'offline';
      const statusIcon = server.status === 'online' ? 'fa-check-circle' : 'fa-times-circle';
      const statusText = server.status === 'online' ? '온라인' : '오프라인';
      
      const roleText = server.role === 'central' ? '중앙 서버' : '클라이언트';
      const roleClass = server.role === 'central' ? 'role-central' : 'role-client';
      
      serverItem.innerHTML = `
        <div class="server-info">
          <div class="server-name">${server.label || server.id}</div>
          <div class="server-details">
            <span><i class="fas fa-server"></i> ${server.id}</span>
            <span class="server-role ${roleClass}">
              <i class="fas ${server.role === 'central' ? 'fa-crown' : 'fa-desktop'}"></i>
              ${roleText}
            </span>
            <span class="server-status ${statusClass}">
              <i class="fas ${statusIcon}"></i>
              ${statusText}
            </span>
          </div>
        </div>
        <div class="server-actions">
          ${server.id !== 'main' ? `
          <button class="btn-server-action test" onclick="testServerConnectionById('${server.id}')" title="연결">
            <i class="fas fa-plug"></i>
            <span>연결</span>
          </button>
          <button class="btn-server-action edit" onclick="editServer('${server.id}')" title="수정">
            <i class="fas fa-edit"></i>
            <span>수정</span>
          </button>
          <button class="btn-server-action delete" onclick="deleteServer('${server.id}')" title="삭제">
            <i class="fas fa-trash"></i>
            <span>삭제</span>
          </button>
          ` : ''}
        </div>
      `;
      
      serverList.appendChild(serverItem);
    });
    
    // 서버 그래프 뷰가 활성화되어 있으면 그래프도 업데이트
    if (document.getElementById('serverGraphView') && document.getElementById('serverGraphView').style.display !== 'none') {
      renderServerGraph(servers);
    }
  } catch (error) {
    console.error('서버 목록 로드 오류:', error);
    const errorMessage = error.message || '서버 목록을 불러오는 중 오류가 발생했습니다.';
    showToast(errorMessage, 'error');
    
    // 에러 발생 시에도 currentServers를 빈 배열로 초기화하여 UI 일관성 유지
    if (setCurrentServers) {
      setCurrentServers([]);
    }
    
    // 에러 상태 표시
    const serverList = document.getElementById('serverList');
    if (serverList) {
      serverList.innerHTML = `
        <div class="empty-state">
          <i class="fas fa-exclamation-triangle" style="color: #ef4444; font-size: 2rem; margin-bottom: 1rem;"></i>
          <p style="color: #ef4444;">${errorMessage}</p>
          <button class="btn-modern btn-primary" onclick="loadServerList()" style="margin-top: 1rem;">
            <i class="fas fa-redo"></i>
            <span>다시 시도</span>
          </button>
        </div>
      `;
    }
    
    // 서버 그래프 뷰가 활성화되어 있으면 빈 상태 표시
    const serverGraphView = document.getElementById('serverGraphView');
    if (serverGraphView && serverGraphView.style.display !== 'none') {
      renderServerGraph([]);
    }
  }
}

