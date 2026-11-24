"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

/** Home page links. Anything but a confirmed session shows the signed-out links. */
export function HomeNav() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    let active = true;
    apiFetch("/auth/me", { cache: "no-store" }).then(
      () => active && setSignedIn(true),
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, []);

  return (
    <nav aria-label="Main" className="flex gap-4">
      {signedIn ? (
        <Link href="/dashboard" className="underline">
          Go to dashboard
        </Link>
      ) : (
        <>
          <Link href="/register" className="underline">
            Create account
          </Link>
          <Link href="/login" className="underline">
            Sign in
          </Link>
        </>
      )}
    </nav>
  );
}
