import React from 'react';

interface HeatmapPayload {
  row_labels: string[];
  col_labels: string[];
  matrix: (number | null)[][];
}

interface InteractiveHeatmapProps {
  payload: HeatmapPayload | null;
}

export const InteractiveHeatmap: React.FC<InteractiveHeatmapProps> = ({ payload }) => {
  if (!payload || !payload.row_labels || !payload.row_labels.length) {
    return (
      <div className="flex items-center justify-center h-48 border border-dashed border-white/5 rounded-xl bg-white/[0.01] text-muted text-xs">
        메트릭 데이터 없음
      </div>
    );
  }

  // Min-Max 정규화를 위한 범위 연산
  let maxVal = -Infinity;
  let minVal = Infinity;
  let hasValidData = false;

  payload.matrix.forEach((row) => {
    row.forEach((val) => {
      if (val !== null && val !== undefined) {
        hasValidData = true;
        if (val > maxVal) maxVal = val;
        if (val < minVal) minVal = val;
      }
    });
  });

  const range = maxVal - minVal;

  return (
    <div className="flex-1 overflow-auto rounded-xl border border-white/5 shadow-inner">
      <table className="w-full border-collapse text-xs font-mono">
        <thead>
          <tr className="border-b border-white/5">
            <th className="bg-[#1e293b]/85 px-4 py-2.5 text-text font-bold font-sans text-[10px] uppercase tracking-wider"></th>
            {payload.col_labels.map((c) => (
              <th
                key={c}
                className="bg-[#1e293b]/85 px-4 py-2.5 text-text font-bold font-sans text-[10px] uppercase tracking-wider text-center border-l border-white/5"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {payload.row_labels.map((row, i) => (
            <tr key={row} className="border-b border-white/5 hover:bg-white/[0.01]">
              <th className="px-4 py-3 bg-[#1e293b]/35 border-r border-white/5 font-sans font-bold text-center text-muted">
                {row}
              </th>
              {payload.matrix[i].map((val, j) => {
                if (val === null || val === undefined) {
                  return (
                    <td key={j} className="px-4 py-3 text-center border-l border-white/5 text-muted/30">
                      —
                    </td>
                  );
                }

                let ratio = 0.5;
                if (hasValidData && range > 0) {
                  ratio = (val - minVal) / range;
                } else if (hasValidData) {
                  ratio = val > 0 ? 0.8 : 0.2;
                }

                // HSL Cyan 색상 매핑
                const bgStyle = {
                  background: `rgba(56, 189, 248, ${0.08 + ratio * 0.45})`,
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                };

                return (
                  <td
                    key={j}
                    style={bgStyle}
                    className={`px-4 py-3 text-center border-l border-white/5 font-semibold transition-all duration-300 hover:scale-[1.03] hover:shadow-[inset_0_0_12px_rgba(255,255,255,0.25)] hover:brightness-125 ${
                      ratio > 0.75 ? 'font-bold text-white' : 'text-[#e2e8f0]'
                    }`}
                  >
                    {val.toFixed(3)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
