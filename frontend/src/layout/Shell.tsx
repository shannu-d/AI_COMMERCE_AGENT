import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Link, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { getCart } from "../api/endpoints";
import { useAuth } from "../auth/context";
import { cx } from "../components/cx";
import { useToast } from "../components/toastContext";
import { ConciergeLauncher, ConciergePanel } from "../features/concierge/Concierge";
import { useConcierge } from "../features/concierge/conciergeContext";
import { useCategories } from "../features/catalog/useCatalog";
import { readSessionId } from "../session";

/**
 * The application shell.
 *
 * The layout is a two-column grid on desktop: storefront, then the concierge
 * rail. The rail is part of the grid rather than floating above it, so opening
 * the assistant *narrows the catalogue* instead of covering it — the two are
 * peers, which is the whole thesis of this UI.
 *
 * The header carries the EASY BUY wordmark, a centred primary nav
 * (Home / Shopping / Smart Agent / Services) and the account controls; a thin
 * category bar sits directly beneath it. Interaction and emphasis are the only
 * places the volt accent (#94DD26) appears — an active nav item, a hover, the
 * concierge marker — while the surface stays paper, ink and grey.
 */

/** Cart line count, for the header. Cheap, cached, and tolerant of no session. */
function useCartCount() {
  const sessionId = readSessionId();
  const { data } = useQuery({
    queryKey: ["cart", sessionId],
    queryFn: ({ signal }) => getCart(sessionId!, signal),
    enabled: Boolean(sessionId),
    // A 404 means "no cart yet", which is a normal state, not a failure worth
    // retrying or surfacing.
    retry: false,
    staleTime: 5_000,
  });
  return data?.items.reduce((n, item) => n + item.quantity, 0) ?? 0;
}

export function Shell({ children }: { children: ReactNode }) {
  const { isOpen } = useConcierge();

  return (
    <div className="flex min-h-[100dvh] flex-col lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer />
        {/* Clears the fixed mobile launcher so the footer is never trapped. */}
        {!isOpen && <div aria-hidden="true" className="h-16 lg:hidden" />}
      </div>

      <ConciergePanel />
      <ConciergeLauncher />
    </div>
  );
}

/* -- small inline glyphs -------------------------------------------------------
   No icon dependency: three hairline marks drawn to the same 1.6–2.2px weight
   as SpecMark, so they sit in the same family as the rest of the catalogue. */

function CartGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M2.5 3.5h2.2l2.3 11.4a1.8 1.8 0 0 0 1.8 1.5h8.6a1.8 1.8 0 0 0 1.8-1.4L22 7H6" />
      <circle cx="9" cy="20" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18" cy="20" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function UserGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      className={className}
      aria-hidden="true"
    >
      <circle cx="12" cy="8.5" r="3.75" />
      <path d="M4.5 20c1.4-3.9 4.1-5.8 7.5-5.8s6.1 1.9 7.5 5.8" />
    </svg>
  );
}

function Chevron({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 10 6"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <path d="M1 1 L5 5 L9 1" />
    </svg>
  );
}

/* -- primary navigation ------------------------------------------------------ */

type NavAction = "services";
type NavItem =
  | { label: string; to: string; match: (pathname: string) => boolean }
  | { label: string; action: NavAction };

const PRIMARY_NAV: NavItem[] = [
  { label: "Home", to: "/", match: (p) => p === "/" },
  {
    label: "Shopping",
    to: "/c/phone_case",
    match: (p) => p.startsWith("/c/") || p.startsWith("/p/"),
  },
  { label: "Smart Agent", to: "/agent", match: (p) => p === "/agent" },
  { label: "Services", action: "services" },
];

/** Scrolls the footer into view — the "Services" target, kept honest rather
    than pointing at a page that does not exist. Respects reduced motion via the
    global `scroll-behavior` reset. */
function scrollToServices() {
  document.getElementById("site-footer")?.scrollIntoView({ block: "start" });
}

