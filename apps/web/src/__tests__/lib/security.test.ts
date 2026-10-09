/**
 * VEDA AI — Session token and password hashing tests
 */

import { createHash } from "crypto";
import { createSessionToken, verifySessionToken } from "@/lib/session";
import { hashPassword, needsRehash, verifyPassword } from "@/lib/password";

const SESSION_DATA = {
  userId: "u1",
  email: "a@b.com",
  name: "A",
  role: "admin",
  tenantId: "t1",
  tenantSlug: "acme",
};

describe("session tokens", () => {
  it("round-trips a payload", async () => {
    const token = await createSessionToken(SESSION_DATA);
    expect(await verifySessionToken(token)).toMatchObject(SESSION_DATA);
  });

  it("rejects a token signed with a different secret", async () => {
    const token = await createSessionToken(SESSION_DATA);
    const original = process.env.SESSION_SECRET;
    process.env.SESSION_SECRET = "a-completely-different-secret-value";
    try {
      expect(await verifySessionToken(token)).toBeNull();
    } finally {
      if (original === undefined) delete process.env.SESSION_SECRET;
      else process.env.SESSION_SECRET = original;
    }
  });

  it("rejects a modified signature", async () => {
    const token = await createSessionToken(SESSION_DATA);
    // Change a character in the middle: the last base64url character can carry
    // only padding bits, so changing it may leave the signature bytes intact
    const i = token.length - 10;
    const flipped = token.slice(0, i) + (token[i] === "A" ? "B" : "A") + token.slice(i + 1);
    expect(await verifySessionToken(flipped)).toBeNull();
  });

  it("rejects expired tokens", async () => {
    expect(await verifySessionToken(await createSessionToken(SESSION_DATA, -1))).toBeNull();
  });

  it.each([undefined, null, "", "nodot", "a.b.c", "{}"])("rejects %p", async (value) => {
    expect(await verifySessionToken(value as string)).toBeNull();
  });
});

describe("password hashing", () => {
  it("verifies the correct password and rejects others", async () => {
    const hash = await hashPassword("correct horse");
    expect(hash).toMatch(/^scrypt\$/);
    expect(await verifyPassword("correct horse", hash)).toBe(true);
    expect(await verifyPassword("wrong horse", hash)).toBe(false);
  });

  it("salts hashes so equal passwords differ", async () => {
    expect(await hashPassword("same")).not.toBe(await hashPassword("same"));
  });

  it("accepts legacy SHA-256 hashes and flags them for rehash", async () => {
    const legacy = createHash("sha256").update("legacy-pass").digest("hex");
    expect(await verifyPassword("legacy-pass", legacy)).toBe(true);
    expect(await verifyPassword("other", legacy)).toBe(false);
    expect(needsRehash(legacy)).toBe(true);
    expect(needsRehash(await hashPassword("x"))).toBe(false);
  });

  it("rejects null or unknown hash formats", async () => {
    expect(await verifyPassword("x", null)).toBe(false);
    expect(await verifyPassword("x", "$2b$12$placeholder")).toBe(false);
  });
});
