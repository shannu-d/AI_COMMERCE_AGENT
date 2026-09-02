/**
 * Conditional class names, so components stay readable.
 *
 * Lives apart from `primitives.tsx` deliberately: a module that exports both
 * components and plain functions breaks React Fast Refresh for that module,
 * which is what `react-refresh/only-export-components` reports.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