function Header() {
  const { data: categories } = useCategories();
  const count = useCartCount();
  const { open, isOpen } = useConcierge();
  const { pathname } = useLocation();
  const notify = useToast();
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  // The account menu is the one part of the header that changes with who is
  // looking. It shows what the API will actually honour: an anonymous visitor
  // gets sign-in and sign-up, a shopper gets their account and orders, and an
  // administrator gets the dashboard — because `/api/account/orders` answers
  // 403 for a merchant token and the dashboard 403s for a shopper's.
  const accountMenu = !user
    ? [
        { label: "Sign in", to: "/login" },
        { label: "Create an account", to: "/register" },
      ]
    : user.role === "MERCHANT"
      ? [
          { label: "Merchant dashboard", to: "/merchant" },
          {
            label: "Sign out",
            onSelect: () => {
              void signOut().then(() => navigate("/"));
            },
          },
        ]
      : [
          { label: "My profile", to: "/account" },
          { label: "Orders", to: "/account" },
          {
            label: "Sign out",
            onSelect: () => {
              void signOut().then(() => navigate("/"));
            },
          },
        ];

  // The seed has ten categories including structural parents; the bar shows the
  // ones a shopper actually browses rather than every row in the table. The API
  // already returns them slug-sorted, which is the reference's order.
  const primary = (categories ?? []).filter((c) =>
    ["phone_case", "charger", "usb_cable", "earbuds", "power_bank", "screen_protector"].includes(
      c.slug,
    ),
  );

  function runAction(action: NavAction) {
    if (action === "services") scrollToServices();
  }

  function isNavActive(item: NavItem) {
    if ("action" in item) return false;
    return item.match(pathname);
  }

  const navLinkClass = (active: boolean) =>
    cx(
      "whitespace-nowrap text-[1.05rem] transition-colors duration-fast",
      active ? "font-semibold text-volt" : "font-medium text-ink/75 hover:text-volt",
    );

  return (
    <header className="sticky top-0 z-20 border-b border-rule bg-paper/90 backdrop-blur-[6px]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-paper"
      >
        Skip to content
      </a>

      <div className="mx-auto grid h-16 max-w-shell grid-cols-[auto_1fr_auto] items-center gap-3 px-4 sm:px-6 lg:h-24 lg:grid-cols-[1fr_auto_1fr] lg:gap-6">
        <Link
          to="/"
          aria-label="EASY BUY — home"
          className="group flex shrink-0 items-center gap-2.5"
        >
          <CartGlyph className="h-6 w-6 text-volt transition-transform duration-fast ease-out group-hover:-translate-y-0.5 motion-reduce:transform-none lg:h-8 lg:w-8" />
          <span className="text-[1.2rem] font-bold italic tracking-[-0.045em] text-volt lg:text-[1.7rem]">
            EASY BUY
          </span>
        </Link>

        {/* When the concierge rail is docked the storefront loses ~380px, so the
            centred nav waits for the wider breakpoint rather than colliding with
            the account controls. */}
        <nav
          aria-label="Primary"
          className={cx(
            "hidden justify-center gap-7 xl:gap-10",
            isOpen ? "xl:flex" : "lg:flex",
          )}
        >
          {PRIMARY_NAV.map((item) =>
            "to" in item ? (
              <NavLink key={item.label} to={item.to} className={navLinkClass(isNavActive(item))}>
                {item.label}
              </NavLink>
            ) : (
              <button
                key={item.label}
                type="button"
                onClick={() => runAction(item.action)}
                className={navLinkClass(isNavActive(item))}
              >
                {item.label}
              </button>
            ),
          )}
        </nav>

        <div className="flex items-center justify-end gap-1 sm:gap-1.5">
          {/* Redundant once the rail is open — the rail itself and the active
              "Smart Agent" nav item both say so — and hiding it frees the row. */}
          {!isOpen && (
            <button
              type="button"
              onClick={() => open()}
              aria-expanded={isOpen}
              className="hidden items-center gap-2 border border-rule px-3 py-1.5 text-sm text-ink-soft transition-colors duration-fast hover:border-volt hover:text-ink lg:flex"
            >
              <span aria-hidden="true" className="h-1.5 w-1.5 bg-volt" />
              Concierge
            </button>
          )}

          <Link
            to="/cart"
            className={cx(
              "relative flex h-10 items-center gap-2 px-2.5 text-sm transition-colors duration-fast sm:px-3",
              pathname === "/cart" ? "text-volt" : "text-ink-soft hover:text-volt",
            )}
          >
            <span className="hidden sm:inline">Cart</span>
            <CartGlyph className="h-[18px] w-[18px] sm:hidden" />
            <span
              className={cx(
                "tabular grid h-5 min-w-5 place-items-center px-1 text-2xs",
                count > 0 ? "bg-ink text-paper" : "bg-paper-sunken text-ink-faint",
              )}
              aria-label={`${count} item${count === 1 ? "" : "s"} in cart`}
            >
              {count}
            </span>
          </Link>

          <HeaderMenu
            className="hidden lg:block"
            align="end"
            label="More"
            items={[
              {
                label: "Become a merchant",
                onSelect: () =>
                  notify({
                    title: "Become a merchant",
                    detail: "Merchant onboarding is not part of this demo yet.",
                  }),
              },
              { label: "Support", onSelect: scrollToServices },
            ]}
          />

          <HeaderMenu
            align="end"
            trigger={
              <span className="flex items-center gap-1">
                <span
                  className={cx(
                    "grid h-7 w-7 place-items-center rounded-full border text-ink-soft",
                    user ? "border-ink text-ink" : "border-rule",
                  )}
                >
                  <UserGlyph className="h-4 w-4" />
                </span>
                <Chevron className="h-1 w-2 text-ink-faint" />
              </span>
            }
            triggerLabel={user ? `Account: ${user.display_name || user.email}` : "Account"}
            items={accountMenu}
          />

          {/* Mobile: the primary nav folds into one menu rather than a second
              scrolling row on top of the category bar. */}
          <HeaderMenu
            align="end"
            className="lg:hidden"
            triggerLabel="Menu"
            trigger={
              <svg
                viewBox="0 0 20 20"
                className="h-5 w-5 text-ink-soft"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M3 6h14M3 10h14M3 14h14" />
              </svg>
            }
            items={[
              { label: "Home", to: "/" },
              { label: "Shopping", to: "/c/phone_case" },
              { label: "Smart Agent", to: "/agent" },
              { label: "Services", onSelect: scrollToServices },
              {
                label: "Become a merchant",
                onSelect: () =>
                  notify({
                    title: "Become a merchant",
                    detail: "Merchant onboarding is not part of this demo yet.",
                  }),
              },
              { label: "Support", onSelect: scrollToServices },
            ]}
          />
        </div>
      </div>

      <CategoryBar
        items={primary.map((c) => ({ slug: c.slug, name: c.name }))}
      />
    </header>
  );
}

