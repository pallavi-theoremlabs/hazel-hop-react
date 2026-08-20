import React from "react";

export default function Button({ variant = 'primary', className = '', ...props }) {
  return <button className={`btn ${variant} ${className}`.trim()} {...props} />
}
