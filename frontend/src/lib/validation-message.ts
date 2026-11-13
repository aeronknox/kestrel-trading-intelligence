/** The server's first field error, made readable for a person: no Python field paths or validator jargon. */
export function validationMessage(loc: (string | number)[] | undefined, msg: string): string {
  if (/valid email address/i.test(msg)) return "Enter a valid email address, like name@example.com.";
  const text = msg.replace(/^Value error, /, "");
  const field = (loc ?? []).filter((x) => x !== "body" && typeof x === "string").at(-1);
  if (!field) return text;
  const label = String(field).replace(/_/g, " ");
  return `${label[0]!.toUpperCase()}${label.slice(1)}: ${text}`;
}

/** Loose check before submitting: something@something.tld, no spaces. The server validates properly. */
export function looksLikeEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}
