import { useQuery } from "@tanstack/react-query";

import { getMerchantMe } from "../../api/endpoints";
import { Eyebrow } from "../../components/primitives";
import { PageHead } from "../../features/merchant/MerchantShell";
import { useMerchantOverview } from "../../features/merchant/useMerchant";

/**
 * Settings shows the merchant context the application resolves **server-side**,
 * and names what is still missing rather than hiding it behind disabled toggles.
 *
 * Everything in the identity panel comes from `/api/merchant/me`, which reads
 * the merchant from the bearer token's user row. Nothing on this page is a
 * value the browser chose, which is the point worth showing an administrator:
 * the scope they are looking at is not one they can change.
 */
export function SettingsPage() {
  const { data } = useMerchantOverview();
  const { data: me } = useQuery({
    queryKey: ["merchant", "me"],
    queryFn: ({ signal }) => getMerchantMe(signal),
  });

  return (
    <>
      <PageHead title="Settings" />

      <div className="max-w-xl space-y-6">
        <section className="border border-rule bg-paper-raised p-4">
          <Eyebrow>Signed in as</Eyebrow>
          <dl className="mt-3 space-y-2 text-sm">
            <Row term="Administrator" value={me?.display_name || me?.email || "—"} />
            <Row term="Email" value={me?.email ?? "—"} />
            <Row term="Role" value={me?.role ?? "—"} />
          </dl>
          <p className="mt-3 text-2xs leading-relaxed text-ink-faint">
            Resolved from the bearer token, not from anything this page sent. Every
            dashboard route scopes itself to this merchant and no other (ADR-023).
          </p>
        </section>

        <section className="border border-rule bg-paper-raised p-4">
          <Eyebrow>Merchant</Eyebrow>
          <dl className="mt-3 space-y-2 text-sm">
            <Row term="Storefront name" value={me?.merchant_name ?? "EASY BUY"} />
            <Row term="Merchant id" value={me?.merchant_id ?? "—"} />
            <Row term="Currency" value={data?.currency ?? "INR"} />
            <Row
              term="Catalogue"
              value={
                data ? `${data.total_products} products · ${data.total_variants} SKUs` : "—"
              }
            />
          </dl>
        </section>

        <section className="border border-rule bg-paper-raised p-4">
          <Eyebrow>Known limitations (MVP)</Eyebrow>
          <ul className="mt-3 space-y-2 text-sm text-ink-soft">
            <li>
              <span className="text-ink">One merchant per deployment.</span> The schema and the
              authorization model both support many; the storefront serves the one configured
              merchant. A merchant switcher is a product decision, not a missing mechanism.
            </li>
            <li>
              <span className="text-ink">Accounts are provisioned by an operator.</span> There is no
              self-service merchant sign-up, and no route that could create one — registration makes
              customers only, so privilege cannot be granted by a request body (ADR-023).
            </li>
            <li>
              <span className="text-ink">No password reset or email verification.</span> Neither is
              implemented in this milestone, and neither is silently faked.
            </li>
            <li>
              <span className="text-ink">Razorpay is test-mode / unconfigured.</span> Revenue counts
              only orders that reached <span className="tabular text-2xs">PAYMENT_CONFIRMED</span>,
              which only a signature-verified webhook can set.
            </li>
          </ul>
        </section>
      </div>
    </>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-ink-faint">{term}</dt>
      <dd className="truncate text-ink">{value}</dd>
    </div>
  );
}
