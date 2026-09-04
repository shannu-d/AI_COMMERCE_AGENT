import { useState } from "react";

import { Alert, Button, Eyebrow, Skeleton } from "../../components/primitives";
import { cx } from "../../components/cx";
import { PageHead } from "../../features/merchant/MerchantShell";
import { useCreateCategory, useMerchantCategories } from "../../features/merchant/useMerchant";

/**
 * Category management, against the real `categories` table. The tree is the
 * merchant's own; the storefront and the Smart Agent's tool vocabulary are both
 * built from it, so a category added here becomes a slug the agent may choose.
 */
export function CategoriesPage() {
  const { data, isPending, isError } = useMerchantCategories();
  const create = useCreateCategory();

  const [name, setName] = useState("");
  const [parent, setParent] = useState("");

  const roots = (data ?? []).filter((c) => !c.parent_slug);
  const childrenOf = (slug: string) => (data ?? []).filter((c) => c.parent_slug === slug);

  return (
    <>
      <PageHead title="Categories" count={data ? `${data.length}` : undefined} />

      <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
        <div>
          {isError ? (
            <Alert tone="critical" title="Could not load categories" />
          ) : isPending ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <ul className="border border-rule bg-paper-raised">
              {roots.map((root) => (
                <li key={root.slug} className="border-b border-rule/60 last:border-0">
                  <div className="flex items-baseline justify-between px-4 py-2.5">
                    <span className="font-medium text-ink">{root.name}</span>
                    <span className="tabular text-2xs text-ink-faint">{root.slug}</span>
                  </div>
                  {childrenOf(root.slug).length > 0 && (
                    <ul className="border-t border-rule/40 bg-paper-sunken/40">
                      {childrenOf(root.slug).map((child) => (
                        <li
                          key={child.slug}
                          className="flex items-baseline justify-between px-4 py-2 pl-8 text-sm"
                        >
                          <span className="text-ink-soft">{child.name}</span>
                          <span className="tabular text-2xs text-ink-faint">{child.slug}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { name: name.trim(), parent: parent || null },
              { onSuccess: () => { setName(""); setParent(""); } },
            );
          }}
          className="h-fit border border-rule bg-paper-raised p-4"
        >
          <Eyebrow>New category</Eyebrow>
          <label className="mt-3 block">
            <span className="mb-1 block text-2xs uppercase tracking-[0.1em] text-ink-faint">Name</span>
            <input
              className={cx(
                "h-9 w-full border border-rule bg-paper px-3 text-sm",
                "placeholder:text-ink-faint focus:border-volt focus:outline-none",
              )}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Scarves"
              required
            />
          </label>
          <label className="mt-3 block">
            <span className="mb-1 block text-2xs uppercase tracking-[0.1em] text-ink-faint">Parent</span>
            <select
              className="h-9 w-full appearance-none border border-rule bg-paper px-3 text-sm focus:border-volt focus:outline-none"
              value={parent}
              onChange={(e) => setParent(e.target.value)}
            >
              <option value="">Top level</option>
              {(data ?? []).map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-2 text-2xs text-ink-faint">
            The slug is derived from the name — lowercase, words joined by “_”.
          </p>
          <Button type="submit" size="sm" className="mt-4 w-full" disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Creating…" : "Create category"}
          </Button>
        </form>
      </div>
    </>
  );
}
