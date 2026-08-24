/** 서버 그래프 렌더링 컴포넌트 */
let serverCy = null; // 서버 그래프 인스턴스

// 상태 아이콘 매핑 함수
function getServerStatusIcon(status) {
  return status === 'online' ? '✓' : '✗';
}

export function renderServerGraph(servers) {
  const container = document.getElementById('serverCy');
  
  if (!container) {
    console.error('서버 그래프 컨테이너를 찾을 수 없습니다.');
    return;
  }

  // 기존 그래프 제거
  if (serverCy) {
    serverCy.destroy();
    serverCy = null;
  }

  // 서버가 없을 때 처리
  if (!servers || servers.length === 0) {
    container.innerHTML = `
      <div class="graph-empty-state">
        <i class="fas fa-server" style="font-size: 4rem; color: #9ca3af; margin-bottom: 1.5rem;"></i>
        <h3 style="font-size: 1.5rem; color: var(--text-primary); margin-bottom: 0.5rem; font-weight: 600;">등록된 서버가 없습니다</h3>
        <p style="color: var(--text-secondary); margin-bottom: 1.5rem; font-size: 0.875rem;">서버를 추가하여 연합학습 네트워크를 구성하세요.</p>
        <button class="btn-modern btn-primary" onclick="showAddServerForm()" style="margin-top: 0.5rem;">
          <i class="fas fa-plus"></i>
          <span>서버 추가</span>
        </button>
      </div>
    `;
    return;
  }

  // Cytoscape가 로드되지 않았을 때 처리
  if (typeof cytoscape === 'undefined') {
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #f00;">Cytoscape.js 라이브러리를 로드할 수 없습니다.</div>';
    console.error('Cytoscape.js가 로드되지 않았습니다.');
    return;
  }

  // cytoscape-dagre 플러그인 등록 (사용 가능한 경우)
  if (typeof cytoscapeDagre !== 'undefined') {
    cytoscape.use(cytoscapeDagre);
  }

  // 중앙 서버와 클라이언트 서버 분리
  const centralServer = servers.find(s => s.role === 'central');
  const clientServers = servers.filter(s => s.role !== 'central');

  // 클라이언트 서버가 없을 때 처리 (실무 패턴: 조건부 빈 상태)
  if (clientServers.length === 0) {
    container.innerHTML = `
      <div class="graph-empty-state">
        <i class="fas fa-network-wired" style="font-size: 4rem; color: #9ca3af; margin-bottom: 1.5rem;"></i>
        <h3 style="font-size: 1.5rem; color: var(--text-primary); margin-bottom: 0.5rem; font-weight: 600;">서버 네트워크 구성 필요</h3>
        <p style="color: var(--text-secondary); margin-bottom: 1.5rem; font-size: 0.875rem; max-width: 400px; margin-left: auto; margin-right: auto;">
          클라이언트 서버를 추가하여 연합학습 네트워크를 구성하세요.<br>
          중앙 서버만으로는 네트워크를 시각화할 수 없습니다.
        </p>
        <button class="btn-modern btn-primary" onclick="showAddServerForm()" style="margin-top: 0.5rem;">
          <i class="fas fa-plus"></i>
          <span>클라이언트 서버 추가</span>
        </button>
      </div>
    `;
    return;
  }

  // 노드 데이터 생성
  const nodes = servers.map(s => ({
    data: {
      id: s.id,
      label: s.label || s.id,
      status: s.status,
      statusIcon: getServerStatusIcon(s.status),
      type: s.type || 'remote',
      role: s.role || 'client',
      fullId: s.id,
      base_url: s.base_url || '',
      isCentral: s.role === 'central'
    }
  }));

  // 엣지 생성: 중앙 서버 → 클라이언트 서버
  const edges = [];
  if (centralServer && clientServers.length > 0) {
    clientServers.forEach(client => {
      edges.push({
        data: {
          id: `edge-${centralServer.id}-${client.id}`,
          source: centralServer.id,
          target: client.id
        }
      });
    });
  }

  try {
    // Cytoscape 초기화
    serverCy = cytoscape({
      container: container,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: 'node',
          style: {
            'label': function(ele) {
              const icon = ele.data('statusIcon') || '?';
              const label = ele.data('label') || '';
              return `${icon} ${label}`;
            },
            'text-valign': 'center',
            'text-halign': 'center',
            'width': 'label',
            'height': 'label',
            'shape': 'roundrectangle',
            'min-width': '140px',
            'min-height': '60px',
            'padding': '12px 16px',
            'background-color': '#FFFFFF',
            'border-width': '1px',
            'border-color': function(ele) {
              const status = ele.data('status');
              const role = ele.data('role');
              if (role === 'central') {
                return status === 'online' ? '#4B5563' : '#EA4335';
              }
              if (status === 'online') {
                return '#60A5FA'; // 연파랑 (기존: #34A853)
              } else if (status === 'offline') {
                return '#EA4335'; // Kubeflow 실패 테두리 (정확한 색상)
              }
              return '#9E9E9E'; // 대기 상태
            },
            'border-radius': '8px',
            'color': '#1F2937',
            'font-size': '13px',
            'font-weight': '500',
            'font-family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            'text-wrap': 'wrap',
            'text-max-width': '120px',
            'text-margin-y': '0px',
            'overlay-opacity': 0,
            'transition-property': 'border-width, border-color, background-color, transform',
            'transition-duration': '0.2s',
            'transition-timing-function': 'ease-in-out'
          }
        },
        {
          selector: 'node[isCentral = true]',
          style: {
            'label': function(ele) {
              const icon = ele.data('statusIcon') || '?';
              const label = ele.data('label') || '';
              return `${icon} ${label}`;
            },
            'background-color': '#FFFFFF',
            'border-width': '1.5px',
            'border-color': function(ele) {
              const status = ele.data('status');
              return status === 'online' ? '#4B5563' : '#EA4335';
            },
            'min-width': '160px',
            'min-height': '70px',
            'font-size': '14px',
            'font-weight': '600',
            'padding': '14px 18px'
          }
        },
        {
          selector: 'node:active',
          style: {
            'border-width': '1.5px',
            'transform': 'scale(0.98)',
            'transition-duration': '0.1s'
          }
        },
        {
          selector: 'node:hover',
          style: {
            'border-width': '1.5px',
            'border-color': function(ele) {
              const status = ele.data('status');
              const role = ele.data('role');
              if (role === 'central') {
                return status === 'online' ? '#4B5563' : '#EA4335';
              }
              if (status === 'online') {
                return '#60A5FA';
              } else if (status === 'offline') {
                return '#EA4335';
              }
              return '#9E9E9E';
            },
            'transition-duration': '0.15s',
            'box-shadow': '0 4px 12px rgba(0, 0, 0, 0.15)'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': '2px',
            'border-color': function(ele) {
              const status = ele.data('status');
              const role = ele.data('role');
              if (role === 'central') {
                return status === 'online' ? '#4B5563' : '#EA4335';
              }
              if (status === 'online') {
                return '#60A5FA';
              } else if (status === 'offline') {
                return '#EA4335';
              }
              return '#9E9E9E';
            },
            'background-color': '#FFFFFF',
            'z-index': 1000,
            'box-shadow': '0 6px 16px rgba(0, 0, 0, 0.2)'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 1,
            'line-color': '#9CA3AF', // Kubeflow 기본 엣지 색상
            'line-style': 'solid',
            'target-arrow-shape': 'triangle',
            'target-arrow-color': '#9CA3AF',
            'target-arrow-size': '8px',
            'target-arrow-fill': 'filled',
            'curve-style': 'bezier',
            'control-point-distances': [0, -20],
            'control-point-weights': [0.25, 0.75],
            'opacity': 0.6,
            'transition-property': 'width, line-color, opacity',
            'transition-duration': '0.2s'
          }
        },
        {
          selector: 'edge:hover',
          style: {
            'width': 1.5,
            'line-color': '#6366F1',
            'target-arrow-color': '#6366F1',
            'opacity': 0.9
          }
        },
        {
          selector: 'edge:selected',
          style: {
            'width': 1.5,
            'line-color': '#6366F1',
            'target-arrow-color': '#6366F1',
            'opacity': 1
          }
        }
      ],
      layout: (typeof cytoscapeDagre !== 'undefined') ? {
        name: 'dagre',
        rankDir: 'TB',
        nodeSep: 80,
        edgeSep: 40,
        rankSep: 120,
        ranker: 'network-simplex',
        padding: 40
      } : {
        name: 'breadthfirst',
        directed: true,
        spacingFactor: 1.2,
        padding: 40,
        roots: centralServer ? `#${centralServer.id}` : undefined
      }
    });

    // 그래프 배경 설정 (Kubeflow 스타일)
    container.style.background = '#FAFBFC';
    container.style.border = '1px solid #E5E7EB';
    container.style.borderRadius = '8px';

    // 노드 클릭 이벤트는 외부에서 설정 (showServerDetailsPanel 함수 필요)
    serverCy.on('tap', 'node', function(evt) {
      const node = evt.target;
      const data = node.data();
      
      // 다른 노드 선택 해제
      serverCy.elements().removeClass('selected');
      // 현재 노드 선택
      node.addClass('selected');
      // 연결된 엣지 선택
      node.connectedEdges().addClass('selected');
      
      // 상세 정보 패널 표시 (외부 함수 호출)
      if (window.showServerDetailsPanel) {
        window.showServerDetailsPanel(data);
      }
    });

    // 배경 클릭 시 패널 닫기
    serverCy.on('tap', function(evt) {
      if (evt.target === serverCy) {
        serverCy.elements().removeClass('selected');
        if (window.closeServerDetailsPanel) {
          window.closeServerDetailsPanel();
        }
      }
    });

    console.log('서버 그래프 렌더링 완료:', nodes.length, '노드,', edges.length, '엣지');
  } catch (error) {
    console.error('서버 그래프 렌더링 오류:', error);
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #f00;">그래프를 렌더링하는 중 오류가 발생했습니다. 콘솔을 확인하세요.</div>';
  }
}

export function resetServerGraphLayout() {
  if (serverCy) {
    const centralNode = serverCy.nodes('[isCentral = true]');
    const layoutOptions = (typeof cytoscapeDagre !== 'undefined') ? {
      name: 'dagre',
      rankDir: 'TB',
      nodeSep: 80,
      edgeSep: 40,
      rankSep: 120,
      ranker: 'network-simplex',
      padding: 40
    } : {
      name: 'breadthfirst',
      directed: true,
      spacingFactor: 1.2,
      padding: 40,
      roots: centralNode.length > 0 ? `#${centralNode[0].id()}` : undefined
    };
    serverCy.layout(layoutOptions).run();
  }
}

export function fitServerGraph() {
  if (serverCy) {
    serverCy.fit(undefined, 50);
    if (serverCy.zoom() < 0.5) {
      serverCy.zoom(0.5);
    }
  }
}

export function getServerGraphInstance() {
  return serverCy;
}

