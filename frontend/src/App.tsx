import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { LeftNav, TopBar } from "./components/AppShell";
import { api, type DataMode } from "./lib/api";
import { SearchPalette } from "./pages/SearchPalette";
import OverviewPage from "./pages/OverviewPage";
import DemoCasesPage from "./pages/DemoCasesPage";
import CaseWorkspacePage from "./pages/CaseWorkspacePage";
import AttributionPage from "./pages/AttributionPage";
import CrossChainPage from "./pages/CrossChainPage";
import EvidencePage from "./pages/EvidencePage";
import DecisionSupportPage from "./pages/DecisionSupportPage";
import SystemStatusPage from "./pages/SystemStatusPage";
import IntegrationsPage from "./pages/IntegrationsPage";
import ReportsPage from "./pages/ReportsPage";
import CaseDbPage from "./pages/CaseDbPage";
import MonitoringPage from "./pages/MonitoringPage";
import AlertsPage from "./pages/AlertsPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, staleTime: 15_000, retry: 1 },
  },
});

function Shell() {
  const [searchOpen, setSearchOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const meta = useQuery({ queryKey: ["meta", "envelope"], queryFn: api.metaEnvelope });
  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });
  const cctp = useQuery({ queryKey: ["demo", "cctp"], queryFn: api.demo.cctp });

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const counts: Record<string, number> = {
    "/cases": presets.data?.count ?? 0,
    "/cross-chain": cctp.data?.count ?? 0,
  };

  return (
    <div className="shell">
      <TopBar
        mode={(meta.data?.meta.data_mode as DataMode) ?? "UNKNOWN"}
        engineVersion={meta.data?.meta.engine_version}
        cutoff={meta.data?.meta.analysis_cutoff}
        onOpenSearch={() => setSearchOpen(true)}
        onToggleNav={() => setNavOpen((value) => !value)}
      />
      <LeftNav open={navOpen} onNavigate={() => setNavOpen(false)} counts={counts} />
      <main className="main">
        <div className="workspace">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/cases" element={<DemoCasesPage />} />
            <Route path="/cases/:presetId" element={<CaseWorkspacePage />} />
            <Route path="/attribution" element={<AttributionPage />} />
            <Route path="/cross-chain" element={<CrossChainPage />} />
            <Route path="/evidence" element={<EvidencePage />} />
            <Route path="/decision-support" element={<DecisionSupportPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/system" element={<SystemStatusPage />} />
            <Route path="/integrations" element={<IntegrationsPage />} />
            <Route path="/case-db" element={<CaseDbPage />} />
            <Route path="/monitoring" element={<MonitoringPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="*" element={<OverviewPage />} />
          </Routes>
        </div>
      </main>
      {searchOpen ? <SearchPalette onClose={() => setSearchOpen(false)} /> : null}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/investigator">
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
