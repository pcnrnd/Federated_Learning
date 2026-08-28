import React from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';

interface TimeseriesPayload {
  series: {
    [siloId: string]: { timestamp: string; value: number }[];
  };
}

interface HistogramPayload {
  bin_edges: number[];
  bin_counts: number[];
}

interface BarPayload {
  items: { silo_id: string; value: number }[];
}

interface ChartCardProps {
  type: 'timeseries' | 'histogram' | 'bar';
  timeseriesData?: TimeseriesPayload | null;
  histogramData?: HistogramPayload | null;
  barData?: BarPayload | null;
}

export const MetricChartCard: React.FC<ChartCardProps> = ({
  type,
  timeseriesData,
  histogramData,
  barData,
}) => {
  // 1. 시계열(Timeseries) 차트 렌더러
  if (type === 'timeseries') {
    const series = timeseriesData?.series || {};
    const siloIds = Object.keys(series);
    if (siloIds.length === 0) {
      return (
        <div className="flex items-center justify-center h-48 border border-dashed border-white/5 rounded-xl bg-white/[0.01] text-muted text-xs">
          데이터 없음
        </div>
      );
    }

    // 시계열 데이터 가공 (Recharts 포맷용)
    // 모든 타임스탬프를 수집하여 유니크 리스트 추출
    const timestampsSet = new Set<string>();
    siloIds.forEach((silo) => {
      series[silo].forEach((p) => timestampsSet.add(p.timestamp));
    });
    const sortedTimestamps = Array.from(timestampsSet).sort();

    const chartData = sortedTimestamps.map((ts) => {
      const row: { [key: string]: string | number } = { timestamp: ts };
      siloIds.forEach((silo) => {
        const point = series[silo].find((p) => p.timestamp === ts);
        if (point) row[silo] = point.value;
      });
      return row;
    });

    const colors = ['#38bdf8', '#34d399', '#fb923c', '#f87171', '#a78bfa', '#f472b6'];

    return (
      <div className="w-full h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.03)" />
            <XAxis
              dataKey="timestamp"
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }}
            />
            <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }} />
            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                borderColor: 'rgba(255, 255, 255, 0.08)',
                borderRadius: '8px',
                color: '#f8fafc',
                fontSize: '11px',
                fontFamily: 'Inter',
              }}
            />
            <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'Inter', paddingTop: '10px' }} />
            {siloIds.map((silo, idx) => (
              <Line
                key={silo}
                type="monotone"
                dataKey={silo}
                stroke={colors[idx % colors.length]}
                strokeWidth={2}
                dot={{ r: 2 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // 2. 히스토그램(Histogram) 차트 렌더러
  if (type === 'histogram') {
    if (!histogramData || !histogramData.bin_edges) {
      return (
        <div className="flex items-center justify-center h-48 border border-dashed border-white/5 rounded-xl bg-white/[0.01] text-muted text-xs">
          feature 입력 또는 베이스라인 등록 필요
        </div>
      );
    }

    const labels = histogramData.bin_edges.slice(0, -1).map((e, idx) =>
      `${e.toFixed(1)}~${histogramData.bin_edges[idx + 1].toFixed(1)}`
    );

    const chartData = labels.map((label, idx) => ({
      name: label,
      count: histogramData.bin_counts[idx],
    }));

    return (
      <div className="w-full h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.03)" />
            <XAxis
              dataKey="name"
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }}
            />
            <YAxis
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                borderColor: 'rgba(255, 255, 255, 0.08)',
                borderRadius: '8px',
                color: '#f8fafc',
                fontSize: '11px',
              }}
            />
            <Bar
              dataKey="count"
              fill="#38bdf8"
              radius={[10, 10, 0, 0]} // Highly rounded waterdrop shape
              maxBarSize={45}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // 3. 사일로 리소스(Silo Bar) 차트 렌더러
  if (type === 'bar') {
    const items = barData?.items || [];
    if (items.length === 0) {
      return (
        <div className="flex items-center justify-center h-48 border border-dashed border-white/5 rounded-xl bg-white/[0.01] text-muted text-xs">
          리소스 샘플 없음
        </div>
      );
    }

    const chartData = items.map((it) => ({
      name: it.silo_id,
      value: it.value,
      // 임계값 초과 여부에 따른 색상 분기
      color: it.value > 80 ? '#f87171' : '#34d399',
    }));

    return (
      <div className="w-full h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.03)" />
            <XAxis
              dataKey="name"
              stroke="#94a3b8"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }}
            />
            <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'Inter' }} />
            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                borderColor: 'rgba(255, 255, 255, 0.08)',
                borderRadius: '8px',
                color: '#f8fafc',
                fontSize: '11px',
              }}
            />
            {/* Custom rounded bar rendering */}
            <Bar
              dataKey="value"
              radius={[10, 10, 0, 0]}
              maxBarSize={40}
            >
              {chartData.map((entry, index) => (
                <Bar key={`cell-${index}`} fill={entry.color} dataKey="value" />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return null;
};
