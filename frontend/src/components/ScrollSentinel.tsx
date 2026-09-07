import { useEffect, useRef } from "react";

// A 1px sentinel that calls onVisible when it scrolls into view (200px early),
// used to trigger the next page in infinite-scroll lists. Render it only while
// there is another page to load and no fetch is in flight, so it can't fire
// repeatedly for the same page.
export default function ScrollSentinel({ onVisible }: { onVisible: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) onVisible();
    }, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [onVisible]);
  return <div ref={ref} style={{ height: 1 }} aria-hidden="true" />;
}
