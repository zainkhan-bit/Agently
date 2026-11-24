"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ErrorRetry } from "@/components/ErrorRetry";
import { PageHeading } from "@/components/PageHeading";
import { useWorkspace } from "@/features/workspaces/useWorkspace";
import { WorkspaceMissing } from "@/features/workspaces/WorkspaceMissing";
import { ApiError, apiPost, errorMessage, fieldErrors } from "@/lib/api";
import { clearUnsaved, useUnsavedChanges } from "@/lib/unsavedChanges";
import { usePageRouter } from "@/lib/usePageRouter";

import { AgentForm, type AgentFields } from "./AgentForm";
import { agentPath, agentsPath, builderPath } from "./paths";
import type { Agent } from "./types";
import { useBuilder } from "./useBuilder";

/** The server's limits. It enforces them too. */
const ANSWER_MAX = 1_000;
const TOTAL_MAX = 3_000;

const QUESTIONS = [
  { field: "purpose", label: "What is the agent for?", required: true },
  { field: "tasks", label: "What should it do?", required: true },
  { field: "tone", label: "What tone should it use?", required: false },
  { field: "constraints", label: "What must it avoid?", required: false },
  { field: "extra", label: "Anything else?", required: false },
] as const;

type Question = (typeof QUESTIONS)[number]["field"];
type Answers = Record<Question, string>;

const EMPTY: Answers = { purpose: "", tasks: "", tone: "", constraints: "", extra: "" };

/** Counts as the server does: without the spaces around, and one per character. */
const count = (text: string) => [...text.trim()].length;
const number = (value: number) => value.toLocaleString("en-US");

function check(answers: Answers): Partial<Answers> {
  const errors: Partial<Answers> = {};
  for (const { field, required } of QUESTIONS) {
    const length = count(answers[field]);
    if (required && length === 0) errors[field] = "Please answer this question.";
    else if (length > ANSWER_MAX) {
      errors[field] = `Must be at most ${number(ANSWER_MAX)} characters.`;
    }
  }
  return errors;
}

function failureText(error: unknown): string {
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 401) return "You are signed out.";
  if (status === 404) return "No draft: this workspace no longer exists, or you lost access to it.";
  return errorMessage(error);
}

type Draft = { id: number; values: AgentFields; sample: boolean };

