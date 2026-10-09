"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Brain, ArrowLeft, ShieldAlert, CheckCircle2 } from "lucide-react";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [formData, setFormData] = useState({
    tenantSlug: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const tenant = searchParams.get("tenant");
    const registered = searchParams.get("registered");
    if (tenant) {
      setFormData((prev) => ({ ...prev, tenantSlug: tenant }));
    }
    if (registered) {
      setSuccess("Tenant created successfully! Please sign in below.");
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Authentication failed");
      }

      // Successful login — redirect to dashboard
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
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
            textDecoration: "none",
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
          Log In
        </h2>
        <p style={{ fontSize: "0.8rem", color: "#737373", margin: 0, textAlign: "center" }}>
          Access your operational partition
        </p>
      </div>

      {success && (
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            alignItems: "center",
            backgroundColor: "#f0fdf4",
            border: "1px solid #bbf7d0",
            padding: "0.75rem",
            borderRadius: "4px",
            marginBottom: "1.5rem",
            color: "#166534",
            fontSize: "0.85rem",
          }}
        >
          <CheckCircle2 size={16} />
          <span>{success}</span>
        </div>
      )}

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
            Tenant Slug
          </label>
          <input
            type="text"
            required
            placeholder="Your tenant slug"
            value={formData.tenantSlug}
            onChange={(e) => setFormData({ ...formData, tenantSlug: e.target.value.toLowerCase() })}
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
            Email Address
          </label>
          <input
            type="email"
            required
            placeholder="you@company.com"
            value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
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
            Password
          </label>
          <input
            type="password"
            required
            placeholder="••••••••"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
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
          {loading ? "Authenticating..." : "Log In"}
        </button>
      </form>

      <div
        style={{ textAlign: "center", marginTop: "1.5rem", fontSize: "0.85rem", color: "#737373" }}
      >
        Don&apos;t have a tenant?{" "}
        <Link href="/register" style={{ color: "#000000", fontWeight: 600 }}>
          Sign Up
        </Link>
      </div>
    </motion.div>
  );
}

export default function LoginPage() {
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

      <Suspense fallback={<div style={{ color: "#737373" }}>Loading...</div>}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
