import * as echarts from "echarts";
import { useEffect, useRef } from "react";

type Props = {
  /** Any ECharts option object (kept loose so pages can build options inline). */
  option: object;
  height?: number | string;
  className?: string;
  onClick?: (params: echarts.ECElementEvent) => void;
};

/** Thin React wrapper around Apache ECharts with resize handling. */
export function EChart({ option, height = 280, className, onClick }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ textStyle: { fontFamily: "Inter, system-ui, sans-serif" }, ...option } as echarts.EChartsOption, true);
  }, [option]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onClick) return;
    c.on("click", onClick);
    return () => {
      c.off("click", onClick);
    };
  }, [onClick]);

  return <div ref={ref} className={className} style={{ height, width: "100%" }} />;
}
