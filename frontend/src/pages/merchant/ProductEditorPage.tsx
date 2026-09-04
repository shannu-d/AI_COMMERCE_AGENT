import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Alert, Button, Eyebrow, Skeleton, StockBadge } from "../../components/primitives";
import { cx } from "../../components/cx";
import { PageHead } from "../../features/merchant/MerchantShell";
import {
  useAddVariant,
  useArchiveProduct,
  useCreateProduct,
  useMerchantCategories,
  useMerchantProduct,
  useSetStock,
  useUpdateProduct,
  useUpdateVariant,
} from "../../features/merchant/useMerchant";
import {
  attributeTemplate,
  coerceAttrValue,
  type AttrField,
} from "../../features/merchant/attributeTemplates";
import type { MerchantVariant } from "../../features/merchant/api";

/**
 * Create or edit a product. The form is built from the real schema (name,
 * category, description, brand, tags, per-variant SKU / price / stock) plus a
 * category-shaped set of attribute fields (frontend scaffolding — see
 * `attributeTemplates.ts`). Price is a string end to end (ADR-008); the form
 * never does arithmetic.
 */
export function ProductEditorPage() {
  const { productId } = useParams<{ productId: string }>();
  const isNew = productId === undefined;
  return isNew ? <CreateForm /> : <EditForm productId={productId} />;
}

// -- create -------------------------------------------------------------

