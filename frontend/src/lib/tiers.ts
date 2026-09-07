// Quarterly tier presentation. The design system defines .tier.gold/.silver/
// .bronze/.rising chips (see portal.css) and the mockups pair each with a medal
// glyph, so keep the class + glyph mapping in one place rather than per page.
const TIER_META: Record<string, { cls: string; icon: string }> = {
  gold: { cls: "tier gold", icon: "🥇" },
  silver: { cls: "tier silver", icon: "🥈" },
  bronze: { cls: "tier bronze", icon: "🥉" },
  rising: { cls: "tier rising", icon: "🌱" },
};

const meta = (tier?: string | null) => TIER_META[(tier ?? "").trim().toLowerCase()];

/** Chip class for a tier name; falls back to the neutral chip for unknown tiers. */
export function tierClass(tier?: string | null): string {
  return meta(tier)?.cls ?? "tier";
}

/** Medal glyph for a tier name, or "" when the tier isn't one of the known four. */
export function tierIcon(tier?: string | null): string {
  return meta(tier)?.icon ?? "";
}
