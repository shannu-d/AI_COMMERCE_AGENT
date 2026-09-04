import { Eyebrow } from "../../components/primitives";
import { PageHead } from "../../features/merchant/MerchantShell";
import { useMerchantOverview } from "../../features/merchant/useMerchant";

/**
 * Settings is honest about what the MVP is: a single-tenant dashboard with no
 * authentication. It shows the merchant context the whole application resolves
 * server-side, and names the limitations rather than hiding them behind
 * disabled toggles.
 */
export function SettingsPage() {
  const { data } = useMerchantOverview();

  return (
    <>
      <PageHead title="Settings" />

      <div className="max-w-xl space-y-6">
        <section className="border border-rule bg-paper-raised p-4">
          <Eyebrow>Merchant</Eyebrow>
          <dl className="mt-3 space-y-2 text-sm">
            <Row term="Storefront name" value="EASY BUY" />
            <Row term="Currency" value={data?.currency ?? "INR"} />
            <Row term="Catalogue" value={data ? `${data.total_products} products · ${data.total_variants} SKUs` : "—"} />
          </dl>
        </section>

        <section className="border border-rule bg-paper-raised p-4">
          <Eyebrow>Known limitations (MVP)</Eyebrow>
          <ul className="mt-3 space-y-2 text-sm text-ink-soft">
            <li>
              <span className="text-ink">No authentication.</span> The project has no{" "}
              <span className="tabular text-2xs">users</span> table (ADR-006). This dashboard operates
              on the one configured merchant, resolved server-side. Anyone who reaches{" "}
              <span className="tabular text-2xs">/merchant</span> can use it.
            </li>
            <li>
              <span className="text-ink">Single tenant.</span> The schema supports many merchants;
              the application serves one. A merchant switcher would need a real sign-in first.
            </li>
            <li>
              <span className="text-ink">No change log.</span> Edits take effect immediately and are
              not recorded as an activity feed. The commerce audit trail
              (<span className="tabular text-2xs">audit_events</span>) covers the order path only.
            </li>
            <li>
              <span className="text-ink">Razorpay is test-mode / unconfigured.</span> Revenue counts
              only orders that reached <span className="tabular text-2xs">PAYMENT_CONFIRMED</span>.
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
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
