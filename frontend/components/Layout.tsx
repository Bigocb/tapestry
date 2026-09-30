"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import {
  MicrophoneIcon,
  MagnifyingGlassIcon,
  ClockIcon,
  BookOpenIcon,
  ChartBarIcon,
  InboxIcon,
  UsersIcon,
  MapPinIcon,
  EllipsisHorizontalIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";

const RAIL_ITEMS = [
  { href: "/timeline", label: "Timeline", icon: ClockIcon },
  { href: "/search", label: "Search", icon: MagnifyingGlassIcon },
  { href: "/people", label: "People", icon: UsersIcon },
  { href: "/places", label: "Places", icon: MapPinIcon },
  { href: "/stories", label: "Stories", icon: BookOpenIcon },
  { href: "/insights", label: "Insights", icon: ChartBarIcon },
  { href: "/review", label: "Review", icon: InboxIcon, badgeKey: true },
] as const;

// The bottom bar only has room for four icons either side of the FAB, so the
// remaining sections live behind "More" rather than getting dropped.
const BOTTOM_PRIMARY = RAIL_ITEMS.filter((i) =>
  ["/timeline", "/search", "/people", "/places"].includes(i.href)
);
const MORE_ITEMS = RAIL_ITEMS.filter(
  (i) => !["/timeline", "/search", "/people", "/places"].includes(i.href)
);

type NavItem = (typeof RAIL_ITEMS)[number];

