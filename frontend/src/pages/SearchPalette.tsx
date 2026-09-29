import { useQuery } from "@tanstack/react-query";
import { Boxes, Search, Waypoints } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { truncate } from "../lib/format";

interface Result {
  group: string;
  label: string;
  detail: string;
  to: string;
}

const PAGES: Result[] = [
  { group: "Page", label: "Overview", detail: "Operational overview", to: "/" },
  { group: "Page", label: "Demo Cases", detail: "Saved trace bundles", to: "/cases" },
  { group: "Page", label: "Attribution & VASP", detail: "Verified vs candidate", to: "/attribution" },
  { group: "Page", label: "Cross-Chain", detail: "Circle CCTP V2", to: "/cross-chain" },
  { group: "Page", label: "Decision Support", detail: "System-1 routing", to: "/decision-support" },
  { group: "Page", label: "Evidence", detail: "Manifests and replay", to: "/evidence" },
  { group: "Page", label: "System Status", detail: "Capability matrix", to: "/system" },
  { group: "Page", label: "Integrations", detail: "Providers and connectors", to: "/integrations" },
];

export function SearchPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });
  const candidates = useQuery({ queryKey: ["demo", "candidates"], queryFn: api.demo.candidates });
  const cctp = useQuery({ queryKey: ["demo", "cctp"], queryFn: api.demo.cctp });

  const results = useMemo<Result[]>(() => {
    const list: Result[] = [...PAGES];
    for (const preset of presets.data?.presets ?? []) {
      list.push({
        group: "Case",
        label: preset.id,
        detail: `${preset.data_mode} · ${truncate(preset.address, 8, 6)}`,
        to: `/cases/${encodeURIComponent(preset.id)}`,
      });
      list.push({
        group: "Wallet",
        label: preset.address,
        detail: `seed wallet · ${preset.network ?? "—"}`,
        to: `/cases/${encodeURIComponent(preset.id)}`,
      });
    }
    for (const report of candidates.data?.reports ?? []) {
      for (const candidate of report.report.candidates ?? []) {
        const address = String(candidate.address);
        list.push({ group: "Candidate", label: address, detail: `candidate · ${report.run_id}`, to: "/attribution" });
      }
    }
    for (const bundle of cctp.data?.bundles ?? []) {
      list.push({ group: "Cross-chain", label: bundle.run_id, detail: bundle.route, to: "/cross-chain" });
    }
    const needle = query.trim().toLowerCase();
    if (!needle) return list.slice(0, 24);
    return list.filter((item) => `${item.label} ${item.detail} ${item.group}`.toLowerCase().includes(needle)).slice(0, 40);
  }, [presets.data, candidates.data, cctp.data, query]);

  // The palette is mounted only while open, so initial focus and a fresh query
  // are the mount defaults rather than a reactive reset.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((value) => Math.min(results.length - 1, value + 1));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((value) => Math.max(0, value - 1));
      }
      if (event.key === "Enter" && results[active]) {
        navigate(results[active].to);
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [results, active, navigate, onClose]);

  let lastGroup = "";
  return (
    <div className="overlay" onClick={onClose}>
      <div className="palette" onClick={(event) => event.stopPropagation()} role="dialog" aria-label="Search">
        <div className="row" style={{ padding: "0 var(--space-2)" }}>
          <Search size={15} style={{ color: "var(--text-muted)", marginLeft: 8 }} aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            placeholder="Search cases, wallets, candidates, cross-chain…"
            aria-label="Search"
          />
        </div>
        <div className="palette-results">
          {results.length === 0 ? (
            <div className="muted" style={{ padding: "var(--space-3)" }}>
              No match. This read-only surface does not trace live, so it cannot look up an address
              that has no saved evidence.
            </div>
          ) : (
            results.map((item, index) => {
              const showGroup = item.group !== lastGroup;
              lastGroup = item.group;
              return (
                <div key={`${item.group}-${item.label}`}>
                  {showGroup ? <div className="palette-group">{item.group}</div> : null}
                  <button
                    type="button"
                    className={`palette-item${index === active ? " active" : ""}`}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => {
                      navigate(item.to);
                      onClose();
                    }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>
                      {item.group === "Cross-chain" ? <Waypoints size={14} /> : <Boxes size={14} />}
                    </span>
                    <span className="grow">
                      <div className="mono" style={{ color: "var(--text-primary)" }}>
                        {truncate(item.label, 34, 8)}
                      </div>
                      <div className="muted" style={{ fontSize: 11 }}>
                        {item.detail}
                      </div>
                    </span>
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
