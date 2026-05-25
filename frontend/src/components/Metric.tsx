interface MetricProps {
  label: string;
  value: string;
  hint?: string;
}

export function Metric({ label, value, hint }: MetricProps) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}
