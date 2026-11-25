/** Who receives what people type. The server names the case; without a known one, nobody types. */
const NOTICES = {
  none: () => "",
  gemini_free: (what: string) =>
    `${what} sent to Google Gemini. Google may use them to improve its products and people may read them. Don't include personal or confidential information.`,
  gemini_paid: (what: string) =>
    `${what} sent to Google Gemini. Don't include personal or confidential information.`,
} as const;

export type Disclosure = keyof typeof NOTICES;

/** What the notice is about: the builder's answers, or a chat with the agent's instructions. */
const SUBJECTS = {
  answers: "Your answers are",
  chat: "Your messages, the conversation so far and the agent's instructions are",
} as const;

export const isDisclosure = (value: unknown): value is Disclosure =>
  typeof value === "string" && Object.hasOwn(NOTICES, value);

export const noticeText = (
  disclosure: Disclosure,
  subject: keyof typeof SUBJECTS = "answers",
): string => NOTICES[disclosure](SUBJECTS[subject]);
