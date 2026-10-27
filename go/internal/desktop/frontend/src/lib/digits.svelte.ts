// The decimals the team chose (Settings → Team → Rounding). Every amount in the window is shown with
// them, so the number on screen is the one the core calculated (a rounded 13 hides 12,89).

const digits = $state({ plan: 1, capacity: 1 });

/** Decimals of the Forecast PLAN and of every amount planned from it (points, person days). */
export const planDigits = (): number => digits.plan;

/** Decimals of the capacity. */
export const capacityDigits = (): number => digits.capacity;

/** Takes over the rounding of the selected team; anything out of range falls back to one decimal. */
export function setDigits(plan: number | undefined, capacity: number | undefined): void {
  const ok = (n: number | undefined) => (n !== undefined && Number.isInteger(n) && n >= 0 && n <= 3 ? n : 1);
  digits.plan = ok(plan);
  digits.capacity = ok(capacity);
}
