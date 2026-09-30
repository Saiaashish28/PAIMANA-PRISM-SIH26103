import { Loader2 } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Logo } from "./components/Logo";
import { LiveProvider } from "./lib/live";
import { useApi } from "./lib/api";
import type { Health } from "./lib/types";

const AssistantPage = lazy(() => import("./pages/Assistant"));
const BenchmarkPage = lazy(() => import("./pages/Benchmark"));
const DataPage = lazy(() => import("./pages/Data"));
const LiveFeedPage = lazy(() => import("./pages/LiveFeed"));
const TrendsPage = lazy(() => import("./pages/Trends"));
const BenchmarkingPage = lazy(() => import("./pages/Benchmarking"));
const CostDriversPage = lazy(() => import("./pages/CostDrivers"));
const IntelligencePage = lazy(() => import("./pages/Intelligence"));
const InterventionsPage = lazy(() => import("./pages/Interventions"));
const MapPage = lazy(() => import("./pages/MapView"));
const OverviewPage = lazy(() => import("./pages/Overview"));
const ProjectPage = lazy(() => import("./pages/Project"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const TrustPage = lazy(() => import("./pages/Trust"));
const WarningsPage = lazy(() => import("./pages/Warnings"));

export default function App() {
  const health = useApi<Health>("/health", { refetchInterval: 4000 });
  const status = health.data?.status;
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (health.data) {
      setSlow(false);
      return;
    }
    const t = window.setTimeout(() => setSlow(true), 8000);
    return () => window.clearTimeout(t);
  }, [health.data]);
  if (status !== "ready") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 bg-brand-900 p-6 text-center text-slate-200">
        <Logo className="h-16 w-16" />
        <h1 className="text-2xl font-semibold text-white">PAIMANA PRISM</h1>
        {health.isError ? (
          <p className="max-w-md text-sm text-red-300">
            Cannot reach the PRISM API. Start it with <code className="rounded bg-white/10 px-1">uvicorn prism.api.main:app</code>.
          </p>
        ) : status === "error" ? (
          <p className="max-w-md text-sm text-red-300">Pipeline failed: {health.data?.detail}</p>
        ) : slow && !health.data ? (
          <div className="max-w-lg space-y-3 text-sm">
            <p className="flex items-center justify-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> The browser is still waiting for the PRISM API ({window.location.origin}/api/health)…</p>
            <ul className="list-disc space-y-1 pl-5 text-left text-slate-300">
              <li>Close other PRISM tabs: browsers allow only a few connections to one site.</li>
              <li>Check the <b>PRISM API</b> window is running and shows no error.</li>
              <li>Hard-reload this page with <b>Ctrl+Shift+R</b>.</li>
            </ul>
            <button className="btn" onClick={() => window.location.reload()}>Reload</button>
          </div>
        ) : (
          <p className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Validating data, training risk models and computing explanations… (first start takes ~2 minutes)
          </p>
        )}
      </div>
    );
  }
  return (
    <Suspense fallback={
      <div className="flex h-full items-center justify-center text-sm text-slate-500"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading…</div>
    }>
      <Routes>
        <Route element={<LiveProvider><Layout /></LiveProvider>}>
          <Route index element={<OverviewPage />} />
          <Route path="warnings" element={<WarningsPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<ProjectPage />} />
          <Route path="map" element={<MapPage />} />
          <Route path="intelligence" element={<IntelligencePage />} />
          <Route path="interventions" element={<InterventionsPage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="models" element={<BenchmarkPage />} />
          <Route path="trust" element={<TrustPage />} />
          <Route path="data" element={<DataPage />} />
          <Route path="live" element={<LiveFeedPage />} />
          <Route path="trends" element={<TrendsPage />} />
          <Route path="benchmarking" element={<BenchmarkingPage />} />
          <Route path="cost-drivers" element={<CostDriversPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
