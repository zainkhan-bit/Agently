/** Who receives what people type. The server names the case; without a known one, nobody types. */
const NOTICES = {
  none: "",
  gemini_free:
    "Your answers are sent to Google Gemini. Google may use them to improve its products and people may read them. Don't include personal or confidential information.",
  gemini_paid:
    "Your answers are sent to Google Gemini. Don't include personal or confidential information.",
} as const;

export type Disclosure = keyof typeof NOTICES;

export const isDisclosure = (value: unknown): value is Disclosure =>
  typeof value === "string" && Object.hasOwn(NOTICES, value);

export const noticeText = (disclosure: Disclosure): string => NOTICES[disclosure];
