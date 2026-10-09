import { Network, Shield, FileText, Database } from "lucide-react";

export const landingContent = {
  hero: {
    eyebrow: "Enterprise Knowledge Intelligence",
    title: "The industrial brain that never forgets.",
    description:
      "Unify SOPs, maintenance history, engineering documents, and operational signals into one governed AI-native workspace.",
    primaryCta: { label: "Launch Platform", href: "/register" },
    secondaryCta: { label: "View Security", href: "/privacy" },
  },
  features: [
    {
      icon: Network,
      tag: "Graph intelligence",
      title: "Context-aware retrieval",
      description:
        "Combine semantic search with explicit dependency mapping for maintenance, operations, and safety workflows.",
    },
    {
      icon: Shield,
      tag: "Enterprise governance",
      title: "Controls by design",
      description:
        "Role-based access, immutable audit trails, and policy-enforced data handling across every workflow.",
    },
    {
      icon: FileText,
      tag: "Document intelligence",
      title: "Structured knowledge extraction",
      description:
        "Turn manuals, procedures, and inspection reports into normalized, searchable knowledge assets.",
    },
    {
      icon: Database,
      tag: "Operational resilience",
      title: "Reliable execution at scale",
      description:
        "Designed for high-throughput environments with observability, caching, and durable processing pipelines.",
    },
  ],
  footer: {
    badge: "Built for industrial-grade reliability",
    cta: "Accelerate critical decisions with AI-native operations.",
  },
};
