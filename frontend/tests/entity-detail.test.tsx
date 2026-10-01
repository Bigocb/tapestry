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
    lookupEntity: vi.fn(),
    keepEntityFact: vi.fn(),
    discardEntityFact: vi.fn(),
    updateEntity: vi.fn(),
    verifyAddress: vi.fn(),
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

const THEATRE = {
  id: "e5",
  kind: "place",
  canonical_name: "Mission Valley Theater",
  mention_count: 1,
  aliases: ["mission valley theater"],
  memories: [],
  facts: [],
};

const CANDIDATE = {
  source: "wikidata",
  source_id: "Q43096397",
  label: "Mission Valley Cinemas",
  description: "movie theater in Raleigh, North Carolina",
  url: "http://www.wikidata.org/entity/Q43096397",
};

describe("EntityDetailView lookup", () => {
  beforeEach(() => {
    vi.mocked(api.getEntity).mockResolvedValue(THEATRE);
    vi.mocked(api.getMergeSuggestions).mockResolvedValue([]);
    vi.mocked(api.getEntities).mockResolvedValue({
      items: [THEATRE],
      total: 1,
      limit: 200,
      offset: 0,
    });
  });

  it("keeps the candidate you choose, not the first one offered", async () => {
    const user = userEvent.setup();
    vi.mocked(api.lookupEntity).mockResolvedValue([
      CANDIDATE,
      { ...CANDIDATE, source_id: "Q999", label: "Somewhere else" },
    ]);
    vi.mocked(api.keepEntityFact).mockResolvedValue({
      id: "f1",
      ...CANDIDATE,
      fetched_at: "2026-01-01T00:00:00",
    });

    render(<EntityDetailView id="e5" />);

    await user.click(
      await screen.findByRole("button", { name: /look this up/i })
    );

    // Both are shown, because "Raleigh" matches three different things.
    expect(await screen.findByText("Mission Valley Cinemas")).toBeInTheDocument();
    expect(screen.getByText("Somewhere else")).toBeInTheDocument();

    const keeps = screen.getAllByRole("button", { name: /keep this/i });
    await user.click(keeps[1]);

    expect(api.keepEntityFact).toHaveBeenCalledWith("e5", {
      source: "wikidata",
      source_id: "Q999",
      label: "Somewhere else",
      description: CANDIDATE.description,
      url: CANDIDATE.url,
    });
  });

  it("says so when nothing is found", async () => {
    const user = userEvent.setup();
    vi.mocked(api.lookupEntity).mockResolvedValue([]);

    render(<EntityDetailView id="e5" />);
    await user.click(
      await screen.findByRole("button", { name: /look this up/i })
    );

    expect(
      await screen.findByText(/nothing found under that name/i)
    ).toBeInTheDocument();
  });
});

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

  it("offers no lookup on a person", async () => {
    render(<EntityDetailView id="e1" />);

    await screen.findByText("Dave");
    // Resolving a first name to a real individual is unreliable and invasive.
    expect(
      screen.queryByRole("button", { name: /look this up/i })
    ).not.toBeInTheDocument();
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

describe("EntityDetailView editing the card", () => {
  beforeEach(() => {
    vi.mocked(api.getEntity).mockResolvedValue(THEATRE);
    vi.mocked(api.getMergeSuggestions).mockResolvedValue([]);
    vi.mocked(api.getEntities).mockResolvedValue({
      items: [THEATRE],
      total: 1,
      limit: 200,
      offset: 0,
    });
  });

  it("renames a place from the card", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateEntity).mockResolvedValue({
      ...THEATRE,
      canonical_name: "Mission Valley Cinemas",
    });

    render(<EntityDetailView id="e5" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    const name = screen.getByLabelText(/^name$/i);
    await user.clear(name);
    await user.type(name, "Mission Valley Cinemas");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.updateEntity).toHaveBeenCalledWith("e5", {
      canonical_name: "Mission Valley Cinemas",
    });
  });

  it("adds an address to a place, and only the address", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateEntity).mockResolvedValue(THEATRE);

    render(<EntityDetailView id="e5" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(
      screen.getByLabelText(/^address$/i),
      "1201 Larimer St, Denver"
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    // Untouched fields are omitted, not sent back unchanged. The address brings
    // its coordinates with it, and here there are none to bring.
    expect(api.updateEntity).toHaveBeenCalledWith("e5", {
      address: "1201 Larimer St, Denver",
      latitude: null,
      longitude: null,
    });
  });

  it("sends no request when nothing changed", async () => {
    const user = userEvent.setup();
    render(<EntityDetailView id="e5" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.updateEntity).not.toHaveBeenCalled();
  });

  it("offers no address field on a person", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getEntity).mockResolvedValue(DAVE);

    render(<EntityDetailView id="e1" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));

    // A person does not have an address; a description is fine.
    expect(screen.queryByLabelText(/^address$/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^description$/i)).toBeInTheDocument();
  });

  it("verifies an address and saves the coordinates with it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.verifyAddress).mockResolvedValue([
      {
        source: "nominatim",
        source_id: "node/123456",
        label: "1201 Larimer Street",
        description: null,
        url: "https://www.openstreetmap.org/node/123456",
        latitude: 39.739236,
        longitude: -104.990251,
        address: "1201 Larimer Street, Denver, Colorado, 80204, United States",
      },
    ]);
    vi.mocked(api.updateEntity).mockResolvedValue(THEATRE);

    render(<EntityDetailView id="e5" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^address$/i), "1201 Larimer St");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    // The candidate's canonical address replaces what was typed.
    await user.click(await screen.findByRole("button", { name: /use this/i }));

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.updateEntity).toHaveBeenCalledWith("e5", {
      address: "1201 Larimer Street, Denver, Colorado, 80204, United States",
      latitude: 39.739236,
      longitude: -104.990251,
    });
  });

  it("does not invent coordinates when none were verified", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateEntity).mockResolvedValue(THEATRE);

    render(<EntityDetailView id="e5" />);

    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    await user.type(screen.getByLabelText(/^address$/i), "somewhere I typed");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.updateEntity).toHaveBeenCalledWith("e5", {
      address: "somewhere I typed",
      latitude: null,
      longitude: null,
    });
  });
});
