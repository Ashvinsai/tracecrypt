import type { CSSProperties } from "react";

/** Shared inline control styling. Kept in one place so pages do not re-declare it. */
export const inputStyle: CSSProperties = {
  font: "inherit",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius)",
  padding: "6px 9px",
};

export const selectStyle: CSSProperties = { ...inputStyle, padding: "5px 8px" };
