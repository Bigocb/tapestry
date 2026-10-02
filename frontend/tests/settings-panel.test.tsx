import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPanel } from "@/components/SettingsPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { changePassword: vi.fn() },
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

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  current: string,
  next: string,
  confirm: string
) {
  await user.type(screen.getByLabelText(/current password/i), current);
  await user.type(screen.getByLabelText(/^new password$/i), next);
  await user.type(screen.getByLabelText(/confirm new password/i), confirm);
}

describe("SettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(api.changePassword).mockResolvedValue({
      detail: "Your password has been changed.",
    });
  });

  it("changes the password with the current one", async () => {
    const user = userEvent.setup();
    render(<SettingsPanel />);

    await fill(user, "password123", "a-much-longer-secret", "a-much-longer-secret");
    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(api.changePassword).toHaveBeenCalledWith(
      "password123",
      "a-much-longer-secret"
    );
  });

  it("refuses to submit when the two new passwords differ", async () => {
    const user = userEvent.setup();
    render(<SettingsPanel />);

    await fill(user, "password123", "a-much-longer-secret", "something-else");

    expect(
      screen.getByRole("button", { name: /change password/i })
    ).toBeDisabled();
    expect(screen.getByText(/differ/i)).toBeInTheDocument();
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("refuses a new password under eight characters", async () => {
    const user = userEvent.setup();
    render(<SettingsPanel />);

    await fill(user, "password123", "short", "short");

    expect(
      screen.getByRole("button", { name: /change password/i })
    ).toBeDisabled();
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
  });

  it("points at the reset link when the current password is forgotten", async () => {
    render(<SettingsPanel />);

    expect(
      screen.getByRole("link", { name: /don.t know my current password/i })
    ).toHaveAttribute("href", "/forgot-password");
  });

  it("shows the server's reason when the current password is wrong", async () => {
    const user = userEvent.setup();
    vi.mocked(api.changePassword).mockRejectedValue(
      new Error("That is not your current password.")
    );
    render(<SettingsPanel />);

    await fill(user, "wrong", "a-much-longer-secret", "a-much-longer-secret");
    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(
      await screen.findByText(/not your current password/i)
    ).toBeInTheDocument();
  });
});
