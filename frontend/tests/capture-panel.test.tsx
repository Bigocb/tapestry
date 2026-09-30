import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CapturePanel } from "@/components/CapturePanel";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    captureText: vi.fn(),
    captureForm: vi.fn(),
    captureVoice: vi.fn(),
    getTellings: vi.fn().mockResolvedValue([]),
    createTelling: vi.fn(),
    createVoiceTelling: vi.fn(),
  },
}));

describe("CapturePanel modes", () => {
  it("only shows the story form when the Story tab is selected", async () => {
    const user = userEvent.setup();
    render(<CapturePanel />);

    // Capture defaults to text, so a story form must not be showing.
    expect(
      screen.queryByLabelText(/what do you want to tell/i)
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Story" }));

    expect(
      screen.getByLabelText(/what do you want to tell/i)
    ).toBeInTheDocument();
  });

  it("hides the story form again when leaving the Story tab", async () => {
    const user = userEvent.setup();
    render(<CapturePanel />);

    await user.click(screen.getByRole("button", { name: "Story" }));
    await user.click(screen.getByRole("button", { name: "Memory" }));

    expect(
      screen.queryByLabelText(/what do you want to tell/i)
    ).not.toBeInTheDocument();
  });
});
