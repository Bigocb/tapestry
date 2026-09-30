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
    splitEntity: vi.fn(),
    undoEntitySplit: vi.fn(),
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
  memories: [
    { id: "m1", title: "The wrong Dave", created_at: "2026-01-01T00:00:00" },
    { id: "m2", title: "The right Dave", created_at: "2026-01-02T00:00:00" },
  ],
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

  it("moves the memories you tick into a new entity", async () => {
    const user = userEvent.setup();
    vi.mocked(api.splitEntity).mockResolvedValue({
      split_id: "sp1",
      source_entity_id: "e1",
      new_entity_id: "e2",
      moved_mention_count: 1,
    });

    render(<EntityDetailView id="e1" />);

    await user.click(await screen.findByLabelText("The wrong Dave"));
    await user.type(screen.getByLabelText(/new entity name/i), "Dave Smith");
    await user.click(screen.getByRole("button", { name: /split out/i }));

    expect(api.splitEntity).toHaveBeenCalledWith("e1", {
      name: "Dave Smith",
      memory_ids: ["m1"],
    });
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
