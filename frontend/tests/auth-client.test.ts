import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

function rejected(status: number, body: unknown) {
  return Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

function ok(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response);
}

describe("auth client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("surfaces the server's reason when login is rejected", async () => {
    // A 401 from /auth/login means "wrong credentials", not "your session
    // expired" — the user was never signed in to begin with.
    fetchMock.mockReturnValue(
      rejected(401, { detail: "Invalid username or password" })
    );

    await expect(api.login("bigocb", "wrong")).rejects.toThrow(
      /invalid username or password/i
    );
  });

  it("does not discard a stored token when login is rejected", async () => {
    localStorage.setItem("token", "a-valid-existing-token");
    // Only the login request gets an answer; a refresh attempt would get this
    // next, and would overwrite the stored token.
    fetchMock.mockReturnValue(
      rejected(401, { detail: "Invalid username or password" })
    );

    await api.login("bigocb", "wrong").catch(() => {});

    expect(localStorage.getItem("token")).toBe("a-valid-existing-token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still refreshes on a 401 from an ordinary request", async () => {
    localStorage.setItem("token", "stale-token");
    fetchMock
      .mockReturnValueOnce(rejected(401, { detail: "Expired" }))
      .mockReturnValueOnce(ok({ access_token: "fresh-token" }))
      .mockReturnValueOnce(ok({ items: [] }));

    await api.getMemories();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(localStorage.getItem("token")).toBe("fresh-token");
  });
});
