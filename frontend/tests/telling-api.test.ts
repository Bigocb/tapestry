import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

function ok(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response);
}

describe("telling API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a telling with the transcript", async () => {
    fetchMock.mockReturnValue(ok({ id: "t1" }));

    await api.createTelling("In the summer of 1985...");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:3000/api/tellings");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      raw_transcript: "In the summer of 1985...",
    });
  });

  it("fetches one telling", async () => {
    fetchMock.mockReturnValue(ok({ id: "t1" }));

    await api.getTelling("t1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:3000/api/tellings/t1");
    expect(init.method).toBe("GET");
  });

  it("patches a single segment", async () => {
    fetchMock.mockReturnValue(ok({ id: "s1" }));

    await api.updateTellingSegment("t1", "s1", { title: "Renamed" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:3000/api/tellings/t1/segments/s1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ title: "Renamed" });
  });

  it("commits a telling", async () => {
    fetchMock.mockReturnValue(ok({ id: "t1", status: "committed" }));

    await api.commitTelling("t1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:3000/api/tellings/t1/commit");
    expect(init.method).toBe("POST");
  });
});
