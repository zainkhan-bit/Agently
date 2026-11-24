"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { apiPost } from "@/lib/api";
import { clearUnsaved, confirmLeave } from "@/lib/unsavedChanges";

export function SignOutButton() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function signOut() {
    if (!confirmLeave()) return;
    setPending(true);
    setError(null);
    try {
      await apiPost("/auth/logout");
      clearUnsaved(); // agreed to above
      router.replace("/login");
    } catch {
      setError("Could not confirm sign out. You may still be signed in. Please try again.");
      setPending(false);
    }
  }

  return (
    <>
      {error && <p role="alert">{error}</p>}
      <button
        type="button"
        disabled={pending}
        onClick={() => void signOut()}
        className={buttonClass}
      >
        Sign out
      </button>
    </>
  );
}
