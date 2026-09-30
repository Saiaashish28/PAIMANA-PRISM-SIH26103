import { Component, type ReactNode } from "react";

/** Shows what went wrong (and a reload button) instead of a blank page when rendering crashes. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-slate-50 p-6 text-center">
        <h1 className="text-xl font-semibold text-slate-900">PRISM hit an unexpected error</h1>
        <pre className="max-w-2xl overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-left text-xs text-red-700 shadow">
          {this.state.error.message}
        </pre>
        <p className="text-sm text-slate-600">Reloading usually fixes it. If it keeps happening, press F12 and share the Console output.</p>
        <button className="btn" onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}
