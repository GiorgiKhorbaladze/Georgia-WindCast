"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

export interface NavItem {
  href: string;
  label: string;
}

interface MenuLabels {
  open: string;
  close: string;
  label: string;
}

/**
 * Inline navigation on large screens; a disclosure menu below the lg breakpoint.
 * The toggle exposes aria-expanded/aria-controls, Escape closes the menu and returns focus to the
 * toggle, and the menu closes on navigation. On small screens the menu needs JavaScript (as do the
 * charts and the map); the dashboard links to the main sections as a fallback.
 */
export function NavLinks({ items, label, menu }: { items: NavItem[]; label: string; menu: MenuLabels }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const listId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Close the menu after navigating (state adjusted during render, not in an effect).
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <nav aria-label={label} className="relative">
      <button
        ref={toggleRef}
        type="button"
        className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm text-slate-200 hover:bg-white/5 lg:hidden"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={open ? menu.close : menu.open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4">
          {open ? (
            <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          ) : (
            <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          )}
        </svg>
        <span className="hidden sm:inline">{menu.label}</span>
      </button>
      <ul
        id={listId}
        className={`${open ? "flex" : "hidden"} absolute right-0 top-full z-30 mt-2 min-w-48 flex-col gap-1 rounded-lg border border-line bg-ink-950 p-2 shadow-xl lg:static lg:mt-0 lg:flex lg:min-w-0 lg:flex-row lg:border-0 lg:bg-transparent lg:p-0 lg:shadow-none`}
      >
        {items.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`block whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-cyan-glow/10 text-cyan-glow shadow-[inset_0_-2px_0_0_var(--color-cyan-glow)]"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
