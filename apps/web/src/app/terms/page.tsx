"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { motion } from "framer-motion";

export default function TermsPage() {
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
            Terms & Conditions
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
                1. Acceptance of Terms
              </h2>
              <p>
                By registering an account and provisioning an enterprise partition on VEDA AI
                (&quot;the Platform&quot;), you agree to be bound by these Terms and Conditions.
                These terms govern the relationship between VEDA AI and your corporate entity
                (&quot;Tenant&quot;).
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
                2. Tenant Isolation & Access Control
              </h2>
              <p>
                VEDA AI utilizes strict Row-Level Security (RLS) and schema isolation to partition
                operational data. The Tenant is solely responsible for:
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
                <li>Maintaining the confidentiality of admin and operator credentials.</li>
                <li>
                  Appointing authorized users and configuring appropriate Role-Based Access Controls
                  (RBAC).
                </li>
                <li>
                  Ensuring all ingested plant documentation, SOPs, and work orders comply with
                  active statutory regulations.
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
                3. Data Protection & Regulatory Compliance
              </h2>
              <p>
                In alignment with applicable data protection regulations and industry security
                standards:
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
                  <strong>Data Ownership:</strong> The Tenant retains sole ownership of all uploaded
                  materials and operational logs.
                </li>
                <li>
                  <strong>Security Safeguards:</strong> VEDA AI implements robust technical
                  safeguards, including data encryption in transit and at rest.
                </li>
                <li>
                  <strong>Audit Controls:</strong> Access and processing streams are logged
                  dynamically to support fiduciary compliance reporting.
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
                4. Service Availability & SLA
              </h2>
              <p>
                While VEDA AI strives to maintain continuous uptime of the ingestion pipeline and
                knowledge graph queries, operational performance is subject to database capacity
                configurations. Scheduled maintenance windows will be communicated to Tenant
                administrators in advance.
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
                5. Limitation of Liability
              </h2>
              <p>
                VEDA AI shall not be liable for operational disruptions, predictive maintenance
                prediction variations, or compliance gaps resulting from incomplete document
                ingestion, corrupted PDF schemas, or unauthorized user credential disclosures.
              </p>
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
