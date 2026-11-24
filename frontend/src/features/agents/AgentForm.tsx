"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/buttonClass";
import { ApiError, fieldErrors } from "@/lib/api";
import { useUnsavedChanges } from "@/lib/unsavedChanges";

import { changeFailure } from "./failure";

export type AgentFields = {
  name: string;
  purpose: string;
  description: string;
  instructions: string;
};

type Field = keyof AgentFields;

/** The server's limits. It enforces them too. */
const FIELDS: { field: Field; label: string; maximum: number; rows: number; required: boolean }[] =
  [
    { field: "name", label: "Name", maximum: 100, rows: 1, required: true },
    { field: "purpose", label: "Purpose", maximum: 500, rows: 2, required: false },
    { field: "description", label: "Description", maximum: 1_000, rows: 4, required: false },
    { field: "instructions", label: "Instructions", maximum: 10_000, rows: 14, required: true },
  ];

/** Counts as the server does: one per character, also for emoji. */
const count = (text: string) => [...text].length;
const number = (value: number) => value.toLocaleString("en-US");

function check(values: AgentFields): Partial<AgentFields> {
  const errors: Partial<AgentFields> = {};
  for (const { field, label, maximum, required } of FIELDS) {
    const trimmed = values[field].trim();
    // The server keeps the spaces around instructions, so they count.
    const length = count(field === "instructions" ? values[field] : trimmed);
    if (required && !trimmed) errors[field] = `${label} ${field === "instructions" ? "are" : "is"} required.`;
    else if (length > maximum) {
      errors[field] = `${label} must be at most ${number(maximum)} characters.`;
    }
  }
  return errors;
}

function failureText(failure: unknown, checkHint: string): string {
  const status = failure instanceof ApiError ? failure.status : 0;
  if (status === 401) return "You are signed out. Nothing was saved.";
  if (status === 404) return "Not saved: this no longer exists, or you lost access to it.";
  return changeFailure(failure, checkHint);
}

type Props = {
  initial: AgentFields;
  submitLabel: string;
  cancelHref: string;
  /** What to do when it is unknown whether the save happened. */
  checkHint: string;
  /** Saves and navigates away, or throws. */
  onSave: (values: AgentFields) => Promise<void>;
  /** Extra help for some errors. */
  errorHelp?: (error: unknown) => React.ReactNode;
  /** Nothing can be typed or saved, e.g. while the text is being replaced. */
  locked?: boolean;
  /** The page asks before leaving, and wants to know whether anything was edited. */
  onEdited?: (edited: boolean) => void;
};

export function AgentForm(props: Props) {
  const { initial, submitLabel, cancelHref, checkHint, onSave, errorHelp, locked = false, onEdited } = props;
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState<Partial<AgentFields>>({});
  const [failure, setFailure] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const form = useRef<HTMLFormElement>(null);
  const edited = FIELDS.some(({ field }) => values[field] !== initial[field]);
  useUnsavedChanges(edited, !onEdited);
  useEffect(() => onEdited?.(edited), [edited, onEdited]);

  // Runs for every new set of errors, also when it names the same fields again.
  useEffect(() => {
    const first = FIELDS.find(({ field }) => errors[field]);
    if (first) form.current?.querySelector<HTMLElement>(`#agent-${first.field}`)?.focus();
  }, [errors]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || locked) return;
    setFailure(null);
    const found = check(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    inFlight.current = true;
    setPending(true);
    try {
      await onSave(values);
    } catch (error) {
      const onFields = Object.entries(fieldErrors(error)).filter(([name]) =>
        FIELDS.some(({ field }) => field === name),
      );
      if (onFields.length > 0) setErrors(Object.fromEntries(onFields));
      else setFailure(error);
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    <form ref={form} onSubmit={submit} noValidate className="flex flex-col gap-4">
      {FIELDS.map(({ field, label, maximum, rows, required }) => {
        const id = `agent-${field}`;
        const counted = field === "instructions";
        const length = count(values[field]);
        const tooLong = counted && length > maximum;
        const described = [
          errors[field] && `${id}-error`,
          counted && `${id}-count`,
        ].filter(Boolean);
        const shared = {
          id,
          value: values[field],
          readOnly: pending || locked, // text typed while saving would be lost
          autoComplete: "off",
          "aria-required": required,
          "aria-invalid": Boolean(errors[field]) || tooLong,
          "aria-describedby": described.join(" ") || undefined,
          className: "rounded-md border border-current px-3 py-2",
          onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
            setValues({ ...values, [field]: event.target.value }),
        };
        return (
          <div key={field} className="flex flex-col gap-1">
            <label htmlFor={id}>
              {label} {required ? "(required)" : "(optional)"}
            </label>
            {rows === 1 ? <input {...shared} /> : <textarea {...shared} rows={rows} />}
            {counted && (
              <>
                <p id={`${id}-count`} className={tooLong ? "font-semibold" : undefined}>
                  {number(length)} / {number(maximum)}
                </p>
                {/* Announced once when crossing the limit, not on every key. */}
                <p role="status">
                  {tooLong ? `Over the limit. Shorten the ${field} before saving.` : ""}
                </p>
              </>
            )}
            {errors[field] && (
              <p id={`${id}-error`} role="alert">
                {errors[field]}
              </p>
            )}
          </div>
        );
      })}
      {failure !== null && (
        <div className="flex flex-col gap-2">
          <p role="alert">{failureText(failure, checkHint)} Your text is still here.</p>
          {failure instanceof ApiError && failure.status === 401 && (
            <p>
              <a href="/login" target="_blank" rel="noopener" className="underline">
                Sign in again (opens a new tab)
              </a>{" "}
              with the same account, then come back and save.
            </p>
          )}
          {errorHelp?.(failure)}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" aria-disabled={pending || locked} className={buttonClass}>
          {pending ? "Saving…" : submitLabel}
        </button>
        <Link href={cancelHref} className="underline">
          Cancel
        </Link>
      </div>
    </form>
  );
}
