"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Brain, ArrowLeft, ShieldAlert } from "lucide-react";

export default function RegisterPage() {
  const router = useRouter();
  const [formData, setFormData] = useState({
    companyName: "",
    tenantSlug: "",
    name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);

  // Validate email format using RFC 5322 simplified regex
  const isValidEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim());

  const validate = () => {
    const errors: Record<string, string> = {};
    if (!formData.companyName.trim()) errors.companyName = "Company name is required";
    if (formData.tenantSlug.trim().length < 3)
      errors.tenantSlug = "Slug must be at least 3 characters";
    if (!formData.name.trim()) errors.name = "Admin name is required";
    if (!formData.email.trim()) {
      errors.email = "Email address is required";
    } else if (!isValidEmail(formData.email)) {
      errors.email = "Enter a valid email address (e.g. name@company.com)";
    }
    if (!acceptedTerms) {
      errors.terms = "You must accept the Terms & Conditions";
    }
    if (formData.password.length < 8) errors.password = "Password must be at least 8 characters";
    return errors;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // Run client-side validation first
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    setLoading(true);

    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Registration failed");
      }

      // Successful registration — redirect to login
      router.push(`/login?tenant=${formData.tenantSlug}&registered=true`);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        backgroundColor: "#f5f5f5",
        color: "#000000",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        justifyItems: "center",
        justifyContent: "center",
        alignItems: "center",
        padding: "2rem",
      }}
    >
      <div style={{ position: "absolute", top: "2rem", left: "2rem" }}>
        <Link
          href="/"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            fontSize: "0.85rem",
            color: "#737373",
          }}
        >
          <ArrowLeft size={16} /> Back to home
        </Link>
      </div>

      <motion.div
        style={{
          width: "100%",
          maxWidth: "420px",
          border: "1px solid #e5e5e5",
          padding: "2.5rem",
          borderRadius: "8px",
          backgroundColor: "#ffffff",
          boxShadow: "0 4px 6px -1px rgba(0,0,0,0.07)",
        }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "0.75rem",
            marginBottom: "2rem",
          }}
        >
          <Link
            href="/"
            style={{
              width: "40px",
              height: "40px",
              border: "1.5px solid #000000",
              borderRadius: "4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
            }}
          >
            <Brain size={22} color="#000000" />
          </Link>
          <h2
            style={{
              fontSize: "1.5rem",
              fontWeight: 900,
              letterSpacing: "-0.03em",
              margin: 0,
              color: "#000000",
            }}
          >
            Register Tenant
          </h2>
          <p style={{ fontSize: "0.8rem", color: "#737373", margin: 0, textAlign: "center" }}>
            Provision your enterprise partition
          </p>
        </div>

        {error && (
          <div
            style={{
              display: "flex",
              gap: "0.5rem",
              alignItems: "center",
              backgroundColor: "#fef2f2",
              border: "1px solid #fecaca",
              padding: "0.75rem",
              borderRadius: "4px",
              marginBottom: "1.5rem",
              color: "#991b1b",
              fontSize: "0.85rem",
            }}
          >
            <ShieldAlert size={16} />
            <span>{error}</span>
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}
        >
          <div>
            <label
              style={{
                display: "block",
                fontSize: "0.75rem",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#737373",
                marginBottom: "0.5rem",
              }}
            >
              Company Name
            </label>
            <input
              type="text"
              required
              placeholder="Your company name"
              value={formData.companyName}
              onChange={(e) => setFormData({ ...formData, companyName: e.target.value })}
              style={{
                width: "100%",
                padding: "0.6rem 0.8rem",
                backgroundColor: "#fafafa",
                border: "1px solid #d4d4d4",
                borderRadius: "4px",
                color: "#000000",
                fontSize: "0.9rem",
              }}
            />
          </div>

          <div>
            <label
              style={{
                display: "block",
                fontSize: "0.75rem",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#737373",
                marginBottom: "0.5rem",
              }}
            >
              Subdomain / Tenant Slug
            </label>
            <input
              type="text"
              required
              placeholder="your-company"
              value={formData.tenantSlug}
              onChange={(e) => {
                setFormData({
                  ...formData,
                  tenantSlug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""),
                });
                if (fieldErrors.tenantSlug) setFieldErrors((prev) => ({ ...prev, tenantSlug: "" }));
              }}
              style={{
                width: "100%",
                padding: "0.6rem 0.8rem",
                backgroundColor: "#fafafa",
                border: `1px solid ${fieldErrors.tenantSlug ? "#991b1b" : "#d4d4d4"}`,
                borderRadius: "4px",
                color: "#000000",
                fontSize: "0.9rem",
              }}
            />
            {fieldErrors.tenantSlug ? (
              <p style={{ fontSize: "0.7rem", color: "#991b1b", marginTop: "0.25rem" }}>
                {fieldErrors.tenantSlug}
              </p>
            ) : (
              <p style={{ fontSize: "0.7rem", color: "#737373", marginTop: "0.25rem" }}>
                Will be used as your URL context
              </p>
            )}
          </div>

          <div>
            <label
              style={{
                display: "block",
                fontSize: "0.75rem",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#737373",
                marginBottom: "0.5rem",
              }}
            >
              Admin Name
            </label>
            <input
              type="text"
              required
              placeholder="Full name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              style={{
                width: "100%",
                padding: "0.6rem 0.8rem",
                backgroundColor: "#fafafa",
                border: "1px solid #d4d4d4",
                borderRadius: "4px",
                color: "#000000",
                fontSize: "0.9rem",
              }}
            />
          </div>

          <div>
            <label
              style={{
                display: "block",
                fontSize: "0.75rem",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#737373",
                marginBottom: "0.5rem",
              }}
            >
              Admin Email
            </label>
            <input
              type="email"
              required
              placeholder="you@company.com"
              value={formData.email}
              onChange={(e) => {
                setFormData({ ...formData, email: e.target.value });
                if (fieldErrors.email) setFieldErrors((prev) => ({ ...prev, email: "" }));
              }}
              onBlur={(e) => {
                if (
                  e.target.value &&
                  !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e.target.value.trim())
                ) {
                  setFieldErrors((prev) => ({
                    ...prev,
                    email: "Enter a valid email address (e.g. name@company.com)",
                  }));
                }
              }}
              style={{
                width: "100%",
                padding: "0.6rem 0.8rem",
                backgroundColor: "#fafafa",
                border: `1px solid ${fieldErrors.email ? "#991b1b" : "#d4d4d4"}`,
                borderRadius: "4px",
                color: "#000000",
                fontSize: "0.9rem",
              }}
            />
            {fieldErrors.email && (
              <p style={{ fontSize: "0.7rem", color: "#991b1b", marginTop: "0.25rem" }}>
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div>
            <label
              style={{
                display: "block",
                fontSize: "0.75rem",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#737373",
                marginBottom: "0.5rem",
              }}
            >
              Password
            </label>
            <input
              type="password"
              required
              placeholder="min. 8 characters"
              value={formData.password}
              onChange={(e) => {
                setFormData({ ...formData, password: e.target.value });
                if (fieldErrors.password) setFieldErrors((prev) => ({ ...prev, password: "" }));
              }}
              style={{
                width: "100%",
                padding: "0.6rem 0.8rem",
                backgroundColor: "#fafafa",
                border: `1px solid ${fieldErrors.password ? "#991b1b" : "#d4d4d4"}`,
                borderRadius: "4px",
                color: "#000000",
                fontSize: "0.9rem",
              }}
            />
            {fieldErrors.password && (
              <p style={{ fontSize: "0.7rem", color: "#991b1b", marginTop: "0.25rem" }}>
                {fieldErrors.password}
              </p>
            )}
          </div>

          {/* Terms & Conditions checkbox */}
          <div style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem" }}>
            <input
              type="checkbox"
              id="accept-terms"
              checked={acceptedTerms}
              onChange={(e) => {
                setAcceptedTerms(e.target.checked);
                if (fieldErrors.terms) setFieldErrors((prev) => ({ ...prev, terms: "" }));
              }}
              style={{ marginTop: "0.2rem", accentColor: "#000000" }}
            />
            <label
              htmlFor="accept-terms"
              style={{ fontSize: "0.8rem", color: "#737373", lineHeight: 1.4 }}
            >
              I agree to the{" "}
              <Link href="/terms" target="_blank" style={{ color: "#000000", fontWeight: 600 }}>
                Terms & Conditions
              </Link>{" "}
              and{" "}
              <Link href="/privacy" target="_blank" style={{ color: "#000000", fontWeight: 600 }}>
                Privacy Policy
              </Link>
            </label>
          </div>
          {fieldErrors.terms && (
            <p style={{ fontSize: "0.7rem", color: "#991b1b", marginTop: "-0.5rem" }}>
              {fieldErrors.terms}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "0.75rem",
              backgroundColor: "#000000",
              color: "#ffffff",
              border: "none",
              borderRadius: "4px",
              fontWeight: 700,
              cursor: "pointer",
              transition: "opacity 0.2s",
              marginTop: "0.5rem",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.8")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            {loading ? "Registering..." : "Create Tenant"}
          </button>
        </form>

        <div
          style={{
            textAlign: "center",
            marginTop: "1.5rem",
            fontSize: "0.85rem",
            color: "#737373",
          }}
        >
          Already have a tenant?{" "}
          <Link href="/login" style={{ color: "#000000", fontWeight: 600 }}>
            Log In
          </Link>
        </div>
      </motion.div>
    </div>
  );
}
