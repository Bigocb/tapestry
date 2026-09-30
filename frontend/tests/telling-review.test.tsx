import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("rejects a segment and shows that it will be left out", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateTellingSegment).mockResolvedValue({
      id: "s2",
      ordinal: 1,
      text: "The next day we went to Disney.",
      status: "rejected",
      title: "Disney",
    });

    render(<TellingReview tellingId="t1" />);
    const cards = await screen.findAllByTestId("telling-segment");

    await user.click(within(cards[1]).getByRole("button", { name: "Reject" }));

    expect(api.updateTellingSegment).toHaveBeenCalledWith("t1", "s2", {
      status: "rejected",
    });

    const updated = await screen.findAllByTestId("telling-segment");
    expect(
      within(updated[1]).getByText(/will not become a memory/i)
    ).toBeInTheDocument();
  });

  it("commits the split and reports how many memories it created", async () => {
    const user = userEvent.setup();
    vi.mocked(api.commitTelling).mockResolvedValue(
      telling({
        status: "committed",
        segments: [
          {
            id: "s1",
            ordinal: 0,
            text: "In the summer of 1985 we drove down to Florida.",
            status: "accepted",
            title: "Trip to Florida",
            memory_id: "m1",
          },
          {
            id: "s2",
            ordinal: 1,
            text: "The next day we went to Disney.",
            status: "rejected",
            title: "Disney",
            memory_id: null,
          },
        ],
      })
    );

    render(<TellingReview tellingId="t1" />);
    await screen.findAllByTestId("telling-segment");

    await user.click(
      screen.getByRole("button", { name: /save these memories/i })
    );

    expect(api.commitTelling).toHaveBeenCalledWith("t1");
    expect(await screen.findByText(/1 memory created/i)).toBeInTheDocument();
  });
});

describe("TellingReview dates", () => {
  beforeEach(() => {
    vi.mocked(api.getTelling).mockResolvedValue(
      telling({
        segments: [
          {
            id: "s1",
            ordinal: 0,
            text: "First memory.",
            status: "proposed",
            title: "Labelled",
            date_label: "first month in high school",
          },
          {
            id: "s2",
            ordinal: 1,
            text: "Second memory.",
            status: "proposed",
            title: "Resolved from the cursor",
            event_date: "2003-08-01T00:00:00",
            date_precision: "month",
          },
          {
            id: "s3",
            ordinal: 2,
            text: "Third memory.",
            status: "proposed",
            title: "Undated",
          },
        ],
      })
    );
  });

  it("shows each segment's resolved date, and says so when there is none", async () => {
    render(<TellingReview tellingId="t1" />);
    const cards = await screen.findAllByTestId("telling-segment");

    // A fuzzy period is shown in the account's own words.
    expect(
      within(cards[0]).getByText("first month in high school")
    ).toBeInTheDocument();
    // The year is locale-independent, unlike the month name.
    expect(within(cards[1]).getByText(/2003/)).toBeInTheDocument();
    // Silence would hide a draft the user still needs to date.
    expect(within(cards[2]).getByText("No date")).toBeInTheDocument();
  });

  it("shows the period the telling is about", async () => {
    vi.mocked(api.getTelling).mockResolvedValue(
      telling({ frame_label: "first month in high school" })
    );

    render(<TellingReview tellingId="t1" />);

    // Without this the inherited label appears from nowhere.
    expect(
      await screen.findByText(/first month in high school/)
    ).toBeInTheDocument();
  });
});

describe("TellingReview date correction", () => {
  beforeEach(() => {
    vi.mocked(api.getTelling).mockResolvedValue(
      telling({
        segments: [
          {
            id: "s1",
            ordinal: 0,
            text: "In August 2003 I started high school.",
            status: "proposed",
            title: "Trip to Florida",
            event_date: "2003-08-01T00:00:00",
            date_precision: "month",
          },
        ],
      })
    );
  });

  it("saves a corrected date and precision", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateTellingSegment).mockResolvedValue({
      id: "s1",
      ordinal: 0,
      text: "In August 2003 I started high school.",
      status: "proposed",
      title: "Trip to Florida",
      event_date: "1985-07-01T00:00:00",
      date_precision: "year",
    });

    render(<TellingReview tellingId="t1" />);
    const cards = await screen.findAllByTestId("telling-segment");
    const card = within(cards[0]);

    // fireEvent rather than userEvent: jsdom's date input does not accept
    // typed characters the way a real one does.
    fireEvent.change(card.getByLabelText("Date"), {
      target: { value: "1985-07-01" },
    });
    fireEvent.change(card.getByLabelText("Precision"), {
      target: { value: "year" },
    });
    await user.click(card.getByRole("button", { name: "Save" }));

    expect(api.updateTellingSegment).toHaveBeenCalledWith("t1", "s1", {
      title: "Trip to Florida",
      event_date: "1985-07-01T00:00:00",
      date_precision: "year",
      date_label: null,
    });
  });

  it("leaves the date untouched when only the title changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateTellingSegment).mockResolvedValue({
      id: "s1",
      ordinal: 0,
      text: "In August 2003 I started high school.",
      status: "proposed",
      title: "Renamed",
      event_date: "2003-08-01T00:00:00",
      date_precision: "month",
    });

    render(<TellingReview tellingId="t1" />);
    const cards = await screen.findAllByTestId("telling-segment");
    const card = within(cards[0]);

    const titleInput = card.getByLabelText("Title");
    await user.clear(titleInput);
    await user.type(titleInput, "Renamed");
    await user.click(card.getByRole("button", { name: "Save" }));

    // Sending dates here would wipe a fuzzy label the user never touched.
    expect(api.updateTellingSegment).toHaveBeenCalledWith("t1", "s1", {
      title: "Renamed",
    });
  });
});