export function Layout({ children }: { children: React.ReactNode }) {
  const { token, logout } = useAuth();
  const pathname = usePathname();
  const [reviewCount, setReviewCount] = useState(0);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    api
      .getReviewCount()
      .then((data) => {
        if (active) setReviewCount(data?.count ?? 0);
      })
      .catch(() => {
        if (active) setReviewCount(0);
      });
    return () => {
      active = false;
    };
  }, [token, pathname]);

  if (!token) {
    return <main className="min-h-screen w-full bg-bg">{children}</main>;
  }

  return (
    <div className="min-h-screen flex bg-bg">
      {/* Desktop rail */}
      <nav className="hidden md:flex fixed left-0 top-0 bottom-0 w-[84px] bg-bg-raised border-r border-line flex-col items-center py-6 gap-1.5 z-20">
        <span className="w-3 h-3 rounded-full bg-flash fab-pulse mb-4" aria-hidden="true" />
        <Link
          href="/timeline"
          aria-label="Timeline"
          aria-current={pathname === "/timeline"}
          className={railClass(pathname === "/timeline")}
        >
          <ClockIcon className="w-[22px] h-[22px]" />
        </Link>
        <Link
          href="/search"
          aria-label="Search"
          aria-current={pathname === "/search"}
          className={railClass(pathname === "/search")}
        >
          <MagnifyingGlassIcon className="w-[22px] h-[22px]" />
        </Link>

        <Link
          href="/capture"
          aria-label="Capture a memory"
          className="w-[58px] h-[58px] rounded-full bg-flash text-flash-ink flex items-center justify-center my-1.5 fab-pulse"
        >
          <MicrophoneIcon className="w-6 h-6" />
        </Link>

        <Link
          href="/people"
          aria-label="People"
          aria-current={pathname === "/people"}
          className={railClass(pathname === "/people")}
        >
          <UsersIcon className="w-[22px] h-[22px]" />
        </Link>
        <Link
          href="/places"
          aria-label="Places"
          aria-current={pathname === "/places"}
          className={railClass(pathname === "/places")}
        >
          <MapPinIcon className="w-[22px] h-[22px]" />
        </Link>
        <Link
          href="/stories"
          aria-label="Stories"
          aria-current={pathname === "/stories"}
          className={railClass(pathname === "/stories")}
        >
          <BookOpenIcon className="w-[22px] h-[22px]" />
        </Link>
        <Link
          href="/insights"
          aria-label="Insights"
          aria-current={pathname === "/insights"}
          className={railClass(pathname === "/insights")}
        >
          <ChartBarIcon className="w-[22px] h-[22px]" />
        </Link>
        <Link
          href="/review"
          aria-label="Review"
          aria-current={pathname === "/review"}
          className={`relative ${railClass(pathname === "/review")}`}
        >
          <InboxIcon className="w-[22px] h-[22px]" />
          {reviewCount > 0 && <RailBadge count={reviewCount} />}
        </Link>

        <div className="flex-1" />
        <button
          onClick={logout}
          className="px-2 py-1.5 text-ink-faint hover:text-ink text-xs"
        >
          Logout
        </button>
      </nav>

      <main className="flex-1 min-w-0 md:ml-[84px] px-4 md:px-8 py-8 md:py-10 pb-24 md:pb-10 w-full max-w-5xl mx-auto">
        {children}
      </main>

      {/* Mobile bottom bar */}
      <nav className="md:hidden fixed left-0 right-0 bottom-0 bg-bg-raised border-t border-line flex items-center justify-between px-4 py-2.5 z-20">
        {BOTTOM_PRIMARY.slice(0, 2).map((item) => (
          <BottomLink key={item.href} item={item} active={pathname === item.href} />
        ))}
        <Link
          href="/capture"
          aria-label="Capture a memory"
          className="w-14 h-14 rounded-full bg-flash text-flash-ink flex items-center justify-center -translate-y-3.5 fab-pulse"
        >
          <MicrophoneIcon className="w-6 h-6" />
        </Link>
        {BOTTOM_PRIMARY.slice(2, 4).map((item) => (
          <BottomLink key={item.href} item={item} active={pathname === item.href} />
        ))}
        <button
          onClick={() => setMoreOpen(true)}
          aria-label="More"
          className="relative w-11 h-11 rounded-xl flex items-center justify-center text-ink-muted"
        >
          <EllipsisHorizontalIcon className="w-6 h-6" />
          {reviewCount > 0 && <RailBadge count={reviewCount} />}
        </button>
      </nav>

      {moreOpen && (
        <div className="md:hidden fixed inset-0 z-30">
          <button
            className="absolute inset-0 bg-bg/70"
            aria-label="Close menu"
            onClick={() => setMoreOpen(false)}
          />
          <div className="absolute right-0 bottom-0 top-0 w-64 bg-bg-raised border-l border-line flex flex-col">
            <div className="h-14 px-4 flex items-center justify-between border-b border-line">
              <span className="font-display text-sm text-ink-muted">More</span>
              <button onClick={() => setMoreOpen(false)} aria-label="Close menu">
                <XMarkIcon className="w-5 h-5 text-ink-muted" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto py-2">
              {MORE_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMoreOpen(false)}
                  className={`flex items-center gap-3 px-4 py-3 text-sm ${
                    pathname === item.href
                      ? "text-flash bg-surface-2"
                      : "text-ink hover:bg-surface"
                  }`}
                >
                  <item.icon className="w-5 h-5" />
                  {item.label}
                  {"badgeKey" in item && item.badgeKey && reviewCount > 0 && (
                    <span className="ml-auto bg-flash text-flash-ink text-xs font-bold rounded-full min-w-[20px] h-5 px-1.5 flex items-center justify-center">
                      {reviewCount}
                    </span>
                  )}
                </Link>
              ))}
            </div>
            <button
              onClick={logout}
              className="m-4 px-3 py-2 border border-line rounded-lg text-sm text-ink-muted hover:bg-surface"
            >
              Logout
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function railClass(active: boolean): string {
  return `relative w-[52px] h-[52px] rounded-2xl flex items-center justify-center transition ${
    active ? "text-flash bg-surface-2" : "text-ink-muted hover:text-ink hover:bg-surface"
  }`;
}

function RailBadge({ count }: { count: number }) {
  return (
    <span className="absolute top-1 right-1 bg-flash text-flash-ink text-[10px] font-bold rounded-full min-w-[16px] h-4 px-1 flex items-center justify-center">
      {count}
    </span>
  );
}

function BottomLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={active}
      className={`w-11 h-11 rounded-xl flex items-center justify-center ${
        active ? "text-flash" : "text-ink-muted"
      }`}
    >
      <Icon className="w-6 h-6" />
    </Link>
  );
}
