import { Check, Copy, Info, type LucideIcon } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { truncate } from "../lib/format";
import type { StatusDescriptor, Tone } from "../lib/status";

export function Badge({
  tone = "neutral",
  children,
  icon: Icon,
  title,
}: {
  tone?: Tone | "neutral";
  children: ReactNode;
  icon?: LucideIcon;
  title?: string;
}) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {Icon ? <Icon size={11} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function StatusBadge({ descriptor, icon }: { descriptor: StatusDescriptor; icon?: LucideIcon }) {
  return (
    <Badge tone={descriptor.tone} icon={icon} title={descriptor.meaning}>
      {descriptor.label}
    </Badge>
  );
}

/** Full value in the DOM for copying; a truncated value on screen. */
export function CopyableValue({
  value,
  head = 6,
  tail = 4,
  label = "value",
  mono = true,
}: {
  value: string | null | undefined;
  head?: number;
  tail?: number;
  label?: string;
  mono?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const text = value ?? "";
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }, [text]);

  if (!text) return <span className="muted">—</span>;
  return (
    <span className="addr" title={text}>
      <code className={mono ? "mono" : undefined}>{truncate(text, head, tail)}</code>
      <button
        type="button"
        className="copy-btn"
        onClick={copy}
        aria-label={`Copy ${label}`}
        title={`Copy ${label}`}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
    </span>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="mono">{children}</span>;
}

export function ChainMark({ chain }: { chain: string | null | undefined }) {
  const key = (chain || "").toLowerCase();
  const text = key === "tron" ? "TRON" : key === "ethereum" ? "ETH" : key === "bsc" ? "BSC" : key === "base" ? "BASE" : (chain || "—").toUpperCase();
  return <span className="chain-mark" title={chain ?? undefined}>{text}</span>;
}

export function Panel({
  title,
  actions,
  children,
  bodyClass,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  bodyClass?: string;
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions ? <div className="panel-actions">{actions}</div> : null}
        </header>
      )}
      <div className={`panel-body${bodyClass ? ` ${bodyClass}` : ""}`}>{children}</div>
    </section>
  );
}

export function Callout({
  tone = "neutral",
  icon: Icon = Info,
  title,
  children,
}: {
  tone?: Tone | "neutral";
  icon?: LucideIcon;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`callout ${tone === "neutral" ? "" : tone}`}>
      <span className="callout-icon">
        <Icon size={15} aria-hidden="true" />
      </span>
      <div>
        {title ? <strong>{title} </strong> : null}
        {children}
      </div>
    </div>
  );
}

export function Metric({
  value,
  label,
  hint,
}: {
  value: ReactNode;
  label: string;
  hint?: string;
}) {
  return (
    <div className="metric">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      {hint ? <div className="metric-hint">{hint}</div> : null}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={22} aria-hidden="true" />
      </span>
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="empty">
      <strong style={{ color: "var(--danger)" }}>Could not load this view</strong>
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="btn sm" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Loading({ rows = 5 }: { rows?: number }) {
  return (
    <div className="stack" style={{ padding: "var(--space-4)" }}>
      {Array.from({ length: rows }).map((_, index) => (
        <span className="skeleton" key={index} />
      ))}
    </div>
  );
}
