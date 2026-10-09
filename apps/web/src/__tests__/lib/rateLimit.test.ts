/**
 * VEDA AI — Rate limiter tests
 */

import { _resetAll, clientIp, hit, reset } from "@/lib/rateLimit";

beforeEach(() => _resetAll());

describe("hit", () => {
  it("allows up to the limit, then asks the caller to wait", () => {
    for (let i = 0; i < 3; i++) expect(hit("k", 3, 60)).toBe(0);
    const wait = hit("k", 3, 60);
    expect(wait).toBeGreaterThan(0);
    expect(wait).toBeLessThanOrEqual(60);
  });

  it("keeps keys apart and can be reset", () => {
    for (let i = 0; i < 4; i++) hit("a", 3, 60);
    expect(hit("b", 3, 60)).toBe(0);
    reset("a");
    expect(hit("a", 3, 60)).toBe(0);
  });

  it("opens a new window after the old one expires", () => {
    jest.useFakeTimers();
    for (let i = 0; i < 4; i++) hit("k", 3, 60);
    jest.advanceTimersByTime(61_000);
    expect(hit("k", 3, 60)).toBe(0);
    jest.useRealTimers();
  });
});

describe("clientIp", () => {
  it("takes the first forwarded address", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "1.2.3.4, 10.0.0.1" }))).toBe("1.2.3.4");
    expect(clientIp(new Headers())).toBe("unknown");
  });
});
