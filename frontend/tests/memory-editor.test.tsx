import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryEditor } from "@/components/MemoryEditor";
import { api } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

vi.mock("@/lib/api", () => ({
  api: {
    getMemory: vi.fn(),
    getRelatedMemories: vi.fn(),
    getEntities: vi.fn(),
    updateMemory: vi.fn(),
    deleteMemory: vi.fn(),
  },
}));

vi.mock("@/lib/privacy", () => ({
  usePrivacy: () => ({
    isUnlocked: () => false,
    unlock: vi.fn(),
    relock: vi.fn(),
  }),
}));

const FUZZY = {
  id: "m1",
  raw_input: "the 80s",
  title: "The 80s",
  created_at: "2026-01-01T00:00:00",
  event_date: "1980-01-01T00:00:00",
  date_precision: "decade",
  date_label: "1980s",
};

describe("MemoryEditor exact dates", () => {
  beforeEach(() => {
    vi.mocked(api.getMemory).mockResolvedValue(FUZZY);
    vi.mocked(api.getRelatedMemories).mockResolvedValue({ items: [] });
    vi.mocked(api.getEntities).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.updateMemory).mockResolvedValue(FUZZY);
  });

  it("sends a coherent exact date, clearing the fuzzy fields with it", async () => {
    const user = userEvent.setup();
    render(<MemoryEditor id="m1" />);

    // A fuzzy memory opens in fuzzy mode; switch to the exact date field.
    await user.click(await screen.findByText("Exact date"));
    const date = screen.getByDisplayValue(/1980-01-01/);
    fireEvent.change(date, { target: { value: "1988-09-17T00:00" } });

    await user.click(screen.getByRole("button", { name: /save changes/i }));

    // The old label and decade precision must not ride along, or the server
    // writes the memory straight back to where it was.
    expect(api.updateMemory).toHaveBeenCalledWith(
      "m1",
      expect.objectContaining({
        date_precision: "exact",
        date_label: null,
        event_date_end: null,
      })
    );
  });
});
