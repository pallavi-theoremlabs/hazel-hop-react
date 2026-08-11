import React from "react";

export default function Card({ title, subtitle, className = '', children }) {
  return (
    <section className={`card ${className}`.trim()}>
      {title && <h2>{title}</h2>}
      {subtitle && <p className="sub">{subtitle}</p>}
      {children}
    </section>
  )
}
