"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { motion } from "framer-motion";

export default function PrivacyPage() {
  return (
    <div
      style={{
        backgroundColor: "#ffffff",
        color: "#000000",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        padding: "2rem",
      }}
    >
      <header style={{ maxWidth: "800px", margin: "0 auto", width: "100%", marginBottom: "3rem" }}>
        <Link
          href="/"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            fontSize: "0.85rem",
            color: "#737373",
            textDecoration: "none",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "#000000")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "#737373")}
        >
          <ArrowLeft size={16} /> Back to home
        </Link>
      </header>

      <main style={{ flex: 1, maxWidth: "800px", margin: "0 auto", width: "100%" }}>
        <motion.article
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <h1
            style={{
              fontSize: "2.5rem",
              fontWeight: 900,
              letterSpacing: "-0.03em",
              marginBottom: "0.5rem",
              color: "#000000",
            }}
          >
            Privacy Policy
          </h1>
          <p style={{ fontSize: "0.85rem", color: "#737373", marginBottom: "2.5rem" }}>
            Last Updated: July 3, 2026
          </p>

          <section
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "2rem",
              fontSize: "0.95rem",
              lineHeight: 1.6,
              color: "#262626",
            }}
          >
            <div>
              <h2
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "#000000",
                  marginBottom: "0.75rem",
                }}
              >
                1. Information Collected
              </h2>
              <p>
                VEDA AI processes operational plant files, technical schematics, and work orders
                solely on behalf of the registered Tenant. Personal data collected is limited to:
              </p>
              <ul
                style={{
                  paddingLeft: "1.25rem",
                  marginTop: "0.5rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <li>
                  <strong>Account Credentials:</strong> Full name, email address, corporate
                  association, and password hashes for user account provisioning.
                </li>
                <li>
                  <strong>Audit Trails:</strong> IP addresses, request timestamps, and processing
                  logs logged dynamically to maintain secure operational integrity.
                </li>
              </ul>
            </div>

            <div>
              <h2
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "#000000",
                  marginBottom: "0.75rem",
                }}
              >
                2. Data Isolation & Sub-processing
              </h2>
              <p>
                All data is isolated logically by tenant UUIDs mapped through row-level database
                structures. VEDA AI does not sell, lease, or distribute operational datasets or user
                email records. Metadata and processing logs are used strictly to maintain network
                and database functionality.
              </p>
            </div>

            <div>
              <h2
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "#000000",
                  marginBottom: "0.75rem",
                }}
              >
                3. Regulatory Compliance
              </h2>
              <p>
                VEDA AI is designed to support alignment with applicable data protection and
                industry-specific regulations in the jurisdictions where the Tenant operates:
              </p>
              <ul
                style={{
                  paddingLeft: "1.25rem",
                  marginTop: "0.5rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <li>
                  <strong>Erasure & Deletion:</strong> Upon tenant account cancellation or document
                  deletion requests, personal user records are permanently deleted from database
                  tables.
                </li>
                <li>
                  <strong>Accuracy Safeguards:</strong> Ingested operator files are checked for
                  consistency during normalized indexing.
                </li>
              </ul>
            </div>

            <div>
              <h2
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "#000000",
                  marginBottom: "0.75rem",
                }}
              >
                4. Security Controls
              </h2>
              <p>To support data security and access governance requirements:</p>
              <ul
                style={{
                  paddingLeft: "1.25rem",
                  marginTop: "0.5rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <li>
                  <strong>RBAC Restrictions:</strong> Viewer permissions isolate standard
                  operational users from modifying sensitive data logs.
                </li>
                <li>
                  <strong>Audit Logs:</strong> Detailed action tracks are recorded in the PostgreSQL
                  audit log tables and are non-volatile.
                </li>
              </ul>
            </div>
          </section>
        </motion.article>
      </main>

      <footer
        style={{
          borderTop: "1px solid rgba(0, 0, 0, 0.08)",
          padding: "2rem 0",
          textAlign: "center",
          fontSize: "0.8rem",
          color: "#a3a3a3",
          marginTop: "4rem",
        }}
      >
        &copy; {new Date().getFullYear()} VEDA AI. All rights reserved. Grayscale edition.
      </footer>
    </div>
  );
}
