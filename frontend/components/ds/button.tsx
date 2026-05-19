"use client";

import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

export type ButtonVariant =
  | "primary"
  | "volt"
  | "dark"
  | "ghost"
  | "secondary"
  | "danger";

export type ButtonSize = "sm" | "md" | "lg" | "xl";

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  children?: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  full?: boolean;
  dark?: boolean;
  type?: "button" | "submit" | "reset";
}

const SIZE_MAP: Record<ButtonSize, { padding: string; fontSize: number; height: number }> = {
  sm: { padding: "6px 12px", fontSize: 12, height: 30 },
  md: { padding: "9px 16px", fontSize: 13, height: 38 },
  lg: { padding: "14px 22px", fontSize: 15, height: 50 },
  xl: { padding: "18px 28px", fontSize: 17, height: 60 },
};

interface VariantSpec {
  bg: string;
  fg: string;
  border: string;
  shadow: string;
}

function variantSpec(variant: ButtonVariant, dark: boolean): VariantSpec {
  switch (variant) {
    case "primary":
      return {
        bg: "#2563eb",
        fg: "#fff",
        border: "transparent",
        shadow: "0 1px 0 rgba(0,0,0,0.05), 0 0 0 1px rgba(37,99,235,0.2)",
      };
    case "volt":
      return { bg: "#facc15", fg: "#0f172a", border: "transparent", shadow: "0 1px 0 rgba(0,0,0,0.1)" };
    case "dark":
      return { bg: "#0f172a", fg: "#fff", border: "transparent", shadow: "none" };
    case "ghost":
      return { bg: "transparent", fg: dark ? "#e2e8f0" : "#0f172a", border: "transparent", shadow: "none" };
    case "danger":
      return { bg: "#fff", fg: "#991b1b", border: "#fecaca", shadow: "none" };
    case "secondary":
    default:
      return {
        bg: dark ? "#1e293b" : "#fff",
        fg: dark ? "#e2e8f0" : "#0f172a",
        border: dark ? "#334155" : "#e2e8f0",
        shadow: dark ? "none" : "0 1px 0 rgba(0,0,0,0.02)",
      };
  }
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  icon,
  full,
  dark = false,
  type = "button",
  style,
  className,
  ...rest
}: ButtonProps) {
  const sz = SIZE_MAP[size];
  const v = variantSpec(variant, dark);
  const inline: CSSProperties = {
    padding: sz.padding,
    height: sz.height,
    minHeight: sz.height,
    width: full ? "100%" : "auto",
    background: v.bg,
    color: v.fg,
    border: `1px solid ${v.border}`,
    fontSize: sz.fontSize,
    boxShadow: v.shadow,
    ...style,
  };
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-body font-semibold tracking-[-0.005em] transition-[transform,filter] duration-100 active:scale-[0.985] cursor-pointer ${className ?? ""}`}
      style={inline}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}
