/**
 * useTheme — persists "light" | "dark" to localStorage and applies
 * body.dark class. Call once at app root; anywhere else just reads
 * the value for display.
 */
import { useEffect, useState } from "react";

const STORAGE_KEY = "theme";
type Theme = "light" | "dark";

function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    // Private browsing / storage blocked
  }
  return "dark"; // default theme — applied when no preference has been saved
}

function applyTheme(theme: Theme) {
  if (theme === "dark") {
    document.body.classList.add("dark");
  } else {
    document.body.classList.remove("dark");
  }
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);

  // Apply on mount and whenever theme changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = (t: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch {
      // ignore
    }
    setThemeState(t);
    applyTheme(t);
  };

  return [theme, setTheme];
}
