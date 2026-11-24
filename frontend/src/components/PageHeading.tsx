"use client";

import { type ReactNode, useEffect, useRef } from "react";

import { brand } from "@/config/brand";

type Props = {
  children: ReactNode;
  /** Page title, for pages whose title depends on loaded data. */
  title?: string;
  className?: string;
};

/** The page's h1. Takes the focus a followed link left on <main>, so the new page is announced. */
export function PageHeading({ children, title, className = "" }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (document.activeElement?.id === "content") heading.current?.focus();
  }, []);
  useEffect(() => {
    if (title) document.title = `${title} | ${brand.name}`;
  }, [title]);
  return (
    <h1 ref={heading} tabIndex={-1} className={`text-2xl font-bold ${className}`}>
      {children}
    </h1>
  );
}
