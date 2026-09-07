// Avatar that prefers the member's uploaded/linked image (profile `avatar`
// field, US-3.2) and falls back to initials, which is all the mockups show.
// Sizes map to the .avatar/.sm/.lg/.xl variants in portal.css.
export default function Avatar(props: {
  firstName?: string;
  lastName?: string;
  src?: string | null;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  style?: React.CSSProperties;
}) {
  const { firstName = "", lastName = "", src, size = "md" } = props;
  const initials = ((firstName[0] ?? "") + (lastName[0] ?? "")).toUpperCase() || "?";
  const cls = ["avatar", size === "md" ? "" : size, props.className ?? ""].filter(Boolean).join(" ");
  const alt = `${firstName} ${lastName}`.trim() || "Member avatar";
  if (src) {
    return <img className={cls} src={src} alt={alt} style={{ objectFit: "cover", ...props.style }} />;
  }
  return <div className={cls} aria-label={alt} style={props.style}>{initials}</div>;
}
