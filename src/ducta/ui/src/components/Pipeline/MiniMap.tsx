import { useRef, useCallback, useEffect } from "react";
import { useBuilderStore } from "../../store/builderStore";

interface MiniMapNode {
  id: string;
  x: number;
  y: number;
  type?: string;
}

interface MiniMapProps {
  nodes: MiniMapNode[];
  containerWidth: number;
  containerHeight: number;
}

const NODE_COLORS: Record<string, string> = {
  source: "var(--blue)",
  transform: "var(--purple)",
  ml: "var(--teal)",
  sink: "var(--green)",
  custom: "var(--amber)",
};

const MINIMAP_WIDTH = 200;
const MINIMAP_HEIGHT = 140;
const PADDING = 16;

export function MiniMap({ nodes, containerWidth, containerHeight }: MiniMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const isDragging = useRef(false);
  const viewportScale = useBuilderStore((s) => s.viewportScale);
  const viewportX = useBuilderStore((s) => s.viewportX);
  const viewportY = useBuilderStore((s) => s.viewportY);
  const setViewport = useBuilderStore((s) => s.setViewport);

  const contentWidth = containerWidth / (viewportScale || 1);
  const contentHeight = containerHeight / (viewportScale || 1);

  const scaleX = (MINIMAP_WIDTH - PADDING * 2) / Math.max(contentWidth, 1);
  const scaleY = (MINIMAP_HEIGHT - PADDING * 2) / Math.max(contentHeight, 1);
  const mmScale = Math.min(scaleX, scaleY, 1);

  const viewX = (-viewportX / Math.max(contentWidth, 1)) * (MINIMAP_WIDTH - PADDING * 2) * mmScale + PADDING;
  const viewY = (-viewportY / Math.max(contentHeight, 1)) * (MINIMAP_HEIGHT - PADDING * 2) * mmScale + PADDING;
  const viewW = (containerWidth / Math.max(contentWidth, 1)) * (MINIMAP_WIDTH - PADDING * 2) * mmScale;
  const viewH = (containerHeight / Math.max(contentHeight, 1)) * (MINIMAP_HEIGHT - PADDING * 2) * mmScale;

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const nx = (e.clientX - rect.left - PADDING) / mmScale / (MINIMAP_WIDTH - PADDING * 2) * contentWidth + viewportX;
    const ny = (e.clientY - rect.top - PADDING) / mmScale / (MINIMAP_HEIGHT - PADDING * 2) * contentHeight + viewportY;
    setViewport(viewportScale, -(nx - containerWidth / 2), -(ny - containerHeight / 2));
  }, [mmScale, contentWidth, contentHeight, viewportScale, viewportX, viewportY, containerWidth, containerHeight, setViewport]);

  useEffect(() => {
    if (!isDragging.current) return;
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      const nx = (e.clientX - rect.left - PADDING) / mmScale / (MINIMAP_WIDTH - PADDING * 2) * contentWidth + viewportX;
      const ny = (e.clientY - rect.top - PADDING) / mmScale / (MINIMAP_HEIGHT - PADDING * 2) * contentHeight + viewportY;
      setViewport(viewportScale, -(nx - containerWidth / 2), -(ny - containerHeight / 2));
    };
    const onMouseUp = () => { isDragging.current = false; };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [mmScale, contentWidth, contentHeight, viewportScale, viewportX, viewportY, containerWidth, containerHeight, setViewport]);

  // After all hooks: rendering nothing must not change the hook count between
  // renders (React #310) when nodes/size arrive on a later pass.
  if (nodes.length === 0 || containerWidth === 0 || containerHeight === 0) return null;

  return (
    <div className="minimap" data-no-pan>
      <svg
        ref={svgRef}
        width={MINIMAP_WIDTH}
        height={MINIMAP_HEIGHT}
        viewBox={`0 0 ${MINIMAP_WIDTH} ${MINIMAP_HEIGHT}`}
        onMouseDown={handleMouseDown}
      >
        <rect width={MINIMAP_WIDTH} height={MINIMAP_HEIGHT} rx={6} fill="var(--minimap-bg)" opacity={0.9} />
        {nodes.map((node) => {
          // mmScale already maps content px → minimap px; dividing by the
          // content size again squashed every node into a strip at the left.
          const nx = node.x * mmScale + PADDING;
          const ny = node.y * mmScale + PADDING;
          const color = NODE_COLORS[node.type ?? ""] ?? "var(--text-dim)";
          return <circle key={node.id} cx={nx} cy={ny} r={3} fill={color} />;
        })}
        <rect
          x={viewX}
          y={viewY}
          width={viewW}
          height={viewH}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={1.5}
          rx={3}
          className="minimap-viewport"
        />
      </svg>
    </div>
  );
}
