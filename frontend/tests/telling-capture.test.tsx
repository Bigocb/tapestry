import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TellingCapture } from "@/components/TellingCapture";
import { api, type Telling } from "@/lib/api";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getTellings: vi.fn(),
    createTelling: vi.fn(),
    createVoiceTelling: vi.fn(),
  },
}));

beforeEach(() => {
  // Nothing waiting by default; individual tests opt in.
  vi.mocked(api.getTellings).mockResolvedValue([]);
});

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

  it("uploads a recording and opens its review screen", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createVoiceTelling).mockResolvedValue(CREATED);

    render(<TellingCapture />);

    const file = new File(["pretend audio"], "story.webm", {
      type: "audio/webm",
    });
    fireEvent.change(screen.getByLabelText(/upload a recording/i), {
      target: { files: [file] },
    });
    await user.click(
      screen.getByRole("button", { name: /upload recording/i })
    );

    expect(api.createVoiceTelling).toHaveBeenCalledWith(file);
    expect(push).toHaveBeenCalledWith("/tellings/t1");
  });

  it("records a story in the browser and uploads it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createVoiceTelling).mockResolvedValue(CREATED);

    // jsdom has no MediaRecorder, so stand one in that hands back a chunk.
    class FakeRecorder {
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      stream = { getTracks: () => [{ stop: vi.fn() }] };
      start() {}
      stop() {
        this.ondataavailable?.({
          data: new Blob(["pretend audio"], { type: "audio/webm" }),
        });
        this.onstop?.();
      }
    }

    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue({}) },
      configurable: true,
    });

    render(<TellingCapture />);

    await user.click(
      screen.getByRole("button", { name: /start recording/i })
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));

    await waitFor(() => expect(api.createVoiceTelling).toHaveBeenCalled());
    const uploaded = vi.mocked(api.createVoiceTelling).mock.calls[0][0];
    expect(uploaded).toBeInstanceOf(File);
    expect(push).toHaveBeenCalledWith("/tellings/t1");
  });

  it("points at a telling that is already waiting", async () => {
    vi.mocked(api.getTellings).mockResolvedValue([
      {
        id: "t9",
        status: "draft",
        input_type: "text",
        raw_transcript: "An account I started and never finished.",
        segment_count: 3,
        created_at: "2026-01-01T00:00:00",
      },
    ]);

    render(<TellingCapture />);

    expect(
      await screen.findByText(/1 unfinished telling/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /started and never finished/i })
    ).toHaveAttribute("href", "/tellings/t9");
  });
});
