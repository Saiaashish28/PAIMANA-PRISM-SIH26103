/** PAIMANA PRISM mark: project data enters a prism and splits into Green / Amber / Red risk bands. */
export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return <img src="/favicon.svg" className={className} alt="PAIMANA PRISM" />;
}

export function Wordmark({ dark = true }: { dark?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <Logo />
      <div className="leading-tight">
        <div className={`text-[15px] font-extrabold tracking-wide ${dark ? "text-white" : "text-slate-900"}`}>
          PAIMANA <span className="bg-gradient-to-r from-green-400 via-amber-400 to-red-400 bg-clip-text text-transparent">PRISM</span>
        </div>
        <div className={`text-[11px] ${dark ? "text-slate-400" : "text-slate-500"}`}>Predictive Risk Intelligence</div>
      </div>
    </div>
  );
}
