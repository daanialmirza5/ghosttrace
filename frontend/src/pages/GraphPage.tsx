import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { Card, EmptyState, ErrorState, Field, Loading, PageHeader } from "../components/ui";
import { GraphExplorer } from "../features/dependency-graph/GraphExplorer";
import { useImportGraph, useImports } from "../hooks/queries";

export function GraphPage() {
  const imports = useImports({ limit: 100 });
  const [chosen, setChosen] = useState("");
  const importId = chosen || imports.data?.items.find((item) => item.status !== "failed")?.id || "";
  const graph = useImportGraph(importId || undefined);
  const id = useId();

  return (
    <>
      <PageHeader
        title="Service graph"
        description="Directed dependencies reconstructed from trace ancestry and recorded target_service calls across a whole import. Open an incident for the graph of its window with hypothesis ranks."
      />
      {imports.isLoading && <Loading />}
      {imports.error && <ErrorState error={imports.error} />}
      {imports.data && imports.data.items.length === 0 && (
        <Card>
          <EmptyState title="No imports yet" action={<Link to="/import" className="text-sm font-medium text-accent-700">Import events →</Link>} />
        </Card>
      )}
      {importId && (
        <div className="space-y-4">
          <div className="max-w-md">
            <Field label="Import" htmlFor={id}>
              <select id={id} className="input" value={importId} onChange={(e) => setChosen(e.target.value)}>
                {imports.data?.items
                  .filter((item) => item.status !== "failed")
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
              </select>
            </Field>
          </div>
          {graph.isLoading && <Loading label="Building graph…" />}
          {graph.error && <ErrorState error={graph.error} />}
          {graph.data && <GraphExplorer graph={graph.data} />}
        </div>
      )}
    </>
  );
}
