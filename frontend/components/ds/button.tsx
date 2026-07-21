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
  type?: "button" | "submit" | "reset";
}

const SIZE_MAP: Record<ButtonSize, { padding: string; fontSize: number; height: number }> = {
  sm: { padding: "6px 12px", fontSize: 12, height: 30 },
  md: { padding: "9px 16px", fontSize: 13, height: 38 },
  lg: { padding: "14px 22px", fontSize: 15, height: 50 },
  xl: { padding: "18px 28px", fontSize: 17, height: 60 },
};

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-rally-cobalt-600 text-white border-transparent shadow-[0_1px_0_rgba(0,0,0,0.05),0_0_0_1px_rgba(37,99,235,0.2)] hover:bg-rally-cobalt-700",
  volt: "bg-rally-volt-400 text-rally-ink border-transparent shadow-[0_1px_0_rgba(0,0,0,0.1)] hover:bg-rally-volt-500",
  dark: "bg-rally-ink text-white border-transparent hover:bg-rally-night-line",
  ghost: "bg-transparent text-rally-ink border-transparent hover:bg-rally-ink/5",
  danger: "bg-white text-status-red-800 border-status-red-200 hover:bg-status-red-50",
  secondary:
    "bg-white text-rally-ink border-rally-line shadow-[0_1px_0_rgba(0,0,0,0.02)] hover:bg-rally-paper",
};

export function Button({
  children,
  variant = "primary",
  size = "md",
  icon,
  full,
  type = "button",
  style,
  className,
  ...rest
}: ButtonProps) {
  const sz = SIZE_MAP[size];
  const inline: CSSProperties = {
    padding: sz.padding,
    height: sz.height,
    minHeight: sz.height,
    width: full ? "100%" : "auto",
    fontSize: sz.fontSize,
    ...style,
  };
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded-lg border font-body font-semibold tracking-[-0.005em] transition-[transform,filter,background-color] duration-100 active:scale-[0.985] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-600 ${VARIANT_CLASSES[variant]} ${className ?? ""}`}
      style={inline}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}
