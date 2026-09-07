/**
 * TopicTagInput — shared autocomplete tag input for the Content Library (US-2.26).
 *
 * mode='multi'  : multi-tag add with chips (used in Add/Edit Resource modals)
 * mode='single' : single-value filter (used in the Library search bar)
 *
 * Tags are fetched from GET /library/tags?prefix=<input> with 300ms debounce.
 */
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";

interface TopicTagInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  mode: "multi" | "single";
  placeholder?: string;
  disabled?: boolean;
}

export default function TopicTagInput({
  value,
  onChange,
  mode,
  placeholder = "Add topic…",
  disabled = false,
}: TopicTagInputProps) {
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch suggestions on input change (debounced 300ms, min 2 chars)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = input.trim().toLowerCase();
    if (trimmed.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await apiFetch<{ tags: string[] }>(
          `/library/tags?prefix=${encodeURIComponent(trimmed)}`
        );
        setSuggestions(res.tags || []);
        setShowSuggestions(true);
      } catch {
        setSuggestions([]);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [input]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const addTag = (tag: string) => {
    const normalized = tag.trim().toLowerCase();
    if (!normalized) return;
    if (mode === "single") {
      onChange([normalized]);
      setInput(normalized);
    } else {
      if (!value.includes(normalized) && value.length < 20) {
        onChange([...value, normalized]);
      }
      setInput("");
    }
    setSuggestions([]);
    setShowSuggestions(false);
  };

  const removeTag = (tag: string) => {
    onChange(value.filter((t) => t !== tag));
    if (mode === "single") setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      addTag(input.trim());
    }
    if (e.key === "Backspace" && !input && value.length > 0 && mode === "multi") {
      onChange(value.slice(0, -1));
    }
  };

  const displayInput = mode === "single" && value.length > 0 ? value[0] : input;

  return (
    <div ref={containerRef} style={{ position: "relative" }} data-testid="topic-tag-input">
      {/* Chips row (multi mode) */}
      {mode === "multi" && value.length > 0 && (
        <div className="flex wrap" style={{ gap: 4, marginBottom: 4 }}>
          {value.map((tag) => (
            <span
              key={tag}
              className="badge gray"
              style={{ display: "flex", alignItems: "center", gap: 4 }}
              data-testid={`topic-chip-${tag}`}
            >
              {tag}
              {!disabled && (
                <button
                  type="button"
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1 }}
                  data-testid={`topic-chip-remove-${tag}`}
                  onClick={() => removeTag(tag)}
                  aria-label={`Remove tag ${tag}`}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Single mode — show current value as clearable chip */}
      {mode === "single" && value.length > 0 && (
        <div className="flex" style={{ gap: 4, marginBottom: 4 }}>
          <span className="badge primary" style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {value[0]}
            <button
              type="button"
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
              onClick={() => { onChange([]); setInput(""); }}
              aria-label="Clear topic filter"
            >
              ×
            </button>
          </span>
        </div>
      )}

      {/* Text input (hidden in single mode once a value is selected) */}
      {(mode === "multi" || value.length === 0) && (
        <input
          className="input"
          style={{ width: "100%" }}
          type="text"
          placeholder={placeholder}
          value={mode === "single" ? displayInput : input}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          aria-label="Topic tag input"
        />
      )}

      {/* Autocomplete dropdown */}
      {showSuggestions && suggestions.length > 0 && (
        <ul
          style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 100,
            background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 6, margin: 0, padding: 0, listStyle: "none",
            boxShadow: "var(--shadow)", maxHeight: 200, overflowY: "auto",
          }}
        >
          {suggestions.map((s) => (
            <li
              key={s}
              style={{ padding: "8px 12px", cursor: "pointer" }}
              data-testid={`topic-suggestion-${s}`}
              onMouseDown={(e) => { e.preventDefault(); addTag(s); }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
