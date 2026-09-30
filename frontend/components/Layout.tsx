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
} from "@heroicons/react/24/outline";

export function Layout({ children }: { children: React.ReactNode }) {
  const { token, logout } = useAuth();
  const pathname = usePathname();
  const [reviewCount, setReviewCount] = useState(0);

  useEffect(() => {
    if (!token) {
      return;
    }
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

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-indigo-600 text-white">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link href="/capture" className="text-xl font-bold">
            Tapestry
          </Link>
          {token && (
            <nav className="flex items-center gap-4 text-sm">
              <NavLink href="/capture" icon={<MicrophoneIcon className="w-4 h-4" />}>
                Capture
              </NavLink>
              <NavLink href="/search" icon={<MagnifyingGlassIcon className="w-4 h-4" />}>
                Search
              </NavLink>
              <NavLink href="/timeline" icon={<ClockIcon className="w-4 h-4" />}>
                Timeline
              </NavLink>
              <NavLink href="/people" icon={<UsersIcon className="w-4 h-4" />}>
                People
              </NavLink>
              <NavLink href="/places" icon={<MapPinIcon className="w-4 h-4" />}>
                Places
              </NavLink>
              <NavLink href="/stories" icon={<BookOpenIcon className="w-4 h-4" />}>
                Stories
              </NavLink>
              <NavLink href="/insights" icon={<ChartBarIcon className="w-4 h-4" />}>
                Insights
              </NavLink>
              <NavLink
                href="/review"
                icon={<InboxIcon className="w-4 h-4" />}
                badge={reviewCount}
              >
                Review
              </NavLink>
              <button
                onClick={logout}
                className="ml-4 px-3 py-1 bg-white/10 rounded hover:bg-white/20"
              >
                Logout
              </button>
            </nav>
          )}
        </div>
      </header>
      <main className="flex-1 max-w-6xl mx-auto px-4 py-8 w-full">{children}</main>
    </div>
  );
}

function NavLink({
  href,
  icon,
  children,
  badge,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  badge?: number;
}) {
  return (
    <Link href={href} className="flex items-center gap-1 hover:text-indigo-100">
      {icon}
      <span>{children}</span>
      {badge !== undefined && badge > 0 && (
        <span className="ml-1 bg-amber-400 text-amber-950 text-xs font-semibold rounded-full px-1.5 min-w-[1.25rem] text-center">
          {badge}
        </span>
      )}
    </Link>
  );
}
