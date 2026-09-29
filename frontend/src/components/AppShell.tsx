import {
  Activity,
  Banknote,
  Bell,
  Boxes,
  FileText,
  Gavel,
  LayoutDashboard,
  Menu,
  Plug,
  Radar,
  ScanLine,
  Search,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import type { DataMode } from "../lib/api";
import { dataMode } from "../lib/status";
import { Badge, StatusBadge } from "./ui";

export interface NavEntry {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  gated?: boolean;
  count?: number;
}

const GROUPS: { heading: string; items: NavEntry[] }[] = [
  {
    heading: "Operate",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard },
      { to: "/cases", label: "Demo Cases", icon: Boxes },
      { to: "/case-db", label: "Case Intake", icon: ScanLine, gated: true },
      { to: "/monitoring", label: "Monitoring", icon: Radar, gated: true },
      { to: "/alerts", label: "Alerts", icon: Bell, gated: true },
    ],
  },
  {
    heading: "Investigate",
    items: [
      { to: "/attribution", label: "Attribution & VASP", icon: ShieldCheck },
      { to: "/cross-chain", label: "Cross-Chain", icon: Waypoints },
      { to: "/decision-support", label: "Decision Support", icon: Gavel },
      { to: "/evidence", label: "Evidence", icon: FileText },
      { to: "/reports", label: "Reports", icon: Banknote },
    ],
  },
  {
    heading: "System",
    items: [
      { to: "/system", label: "System Status", icon: Activity },
      { to: "/integrations", label: "Integrations", icon: Plug },
    ],
  },
];

export function TopBar({
  mode,
  engineVersion,
  cutoff,
  onOpenSearch,
  onToggleNav,
}: {
  mode: DataMode | "UNKNOWN";
  engineVersion?: string;
  cutoff?: string;
  onOpenSearch: () => void;
  onToggleNav: () => void;
}) {
  const descriptor = dataMode(mode);
  return (
    <header className="topbar">
      <button
        type="button"
        className="btn icon"
        onClick={onToggleNav}
        aria-label="Toggle navigation"
        style={{ display: "none" }}
        id="nav-toggle"
      >
        <Menu size={16} />
      </button>
      <div className="brand">
        <span className="brand-mark">
          <ScanLine size={18} aria-hidden="true" />
        </span>
        <span>
          Crypto Attribution Triage
          <small>Investigator Console · Read-only</small>
        </span>
      </div>
      <button type="button" className="search-trigger" onClick={onOpenSearch} aria-label="Open search">
        <Search size={14} aria-hidden="true" />
        <span>Search cases, wallets, transactions…</span>
        <kbd>Ctrl K</kbd>
      </button>
      <span className="topbar-spacer" />
      <div className="topbar-meta">
        <StatusBadge descriptor={descriptor} icon={ShieldCheck} />
        <span className="kv">
          engine <strong>{engineVersion ?? "—"}</strong>
        </span>
        <span className="kv" title="Analysis cutoff">
          cutoff <strong>{cutoff ? cutoff.slice(0, 10) : "—"}</strong>
        </span>
      </div>
    </header>
  );
}

export function LeftNav({
  open,
  onNavigate,
  counts,
}: {
  open?: boolean;
  onNavigate?: () => void;
  counts?: Record<string, number>;
}) {
  return (
    <nav className={`nav${open ? " open" : ""}`} aria-label="Primary">
      {GROUPS.map((group) => (
        <div key={group.heading}>
          <div className="nav-group">{group.heading}</div>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
              onClick={onNavigate}
              title={item.gated ? "Requires a seeded local case database and a signed-in session" : item.label}
            >
              <span className="nav-icon">
                <item.icon size={15} aria-hidden="true" />
              </span>
              <span>{item.label}</span>
              {item.gated ? (
                <Badge tone="neutral" title="Requires a seeded local case database">
                  gated
                </Badge>
              ) : null}
              {counts && counts[item.to] !== undefined ? (
                <span className="nav-count">{counts[item.to]}</span>
              ) : null}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="nav-group">Prototype</div>
      <div style={{ padding: "0 10px 12px" }} className="muted">
        <p style={{ margin: 0, fontSize: 11 }}>
          Read-only. Saved public/synthetic evidence only. No live tracing on this surface, no
          person identified, no freeze executed.
        </p>
      </div>
    </nav>
  );
}
