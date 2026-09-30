import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TellingCapture } from "@/components/TellingCapture";
import { api, type Telling } from "@/lib/api";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    createTelling: vi.fn(),
  },
}));

const TRANSCRIPT =
  "In the summer of 1985 we drove down to Florida. The next day we went to Disney.";

const CREATED: Telling = {
  id: "t1",
  raw_transcript: TRANSCRIPT,
  input_type: "text",
  status: "draft",
  created_at: "2026-01-01T00:00:00",
  segments: [],
};

describe("TellingCapture", () => {
  it("posts the story and opens its review screen", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createTelling).mockResolvedValue(CREATED);

    render(<TellingCapture />);

    await user.type(
      screen.getByLabelText(/what do you want to tell/i),
      TRANSCRIPT
    );
    await user.click(screen.getByRole("button", { name: /tell it/i }));

    expect(api.createTelling).toHaveBeenCalledWith(TRANSCRIPT);
    expect(push).toHaveBeenCalledWith("/tellings/t1");
  });
});
