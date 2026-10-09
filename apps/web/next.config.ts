import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(__dirname, "../.."),
  // Enable React Server Components (default in Next.js 15)
  reactStrictMode: true,

  // Experimental features
  experimental: {
    // Server Actions for form handling
    serverActions: {
      bodySizeLimit: "50mb", // Allow large file uploads
    },
    // Optimize package imports
    optimizePackageImports: [
      "lucide-react",
      "recharts",
      "framer-motion",
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
    ],
  },

  // Image optimization
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.veda-ai.com",
      },
      {
        // MinIO local development
        protocol: "http",
        hostname: "localhost",
        port: "9000",
      },
    ],
  },

  // Headers for security
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
      {
        // The document viewer embeds PDFs from this route on our own pages.
        // Listed after the global rule so these values win for this path.
        source: "/api/documents/:id/file",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
        ],
      },
    ];
  },

  // Webpack customization for specific packages
  webpack: (config) => {
    // Handle Three.js and force-graph
    config.externals = [...(config.externals || []), { canvas: "canvas" }];
    return config;
  },
};

export default nextConfig;
