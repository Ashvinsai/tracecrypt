import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FlowBranch, FlowEdge, FlowNode, FundFlowGraph as GraphModel } from "../lib/api";
import { truncate } from "../lib/format";

cytoscape.use(dagre);

export type GraphSelection =
  | { kind: "node"; node: FlowNode }
  | { kind: "edge"; edge: FlowEdge }
  | { kind: "branch"; branch: FlowBranch };

interface Props {
  graph: GraphModel;
  selection?: GraphSelection | null;
  onSelect: (selection: GraphSelection | null) => void;
  /** Hop selector: show only edges at or before this depth. */
  maxHop?: number | null;
  /** Initial branch scope. The investigator can toggle it in the toolbar. */
  initialPathOnly?: boolean;
}

const STYLESHEET: cytoscape.StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-family": "IBM Plex Mono, ui-monospace, monospace",
      "font-size": 9,
      color: "#c7d2de",
      "text-valign": "bottom",
      "text-margin-y": 6,
      "text-max-width": "110px",
      "text-wrap": "wrap",
      "text-background-color": "#0d1117",
      "text-background-opacity": 0.85,
      "text-background-padding": "2px",
      width: 42,
      height: 42,
      "border-width": 1.5,
      "background-color": "#222c37",
      "border-color": "#8b98a6",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#5b6b7c",
      "target-arrow-color": "#5b6b7c",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "arrow-scale": 0.8,
      "font-size": 9,
      "font-family": "IBM Plex Mono, ui-monospace, monospace",
      color: "#a7b4c2",
      "text-background-color": "#151b23",
      "text-background-opacity": 0.9,
      "text-background-padding": "2px",
    },
  },
  { selector: "edge.seed-edge", style: { "line-color": "#4a8cff", "target-arrow-color": "#4a8cff", width: 2.4 } },
  { selector: "edge.ambiguous", style: { "line-style": "dashed", "line-dash-pattern": [7, 5] } },
  { selector: "edge.exec-unverified", style: { "line-style": "dashed", "line-dash-pattern": [2, 4] } },
  {
    selector: "node:selected",
    style: { "border-width": 3, "border-color": "#4a8cff", "overlay-opacity": 0 },
  },
  {
    selector: "edge:selected",
    style: { "line-color": "#4a8cff", "target-arrow-color": "#4a8cff", width: 3 },
  },
  { selector: ".dimmed", style: { opacity: 0.18 } },
  { selector: ".labels-hidden", style: { "text-opacity": 0 } },
];

