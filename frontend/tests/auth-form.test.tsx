import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoginForm, SignupForm } from "@/components/AuthForm";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login: vi.fn(), logout: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: { login: vi.fn(), register: vi.fn() },
}));

describe("auth forms on a phone", () => {
  it("does not let iOS capitalise the login username", () => {
    // iOS capitalises a plain text input by default, so "bigocb" is sent as
    // "Bigocb" and the login is rejected.
    render(<LoginForm />);

    const username = screen.getByPlaceholderText("Username");
    expect(username).toHaveAttribute("autoCapitalize", "none");
    expect(username).toHaveAttribute("autoCorrect", "off");
  });

  it("does not let iOS capitalise the signup username or email", () => {
    render(<SignupForm />);

    expect(screen.getByPlaceholderText("Username")).toHaveAttribute(
      "autoCapitalize",
      "none"
    );
    expect(screen.getByPlaceholderText("Email")).toHaveAttribute(
      "autoCapitalize",
      "none"
    );
  });
});
