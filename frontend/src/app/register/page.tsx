import type { Metadata } from "next";

import { AuthForm } from "@/features/auth/AuthForm";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-16">
      <AuthForm mode="register" />
    </main>
  );
}
