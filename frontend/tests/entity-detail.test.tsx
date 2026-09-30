import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EntityDetailView } from "@/components/EntityDetailView";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getEntity: vi.fn(),
    getEntities: vi.fn(),
    getMergeSuggestions: vi.fn(),
    mergeEntities: vi.fn(),
    undoEntityMerge: vi.fn(),
  },
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

const DAVE = {
  id: "e1",
  kind: "person",
  canonical_name: "Dave",
  mention_count: 2,
  aliases: ["dave"],
  memories: [],
};

const DAVE_SMITH = {
  id: "e9",
  kind: "person",
  canonical_name: "Dave Smith",
  mention_count: 1,
};

describe("EntityDetailView manual merge", () => {
  beforeEach(() => {
    vi.mocked(api.getEntity).mockResolvedValue(DAVE);
    // The automation suggests nothing — which used to mean nothing could be
    // merged at all.
    vi.mocked(api.getMergeSuggestions).mockResolvedValue([]);
    vi.mocked(api.getEntities).mockResolvedValue({
      items: [DAVE, DAVE_SMITH],
      total: 2,
      limit: 200,
      offset: 0,
    });
    vi.mocked(api.mergeEntities).mockResolvedValue({ merge_id: "m1" });
  });

  it("merges into an entity you choose yourself", async () => {
    const user = userEvent.setup();
    render(<EntityDetailView id="e1" />);

    const picker = await screen.findByLabelText(/merge into/i);
    // The choices arrive a tick after the entity does.
    await screen.findByRole("option", { name: /dave smith/i });
    await user.selectOptions(picker, "e9");

    await user.click(screen.getByRole("button", { name: /^merge$/i }));

    expect(api.mergeEntities).toHaveBeenCalledWith("e1", "e9");
  });

  it("never offers the entity itself as a merge target", async () => {
    render(<EntityDetailView id="e1" />);

    const picker = await screen.findByLabelText(/merge into/i);
    const options = Array.from(picker.querySelectorAll("option")).map(
      (option) => option.value
    );

    expect(options).not.toContain("e1");
  });
});
