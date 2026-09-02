type Props = {
  readings: number[];
  bandMin: number | null;
  bandMax: number;
  intervalMin: number;
};

export function TemperatureChart({ readings, bandMin, bandMax, intervalMin }: Props) {
  if (!readings.length) {
    return <p className="text-sm text-slate-500">No readings</p>;
  }

  const width = 640;
  const height = 220;
  const pad = { top: 16, right: 12, bottom: 28, left: 44 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const yMin = Math.min(bandMin ?? Math.min(...readings), ...readings) - 2;
  const yMax = Math.max(bandMax, ...readings) + 2;
  const xScale = (i: number) => pad.left + (i / Math.max(readings.length - 1, 1)) * plotW;
  const yScale = (v: number) => pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  const points = readings.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ");
  const bandTop = yScale(bandMax);
  const bandBottom = yScale(bandMin ?? yMin);
  const hours = Math.round((readings.length * intervalMin) / 60);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-3xl" role="img" aria-label="Temperature chart">
      <rect
        x={pad.left}
        y={Math.min(bandTop, bandBottom)}
        width={plotW}
        height={Math.abs(bandBottom - bandTop)}
        fill="#0d4f4f"
        fillOpacity={0.08}
      />
      <line x1={pad.left} x2={pad.left + plotW} y1={bandTop} y2={bandTop} stroke="#C4A35A" strokeDasharray="4 4" />
      {bandMin != null && (
        <line x1={pad.left} x2={pad.left + plotW} y1={bandBottom} y2={bandBottom} stroke="#C4A35A" strokeDasharray="4 4" />
      )}
      <polyline fill="none" stroke="#0B3D5C" strokeWidth={2} points={points} />
      <text x={pad.left} y={height - 8} className="fill-slate-500 text-[10px]">
        0h
      </text>
      <text x={pad.left + plotW} y={height - 8} textAnchor="end" className="fill-slate-500 text-[10px]">
        {hours}h
      </text>
      <text x={8} y={pad.top + 4} className="fill-slate-500 text-[10px]">
        {yMax.toFixed(0)}°C
      </text>
      <text x={8} y={pad.top + plotH} className="fill-slate-500 text-[10px]">
        {yMin.toFixed(0)}°C
      </text>
      <text x={pad.left + plotW - 4} y={bandTop - 4} textAnchor="end" className="fill-gcc-gold text-[10px]">
        max {bandMax}°C
      </text>
    </svg>
  );
}
