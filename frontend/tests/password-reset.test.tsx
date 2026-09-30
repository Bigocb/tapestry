import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ForgotPasswordForm,
  ResetPasswordForm,
} from "@/components/PasswordReset";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    forgotPassword: vi.fn(),
    resetPassword: vi.fn(),
  },
}));

describe("ForgotPasswordForm", () => {
  beforeEach(() => {
    vi.mocked(api.forgotPassword).mockResolvedValue({ detail: "ok" });
  });

  it("asks for a link and promises nothing about whether the account exists", async () => {
    const user = userEvent.setup();
    render(<ForgotPasswordForm />);

    await user.type(
      screen.getByLabelText(/username or email/i),
      "alice@example.com"
    );
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(api.forgotPassword).toHaveBeenCalledWith("alice@example.com");
    // The wording has to hold for a real account and a made-up one alike.
    expect(
      await screen.findByText(/if that account exists/i)
    ).toBeInTheDocument();
  });
});

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/reset-password?token=abc123");
    vi.mocked(api.resetPassword).mockResolvedValue({ detail: "ok" });
  });

  it("uses the token from the link to set a new password", async () => {
    const user = userEvent.setup();
    render(<ResetPasswordForm />);

    await user.type(
      await screen.findByLabelText(/new password/i),
      "brand-new-passphrase"
    );
    await user.click(
      screen.getByRole("button", { name: /set new password/i })
    );

    expect(api.resetPassword).toHaveBeenCalledWith(
      "abc123",
      "brand-new-passphrase"
    );
    expect(
      await screen.findByText(/password changed/i)
    ).toBeInTheDocument();
  });

  it("surfaces a dead link rather than silently doing nothing", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetPassword).mockRejectedValue(
      new Error("That reset link has expired.")
    );

    render(<ResetPasswordForm />);
    await user.type(
      await screen.findByLabelText(/new password/i),
      "brand-new-passphrase"
    );
    await user.click(
      screen.getByRole("button", { name: /set new password/i })
    );

    expect(
      await screen.findByText(/that reset link has expired/i)
    ).toBeInTheDocument();
  });
});
