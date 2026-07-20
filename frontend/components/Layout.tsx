"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  MicrophoneIcon,
  MagnifyingGlassIcon,
  ClockIcon,
  BookOpenIcon,
  ChartBarIcon,
} from "@heroicons/react/24/outline";

export function Layout({ children }: { children: React.ReactNode }) {
  const { token, logout } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-indigo-600 text-white">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link href="/capture" className="text-xl font-bold">
            MEMIND
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
              <NavLink href="/stories" icon={<BookOpenIcon className="w-4 h-4" />}>
                Stories
              </NavLink>
              <NavLink href="/insights" icon={<ChartBarIcon className="w-4 h-4" />}>
                Insights
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
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className="flex items-center gap-1 hover:text-indigo-100">
      {icon}
      <span>{children}</span>
    </Link>
  );
}
