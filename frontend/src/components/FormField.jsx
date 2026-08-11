import React from "react";

export default function FormField({ label, hint, required, as = 'input', options = [], className = '', ...props }) {
  const Control = as
  return (
    <div className={`field ${className}`.trim()}>
      <label htmlFor={props.id}>{label}{required && <span className="required"> *</span>}</label>
      {as === 'select' ? (
        <select className="input" {...props} required={required}>
          <option value="">Select</option>
          {options.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      ) : (
        <Control className="input" {...props} required={required} />
      )}
      {hint && <p className="hint">{hint}</p>}
    </div>
  )
}
