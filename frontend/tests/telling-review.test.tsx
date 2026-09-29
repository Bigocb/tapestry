import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TellingReview } from "@/components/TellingReview";
import { api, type Telling } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getTelling: vi.fn(),
    updateTellingSegment: vi.fn(),
    commitTelling: vi.fn(),
  },
}));

const TRANSCRIPT =
  "In the summer of 1985 we drove down to Florida. The next day we went to Disney.";

function telling(overrides: Partial<Telling> = {}): Telling {
  return {
    id: "t1",
    raw_transcript: TRANSCRIPT,
    input_type: "text",
    status: "draft",
    created_at: "2026-01-01T00:00:00",
    segments: [
      {
        id: "s1",
        ordinal: 0,
        text: "In the summer of 1985 we drove down to Florida.",
        status: "proposed",
        title: "Trip to Florida",
      },
      {
        id: "s2",
        ordinal: 1,
        text: "The next day we went to Disney.",
        status: "proposed",
        title: "Disney",
      },
    ],
    ...overrides,
  };
}

describe("TellingReview", () => {
  beforeEach(() => {
    vi.mocked(api.getTelling).mockResolvedValue(telling());
  });

  it("renders the transcript and one card per proposed segment", async () => {
    render(<TellingReview tellingId="t1" />);

    expect(await screen.findByTestId("telling-transcript")).toHaveTextContent(
      /we drove down to Florida/
    );
    expect(screen.getAllByTestId("telling-segment")).toHaveLength(2);
    expect(screen.getByText("Trip to Florida")).toBeInTheDocument();
    expect(screen.getByText("Disney")).toBeInTheDocument();
  });

  it("saves an edited title through the API", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateTellingSegment).mockResolvedValue({
      id: "s1",
      ordinal: 0,
      text: "In the summer of 1985 we drove down to Florida.",
      status: "proposed",
      title: "Renamed",
    });

    render(<TellingReview tellingId="t1" />);
    const cards = await screen.findAllByTestId("telling-segment");
    const first = within(cards[0]);

    const input = first.getByLabelText("Title");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.click(first.getByRole("button", { name: "Save" }));

    expect(api.updateTellingSegment).toHaveBeenCalledWith("t1", "s1", {
      title: "Renamed",
    });
  });
});
