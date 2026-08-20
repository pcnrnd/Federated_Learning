import React from 'react';

interface TopologyNode {
  id: string;
  label: string;
  role: string;
  over_budget?: boolean;
}

interface TopologyEdge {
  source: string;
  target: string;
  kind: string;
}

interface TopologyPayload {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

interface PulseTopologyProps {
  payload: TopologyPayload | null;
}

export const PulseTopology: React.FC<PulseTopologyProps> = ({ payload }) => {
  if (!payload || !payload.nodes || payload.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 border border-dashed border-white/5 rounded-xl bg-white/[0.01] text-muted text-xs">
        노드/그룹 미등록
      </div>
    );
  }

  const groupNodes = payload.nodes.filter((n) => n.role === 'group');
  const silos = payload.nodes.filter((n) => n.role !== 'group' && n.role !== 'deployment');
  const deployments = payload.nodes.filter((n) => n.role === 'deployment');

  const groupedSilos: { [key: string]: string[] } = {};
  payload.edges
    .filter((e) => e.kind === 'group')
    .forEach((e) => {
      (groupedSilos[e.source] ||= []).push(e.target);
    });

  return (
    <div className="flex-1 overflow-auto flex flex-col gap-3 font-sans">
      {groupNodes.map((g) => (
        <div key={g.id} className="border border-white/5 rounded-xl p-4 bg-[#1e293b]/25 shadow-inner">
          <div className="text-accent font-extrabold mb-3 text-sm flex items-center gap-2">
            <span>📂</span> 그룹: {g.label}
          </div>
          <div className="flex flex-col gap-0.5">
            {(groupedSilos[g.id] || []).map((siloId) => {
              const silo = silos.find((s) => s.id === siloId);
              if (!silo) return null;

              return (
                <div
                  key={silo.id}
                  className="flex justify-between items-center py-2 px-3 hover:bg-white/[0.02] rounded-md border-t border-white/5 first:border-0 transition-colors"
                >
                  <span className="text-xs">
                    <span className="font-mono font-semibold text-text">{silo.id}</span>{' '}
                    <span className="text-muted text-[11px]">({silo.label})</span>
                  </span>

                  <span className="inline-flex items-center gap-2 font-bold text-xs">
                    {silo.over_budget ? (
                      <>
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-danger"></span>
                        </span>
                        <span className="text-danger">자원 압박</span>
                      </>
                    ) : (
                      <>
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-ok opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-ok"></span>
                        </span>
                        <span className="text-ok">정상</span>
                      </>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {deployments.length > 0 && (
        <div className="border border-white/5 rounded-xl p-4 bg-[#1e293b]/25 shadow-inner">
          <div className="text-accent font-extrabold mb-3 text-sm flex items-center gap-2">
            <span>🚀</span> 운영 중 배포: {deployments.length}건
          </div>
          <div className="flex flex-col gap-0.5">
            {deployments.map((d) => (
              <div
                key={d.id}
                className="flex justify-between items-center py-2 px-3 hover:bg-white/[0.03] rounded-md border-t border-white/5 first:border-0"
              >
                <span className="font-mono font-bold text-xs text-accent">{d.id}</span>
                <span className="text-muted text-[11px] font-medium">{d.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
