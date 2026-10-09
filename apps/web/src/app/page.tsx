"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Brain } from "lucide-react";
import { FeatureCard } from "@/components/landing/FeatureCard";
import { landingContent } from "@/lib/content/landing";

export default function LandingPage() {
  return (
    <div className="landing-shell">
      <header className="landing-header">
        <Link href="/" className="brand-mark" aria-label="VEDA AI home">
          <div className="brand-icon">
            <Brain size={20} />
          </div>
          <div>
            <h1>VEDA AI</h1>
            <p>Knowledge Intelligence</p>
          </div>
        </Link>

        <nav className="landing-nav" aria-label="Primary navigation">
          <Link href="/login">Log In</Link>
          <Link href="/register" className="button button-dark">
            Sign Up
          </Link>
        </nav>
      </header>

      <main className="landing-main">
        <motion.section
          className="hero-panel"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <span className="hero-eyebrow">{landingContent.hero.eyebrow}</span>
          <h2>{landingContent.hero.title}</h2>
          <p>{landingContent.hero.description}</p>

          <div className="hero-actions">
            <Link href={landingContent.hero.primaryCta.href} className="button button-dark">
              {landingContent.hero.primaryCta.label} <ArrowRight size={16} />
            </Link>
            <Link href={landingContent.hero.secondaryCta.href} className="button button-light">
              {landingContent.hero.secondaryCta.label}
            </Link>
          </div>
        </motion.section>

        <section className="features-grid" aria-label="Platform capabilities">
          {landingContent.features.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.08 * index }}
            >
              <FeatureCard
                icon={feature.icon}
                title={feature.title}
                description={feature.description}
                tag={feature.tag}
              />
            </motion.div>
          ))}
        </section>
      </main>

      <footer className="landing-footer">
        <div className="footer-links">
          <Link href="/terms">Terms & Conditions</Link>
          <Link href="/privacy">Privacy Policy</Link>
        </div>
        <p>{landingContent.footer.badge}</p>
        <p>{landingContent.footer.cta}</p>
      </footer>
    </div>
  );
}