export function DescribeAgent({ workspaceId }: { workspaceId: string }) {
  const { state, load } = useWorkspace(workspaceId);
  const { builder, load: loadBuilder } = useBuilder(workspaceId);

  if (state.kind === "missing") return <WorkspaceMissing />;
  if (state.kind === "error") {
    return <ErrorRetry message={state.message} onRetry={() => void load()} />;
  }
  if (state.kind === "loading" || builder === "loading") return <p role="status">Loading…</p>;
  if (builder === "unknown") {
    return (
      <ErrorRetry
        message="Could not find out whether drafts are available."
        onRetry={() => void loadBuilder()}
      />
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="Describe your agent">Describe your agent</PageHeading>
      <p>
        <Link href={`${agentsPath(workspaceId)}/new`} className="underline">
          Fill in the agent yourself instead
        </Link>
      </p>
      {builder === "available" ? (
        <Builder workspaceId={workspaceId} />
      ) : (
        <p>Drafts are not available on this server.</p>
      )}
    </div>
  );
}

function Builder({ workspaceId }: { workspaceId: string }) {
  const router = usePageRouter();
  const [answers, setAnswers] = useState(EMPTY);
  const [errors, setErrors] = useState<Partial<Answers>>({});
  const [failure, setFailure] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [edited, setEdited] = useState(false);
  const inFlight = useRef(false);
  const [saving, setSaving] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const draftHeading = useRef<HTMLHeadingElement>(null);
  const path = agentsPath(workspaceId);

  // A draft is unsaved even when nobody has edited it.
  useUnsavedChanges(draft !== null || QUESTIONS.some(({ field }) => answers[field] !== ""));

  useEffect(() => {
    const first = QUESTIONS.find(({ field }) => errors[field]);
    if (first) form.current?.querySelector<HTMLElement>(`#answer-${first.field}`)?.focus();
  }, [errors]);

  useEffect(() => {
    if (draft) draftHeading.current?.focus();
  }, [draft]);

  const total = QUESTIONS.reduce((sum, { field }) => sum + count(answers[field]), 0);
  const tooLong = total > TOTAL_MAX;

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || saving) return;
    setFailure(null);
    const found = check(answers);
    setErrors(found);
    if (Object.keys(found).length > 0 || tooLong) return;
    if (edited && !window.confirm("Replace the draft? Your edits to it will be lost.")) return;
    inFlight.current = true;
    setPending(true);
    try {
      const { data } = await apiPost<{ draft: AgentFields; sample: boolean }>(
        `${builderPath(workspaceId)}/drafts`,
        answers,
      );
      const { name, purpose, description, instructions } = data.draft;
      setDraft((previous) => ({
        id: (previous?.id ?? 0) + 1,
        values: { name, purpose, description, instructions },
        sample: data.sample,
      }));
    } catch (error) {
      const onFields = Object.entries(fieldErrors(error)).filter(([name]) =>
        QUESTIONS.some(({ field }) => field === name),
      );
      if (onFields.length > 0) setErrors(Object.fromEntries(onFields));
      else setFailure(error);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  async function save(values: AgentFields) {
    setSaving(true);
    try {
      const { data } = await apiPost<Agent>(path, values);
      clearUnsaved();
      document.getElementById("content")?.focus();
      router.replace(agentPath(workspaceId, data.id));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <form
        ref={form}
        onSubmit={generate}
        noValidate
        aria-label="Questions"
        className="flex flex-col gap-4"
      >
        {QUESTIONS.map(({ field, label, required }) => {
          const id = `answer-${field}`;
          return (
            <div key={field} className="flex flex-col gap-1">
              <label htmlFor={id}>
                {label} {required ? "(required)" : "(optional)"}
              </label>
              <textarea
                id={id}
                rows={3}
                value={answers[field]}
                readOnly={pending || saving}
                autoComplete="off"
                aria-required={required}
                aria-invalid={Boolean(errors[field])}
                aria-describedby={errors[field] ? `${id}-error` : undefined}
                className="rounded-md border border-current px-3 py-2"
                onChange={(event) => setAnswers({ ...answers, [field]: event.target.value })}
              />
              {errors[field] && (
                <p id={`${id}-error`} role="alert">
                  {errors[field]}
                </p>
              )}
            </div>
          );
        })}
        <p className={tooLong ? "font-semibold" : undefined}>
          All answers: {number(total)} / {number(TOTAL_MAX)}
        </p>
        {/* Announced once when crossing the limit, not on every key. */}
        <p role="status">{tooLong ? "Over the limit. Shorten your answers first." : ""}</p>
        {failure !== null && (
          <div className="flex flex-col gap-2">
            <p role="alert">
              {failureText(failure)} No agent was created. Your answers are still here.
            </p>
            {failure instanceof ApiError && failure.status === 401 && (
              <p>
                <a href="/login" target="_blank" rel="noopener" className="underline">
                  Sign in again (opens a new tab)
                </a>{" "}
                with the same account, then come back and try again.
              </p>
            )}
          </div>
        )}
        <p role="status">{pending ? "Generating a draft. This can take a moment." : ""}</p>
        <button type="submit" aria-disabled={pending || saving} className={buttonClass}>
          {pending ? "Generating…" : draft ? "Generate a new draft" : "Generate draft"}
        </button>
      </form>
      {draft && (
        <section aria-labelledby="draft-heading" className="flex flex-col gap-4">
          <h2
            id="draft-heading"
            ref={draftHeading}
            tabIndex={-1}
            className="text-xl font-bold"
          >
            Review the draft
          </h2>
          {draft.sample && (
            <p className="font-semibold">Sample draft, made without AI for testing.</p>
          )}
          <p>Nothing is saved yet. Check every field, change what you like, then create the agent.</p>
          <AgentForm
            key={draft.id}
            initial={draft.values}
            submitLabel="Create agent"
            cancelHref={path}
            checkHint="look in My Agents before trying again."
            onSave={save}
            locked={pending}
            onEdited={setEdited}
          />
        </section>
      )}
    </>
  );
}
