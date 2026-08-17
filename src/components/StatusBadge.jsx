import React from "react";

export default function StatusBadge({ tone = 'info', children }) {
  return <span className={`status ${tone}`}>{children}</span>
}
