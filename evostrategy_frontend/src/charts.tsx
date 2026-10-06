import { useEffect, useMemo, useRef, useState } from "react";
import { money, monthLabel } from "./api";

export type Series = { name: string; values: Array<number | null>; color: string; dashed?: boolean };
export type Band = { lower: Array<number | null>; upper: Array<number | null>; color: string; label: string };

const H = 260;
const PAD = { top: 16, right: 16, bottom: 30, left: 64 };

function niceTicks(min: number, max: number, count = 4) {
  const span = max - min || Math.abs(max) || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (span / count) / step;
  const nice = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * step;
  const ticks: number[] = [];
  const start = Math.floor(min / nice) * nice;
  const end = Math.ceil(max / nice) * nice;
  for (let v = start; v <= end + nice * 0.001; v += nice) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

export function LineChart({ labels, series, band, height = H, divider }: {
  labels: string[];
  series: Series[];
  band?: Band;
  height?: number;
  divider?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const [W, setWidth] = useState(760);
  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const { ticks, x, y } = useMemo(() => {
    const values = [
      ...series.flatMap((s) => s.values),
      ...(band ? [...band.lower, ...band.upper] : []),
    ].filter((v): v is number => v !== null && Number.isFinite(v));
    const lo = Math.min(0, ...values);
    const hi = Math.max(...values, 1);
    const t = niceTicks(lo, hi);
    const min = t[0];
    const max = t[t.length - 1];
    const innerW = W - PAD.left - PAD.right;
    const innerH = height - PAD.top - PAD.bottom;
    return {
      ticks: t,
      x: (i: number) => PAD.left + (labels.length <= 1 ? innerW / 2 : (i / (labels.length - 1)) * innerW),
      y: (v: number) => PAD.top + innerH - ((v - min) / (max - min || 1)) * innerH,
    };
  }, [labels, series, band, height, W]);

  const path = (values: Array<number | null>) =>
    values.reduce((d, v, i) => (v === null ? d : `${d}${d && values[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`), "");

  const bandPath = band
    ? (() => {
        const idx = band.upper.map((v, i) => (v === null ? -1 : i)).filter((i) => i >= 0);
        if (!idx.length) return "";
        const top = idx.map((i) => `${x(i).toFixed(1)},${y(band.upper[i] as number).toFixed(1)}`).join("L");
        const bottom = [...idx].reverse().map((i) => `${x(i).toFixed(1)},${y(band.lower[i] as number).toFixed(1)}`).join("L");
        return `M${top}L${bottom}Z`;
      })()
    : "";

  const step = Math.max(1, Math.ceil(labels.length / Math.max(2, Math.floor(W / 90))));

  return (
    <div className="chart" ref={container}>
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={series.map((s) => s.name).join(", ")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * W;
          const innerW = W - PAD.left - PAD.right;
          const i = Math.round(((px - PAD.left) / innerW) * (labels.length - 1));
          setHover(i >= 0 && i < labels.length ? i : null);
        }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "chart-zero" : "chart-grid"} />
            <text x={PAD.left - 8} y={y(t) + 4} className="chart-tick" textAnchor="end">{money(t, true)}</text>
          </g>
        ))}
        {labels.map((label, i) => (i === labels.length - 1 ? (labels.length - 1) % step >= step / 2 || step === 1 : i % step === 0) && (
          <text key={label} x={x(i)} y={height - 8} className="chart-tick" textAnchor="middle">{monthLabel(label)}</text>
        ))}
        {divider !== undefined && <line x1={x(divider)} x2={x(divider)} y1={PAD.top} y2={height - PAD.bottom} className="chart-divider" />}
        {band && <path d={bandPath} fill={band.color} opacity={0.14} />}
        {series.map((s) => (
          <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "5 4" : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={height - PAD.bottom} className="chart-hover" />
            {series.map((s) => s.values[hover] !== null && s.values[hover] !== undefined && (
              <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] as number)} r={3.5} fill={s.color} stroke="#fff" strokeWidth={1.5} />
            ))}
          </g>
        )}
      </svg>
      <div className="chart-footer">
        <div className="chart-legend">
          {series.map((s) => <span key={s.name}><i style={{ background: s.color }} className={s.dashed ? "dashed" : ""} />{s.name}</span>)}
          {band && <span><i style={{ background: band.color, opacity: 0.3 }} />{band.label}</span>}
        </div>
        {hover !== null && (
          <div className="chart-readout">
            <strong>{monthLabel(labels[hover])}</strong>
            {series.map((s) => s.values[hover] !== null && s.values[hover] !== undefined && <span key={s.name}>{s.name}: {money(s.values[hover] as number)}</span>)}
            {band && band.lower[hover] !== null && band.lower[hover] !== undefined && <span>Range: {money(band.lower[hover] as number, true)}–{money(band.upper[hover] as number, true)}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

export function BarList({ rows, color = "#4f46e5" }: { rows: Array<{ label: string; amount: number; count?: number }>; color?: string }) {
  const max = Math.max(...rows.map((r) => r.amount), 1);
  if (!rows.length) return <p className="muted">No verified records yet.</p>;
  return (
    <div className="bar-list">
      {rows.map((row) => (
        <div className="bar-row" key={row.label}>
          <div className="bar-copy"><span>{row.label}</span><strong>{money(row.amount, true)}</strong></div>
          <div className="bar-track"><span style={{ width: `${(row.amount / max) * 100}%`, background: color }} /></div>
        </div>
      ))}
    </div>
  );
}

export function Meter({ value }: { value: number | null }) {
  const pct = value === null ? 0 : Math.min(value, 1.25) / 1.25;
  const tone = value === null ? "" : value > 1 ? "over" : value > 0.9 ? "near" : "ok";
  return (
    <div className={`meter ${tone}`}>
      <span style={{ width: `${pct * 100}%` }} />
      <i style={{ left: `${(1 / 1.25) * 100}%` }} />
    </div>
  );
}
