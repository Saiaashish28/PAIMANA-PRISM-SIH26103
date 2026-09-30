import { useQueryClient } from "@tanstack/react-query";
import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export interface FeedEvent {
  id: number | null;
  ts: string;
  kind: "data" | "report" | "warning" | "decision" | "system";
  severity: "info" | "notice" | "high" | "critical";
  title: string;
  detail: string | null;
  project_id: string | null;
  month: string | null;
  data: Record<string, unknown> | null;
}

interface LiveState {
  status: "connecting" | "live" | "reconnecting";
  events: FeedEvent[];
  unread: number;
  markRead: () => void;
  toasts: FeedEvent[];
  dismiss: (e: FeedEvent) => void;
  lastUpdate: Date | null;
}

const Ctx = createContext<LiveState>({
  status: "connecting", events: [], unread: 0, markRead: () => {}, toasts: [], dismiss: () => {}, lastUpdate: null,
});

/**
 * Keeps one Server-Sent Events connection to /api/events/stream for the whole app.
 * - feed events are kept (newest first) for the header bell and the Live feed page;
 * - a "state_updated" event means new data / a retrain finished: every query is refetched,
 *   so all pages update in place without a reload;
 * - high-severity events pop up as toasts.
 */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LiveState["status"]>("connecting");
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<FeedEvent[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const seen = useRef(new Set<number>());
  const initial = useRef(true);

  useEffect(() => {
    let stopped = false;
    const replayDone = window.setTimeout(() => { initial.current = false; }, 1500);

    const handle = (e: FeedEvent) => {
      if (e.kind === "system" && e.title === "state_updated") {
        setLastUpdate(new Date());
        qc.invalidateQueries();
        return;
      }
      if (e.id !== null) {
        if (seen.current.has(e.id)) return;
        seen.current.add(e.id);
      }
      setEvents((prev) => [e, ...prev].slice(0, 300));
      if (!initial.current) {
        setUnread((n) => n + 1);
        if (e.severity === "high" || e.severity === "critical" || e.kind === "data") {
          setToasts((t) => [e, ...t].slice(0, 2));
          window.setTimeout(() => setToasts((t) => t.filter((x) => x !== e)), 8000);
        }
      }
    };

    // every tab loads the recent history with an ordinary request
    fetch("/api/events?limit=20").then((r) => (r.ok ? r.json() : [])).then((items: FeedEvent[]) => {
      if (!stopped) [...items].reverse().forEach(handle);
    }).catch(() => {});

    // Browsers allow ~6 connections per host. One live stream per tab would exhaust them with a few
    // PRISM tabs open (pages then hang on the start screen), so only one tab -- the lock holder --
    // opens the stream and relays events to the other tabs over a BroadcastChannel.
    const bc = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("prism-live") : null;
    let es: EventSource | null = null;
    let leaderStatus: LiveState["status"] = "connecting";
    let release: (() => void) | null = null;
    const ctrl = new AbortController();

    const setLeaderStatus = (st: LiveState["status"]) => {
      leaderStatus = st;
      setStatus(st);
      bc?.postMessage({ type: "status", status: st });
    };
    const startStream = () => {
      es = new EventSource("/api/events/stream?replay=0");
      es.onopen = () => setLeaderStatus("live");
      es.onerror = () => setLeaderStatus("reconnecting");
      es.addEventListener("feed", (msg) => {
        const e = JSON.parse((msg as MessageEvent).data) as FeedEvent;
        handle(e);
        bc?.postMessage({ type: "feed", e });
      });
    };

    if (bc) {
      bc.onmessage = (m) => {
        const d = m.data;
        if (d.type === "feed") handle(d.e);
        else if (d.type === "status" && !es) setStatus(d.status);
        else if (d.type === "hello" && es) bc.postMessage({ type: "status", status: leaderStatus });
      };
    }
    if (bc && navigator.locks?.request) {
      navigator.locks.request("prism-live", { signal: ctrl.signal }, () => {
        if (stopped) return;
        startStream();
        return new Promise<void>((res) => { release = res; });
      }).catch(() => {});
      bc.postMessage({ type: "hello" });
    } else {
      startStream();
    }

    return () => {
      stopped = true;
      window.clearTimeout(replayDone);
      ctrl.abort();
      es?.close();
      release?.();
      bc?.close();
    };
  }, [qc]);

  const value: LiveState = {
    status, events, unread, lastUpdate, toasts,
    markRead: () => setUnread(0),
    dismiss: (e) => setToasts((t) => t.filter((x) => x !== e)),
  };
  return createElement(Ctx.Provider, { value }, children);
}

export const useLive = () => useContext(Ctx);

export const KIND_LABEL: Record<FeedEvent["kind"], string> = {
  data: "Data", report: "Report change", warning: "Risk warning", decision: "Decision", system: "System",
};

export const SEV_STYLE: Record<FeedEvent["severity"], string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  high: "bg-orange-100 text-orange-700 border-orange-200",
  notice: "bg-blue-50 text-blue-700 border-blue-200",
  info: "bg-slate-100 text-slate-600 border-slate-200",
};

export function timeAgo(ts: string) {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
