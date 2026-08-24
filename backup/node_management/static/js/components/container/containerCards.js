/** 컨테이너 카드 렌더링 컴포넌트 */
export function renderContainerCards(containers, nodeId) {
  const containerGrid = document.getElementById('containerGrid');
  
  if (!containers || containers.length === 0) {
    containerGrid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <i class="fas fa-inbox"></i>
        <h3>컨테이너가 없습니다</h3>
        <p>이 노드에 등록된 컨테이너가 없습니다.</p>
      </div>
    `;
    return;
  }

  containerGrid.innerHTML = '';
  
  containers.forEach((c, index) => {
    const card = document.createElement('div');
    card.className = `container-card ${c.status.toLowerCase()}`;
    card.style.animationDelay = `${index * 0.05}s`;
    
    const statusClassMap = {
      "running": "badge-running",
      "exited": "badge-exited",
      "created": "badge-created",
      "restarting": "badge-restarting",
      "removing": "badge-removing",
      "paused": "badge-paused",
      "dead": "badge-dead"
    };
    
    const statusClass = statusClassMap[c.status.toLowerCase()] || "badge-exited";
    const statusIconMap = {
      "running": "fa-play-circle",
      "exited": "fa-stop-circle",
      "created": "fa-plus-circle",
      "restarting": "fa-sync-alt",
      "removing": "fa-trash-alt",
      "paused": "fa-pause-circle",
      "dead": "fa-skull"
    };
    const statusIcon = statusIconMap[c.status.toLowerCase()] || "fa-question-circle";
    
    card.innerHTML = `
      <div class="card-header">
        <div>
          <div class="card-title">${c.name || 'Unnamed'}</div>
          <div class="card-id">${c.id}</div>
        </div>
        <span class="card-badge ${statusClass}">
          <i class="fas ${statusIcon}"></i> ${c.status}
        </span>
      </div>
      <div class="card-body">
        <div class="card-info">
          <i class="fas fa-image"></i>
          <span class="card-info-label">이미지:</span>
          <span class="card-info-value">${c.image || 'N/A'}</span>
        </div>
        ${c.ports ? `
        <div class="card-info">
          <i class="fas fa-network-wired"></i>
          <span class="card-info-label">포트:</span>
          <span class="card-info-value">${c.ports}</span>
        </div>
        ` : ''}
      </div>
      <div class="card-actions">
        <button class="btn-action start" onclick="doAction('start', '${nodeId}', '${c.id}')" ${c.status.toLowerCase() === 'running' ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : ''}>
          <i class="fas fa-play"></i>
          <span>시작</span>
        </button>
        <button class="btn-action stop" onclick="doAction('stop', '${nodeId}', '${c.id}')" ${c.status.toLowerCase() !== 'running' ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : ''}>
          <i class="fas fa-stop"></i>
          <span>중지</span>
        </button>
        <button class="btn-action restart" onclick="doAction('restart', '${nodeId}', '${c.id}')">
          <i class="fas fa-redo"></i>
          <span>재시작</span>
        </button>
      </div>
    `;
    
    containerGrid.appendChild(card);
  });
}

