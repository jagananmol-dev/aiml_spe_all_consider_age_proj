import type { LucideIcon } from "lucide-react";

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  tag: string;
}

export function FeatureCard({ icon: Icon, title, description, tag }: FeatureCardProps) {
  return (
    <article className="card feature-card">
      <div className="card-icon" aria-hidden="true">
        <Icon size={20} />
      </div>
      <p className="card-tag">{tag}</p>
      <h3>{title}</h3>
      <p>{description}</p>
    </article>
  );
}
