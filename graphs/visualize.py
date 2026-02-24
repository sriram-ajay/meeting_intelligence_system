"""
Graph visualisation utility.

Exports LangGraph definitions as Mermaid (.mmd) files for the
VS Code LangGraph Visualiser extension.

Usage (from project root):
    python -m graphs.visualize

Generates:
    graphs/ingestion_graph.mmd
    graphs/query_graph.mmd
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _export_mermaid(graph, output_path: str) -> None:
    """Export a compiled graph to a .mmd Mermaid file."""
    mermaid_str = graph.get_graph().draw_mermaid()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(mermaid_str)
    print(f"  ✓ {output_path}")


def main() -> None:
    """Build both graphs with stub dependencies and export Mermaid diagrams."""

    # ---- Stub dependencies (just need the graph structure, not real calls) ----
    class _Stub:
        """No-op stub that accepts any method call."""
        def __getattr__(self, _):
            return lambda *a, **kw: None

    stub = _Stub()

    from graphs.ingestion_graph import build_ingestion_graph
    from graphs.query_graph import build_query_graph

    print("Exporting LangGraph diagrams …")

    out_dir = os.path.dirname(os.path.abspath(__file__))

    ingestion = build_ingestion_graph(
        artifact_store=stub,
        metadata_store=stub,
        vector_store=stub,
        embedding_provider=stub,
    )
    _export_mermaid(ingestion, os.path.join(out_dir, "ingestion_graph.mmd"))

    query = build_query_graph(
        vector_store=stub,
        embedding_provider=stub,
        llm_provider=stub,
        artifact_store=stub,
        guardrails=stub,
    )
    _export_mermaid(query, os.path.join(out_dir, "query_graph.mmd"))

    print("Done — open the .mmd files in VS Code to see the graphs.")


if __name__ == "__main__":
    main()
