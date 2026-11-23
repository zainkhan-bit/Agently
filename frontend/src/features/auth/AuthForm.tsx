"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import { apiPost, errorMessage, fieldErrors } from "@/lib/api";

const COPY = {
  register: {
    title: "Create your account",
    submit: "Create account",
    pending: "Creating account…",
    otherHref: "/login",
    otherLabel: "Already have an account? Sign in",
  },
  login: {
    title: "Sign in",
    submit: "Sign in",
    pending: "Signing in…",
    otherHref: "/register",
    otherLabel: "New here? Create an account",
  },
} as const;

type Errors = { form?: string; email?: string; password?: string };

function toErrors(error: unknown): Errors {
  const { email, password } = fieldErrors(error);
  return email || password ? { email, password } : { form: errorMessage(error) };
}

export function AuthForm({ mode }: { mode: "register" | "login" }) {
  const copy = COPY[mode];
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false); // set synchronously, so a double click cannot submit twice

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    const form = new FormData(event.currentTarget);
    setPending(true);
    setErrors({});
    try {
      await apiPost(`/auth/${mode}`, {
        email: form.get("email"),
        password: form.get("password"),
      });
      router.replace("/account");
    } catch (error) {
      // Only re-enabled on failure: after a success the form stays off until the page changes.
      setErrors(toErrors(error));
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    // method="post" keeps the password out of the URL if the form is submitted before hydration.
    <form method="post" onSubmit={submit} noValidate className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">{copy.title}</h1>
      {errors.form && <p role="alert">{errors.form}</p>}
      <label className="flex flex-col gap-1">
        Email
        <input
          name="email"
          type="email"
          autoComplete="email"
          aria-invalid={Boolean(errors.email)}
          aria-describedby={errors.email ? "email-error" : undefined}
          className="rounded-md border border-current px-3 py-2"
        />
      </label>
      {errors.email && (
        <p id="email-error" role="alert">
          {errors.email}
        </p>
      )}
      <label className="flex flex-col gap-1">
        Password
        <input
          name="password"
          type="password"
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          aria-invalid={Boolean(errors.password)}
          aria-describedby={errors.password ? "password-error" : undefined}
          className="rounded-md border border-current px-3 py-2"
        />
      </label>
      {mode === "register" && <p className="text-sm">Use 12 to 128 characters.</p>}
      {errors.password && (
        <p id="password-error" role="alert">
          {errors.password}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="rounded-md border border-current px-3 py-2 font-medium disabled:opacity-60"
      >
        {pending ? copy.pending : copy.submit}
      </button>
      <Link href={copy.otherHref} className="underline">
        {copy.otherLabel}
      </Link>
    </form>
  );
}
