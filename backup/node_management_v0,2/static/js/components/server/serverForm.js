/** 서버 폼 모달 컴포넌트 */
import * as nodesAPI from '../../api/nodes.js';
import { showToast } from '../../utils/toast.js';

let currentEditingServerId = null;

export function getCurrentEditingServerId() {
  return currentEditingServerId;
}

export function setCurrentEditingServerId(id) {
  currentEditingServerId = id;
}

export function showAddServerForm() {
  const modal = document.getElementById('serverFormModal');
  const formTitle = document.getElementById('serverFormTitle');
  formTitle.innerHTML = '<i class="fas fa-server"></i> 서버 추가';
  document.getElementById('serverForm').reset();
  currentEditingServerId = null;
  document.getElementById('serverTestResult').style.display = 'none';
  modal.style.display = 'flex';
}

export function closeServerFormModal() {
  const modal = document.getElementById('serverFormModal');
  modal.style.display = 'none';
  document.getElementById('serverForm').reset();
  currentEditingServerId = null;
  document.getElementById('serverTestResult').style.display = 'none';
}

// 모달 외부 클릭 시 닫기
document.addEventListener('click', function(event) {
  const modal = document.getElementById('serverFormModal');
  if (event.target === modal) {
    closeServerFormModal();
  }
});

export async function editServer(serverId) {
  try {
    const server = await nodesAPI.getNode(serverId);
    
    // 서버 정보를 폼에 채우기
    document.getElementById('serverId').value = server.id;
    document.getElementById('serverLabel').value = server.label;
    document.getElementById('serverUrl').value = server.base_url;
    // TLS 옵션은 현재 UI에서 숨기며, 항상 비활성(false)로 취급합니다.
    
    // 모달 열기
    const modal = document.getElementById('serverFormModal');
    const formTitle = document.getElementById('serverFormTitle');
    formTitle.innerHTML = '<i class="fas fa-server"></i> 서버 수정';
    currentEditingServerId = serverId;
    document.getElementById('serverTestResult').style.display = 'none';
    modal.style.display = 'flex';
  } catch (error) {
    console.error('서버 수정 오류:', error);
    showToast('서버 정보를 불러오는 중 오류가 발생했습니다.', 'error');
  }
}

export async function saveServer(event, onSuccess) {
  event.preventDefault();
  
  const formData = {
    id: document.getElementById('serverId').value.trim(),
    label: document.getElementById('serverLabel').value.trim(),
    base_url: document.getElementById('serverUrl').value.trim(),
    // TLS 기능은 아직 미구현 상태이므로 항상 false로 전송합니다.
    tls: false
  };
  
  if (!formData.id || !formData.label || !formData.base_url) {
    showToast('모든 필수 항목을 입력해주세요.', 'error');
    return;
  }
  
  try {
    let result;
    if (currentEditingServerId) {
      // 수정
      result = await nodesAPI.updateNode(currentEditingServerId, formData);
    } else {
      // 추가
      result = await nodesAPI.addNode(formData);
    }
    showToast(result.message || '서버가 저장되었습니다.', 'success');
    
    // 성공 콜백 호출
    if (onSuccess) {
      await onSuccess();
    }
    
    // 모달 닫기
    closeServerFormModal();
  } catch (error) {
    console.error('서버 저장 오류:', error);
    showToast(error.message || '서버 저장 중 오류가 발생했습니다.', 'error');
  }
}

export async function testServerConnection() {
  const serverUrl = document.getElementById('serverUrl').value.trim();
  const serverId = document.getElementById('serverId').value.trim();
  
  if (!serverUrl) {
    showToast('URL을 입력해주세요.', 'error');
    return;
  }
  
  if (!serverId) {
    showToast('서버 ID를 입력한 후 테스트해주세요.', 'error');
    return;
  }
  
  const testResult = document.getElementById('serverTestResult');
  testResult.style.display = 'block';
  testResult.className = 'test-result';
  testResult.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 연결 테스트 중...';
  
  try {
    // 먼저 서버가 존재하는지 확인하고, 없으면 임시로 추가하여 테스트
    let testServerId = serverId;
    let needCleanup = false;
    
    try {
      await nodesAPI.getNode(serverId);
    } catch {
      // 서버가 없으면 임시로 추가 (테스트용)
      const tempServer = {
        id: serverId,
        label: '테스트',
        base_url: serverUrl,
        // TLS 기능은 아직 미구현 상태이므로 테스트 시에도 사용하지 않습니다.
        tls: false
      };
      
      await nodesAPI.addNode(tempServer);
      needCleanup = true;
    }
    
    // 연결 테스트
    const result = await nodesAPI.testConnection(testServerId);
    
      // 임시로 추가한 경우 삭제
      if (needCleanup && !currentEditingServerId) {
        try {
          await nodesAPI.deleteNode(serverId);
        } catch (e) {
          console.warn('임시 서버 삭제 실패:', e);
        }
      }
    
    if (result.ok) {
      testResult.className = 'test-result success';
      testResult.innerHTML = `
        <i class="fas fa-check-circle"></i>
        <strong>연결 성공!</strong><br>
        Docker 버전: ${result.version || 'N/A'}<br>
        API 버전: ${result.api_version || 'N/A'}
      `;
    } else {
      testResult.className = 'test-result error';
      testResult.innerHTML = `
        <i class="fas fa-times-circle"></i>
        <strong>연결 실패</strong><br>
        ${result.error || '알 수 없는 오류'}
      `;
    }
  } catch (error) {
    testResult.className = 'test-result error';
    testResult.innerHTML = `
      <i class="fas fa-times-circle"></i>
      <strong>연결 테스트 실패</strong><br>
      ${error.message}
    `;
  }
}

export function cancelServerForm() {
  closeServerFormModal();
}

