/** 컨테이너 그래프 렌더링 컴포넌트 */
let cy = null; // 그래프 인스턴스

// 상태 아이콘 매핑 함수
function getStatusIcon(status) {
  const iconMap = {
    'running': '▶',
    'exited': '■',
    'created': '+',
    'restarting': '↻',
    'removing': '×',
    'paused': '⏸',
    'dead': '☠'
  };
  return iconMap[status?.toLowerCase()] || '?';
}

export function renderGraph(containers) {
  const container = document.getElementById('cy');
  
  if (!container) {
    console.error('그래프 컨테이너를 찾을 수 없습니다.');
    return;
  }

  // 기존 그래프 제거
  if (cy) {
    cy.destroy();
    cy = null;
  }

  // 컨테이너가 없을 때 처리
  if (!containers || containers.length === 0) {
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">컨테이너가 없습니다.</div>';
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

  // 노드 데이터 생성
  const nodes = containers.map(c => ({
    data: {
      id: c.id,
      label: c.name || c.id.substring(0, 12),
      status: c.status,
      statusIcon: getStatusIcon(c.status),
      image: c.image,
      ports: c.ports,
      fullId: c.id
    }
  }));

  // 엣지 데이터 생성 (같은 네트워크에 있는 컨테이너 간 연결)
  // 실제로는 Docker 네트워크 정보를 기반으로 해야 하지만, 
  // 여기서는 예시로 모든 컨테이너를 중앙 노드에 연결
  const edges = [];
  const centerNodeId = 'center';
  
  // 중앙 노드 추가 (옵션)
  nodes.push({
    data: {
      id: centerNodeId,
      label: 'Docker Host',
      status: 'running',
      statusIcon: getStatusIcon('running'),
      isCenter: true
    }
  });

  // 각 컨테이너를 중앙에 연결
  containers.forEach(c => {
    edges.push({
      data: {
        id: `edge-${c.id}`,
        source: centerNodeId,
        target: c.id
      }
    });
  });

  try {
    // Cytoscape 초기화
    cy = cytoscape({
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
            'min-width': '90px',
            'min-height': '70px',
            'padding': '12px',
            'background-color': '#F6F8FC',
            'border-width': '3px',
            'border-color': function(ele) {
              const status = ele.data('status');
              const borderColors = {
                'running': '#22C55E',      // 활발한 초록
                'exited': '#4C5D7A',       // Slate 600
                'created': '#3B82F6',      // Indigo Blue
                'restarting': '#EAB308',   // Golden Amber
                'removing': '#F87171',     // Soft Red
                'paused': '#FB923C',       // Warm Orange
                'dead': '#475569'          // Dark Slate
              };
              return borderColors[status?.toLowerCase()] || '#4C5D7A';
            },
            'color': '#1E2A3A',
            'font-size': function(ele) {
              // 노드 크기에 따라 폰트 크기 동적 계산
              const width = ele.width();
              const height = ele.height();
              const minSize = Math.min(width, height);
              // 최소 11px, 최대 16px, 노드 크기에 비례
              const fontSize = Math.max(11, Math.min(16, minSize * 0.15));
              return fontSize + 'px';
            },
            'font-weight': '600',
            'text-wrap': 'wrap',
            'text-max-width': function(ele) {
              // 노드 너비의 80%를 최대 텍스트 너비로 설정
              return (ele.width() * 0.8) + 'px';
            },
            'text-outline-width': 0,
            'text-outline-color': 'transparent',
            'text-background-color': 'transparent',
            'text-background-opacity': 0,
            'text-background-padding': '0px',
            'text-background-shape': 'roundrectangle',
            'text-border-width': 0,
            'text-border-color': 'transparent',
            'overlay-opacity': 0,
            'overlay-color': 'transparent',
            'overlay-padding': '0px'
          }
        },
        {
          selector: 'node[isCenter = true]',
          style: {
            'label': function(ele) {
              const icon = ele.data('statusIcon') || '?';
              const label = ele.data('label') || '';
              return `${icon} ${label}`;
            },
            'background-color': '#F6F8FC',
            'border-width': '3px',
            'border-color': '#475569',
            'color': '#1E2A3A',
            'width': 'label',
            'height': 'label',
            'min-width': '150px',
            'min-height': '90px',
            'shape': 'roundrectangle',
            'font-size': function(ele) {
              // 중앙 노드 크기에 따라 폰트 크기 동적 계산
              const width = ele.width();
              const height = ele.height();
              const minSize = Math.min(width, height);
              // 최소 13px, 최대 18px
              const fontSize = Math.max(13, Math.min(18, minSize * 0.12));
              return fontSize + 'px';
            },
            'font-weight': '700',
            'text-outline-width': 0,
            'text-outline-color': 'transparent'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#64748b',
            'line-style': 'solid',
            'target-arrow-shape': 'none',
            'curve-style': 'bezier',
            'opacity': 0.75,
            'source-endpoint': 'outside-to-node',
            'target-endpoint': 'outside-to-node'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': '2px',
            'border-color': '#6366f1',
            'border-style': 'solid',
            'z-index': 1000,
            'background-color': '#f0f4ff'
          }
        },
        {
          selector: 'edge:selected',
          style: {
            'opacity': 0.9,
            'line-color': '#6366f1',
            'width': 2.5
          }
        },
        {
          selector: 'node:hover',
          style: {
            'transition-property': 'width, height',
            'transition-duration': '0.2s',
            'transition-timing-function': 'ease-out'
          }
        }
      ],
    layout: (typeof cytoscapeDagre !== 'undefined') ? {
      name: 'dagre',
      rankDir: 'TB',
      spacingFactor: 1.1,
      nodeSep: 60,
      edgeSep: 30,
      rankSep: 100
    } : {
      name: 'breadthfirst',
      directed: true,
      spacingFactor: 1.1,
      padding: 20
    }
  });

  // 그래프 배경을 밝은 테마로 변경
  container.style.background = '#ffffff';

    // 호버 효과 (미니멀하게)
    cy.on('mouseover', 'node', function(evt) {
      const node = evt.target;
      if (!node.data('isCenter')) {
        // 현재 크기 기준으로 1.1배 확대
        const currentWidth = node.width();
        const currentHeight = node.height();
        const newWidth = currentWidth * 1.1;
        const newHeight = currentHeight * 1.1;
        
        node.style('width', newWidth + 'px');
        node.style('height', newHeight + 'px');
        node.style('z-index', 999);
        node.style('border-width', '4px');  // 호버 시 테두리 더 두껍게
        node.style('background-color', '#EEF2FB');
        
        // 폰트 크기도 함께 조정 (노드 크기에 반응)
        const minSize = Math.min(newWidth, newHeight);
        const fontSize = Math.max(11, Math.min(16, minSize * 0.15));
        node.style('font-size', fontSize + 'px');
        
        // 연결된 엣지 강조
        node.connectedEdges().style('opacity', 0.85);
        node.connectedEdges().style('width', 2.5);
        node.connectedEdges().style('line-color', '#475569');
      }
    });

    cy.on('mouseout', 'node', function(evt) {
      const node = evt.target;
      if (!node.data('isCenter')) {
        // 원래 크기로 복원 (label 기반으로 자동 조정)
        node.style('width', 'label');
        node.style('height', 'label');
        node.style('z-index', 0);
        node.style('border-width', '3px');  // 원래 테두리 두께로 복원
        node.style('background-color', '#F6F8FC');
        // 폰트 크기도 자동으로 조정됨 (font-size 함수가 다시 계산)
        
        // 엣지 원래 스타일로 복원
        node.connectedEdges().style('opacity', 0.75);
        node.connectedEdges().style('width', 2);
        node.connectedEdges().style('line-color', '#64748b');
      }
    });
    
    // 노드 선택 효과 및 정보 표시
    cy.on('tap', 'node', function(evt) {
      const node = evt.target;
      const data = node.data();
      
      if (data.isCenter) return;
      
      // 다른 노드 선택 해제
      cy.elements().removeClass('selected');
      // 현재 노드 선택
      node.addClass('selected');
      // 연결된 엣지 선택
      node.connectedEdges().addClass('selected');
      
      // 정보 표시
      const info = `
컨테이너 ID: ${data.fullId}
이름: ${data.label}
상태: ${data.status}
이미지: ${data.image}
포트: ${data.ports || 'N/A'}
      `.trim();
      
      alert(info);
    });

    console.log('그래프 렌더링 완료:', nodes.length, '노드,', edges.length, '엣지');
  } catch (error) {
    console.error('그래프 렌더링 오류:', error);
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #f00;">그래프를 렌더링하는 중 오류가 발생했습니다. 콘솔을 확인하세요.</div>';
  }
}

export function resetGraphLayout() {
  if (cy) {
    const layoutName = (typeof cytoscapeDagre !== 'undefined') ? 'dagre' : 'breadthfirst';
    cy.layout({
      name: layoutName,
      rankDir: 'TB',
      spacingFactor: 1.1,
      nodeSep: 60,
      edgeSep: 30,
      rankSep: 100
    }).run();
  }
}

export function fitGraph() {
  if (cy) {
    // 패딩 추가 및 최소 줌 레벨 설정
    cy.fit(undefined, 50);  // 50px 패딩 추가
    // 최소 줌 레벨 제한 (너무 작아지지 않도록)
    if (cy.zoom() < 0.5) {
      cy.zoom(0.5);
    }
  }
}

export function getGraphInstance() {
  return cy;
}