export default function FundFlowGraph({ graph, selection, onSelect, maxHop, initialPathOnly = true }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const [layoutName, setLayoutName] = useState<"dagre" | "cose" | "circle">("dagre");
  const [showLabels, setShowLabels] = useState(true);
  const [pathOnly, setPathOnly] = useState(initialPathOnly);

  // Edges that lie on a branch ending at a verified boundary or a candidate.
  const pathEdgeIndexes = useMemo(() => {
    const indexes = new Set<number>();
    for (const branch of graph.branches) {
      if (branch.endpoint_class === "known_service" || branch.endpoint_class === "deposit_candidate") {
        for (const index of branch.edges) indexes.add(index);
      }
    }
    return indexes;
  }, [graph.branches]);
  const hasPath = pathEdgeIndexes.size > 0;

  const visibleEdges = useMemo(() => {
    let list = graph.edges;
    if (maxHop != null) list = list.filter((edge) => Number(edge.hop_depth) <= maxHop);
    if (pathOnly && hasPath) {
      list = list.filter((edge) => pathEdgeIndexes.has(edge.index) || edge.is_seed_transfer);
    }
    return list;
  }, [graph.edges, maxHop, pathOnly, hasPath, pathEdgeIndexes]);
  const visibleNodeAddresses = useMemo(() => {
    const addresses = new Set<string>();
    for (const edge of visibleEdges) {
      addresses.add(edge.from);
      addresses.add(edge.to);
    }
    if (graph.nodes.length === 1 && visibleEdges.length === 0) addresses.add(graph.nodes[0].address);
    return addresses;
  }, [visibleEdges, graph.nodes]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodes: ElementDefinition[] = graph.nodes
      .filter((node) => visibleNodeAddresses.has(node.address))
      .map((node) => {
        const title = node.entity_name && node.role === "known_service" ? node.entity_name : node.role_label;
        return {
          data: {
            id: node.address,
            label: `${title}\n${truncate(node.address, 7, 5)}`,
            role: node.role,
            entity: node.entity_name ?? "",
          },
          classes: node.role,
        };
      });
    const edges: ElementDefinition[] = visibleEdges.map((edge) => ({
      data: {
        id: `e${edge.index}`,
        source: edge.from,
        target: edge.to,
        label: edge.amount_display ? `${edge.amount_display} ${edge.symbol}` : "",
        edgeIndex: edge.index,
      },
      classes: [
        edge.is_seed_transfer ? "seed-edge" : "",
        edge.ordering_ambiguous ? "ambiguous" : "",
        edge.execution_status && edge.execution_status !== "success" ? "exec-unverified" : "",
      ]
        .filter(Boolean)
        .join(" "),
    }));
    return [...nodes, ...edges];
  }, [graph.nodes, visibleEdges, visibleNodeAddresses]);

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements,
      style: STYLESHEET,
      wheelSensitivity: 0.25,
      minZoom: 0.2,
      maxZoom: 3,
    });
    cyRef.current = cy;

    const layout = () => {
      let instance;
      if (layoutName === "dagre") {
        instance = cy.layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 28,
          rankSep: 90,
          edgeSep: 12,
          padding: 40,
          animate: false,
          fit: true,
        } as unknown as cytoscape.LayoutOptions);
      } else if (layoutName === "circle") {
        instance = cy.layout({ name: "circle", padding: 40 });
      } else {
        instance = cy.layout({
          name: "cose",
          padding: 40,
          nodeRepulsion: () => 12000,
          idealEdgeLength: () => 90,
          randomize: false,
          animate: false,
        });
      }
      instance.run();
      // Fit once the layout has settled; dagre resolves positions synchronously
      // but a deferred fit also covers a container that sized after mount.
      const fit = () => cy.fit(undefined, 36);
      window.setTimeout(fit, 40);
      instance.one("layoutstop", fit);
    };
    layout();

    cy.on("tap", "node", (event) => {
      const address = event.target.id();
      const node = graph.nodes.find((candidate) => candidate.address === address);
      if (node) onSelect({ kind: "node", node });
    });
    cy.on("tap", "edge", (event) => {
      const index = Number(event.target.data("edgeIndex"));
      const edge = graph.edges.find((candidate) => candidate.index === index);
      if (edge) onSelect({ kind: "edge", edge });
    });
    cy.on("tap", (event) => {
      if (event.target === cy) onSelect(null);
    });

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements, graph.edges, graph.nodes, layoutName, onSelect]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().forEach((node) => {
      node.toggleClass("labels-hidden", !showLabels);
    });
    cy.edges().forEach((edge) => {
      edge.toggleClass("labels-hidden", !showLabels);
    });
  }, [showLabels, elements]);

  // Reflect an externally-held selection (e.g. from the timeline) onto the graph.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().unselect();
    cy.nodes().removeClass("dimmed");
    cy.edges().removeClass("dimmed");
    if (!selection) return;
    if (selection.kind === "node") {
      const node = cy.getElementById(selection.node.address);
      node.select();
      const neighbourhood = node.closedNeighborhood();
      cy.elements().not(neighbourhood).addClass("dimmed");
    } else if (selection.kind === "edge") {
      const edge = cy.getElementById(`e${selection.edge.index}`);
      edge.select();
      cy.elements().not(edge.connectedNodes()).not(edge).addClass("dimmed");
    } else {
      for (const index of selection.branch.edges) {
        const edge = cy.getElementById(`e${index}`);
        edge.select();
      }
    }
  }, [selection]);

  const fit = useCallback(() => cyRef.current?.fit(undefined, 32), []);
  const zoomBy = useCallback((factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: Math.min(3, Math.max(0.2, cy.zoom() * factor)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }, []);

  return (
    <div>
      <div className="graph-toolbar">
        <label htmlFor="graph-layout">Layout</label>
        <select
          id="graph-layout"
          value={layoutName}
          onChange={(event) => setLayoutName(event.target.value as typeof layoutName)}
        >
          <option value="dagre">Hop order (layered)</option>
          <option value="cose">Organic</option>
          <option value="circle">Circle</option>
        </select>
        <span className="sep" />
        <button type="button" className="btn sm" onClick={fit}>
          Fit
        </button>
        <button type="button" className="btn sm" onClick={() => zoomBy(1.2)} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="btn sm" onClick={() => zoomBy(1 / 1.2)} aria-label="Zoom out">
          −
        </button>
        <span className="sep" />
        <button
          type="button"
          className="btn sm"
          aria-pressed={showLabels}
          onClick={() => setShowLabels((value) => !value)}
        >
          {showLabels ? "Labels on" : "Labels off"}
        </button>
        {hasPath ? (
          <button
            type="button"
            className="btn sm"
            aria-pressed={pathOnly}
            onClick={() => setPathOnly((value) => !value)}
            title="Show only the transfers on branches that end at a verified boundary or candidate"
          >
            {pathOnly ? "Trace path only" : "All branches"}
          </button>
        ) : null}
        <span className="spacer" />
        <span className="muted" style={{ fontSize: 11 }}>
          {visibleEdges.length} of {graph.edges.length} transfers shown
        </span>
      </div>
      <div className="graph-canvas" ref={container} role="img" aria-label="Fund-flow graph of observed transfers" />
    </div>
  );
}
