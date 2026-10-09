"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Search,
  FileText,
  Network,
  MessageSquare,
  Shield,
  Wrench,
  BookOpen,
  Upload,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Zap,
  ChevronRight,
  ArrowRight,
  Database,
  Activity,
  LogOut,
  User,
  Plus,
  Loader,
  RefreshCw,
} from "lucide-react";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import { DocumentFindings } from "@/components/maintenance/DocumentFindings";

// Types
interface Document {
  id: string;
  title: string;
  fileName: string;
  fileType: string;
  fileSize: number;
  status: string;
  documentType: string;
  createdAt: string;
  pageCount?: number;
  wordCount?: number;
}

interface ComplianceRule {
  id: string;
  regulationName: string;
  regulationVersion: string;
  sectionReference: string;
  requirementText: string;
  requirementType: string;
  complianceStatus: string;
  notes: string;
}

export default function DashboardPage() {
  const router = useRouter();
  const [activeNav, setActiveNav] = useState("dashboard");
  const [session, setSession] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Data states
  const [documents, setDocuments] = useState<Document[]>([]);
  const [complianceRules, setComplianceRules] = useState<ComplianceRule[]>([]);
  const [complianceFilter, setComplianceFilter] = useState("");
  const [docsLoading, setDocsLoading] = useState(false);
  const [complianceLoading, setComplianceLoading] = useState(false);

  // Alerts states
  const [alerts, setAlerts] = useState<any[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);

  // Maintenance states
  const [maintenanceOrders, setMaintenanceOrders] = useState<any[]>([]);
  const [maintenanceLoading, setMaintenanceLoading] = useState(false);

  // Copilot Q&A states
  const [query, setQuery] = useState("");
  const [chatHistory, setChatHistory] = useState<
    Array<{ role: "user" | "assistant"; text: string; data?: any }>
  >([]);
  const [chatLoading, setChatLoading] = useState(false);

  // Upload state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState("");

  // Fetch session
  useEffect(() => {
    async function checkSession() {
      try {
        const res = await fetch("/api/auth/session");
        const data = await res.json();
        if (!res.ok || !data.authenticated) {
          router.push("/login");
          return;
        }
        setSession(data.session);
      } catch (err) {
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }
    checkSession();
  }, [router]);

  // Load document list
  const fetchDocuments = async () => {
    setDocsLoading(true);
    try {
      const res = await fetch("/api/documents/upload");
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDocsLoading(false);
    }
  };

  // Load compliance rules
  const fetchCompliance = async () => {
    setComplianceLoading(true);
    try {
      const res = await fetch("/api/compliance/status");
      if (res.ok) {
        const data = await res.json();
        setComplianceRules(data.rules || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setComplianceLoading(false);
    }
  };

  // Load active alerts
  const fetchAlerts = async () => {
    setAlertsLoading(true);
    try {
      const res = await fetch("/api/alerts/status");
      if (res.ok) {
        const data = await res.json();
        setAlerts(data.alerts || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setAlertsLoading(false);
    }
  };

  // Load maintenance orders
  const fetchMaintenance = async () => {
    setMaintenanceLoading(true);
    try {
      const res = await fetch("/api/maintenance/orders");
      if (res.ok) {
        const data = await res.json();
        setMaintenanceOrders(data.orders || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setMaintenanceLoading(false);
    }
  };

  // Trigger loads based on activeNav
  useEffect(() => {
    if (!session) return;
    if (activeNav === "dashboard" || activeNav === "documents") {
      fetchDocuments();
    }
    if (activeNav === "dashboard" || activeNav === "compliance") {
      fetchCompliance();
    }
    if (activeNav === "dashboard") {
      fetchAlerts();
    }
    if (activeNav === "maintenance") {
      fetchMaintenance();
    }
  }, [activeNav, session]);

  // Copilot query submission
  const handleCopilotSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    const userMsg = query;
    setChatHistory((prev) => [...prev, { role: "user", text: userMsg }]);
    setQuery("");
    setChatLoading(true);

    try {
      const res = await fetch("/api/copilot/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userMsg }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Failed to query pipeline");
      }

      setChatHistory((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `Prepared Prompt context compiled (estimated ${data.total_token_estimate || 0} tokens). Ready for paid LLM payload:`,
          data,
        },
      ]);
    } catch (err: any) {
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant", text: `Error: ${err.message || "Something went wrong"}` },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  // Document upload handler
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) return;

    setUploadProgress("Uploading file...");
    const formData = new FormData();
    formData.append("file", uploadFile);

    try {
      const res = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Upload failed");

      setUploadProgress("Upload successful! Processing has started.");
      setUploadFile(null);
      fetchDocuments();
    } catch (err: any) {
      setUploadProgress(`Error: ${err.message}`);
    }
  };

  // Toggle compliance rule status
  const toggleRuleStatus = async (ruleId: string, currentStatus: string) => {
    const nextStatus = currentStatus === "compliant" ? "gaps" : "compliant";
    try {
      const res = await fetch("/api/compliance/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ruleId, complianceStatus: nextStatus }),
      });
      if (res.ok) {
        fetchCompliance();
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Logout handler
  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
  };

  if (loading) {
    return (
      <div
        style={{
          backgroundColor: "#ffffff",
          color: "#000000",
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        <Loader className="animate-spin" size={24} />
        <span style={{ fontSize: "0.85rem", color: "#737373", letterSpacing: "0.1em" }}>
          LOADING SESSION
        </span>
      </div>
    );
  }

  return (
    <div
      style={{ backgroundColor: "#ffffff", color: "#000000", minHeight: "100vh", display: "flex" }}
    >
      {/* Sidebar Navigation */}
      <aside
        style={{
          width: "260px",
          backgroundColor: "#f5f5f5",
          borderRight: "1px solid #e5e5e5",
          display: "flex",
          flexDirection: "column",
          position: "fixed",
          top: 0,
          bottom: 0,
          left: 0,
        }}
      >
        {/* Logo - clickable link to home page */}
        <Link
          href="/"
          style={{
            padding: "1.5rem 1.25rem",
            borderBottom: "1px solid #e5e5e5",
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            textDecoration: "none",
            color: "#000000",
            cursor: "pointer",
          }}
        >
          <div
            style={{
              width: "32px",
              height: "32px",
              border: "1.5px solid #000000",
              borderRadius: "4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Brain size={18} color="#000000" />
          </div>
          <div>
            <h1 style={{ fontSize: "1rem", fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>
              VEDA AI
            </h1>
            <p style={{ fontSize: "0.6rem", color: "#737373", margin: 0 }}>
              Grayscale Intelligence
            </p>
          </div>
        </Link>

        {/* User Card */}
        <div
          style={{
            padding: "1rem 1.25rem",
            borderBottom: "1px solid #e5e5e5",
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
          }}
        >
          <div
            style={{
              width: "30px",
              height: "30px",
              border: "1px solid #d4d4d4",
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "#e5e5e5",
            }}
          >
            <User size={14} color="#737373" />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p
              style={{
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#000000",
                margin: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {session?.name}
            </p>
            <p
              style={{
                fontSize: "0.65rem",
                color: "#737373",
                margin: 0,
                textTransform: "capitalize",
              }}
            >
              {session?.role} · {session?.tenantSlug}
            </p>
          </div>
        </div>

        {/* Nav Links */}
        <nav
          style={{
            flex: 1,
            padding: "1.5rem 1rem",
            display: "flex",
            flexDirection: "column",
            gap: "0.4rem",
          }}
        >
          {[
            { id: "dashboard", label: "Command Center", icon: Activity },
            { id: "copilot", label: "Company Chatbot", icon: MessageSquare },
            { id: "knowledge", label: "Knowledge Graph", icon: Network },
            { id: "documents", label: "Data Uploads", icon: Upload },
            { id: "maintenance", label: "Maintenance Intel", icon: Wrench },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() =>
                item.id === "documents"
                  ? router.push("/upload")
                  : item.id === "copilot"
                    ? router.push("/chat")
                    : setActiveNav(item.id)
              }
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                width: "100%",
                padding: "0.6rem 0.8rem",
                borderRadius: "4px",
                border: "none",
                backgroundColor: activeNav === item.id ? "rgba(0,0,0,0.06)" : "transparent",
                color: activeNav === item.id ? "#000000" : "#525252",
                fontSize: "0.85rem",
                fontWeight: activeNav === item.id ? 600 : 500,
                textAlign: "left",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) => {
                if (activeNav !== item.id)
                  e.currentTarget.style.backgroundColor = "rgba(0,0,0,0.02)";
              }}
              onMouseLeave={(e) => {
                if (activeNav !== item.id) e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <item.icon size={16} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Footer actions */}
        <div style={{ padding: "1rem", borderTop: "1px solid #e5e5e5" }}>
          <button
            onClick={handleLogout}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              width: "100%",
              padding: "0.5rem",
              borderRadius: "4px",
              border: "1px solid #d4d4d4",
              backgroundColor: "transparent",
              color: "#525252",
              fontSize: "0.8rem",
              cursor: "pointer",
              justifyContent: "center",
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "#000000";
              e.currentTarget.style.color = "#000000";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "#d4d4d4";
              e.currentTarget.style.color = "#525252";
            }}
          >
            <LogOut size={14} /> Log Out
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main
        style={{
          flex: 1,
          marginLeft: "260px",
          padding: "2rem",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Dynamic Nav View rendering */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeNav}
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -15 }}
            transition={{ duration: 0.25 }}
            style={{ flex: 1, display: "flex", flexDirection: "column" }}
          >
            {/* ── COMMAND CENTER VIEW ────────────────────── */}
            {activeNav === "dashboard" && (
              <div>
                <header style={{ marginBottom: "2rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Command Center
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Operational and knowledge overview scoped to{" "}
                    {session?.tenantSlug || "your organization"}
                  </p>
                </header>

                {/* Stats row */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, 1fr)",
                    gap: "1.5rem",
                    marginBottom: "2.5rem",
                  }}
                >
                  <div
                    style={{
                      border: "1px solid #e5e5e5",
                      padding: "1.5rem",
                      borderRadius: "6px",
                      backgroundColor: "#fafafa",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ fontSize: "0.8rem", color: "#737373", fontWeight: 600 }}>
                        INDEXED DOCUMENTS
                      </span>
                      <FileText size={16} color="#737373" />
                    </div>
                    <div style={{ fontSize: "2rem", fontWeight: 900, margin: "0.5rem 0" }}>
                      {documents.length}
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "#a3a3a3" }}>From document index</div>
                  </div>

                  <div
                    style={{
                      border: "1px solid #e5e5e5",
                      padding: "1.5rem",
                      borderRadius: "6px",
                      backgroundColor: "#fafafa",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ fontSize: "0.8rem", color: "#737373", fontWeight: 600 }}>
                        COMPLIANCE SCORE
                      </span>
                      <Shield size={16} color="#737373" />
                    </div>
                    <div style={{ fontSize: "2rem", fontWeight: 900, margin: "0.5rem 0" }}>
                      {complianceRules.length > 0
                        ? `${Math.round((complianceRules.filter((r) => r.complianceStatus === "compliant").length / complianceRules.length) * 100)}%`
                        : "100%"}
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "#a3a3a3" }}>
                      Compliance checklists
                    </div>
                  </div>

                  <div
                    style={{
                      border: "1px solid #e5e5e5",
                      padding: "1.5rem",
                      borderRadius: "6px",
                      backgroundColor: "#fafafa",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ fontSize: "0.8rem", color: "#737373", fontWeight: 600 }}>
                        KAFKA QUEUES
                      </span>
                      <Zap size={16} color="#737373" />
                    </div>
                    <div style={{ fontSize: "2rem", fontWeight: 900, margin: "0.5rem 0" }}>
                      ACTIVE
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "#a3a3a3" }}>
                      Event-driven pipeline
                    </div>
                  </div>
                </div>

                {/* Dashboard columns */}
                <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: "2rem" }}>
                  {/* Left Column: Recent documents */}
                  <div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "1rem",
                      }}
                    >
                      <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>
                        Recent Documents
                      </h3>
                      <button
                        onClick={fetchDocuments}
                        style={{
                          background: "none",
                          border: "none",
                          color: "#737373",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.25rem",
                          fontSize: "0.8rem",
                        }}
                      >
                        <RefreshCw size={12} /> Refresh
                      </button>
                    </div>

                    <div
                      style={{
                        border: "1px solid #e5e5e5",
                        borderRadius: "6px",
                        overflow: "hidden",
                        backgroundColor: "#ffffff",
                      }}
                    >
                      {docsLoading ? (
                        <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                          Loading documents...
                        </div>
                      ) : documents.length === 0 ? (
                        <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                          No documents uploaded yet. Open Data Uploads to add your first file.
                        </div>
                      ) : (
                        <table
                          style={{
                            width: "100%",
                            borderCollapse: "collapse",
                            fontSize: "0.85rem",
                            textAlign: "left",
                          }}
                        >
                          <thead>
                            <tr
                              style={{
                                borderBottom: "1px solid #e5e5e5",
                                color: "#737373",
                                backgroundColor: "#fafafa",
                              }}
                            >
                              <th style={{ padding: "0.75rem 1rem" }}>Filename</th>
                              <th style={{ padding: "0.75rem 1rem" }}>Type</th>
                              <th style={{ padding: "0.75rem 1rem" }}>Status</th>
                              <th style={{ padding: "0.75rem 1rem" }}>Processed</th>
                            </tr>
                          </thead>
                          <tbody>
                            {documents.slice(0, 5).map((doc) => (
                              <tr key={doc.id} style={{ borderBottom: "1px solid #e5e5e5" }}>
                                <td style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>
                                  {doc.fileName}
                                </td>
                                <td style={{ padding: "0.75rem 1rem" }}>
                                  <span
                                    style={{
                                      fontSize: "0.7rem",
                                      border: "1px solid #d4d4d4",
                                      padding: "0.1rem 0.4rem",
                                      borderRadius: "3px",
                                      textTransform: "uppercase",
                                      backgroundColor: "#fafafa",
                                    }}
                                  >
                                    {doc.documentType}
                                  </span>
                                </td>
                                <td style={{ padding: "0.75rem 1rem" }}>
                                  <span
                                    style={{
                                      fontSize: "0.7rem",
                                      color: doc.status === "indexed" ? "#000000" : "#737373",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "0.25rem",
                                    }}
                                  >
                                    <span
                                      style={{
                                        width: "6px",
                                        height: "6px",
                                        borderRadius: "50%",
                                        backgroundColor:
                                          doc.status === "indexed" ? "#000000" : "#a3a3a3",
                                      }}
                                    />
                                    {doc.status}
                                  </span>
                                </td>
                                <td style={{ padding: "0.75rem 1rem", color: "#737373" }}>
                                  {doc.pageCount ? `${doc.pageCount} pgs` : "pending"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </div>

                  {/* Right Column: Active alerts list */}
                  <div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "1rem",
                      }}
                    >
                      <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>
                        Active Alerts
                      </h3>
                      <button
                        onClick={fetchAlerts}
                        style={{
                          background: "none",
                          border: "none",
                          color: "#737373",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.25rem",
                          fontSize: "0.8rem",
                        }}
                      >
                        <RefreshCw size={12} /> Sync
                      </button>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                      {alertsLoading ? (
                        <div
                          style={{
                            color: "#737373",
                            fontSize: "0.85rem",
                            textAlign: "center",
                            padding: "1rem",
                          }}
                        >
                          Loading alerts...
                        </div>
                      ) : alerts.length === 0 ? (
                        <div
                          style={{
                            color: "#a3a3a3",
                            fontSize: "0.85rem",
                            textAlign: "center",
                            padding: "1rem",
                            border: "1px dashed #e5e5e5",
                            borderRadius: "4px",
                          }}
                        >
                          No active alerts.
                        </div>
                      ) : (
                        alerts.map((alert) => (
                          <div
                            key={alert.id}
                            style={{
                              border: "1px solid #e5e5e5",
                              borderLeft: `3px solid ${alert.severity === "critical" ? "#000000" : "#737373"}`,
                              padding: "1rem",
                              borderRadius: "4px",
                              backgroundColor: "#fafafa",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                fontSize: "0.8rem",
                                fontWeight: 700,
                                marginBottom: "0.25rem",
                              }}
                            >
                              <span>{alert.title}</span>
                              <span
                                style={{
                                  textTransform: "uppercase",
                                  fontSize: "0.7rem",
                                  border: `1px solid ${alert.severity === "critical" ? "#000000" : "#737373"}`,
                                  padding: "0.1rem 0.3rem",
                                  borderRadius: "3px",
                                  color: alert.severity === "critical" ? "#000000" : "#737373",
                                }}
                              >
                                {alert.severity}
                              </span>
                            </div>
                            <p style={{ fontSize: "0.75rem", color: "#737373", margin: 0 }}>
                              {alert.description}
                            </p>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── AI COPILOT VIEW ────────────────────────── */}
            {activeNav === "copilot" && (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  height: "calc(100vh - 6rem)",
                }}
              >
                <header style={{ marginBottom: "1.5rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    VEDA Copilot
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Query the RAG pipeline. Generates graph-enriched context chunks ready for paid
                    LLM execution.
                  </p>
                </header>

                {/* Chat Area */}
                <div
                  style={{
                    flex: 1,
                    border: "1px solid #e5e5e5",
                    borderRadius: "6px",
                    backgroundColor: "#fafafa",
                    display: "flex",
                    flexDirection: "column",
                    padding: "1.5rem",
                    overflowY: "auto",
                    marginBottom: "1rem",
                    maxHeight: "500px",
                  }}
                >
                  {chatHistory.length === 0 ? (
                    <div
                      style={{
                        flex: 1,
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#737373",
                        gap: "0.5rem",
                      }}
                    >
                      <Brain size={36} color="#d4d4d4" />
                      <span style={{ fontSize: "0.85rem", letterSpacing: "0.05em" }}>
                        ASK A QUESTION TO THE RAG PIPELINE
                      </span>
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
                      {chatHistory.map((msg, idx) => (
                        <div
                          key={idx}
                          style={{
                            alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                            maxWidth: "80%",
                            display: "flex",
                            gap: "0.75rem",
                          }}
                        >
                          {msg.role === "assistant" && (
                            <div
                              style={{
                                width: "28px",
                                height: "28px",
                                border: "1px solid #000000",
                                borderRadius: "50%",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                flexShrink: 0,
                                backgroundColor: "#ffffff",
                              }}
                            >
                              <Brain size={14} color="#000000" />
                            </div>
                          )}
                          <div>
                            <div
                              style={{
                                padding: "0.75rem 1rem",
                                borderRadius: "6px",
                                backgroundColor: msg.role === "user" ? "#000000" : "#ffffff",
                                color: msg.role === "user" ? "#ffffff" : "#000000",
                                fontSize: "0.85rem",
                                lineHeight: 1.4,
                                border: msg.role === "assistant" ? "1px solid #e5e5e5" : "none",
                                boxShadow:
                                  msg.role === "assistant" ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
                              }}
                            >
                              <p style={{ margin: 0 }}>{msg.text}</p>

                              {/* Display prepared prompt payload if available */}
                              {msg.data && (
                                <div
                                  style={{
                                    marginTop: "1rem",
                                    paddingTop: "1rem",
                                    borderTop: "1px solid #e5e5e5",
                                  }}
                                >
                                  <div
                                    style={{
                                      display: "flex",
                                      justifyContent: "space-between",
                                      alignItems: "center",
                                      marginBottom: "0.5rem",
                                    }}
                                  >
                                    <span
                                      style={{
                                        fontSize: "0.7rem",
                                        color: "#737373",
                                        fontWeight: 700,
                                      }}
                                    >
                                      PREPARED PROMPT PAYLOAD
                                    </span>
                                    <span
                                      style={{
                                        fontSize: "0.7rem",
                                        color: "#000000",
                                        border: "1px solid #d4d4d4",
                                        padding: "0.15rem 0.4rem",
                                        borderRadius: "3px",
                                        backgroundColor: "#fafafa",
                                      }}
                                    >
                                      Confidence: {msg.data.confidence_score}%
                                    </span>
                                  </div>
                                  <textarea
                                    readOnly
                                    value={msg.data.formatted_prompt}
                                    style={{
                                      width: "100%",
                                      height: "120px",
                                      backgroundColor: "#fafafa",
                                      border: "1px solid #d4d4d4",
                                      borderRadius: "4px",
                                      padding: "0.5rem",
                                      color: "#525252",
                                      fontFamily: "var(--font-mono)",
                                      fontSize: "0.75rem",
                                      resize: "none",
                                    }}
                                  />
                                </div>
                              )}
                            </div>

                            {/* Display sources linked */}
                            {msg.data?.sources && msg.data.sources.length > 0 && (
                              <div
                                style={{
                                  display: "flex",
                                  gap: "0.5rem",
                                  marginTop: "0.5rem",
                                  flexWrap: "wrap",
                                }}
                              >
                                {msg.data.sources.map((src: any, sIdx: number) => (
                                  <div
                                    key={sIdx}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "0.3rem",
                                      fontSize: "0.7rem",
                                      border: "1px solid #e5e5e5",
                                      padding: "0.2rem 0.5rem",
                                      borderRadius: "3px",
                                      backgroundColor: "#ffffff",
                                      color: "#737373",
                                    }}
                                  >
                                    <FileText size={10} />
                                    <span>
                                      {src.title || src.document_id.substring(0, 8)} (
                                      {src.source_type})
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Input form */}
                <form onSubmit={handleCopilotSubmit} style={{ display: "flex", gap: "0.75rem" }}>
                  <input
                    type="text"
                    required
                    disabled={chatLoading}
                    placeholder="Ask operational questions about your plant equipment..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    style={{
                      flex: 1,
                      padding: "0.75rem 1rem",
                      backgroundColor: "#fafafa",
                      border: "1px solid #d4d4d4",
                      borderRadius: "4px",
                      color: "#000000",
                      fontSize: "0.9rem",
                    }}
                  />
                  <button
                    type="submit"
                    disabled={chatLoading}
                    style={{
                      backgroundColor: "#000000",
                      color: "#ffffff",
                      padding: "0.75rem 1.5rem",
                      borderRadius: "4px",
                      fontWeight: 700,
                      border: "none",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                    }}
                  >
                    {chatLoading ? "Querying..." : "Send"}
                  </button>
                </form>
              </div>
            )}

            {/* ── KNOWLEDGE GRAPH VIEW ───────────────────── */}
            {activeNav === "knowledge" && (
              <div>
                <header style={{ marginBottom: "1.25rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Knowledge Graph
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Every entity and relationship extracted from your company&apos;s documents,
                    updated as new documents are processed.
                  </p>
                </header>
                <KnowledgeGraph />
              </div>
            )}

            {/* ── DOCUMENTS VIEW ─────────────────────────── */}
            {activeNav === "documents" && (
              <div>
                <header style={{ marginBottom: "2rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Documents Library
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Upload and manage documents. Integrates with pgvector and Kafka.
                  </p>
                </header>

                {/* Upload drag drop panel */}
                <div
                  style={{
                    border: "1.5px dashed #d4d4d4",
                    padding: "2.5rem",
                    borderRadius: "6px",
                    backgroundColor: "#fafafa",
                    textAlign: "center",
                    marginBottom: "2.5rem",
                  }}
                >
                  <Upload size={32} color="#737373" style={{ marginBottom: "1rem" }} />
                  <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "0.5rem" }}>
                    Ingest New Document
                  </h3>
                  <p
                    style={{
                      fontSize: "0.8rem",
                      color: "#737373",
                      maxWidth: "400px",
                      margin: "0 auto 1.5rem auto",
                    }}
                  >
                    Select PDFs, Spreadsheets, or Images. Automatically splits into semantic chunks
                    and creates graph entries.
                  </p>

                  <form
                    onSubmit={handleUpload}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: "1rem",
                    }}
                  >
                    <input
                      type="file"
                      id="doc-file-upload"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                      style={{ display: "none" }}
                    />
                    <label
                      htmlFor="doc-file-upload"
                      style={{
                        border: "1px solid #d4d4d4",
                        padding: "0.5rem 1rem",
                        borderRadius: "4px",
                        fontSize: "0.85rem",
                        cursor: "pointer",
                        fontWeight: 600,
                        display: "inline-block",
                        backgroundColor: "#ffffff",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#000000")}
                      onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#d4d4d4")}
                    >
                      {uploadFile ? uploadFile.name : "Select File"}
                    </label>

                    {uploadFile && (
                      <button
                        type="submit"
                        style={{
                          backgroundColor: "#000000",
                          color: "#ffffff",
                          padding: "0.5rem 1.5rem",
                          borderRadius: "4px",
                          fontWeight: 700,
                          border: "none",
                          cursor: "pointer",
                        }}
                      >
                        Inward File
                      </button>
                    )}
                  </form>

                  {uploadProgress && (
                    <div style={{ marginTop: "1rem", fontSize: "0.85rem", fontWeight: 600 }}>
                      {uploadProgress}
                    </div>
                  )}
                </div>

                {/* Documents table */}
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "1rem",
                    }}
                  >
                    <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>
                      Ingested Archives
                    </h3>
                    <button
                      onClick={fetchDocuments}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#737373",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "0.25rem",
                        fontSize: "0.8rem",
                      }}
                    >
                      <RefreshCw size={12} /> Refresh
                    </button>
                  </div>

                  <div
                    style={{
                      border: "1px solid #e5e5e5",
                      borderRadius: "6px",
                      overflow: "hidden",
                      backgroundColor: "#ffffff",
                    }}
                  >
                    {docsLoading ? (
                      <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                        Loading archive rows...
                      </div>
                    ) : documents.length === 0 ? (
                      <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                        No documents found. Upload one to start ingestion.
                      </div>
                    ) : (
                      <table
                        style={{
                          width: "100%",
                          borderCollapse: "collapse",
                          fontSize: "0.85rem",
                          textAlign: "left",
                        }}
                      >
                        <thead>
                          <tr
                            style={{
                              borderBottom: "1px solid #e5e5e5",
                              color: "#737373",
                              backgroundColor: "#fafafa",
                            }}
                          >
                            <th style={{ padding: "0.75rem 1rem" }}>Filename</th>
                            <th style={{ padding: "0.75rem 1rem" }}>Document Type</th>
                            <th style={{ padding: "0.75rem 1rem" }}>Size</th>
                            <th style={{ padding: "0.75rem 1rem" }}>Ingested Date</th>
                            <th style={{ padding: "0.75rem 1rem" }}>Pipeline Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {documents.map((doc) => (
                            <tr key={doc.id} style={{ borderBottom: "1px solid #e5e5e5" }}>
                              <td style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>
                                {doc.fileName}
                              </td>
                              <td style={{ padding: "0.75rem 1rem" }}>
                                <span
                                  style={{
                                    fontSize: "0.7rem",
                                    border: "1px solid #d4d4d4",
                                    padding: "0.1rem 0.4rem",
                                    borderRadius: "3px",
                                    textTransform: "uppercase",
                                    backgroundColor: "#fafafa",
                                  }}
                                >
                                  {doc.documentType}
                                </span>
                              </td>
                              <td style={{ padding: "0.75rem 1rem", color: "#737373" }}>
                                {(doc.fileSize / 1024 / 1024).toFixed(2)} MB
                              </td>
                              <td style={{ padding: "0.75rem 1rem", color: "#737373" }}>
                                {new Date(doc.createdAt).toLocaleDateString()}
                              </td>
                              <td style={{ padding: "0.75rem 1rem" }}>
                                <span
                                  style={{
                                    fontSize: "0.7rem",
                                    color: doc.status === "indexed" ? "#000000" : "#737373",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "0.25rem",
                                  }}
                                >
                                  <span
                                    style={{
                                      width: "6px",
                                      height: "6px",
                                      borderRadius: "50%",
                                      backgroundColor:
                                        doc.status === "indexed" ? "#000000" : "#a3a3a3",
                                    }}
                                  />
                                  {doc.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── COMPLIANCE CENTER VIEW ─────────────────── */}
            {activeNav === "compliance" && (
              <div>
                <header style={{ marginBottom: "2rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Compliance Center
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Map plant operations against compliance requirements and regulatory standards.
                  </p>
                </header>

                {/* Act Toggle tabs */}
                <div
                  style={{
                    display: "flex",
                    gap: "0.5rem",
                    borderBottom: "1px solid #e5e5e5",
                    paddingBottom: "1rem",
                    marginBottom: "2rem",
                  }}
                >
                  {[...new Set(complianceRules.map((r) => r.regulationName))].map((act) => (
                    <button
                      key={act}
                      onClick={() => setComplianceFilter(act)}
                      style={{
                        padding: "0.5rem 1rem",
                        border: "1px solid #d4d4d4",
                        borderRadius: "4px",
                        backgroundColor: complianceFilter === act ? "#000000" : "transparent",
                        color: complianceFilter === act ? "#ffffff" : "#737373",
                        fontWeight: 700,
                        fontSize: "0.8rem",
                        cursor: "pointer",
                      }}
                    >
                      {act} checklist
                    </button>
                  ))}
                </div>

                {/* Checklist grid */}
                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "1rem",
                    }}
                  >
                    <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>
                      {complianceFilter} Requirements Mapping
                    </h3>
                    <button
                      onClick={fetchCompliance}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#737373",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "0.25rem",
                        fontSize: "0.8rem",
                      }}
                    >
                      <RefreshCw size={12} /> Sync Status
                    </button>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                    {complianceLoading ? (
                      <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                        Syncing compliance details...
                      </div>
                    ) : complianceRules.filter((r) => r.regulationName === complianceFilter)
                        .length === 0 ? (
                      <div style={{ padding: "2rem", textAlign: "center", color: "#737373" }}>
                        No mapped regulations found.
                      </div>
                    ) : (
                      complianceRules
                        .filter((r) => r.regulationName === complianceFilter)
                        .map((rule) => (
                          <div
                            key={rule.id}
                            style={{
                              border: "1px solid #e5e5e5",
                              borderRadius: "6px",
                              backgroundColor: "#fafafa",
                              padding: "1.25rem",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "flex-start",
                                marginBottom: "0.5rem",
                              }}
                            >
                              <div>
                                <span
                                  style={{
                                    fontFamily: "var(--font-mono)",
                                    fontSize: "0.8rem",
                                    fontWeight: 700,
                                    border: "1px solid #d4d4d4",
                                    padding: "0.1rem 0.4rem",
                                    borderRadius: "3px",
                                    textTransform: "uppercase",
                                    marginRight: "0.5rem",
                                    backgroundColor: "#ffffff",
                                  }}
                                >
                                  {rule.sectionReference}
                                </span>
                                <span style={{ fontSize: "0.75rem", color: "#737373" }}>
                                  Type: {rule.requirementType}
                                </span>
                              </div>

                              <button
                                onClick={() => toggleRuleStatus(rule.id, rule.complianceStatus)}
                                style={{
                                  padding: "0.2rem 0.6rem",
                                  borderRadius: "4px",
                                  fontSize: "0.75rem",
                                  fontWeight: 700,
                                  border: "1px solid #d4d4d4",
                                  backgroundColor:
                                    rule.complianceStatus === "compliant"
                                      ? "#000000"
                                      : "transparent",
                                  color:
                                    rule.complianceStatus === "compliant" ? "#ffffff" : "#737373",
                                  cursor: "pointer",
                                }}
                              >
                                {rule.complianceStatus === "compliant" ? "Compliant" : "Has Gaps"}
                              </button>
                            </div>
                            <p
                              style={{
                                fontSize: "0.85rem",
                                lineHeight: 1.4,
                                margin: "0 0 0.75rem 0",
                                color: "#000000",
                              }}
                            >
                              {rule.requirementText}
                            </p>
                            <div
                              style={{
                                fontSize: "0.75rem",
                                color: "#525252",
                                backgroundColor: "#ffffff",
                                padding: "0.5rem",
                                borderRadius: "4px",
                                border: "1px solid #e5e5e5",
                              }}
                            >
                              <strong>Audit Note:</strong>{" "}
                              {rule.notes || "No audit documentation linked."}
                            </div>
                          </div>
                        ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── MAINTENANCE INTEL VIEW ─────────────────── */}
            {activeNav === "maintenance" && (
              <div>
                <header style={{ marginBottom: "2rem" }}>
                  <h2
                    style={{
                      fontSize: "1.8rem",
                      fontWeight: 900,
                      margin: 0,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    Maintenance Intel
                  </h2>
                  <p style={{ fontSize: "0.85rem", color: "#737373", margin: 0 }}>
                    Assets, their issues and the actions taken, read from your uploaded documents.
                  </p>
                </header>

                <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
                  <DocumentFindings />
                  <div
                    style={{
                      border: "1px solid #e5e5e5",
                      borderRadius: "6px",
                      backgroundColor: "#fafafa",
                      padding: "1.5rem",
                    }}
                  >
                    <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>
                      Work orders
                    </h3>
                    <p style={{ color: "#737373", fontSize: "0.8rem", marginBottom: "1.25rem" }}>
                      Orders recorded through the API for this company.
                    </p>

                    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                      {maintenanceLoading ? (
                        <div
                          style={{
                            color: "#737373",
                            fontSize: "0.85rem",
                            textAlign: "center",
                            padding: "2rem",
                          }}
                        >
                          Loading work orders...
                        </div>
                      ) : maintenanceOrders.length === 0 ? (
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
                          No maintenance orders on file.
                        </div>
                      ) : (
                        maintenanceOrders.map((order) => (
                          <div
                            key={order.id}
                            style={{
                              border: "1px solid #e5e5e5",
                              padding: "1rem",
                              borderRadius: "4px",
                              backgroundColor: "#ffffff",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                marginBottom: "0.5rem",
                              }}
                            >
                              <span
                                style={{
                                  fontWeight: 700,
                                  fontSize: "0.85rem",
                                  fontFamily: "var(--font-mono)",
                                  color: "#000000",
                                }}
                              >
                                {order.orderNumber}
                              </span>
                              <span style={{ fontSize: "0.75rem", color: "#737373" }}>
                                {order.title}
                              </span>
                            </div>
                            <p
                              style={{
                                fontSize: "0.8rem",
                                color: "#525252",
                                margin: "0 0 0.5rem 0",
                              }}
                            >
                              {order.description}
                            </p>
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                fontSize: "0.7rem",
                                color: "#737373",
                                borderTop: "1px solid #e5e5e5",
                                paddingTop: "0.5rem",
                              }}
                            >
                              <span>
                                Target Tag:{" "}
                                <span
                                  style={{
                                    fontFamily: "var(--font-mono)",
                                    border: "1px solid #d4d4d4",
                                    padding: "0.05rem 0.25rem",
                                    borderRadius: "2px",
                                    fontSize: "0.65rem",
                                    color: "#000000",
                                    backgroundColor: "#fafafa",
                                  }}
                                >
                                  {order.equipmentTag}
                                </span>
                              </span>
                              <span>
                                Status:{" "}
                                <span style={{ textTransform: "capitalize", fontWeight: 600 }}>
                                  {order.status.replace("_", " ")}
                                </span>
                              </span>
                            </div>
                            {order.tolerances && Object.keys(order.tolerances).length > 0 && (
                              <div
                                style={{
                                  marginTop: "0.5rem",
                                  padding: "0.4rem",
                                  backgroundColor: "#fafafa",
                                  borderRadius: "3px",
                                  fontSize: "0.7rem",
                                  color: "#525252",
                                  display: "flex",
                                  gap: "1rem",
                                  border: "1px solid #e5e5e5",
                                }}
                              >
                                <strong>Extracted Parameters:</strong>
                                {Object.entries(order.tolerances).map(([k, v]: any) => (
                                  <span key={k}>
                                    {k}: {v}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
