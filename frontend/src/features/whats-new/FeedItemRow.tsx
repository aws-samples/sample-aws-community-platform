import { useMemo, useState } from "react";
import parse from "html-react-parser";
import { sanitizeFeedHtml } from "./sanitize";
import type { FeedItem } from "./types";

/**
 * One collapsible feed card (US-11.3 list row, US-11.5 inline expand).
 *
 * Collapsed: service icon bubble, title, summary, date, color-coded category badges.
 * Expanded: sanitized full <description> in a tinted reading pane (DW-3/DV-1),
 *           plus the "Read full announcement on AWS ↗" action button.
 *
 * The header is a real <button> so the row is keyboard-operable and announces
 * its expanded state. CSS max-height transition provides the slide-down animation.
 * Domain color is derived from the first recognized category and applied via a
 * data-domain attribute so portal.css rules handle all the color variations in
 * one place.
 */

function formatDate(date: Date | null): string {
  if (!date) return "Date not provided";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/**
 * Maps a category label to a domain key used by CSS for accent colors.
 * Checked in order; the first match wins. Items with no matching category
 * fall back to the default (primary-blue) styling.
 */
const DOMAIN_RULES: Array<{ pattern: RegExp; domain: string }> = [
  { pattern: /\bML\b|machine.learn|artificial.intel|bedrock|sagemaker|rekognition|comprehend|lex\b|polly|transcribe|textract|kendra|forecast|personalize/i, domain: "ml" },
  { pattern: /security|identity|compliance|iam|cognito|kms|secrets|inspector|guardduty|macie|shield|waf|acm|detective/i, domain: "security" },
  { pattern: /database|dynamodb|rds|aurora|redshift|elasticache|neptune|keyspaces|timestream|documentdb/i, domain: "database" },
  { pattern: /serverless|lambda|fargate|eventbridge|step.function|api.gateway|sqs|sns|ses/i, domain: "serverless" },
  { pattern: /storage|s3\b|efs|ebs|fsx|backup|datasync|storage.gateway/i, domain: "storage" },
  { pattern: /network|cloudfront|route.53|vpc|direct.connect|transit.gateway|global.accelerator|load.balanc/i, domain: "network" },
  { pattern: /compute|ec2\b|ecs|eks|elastic.beanstalk|batch|lightsail|outposts|wavelength/i, domain: "compute" },
];

function deriveDomain(categories: string[]): string {
  const text = categories.join(" ");
  for (const rule of DOMAIN_RULES) {
    if (rule.pattern.test(text)) return rule.domain;
  }
  return "default";
}

/** Domain → emoji icon shown in the service bubble. */
const DOMAIN_ICON: Record<string, string> = {
  compute:    "⚡",
  storage:    "🪣",
  database:   "🗄️",
  security:   "🔐",
  ml:         "🤖",
  network:    "🌐",
  serverless: "λ",
  identity:   "🔐",
  default:    "☁️",
};

export default function FeedItemRow({ item }: { item: FeedItem }) {
  const [open, setOpen] = useState(false);
  const domain = useMemo(() => deriveDomain(item.categories), [item.categories]);

  // Sanitize only once the row is actually expanded, and memoize so toggling
  // does not re-run DOMPurify over a multi-KB body on every render.
  const safeHtml = useMemo(
    () => (open ? sanitizeFeedHtml(item.detailsHtml) : ""),
    [open, item.detailsHtml],
  );

  // Render the SANITIZED markup as React elements rather than injecting it with
  // dangerouslySetInnerHTML (bosco/react-dangerouslysetinnerhtml). html-react-parser
  // turns the already-sanitized string into an element tree — no HTML string ever
  // reaches the DOM through an innerHTML sink, so the finding is eliminated at the
  // source. This does NOT relax the security posture: sanitizeFeedHtml (DOMPurify
  // with an explicit allow-list) still runs first and is the only thing parsed;
  // the raw feed body is never handed to the parser. The allow-list emits no
  // `class`/`style`, so there are no attribute-mapping surprises and the rendered
  // DOM — hence the look and feel under the same CSS — is unchanged.
  const parsedBody = useMemo(() => (safeHtml ? parse(safeHtml) : null), [safeHtml]);

  return (
    <li
      className={`wn-card${open ? " is-open" : ""}`}
      data-domain={domain}
      data-testid="wn-item"
    >
      <div className="wn-card-inner">
        {/* Left accent bar — color driven by data-domain via CSS */}
        <div className="wn-card-accent" aria-hidden="true" />

        <div className="wn-card-body">
          {/* Clickable header row */}
          <button
            type="button"
            className="wn-card-head"
            data-testid="wn-item-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {/* Service icon bubble */}
            <div className="wn-svc-icon" aria-hidden="true">
              {DOMAIN_ICON[domain] ?? "☁️"}
            </div>

            <div className="wn-card-main">
              <span className="wn-card-title">{item.title}</span>
              {!open && item.summary && (
                <span className="wn-card-summary">{item.summary}</span>
              )}
              <div className="wn-card-meta">
                <span className="wn-card-date">{formatDate(item.pubDate)}</span>
                {item.categories.map((c) => (
                  <span
                    key={c}
                    className={`wn-badge domain-${domain}`}
                    data-testid="wn-item-category"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </div>

            {/* Rotating chevron */}
            <div className="wn-toggle-icon" aria-hidden="true">▼</div>
          </button>

          {/* Animated slide-down expand — CSS max-height transition */}
          <div className="wn-card-expand" data-testid="wn-item-details">
            <div className="wn-card-detail">
              <div className="wn-card-detail-html">
                {parsedBody
                  ? <div>{parsedBody}</div>
                  : open && (
                    <p className="faint small mb-0">
                      No further details were provided for this announcement.
                    </p>
                  )}
              </div>
              {item.link && (
                <a
                  className="wn-read-more"
                  data-testid="wn-item-external-link"
                  href={item.link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Read full announcement on AWS <span aria-hidden="true">↗</span>
                </a>
              )}
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}
