"use client";

import { useCallback, useEffect, useState } from "react";
import { FileText, Loader, RefreshCw } from "lucide-react";

/**
 * Maintenance findings read from the tenant's knowledge graph: for each asset
 * its issues, the actions taken, and the values recorded, with the documents
 * they come from. Built from whatever the company uploaded — nothing seeded.
 */

interface Fact {
  role: string;
  type: string;
  typeLabel: string;
  value: string;
  relationship: string;
  confidence: number;
  documents: string[];
}

interface Finding {
  type: string;
  typeLabel: string;
  name: string;
  facts: Fact[];
  documents: string[];
  lastSeen: string | null;
  issueCount: number;
  actionCount: number;
}

interface TypeInfo {
  label: string;
  color: string | null;
  role: string | null;
}

const ROLE_TITLES: Record<string, string> = {
  issue: "Issues",
  action: "Actions",
  value: "Values",
};

function readable(relationship: string): string {
  return relationship.toLowerCase().replace(/_/g, " ");
}

export function DocumentFindings() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [types, setTypes] = useState<Record<string, TypeInfo>>({});
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const res = await fetch("/api/maintenance/findings", { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load findings");
      setFindings(data.findings ?? []);
      setTypes(data.types ?? {});
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load findings");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const color = (type: string) => types[type]?.color ?? "#525252";

  return (
    <div
      style={{
        border: "1px solid #e5e5e5",
        borderRadius: "6px",
        backgroundColor: "#fafafa",
        padding: "1.5rem",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
        }}
      >
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: "0 0 0.5rem 0" }}>
            From your documents
          </h3>
          <p style={{ color: "#737373", fontSize: "0.8rem", margin: "0 0 1.25rem 0" }}>
            Issues, actions and readings linked to each asset in the knowledge graph, with the
            documents they come from. Updates as new documents are indexed.
          </p>
        </div>
        <button
          onClick={load}
          disabled={status === "loading"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "0.4rem 0.7rem",
            border: "1px solid #d4d4d4",
            borderRadius: 4,
            background: "#ffffff",
            fontSize: "0.75rem",
            cursor: "pointer",
          }}
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {status === "loading" ? (
        <div
          style={{ color: "#737373", fontSize: "0.85rem", textAlign: "center", padding: "2rem" }}
        >
          <Loader size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
          Reading the knowledge graph...
        </div>
      ) : status === "error" ? (
        <div style={{ color: "#b91c1c", fontSize: "0.85rem", padding: "1rem" }}>{error}</div>
      ) : findings.length === 0 ? (
        <div
          style={{
            color: "#a3a3a3",
            fontSize: "0.85rem",
            textAlign: "center",
            padding: "2rem",
            border: "1px dashed #e5e5e5",
            borderRadius: "4px",
          }}
        >
          No assets with issues or actions found in your documents yet.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {findings.map((f) => {
            const groups: Record<string, Fact[]> = {};
            for (const fact of f.facts) (groups[fact.role] ??= []).push(fact);
            return (
              <div
                key={`${f.type}:${f.name}`}
                style={{
                  border: "1px solid #e5e5e5",
                  padding: "1rem",
                  borderRadius: "4px",
                  background: "#ffffff",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginBottom: "0.6rem",
                    gap: 8,
                  }}
                >
                  <span
                    style={{ fontWeight: 700, fontSize: "0.9rem", fontFamily: "var(--font-mono)" }}
                  >
                    {f.name}
                    <span
                      style={{
                        fontWeight: 500,
                        fontSize: "0.7rem",
                        color: "#737373",
                        marginLeft: 8,
                      }}
                    >
                      {f.typeLabel}
                    </span>
                  </span>
                  <span style={{ fontSize: "0.7rem", color: "#737373" }}>
                    {f.issueCount} issue{f.issueCount === 1 ? "" : "s"} · {f.actionCount} action
                    {f.actionCount === 1 ? "" : "s"}
                    {f.lastSeen && ` · latest ${new Date(f.lastSeen).toLocaleDateString()}`}
                  </span>
                </div>

                {Object.entries(groups).map(([role, facts]) => (
                  <div
                    key={role}
                    style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "baseline" }}
                  >
                    <span
                      style={{
                        width: 64,
                        flexShrink: 0,
                        fontSize: "0.7rem",
                        fontWeight: 700,
                        color: "#525252",
                      }}
                    >
                      {ROLE_TITLES[role] ?? facts[0].typeLabel}
                    </span>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {facts.map((fact) => (
                        <span
                          key={`${fact.relationship}:${fact.value}`}
                          title={`${f.name} ${readable(fact.relationship)} ${fact.value}\nFrom: ${fact.documents.join(", ")}`}
                          style={{
                            fontSize: "0.72rem",
                            padding: "0.1rem 0.45rem",
                            borderRadius: 3,
                            border: `1px solid ${color(fact.type)}`,
                            color: color(fact.type),
                            background: "#ffffff",
                          }}
                        >
                          {fact.value}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}

                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    flexWrap: "wrap",
                    fontSize: "0.68rem",
                    color: "#737373",
                    borderTop: "1px solid #e5e5e5",
                    paddingTop: "0.5rem",
                    marginTop: "0.5rem",
                  }}
                >
                  <FileText size={11} style={{ marginTop: 1 }} />
                  {f.documents.join(" · ")}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