/* -- category bar ----------------------------------------------------------- */

function CategoryBar({ items }: { items: Array<{ slug: string; name: string }> }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Product categories" className="border-t border-rule/70">
      <ul className="scroll-quiet mx-auto flex max-w-shell items-center gap-x-9 overflow-x-auto px-4 py-3 sm:px-6 lg:justify-center">
        {items.map((c) => (
          <li key={c.slug}>
            <NavLink
              to={`/c/${c.slug}`}
              className={({ isActive }) =>
                cx(
                  "block whitespace-nowrap py-0.5 text-sm transition-colors duration-fast",
                  isActive ? "text-volt" : "text-ink-faint hover:text-volt",
                )
              }
            >
              {c.name}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/* -- header dropdown ------------------------------------------------------------
   A minimal disclosure: closes on outside click, on Escape, and on navigation.
   The "More" and account controls hang decorative-but-honest actions off it. */

type MenuItem =
  | { label: string; to: string }
  | { label: string; onSelect: () => void };

function HeaderMenu({
  label,
  trigger,
  triggerLabel,
  items,
  align = "start",
  className,
}: {
  label?: string;
  trigger?: ReactNode;
  triggerLabel?: string;
  items: MenuItem[];
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function choose(item: MenuItem) {
    setOpen(false);
    if ("to" in item) navigate(item.to);
    else item.onSelect();
  }

  return (
    <div ref={rootRef} className={cx("relative", className)}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={triggerLabel ?? label}
        onClick={() => setOpen((v) => !v)}
        className={cx(
          "flex items-center gap-1 px-2 py-1.5 text-sm transition-colors duration-fast",
          open ? "text-ink" : "text-ink-soft hover:text-volt",
        )}
      >
        {trigger ?? (
          <>
            {label}
            <Chevron
              className={cx(
                "h-1 w-2 transition-transform duration-fast",
                open && "rotate-180",
              )}
            />
          </>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className={cx(
            "animate-fade absolute top-full z-30 mt-1 min-w-44 border border-rule bg-paper-raised py-1 shadow-[0_1px_0_rgb(var(--rule))]",
            align === "end" ? "right-0" : "left-0",
          )}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => choose(item)}
              className="block w-full whitespace-nowrap px-3 py-2 text-left text-sm text-ink-soft transition-colors duration-fast hover:bg-paper-sunken hover:text-volt"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Footer() {
  return (
    <footer id="site-footer" className="mt-16 scroll-mt-24 border-t border-rule">
      <div className="mx-auto max-w-shell px-4 py-8 sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="-skew-x-6 text-[0.95rem] font-bold italic tracking-[-0.03em] text-ink">
              EASY BUY
            </p>
            {/* Stated plainly because it is the product's actual guarantee, and
                because it is true: every price and stock figure on this site is
                read from the catalogue, and the total is computed by the server. */}
            <p className="mt-1.5 max-w-md text-2xs leading-relaxed text-ink-faint">
              Prices, stock and compatibility are read from the live catalogue. Totals are computed
              by the server and re-checked before any payment is taken.
            </p>
          </div>
          <p className="eyebrow">Payments by Razorpay · INR</p>
        </div>
      </div>
    </footer>
  );
}