function CreateForm() {
  const navigate = useNavigate();
  const { data: categories } = useMerchantCategories();
  const create = useCreateProduct();

  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [brand, setBrand] = useState("");
  const [tags, setTags] = useState("");
  const [productAttrs, setProductAttrs] = useState<Record<string, string>>({});
  const [variants, setVariants] = useState<VariantDraft[]>([blankVariant()]);

  const template = useMemo(() => attributeTemplate(category), [category]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        category,
        description: description.trim() || null,
        brand: brand.trim() || null,
        tags: splitTags(tags),
        attributes: buildAttrs(productAttrs),
        variants: variants
          .filter((v) => v.sku.trim())
          .map((v) => ({
            sku: v.sku.trim().toUpperCase(),
            name: v.name.trim() || "Default",
            price: v.price.trim(),
            quantity: Number(v.quantity) || 0,
            attributes: buildAttrs(v.attrs),
          })),
      },
      { onSuccess: (detail) => navigate(`/merchant/products/${detail.product_id}`) },
    );
  }

  return (
    <>
      <PageHead title="New product" />
      <form onSubmit={submit} className="max-w-2xl space-y-8">
        <Section title="Details">
          <Field label="Name" required>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Category" required>
            <select
              className={inputCls}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              required
            >
              <option value="">Choose…</option>
              {(categories ?? [])
                .filter((c) => c.parent_slug)
                .map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Description">
            <textarea
              className={cx(inputCls, "h-20 resize-y")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Brand">
              <input className={inputCls} value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="EASY BUY" />
            </Field>
            <Field label="Tags (comma-separated)">
              <input className={inputCls} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="cotton, everyday" />
            </Field>
          </div>
        </Section>

        {category && (
          <Section title="Attributes">
            <AttrGrid fields={template.product} values={productAttrs} onChange={setProductAttrs} />
          </Section>
        )}

        <Section title="Variants">
          <p className="mb-3 text-2xs text-ink-faint">
            Each row is a sellable SKU with its own price and stock. At least one is required.
          </p>
          <div className="space-y-4">
            {variants.map((v, i) => (
              <VariantDraftRow
                key={i}
                draft={v}
                fields={template.variant}
                onChange={(next) => setVariants((rows) => rows.map((r, j) => (j === i ? next : r)))}
                onRemove={variants.length > 1 ? () => setVariants((rows) => rows.filter((_, j) => j !== i)) : undefined}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={() => setVariants((rows) => [...rows, blankVariant()])}
            className="mt-3 border border-rule px-3 py-1.5 text-2xs transition-colors hover:border-volt"
          >
            + Add variant
          </button>
        </Section>

        <div className="flex gap-3">
          <Button type="submit" disabled={create.isPending || !name.trim() || !category}>
            {create.isPending ? "Creating…" : "Create product"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => navigate("/merchant/products")}>
            Cancel
          </Button>
        </div>
      </form>
    </>
  );
}

// -- edit ---------------------------------------------------------------

function EditForm({ productId }: { productId: string }) {
  const { data, isPending, isError } = useMerchantProduct(productId);
  const { data: categories } = useMerchantCategories();
  const update = useUpdateProduct(productId);
  const archive = useArchiveProduct();
  const addVariant = useAddVariant(productId);
  const updateVariant = useUpdateVariant(productId);
  const setStock = useSetStock();

  const [form, setForm] = useState<null | {
    name: string;
    category: string;
    description: string;
    brand: string;
    tags: string;
  }>(null);

  if (isError) return <Alert tone="critical" title="Could not load this product" />;
  if (isPending || !data) {
    return (
      <>
        <PageHead title="Product" />
        <Skeleton className="h-64 w-full max-w-2xl" />
      </>
    );
  }

  const f =
    form ??
    {
      name: data.name,
      category: data.category,
      description: data.description ?? "",
      brand: data.brand ?? "",
      tags: data.tags.join(", "),
    };
  const set = (patch: Partial<typeof f>) => setForm({ ...f, ...patch });
  const archived = !data.is_active;

  return (
    <>
      <PageHead title={data.name} count={<span className="tabular">{data.slug}</span>}>
        <button
          type="button"
          onClick={() => archive.mutate({ productId, archive: !archived })}
          disabled={archive.isPending}
          className={cx(
            "border px-3 py-1.5 text-2xs transition-colors",
            archived ? "border-volt text-ink hover:bg-paper-sunken" : "border-critical/40 text-critical hover:bg-critical/5",
          )}
        >
          {archived ? "Restore" : "Archive"}
        </button>
      </PageHead>

      {archived && (
        <Alert tone="caution" title="This product is archived">
          It is hidden from the storefront and the Smart Agent. Its order history is untouched.
        </Alert>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate({
            name: f.name.trim(),
            category: f.category,
            description: f.description.trim() || null,
            brand: f.brand.trim() || null,
            tags: splitTags(f.tags),
          });
        }}
        className="mt-6 max-w-2xl space-y-6"
      >
        <Section title="Details">
          <Field label="Name">
            <input className={inputCls} value={f.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="Category">
            <select className={inputCls} value={f.category} onChange={(e) => set({ category: e.target.value })}>
              {(categories ?? [])
                .filter((c) => c.parent_slug)
                .map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Description">
            <textarea
              className={cx(inputCls, "h-20 resize-y")}
              value={f.description}
              onChange={(e) => set({ description: e.target.value })}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Brand">
              <input className={inputCls} value={f.brand} onChange={(e) => set({ brand: e.target.value })} />
            </Field>
            <Field label="Tags">
              <input className={inputCls} value={f.tags} onChange={(e) => set({ tags: e.target.value })} />
            </Field>
          </div>
        </Section>
        <Button type="submit" disabled={update.isPending || form === null}>
          {update.isPending ? "Saving…" : "Save details"}
        </Button>
      </form>

      <section className="mt-10 max-w-2xl">
        <Eyebrow>Variants · {data.variants.length}</Eyebrow>
        <ul className="mt-3 space-y-px border border-rule bg-rule">
          {data.variants.map((v) => (
            <ExistingVariantRow
              key={v.variant_id}
              variant={v}
              onPrice={(price) => updateVariant.mutate({ variantId: v.variant_id, body: { price } })}
              onStock={(quantity) => setStock.mutate({ variantId: v.variant_id, quantity })}
              onActive={(is_active) => updateVariant.mutate({ variantId: v.variant_id, body: { is_active } })}
              busy={updateVariant.isPending || setStock.isPending}
            />
          ))}
        </ul>
        <AddVariantInline category={data.category} onAdd={(body) => addVariant.mutate(body)} busy={addVariant.isPending} />
      </section>
    </>
  );
}

// -- pieces -----------------------------------------------------------

type VariantDraft = { sku: string; name: string; price: string; quantity: string; attrs: Record<string, string> };
const blankVariant = (): VariantDraft => ({ sku: "", name: "", price: "", quantity: "0", attrs: {} });

const inputCls =
  "h-9 w-full border border-rule bg-paper-raised px-3 text-sm text-ink placeholder:text-ink-faint focus:border-volt focus:outline-none";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <Eyebrow>{title}</Eyebrow>
      <div className="mt-3 space-y-4">{children}</div>
    </section>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-2xs uppercase tracking-[0.1em] text-ink-faint">
        {label}
        {required && <span className="text-volt"> *</span>}
      </span>
      {children}
    </label>
  );
}

function AttrGrid({
  fields,
  values,
  onChange,
}: {
  fields: AttrField[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.map((field) => (
        <Field key={field.key} label={field.label}>
          <input
            className={inputCls}
            value={values[field.key] ?? ""}
            placeholder={field.placeholder}
            onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
          />
        </Field>
      ))}
    </div>
  );
}

function VariantDraftRow({
  draft,
  fields,
  onChange,
  onRemove,
}: {
  draft: VariantDraft;
  fields: AttrField[];
  onChange: (next: VariantDraft) => void;
  onRemove?: (() => void) | undefined;
}) {
  return (
    <div className="border border-rule bg-paper-raised p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="SKU" required>
          <input
            className={inputCls}
            value={draft.sku}
            onChange={(e) => onChange({ ...draft, sku: e.target.value.toUpperCase() })}
            placeholder="TSHIRT-CREW-BLK-M"
          />
        </Field>
        <Field label="Variant name">
          <input className={inputCls} value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} placeholder="Black / M" />
        </Field>
        <Field label="Price (₹)" required>
          <input
            className={inputCls}
            value={draft.price}
            inputMode="decimal"
            onChange={(e) => onChange({ ...draft, price: e.target.value })}
            placeholder="799.00"
          />
        </Field>
        <Field label="Stock">
          <input
            className={inputCls}
            value={draft.quantity}
            inputMode="numeric"
            onChange={(e) => onChange({ ...draft, quantity: e.target.value.replace(/\D/g, "") })}
          />
        </Field>
      </div>
      {fields.length > 0 && (
        <div className="mt-3">
          <AttrGrid fields={fields} values={draft.attrs} onChange={(attrs) => onChange({ ...draft, attrs })} />
        </div>
      )}
      {onRemove && (
        <button type="button" onClick={onRemove} className="mt-2 text-2xs text-critical hover:underline">
          Remove variant
        </button>
      )}
    </div>
  );
}

function ExistingVariantRow({
  variant,
  onPrice,
  onStock,
  onActive,
  busy,
}: {
  variant: MerchantVariant;
  onPrice: (price: string) => void;
  onStock: (quantity: number) => void;
  onActive: (active: boolean) => void;
  busy: boolean;
}) {
  const [price, setPrice] = useState(variant.price);
  const [qty, setQty] = useState(String(variant.quantity));
  return (
    <li className="bg-paper-raised p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{variant.variant_name}</p>
          <p className="tabular text-2xs text-ink-faint">{variant.sku}</p>
        </div>
        <label className="flex items-center gap-1.5 text-2xs text-ink-faint">
          ₹
          <input
            className="h-8 w-24 border border-rule bg-paper px-2 text-sm tabular focus:border-volt focus:outline-none"
            value={price}
            inputMode="decimal"
            onChange={(e) => setPrice(e.target.value)}
            onBlur={() => price !== variant.price && onPrice(price.trim())}
          />
        </label>
        <label className="flex items-center gap-1.5 text-2xs text-ink-faint">
          Stock
          <input
            className="h-8 w-16 border border-rule bg-paper px-2 text-sm tabular focus:border-volt focus:outline-none"
            value={qty}
            inputMode="numeric"
            onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
            onBlur={() => Number(qty) !== variant.quantity && onStock(Number(qty) || 0)}
          />
        </label>
        <StockBadge status={variant.stock_status} />
        <button
          type="button"
          disabled={busy}
          onClick={() => onActive(!variant.variant_active)}
          className="text-2xs text-ink-soft underline underline-offset-2 hover:text-volt disabled:opacity-40"
        >
          {variant.variant_active ? "Deactivate" : "Activate"}
        </button>
      </div>
    </li>
  );
}

function AddVariantInline({
  category,
  onAdd,
  busy,
}: {
  category: string;
  onAdd: (body: { sku: string; name: string; price: string; quantity: number; attributes: Record<string, string | number | boolean> }) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<VariantDraft>(blankVariant());
  const fields = attributeTemplate(category).variant;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 border border-rule px-3 py-1.5 text-2xs transition-colors hover:border-volt"
      >
        + Add variant
      </button>
    );
  }
  return (
    <div className="mt-3">
      <VariantDraftRow draft={draft} fields={fields} onChange={setDraft} />
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          disabled={busy || !draft.sku.trim() || !draft.price.trim()}
          onClick={() => {
            onAdd({
              sku: draft.sku.trim().toUpperCase(),
              name: draft.name.trim() || "Default",
              price: draft.price.trim(),
              quantity: Number(draft.quantity) || 0,
              attributes: buildAttrs(draft.attrs),
            });
            setDraft(blankVariant());
            setOpen(false);
          }}
        >
          Add
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

// -- helpers --------------------------------------------------------

function splitTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function buildAttrs(values: Record<string, string>): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [key, raw] of Object.entries(values)) {
    if (raw.trim()) out[key] = coerceAttrValue(raw);
  }
  return out;
}
