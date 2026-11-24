import { z } from "zod";

/** Mirrors backend normalisation: spaces/hyphens allowed while typing ("560 001"). */
export function normalizePincode(raw: string): string {
  return raw.replace(/[\s-]/g, "");
}

/**
 * Instant, client-side checks only. The server is authoritative for which links are
 * supported; this just catches empty fields and obviously wrong PIN codes early.
 */
export const lookupSchema = z.object({
  url: z.string().trim().min(1, "Paste a product link.").max(2048, "That link is too long."),
  pincode: z
    .string()
    .transform(normalizePincode)
    .pipe(
      z
        .string()
        .min(1, "Enter your 6-digit PIN code.")
        .regex(/^[0-9]{6}$/, "A PIN code is exactly 6 digits.")
        .regex(/^[1-9]/, "Indian PIN codes don't start with 0."),
    ),
});

export type LookupFormInput = z.input<typeof lookupSchema>;
export type LookupFormValues = z.output<typeof lookupSchema>;
