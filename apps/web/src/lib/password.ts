import { createHash, randomBytes, scrypt, timingSafeEqual } from "crypto";

/**
 * VEDA AI — Password Hashing
 *
 * New hashes use scrypt with a per-password random salt:
 *   scrypt$<N>$<r>$<p>$<salt-hex>$<hash-hex>
 *
 * Legacy hashes (unsalted SHA-256 hex, 64 chars) are still accepted so
 * existing users can log in; callers should re-hash them on success
 * (see `needsRehash`).
 */

const SCRYPT_N = 16384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const KEY_LENGTH = 64;

function scryptAsync(
  password: string,
  salt: Buffer,
  keylen: number,
  options: { N: number; r: number; p: number }
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(password, salt, keylen, { ...options, maxmem: 64 * 1024 * 1024 }, (err, key) =>
      err ? reject(err) : resolve(key)
    );
  });
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16);
  const hash = await scryptAsync(password, salt, KEY_LENGTH, {
    N: SCRYPT_N,
    r: SCRYPT_R,
    p: SCRYPT_P,
  });
  return `scrypt$${SCRYPT_N}$${SCRYPT_R}$${SCRYPT_P}$${salt.toString("hex")}$${hash.toString("hex")}`;
}

function isLegacySha256(stored: string): boolean {
  return /^[0-9a-f]{64}$/i.test(stored);
}

export async function verifyPassword(password: string, stored: string | null): Promise<boolean> {
  if (!stored) return false;

  if (stored.startsWith("scrypt$")) {
    const [, n, r, p, saltHex, hashHex] = stored.split("$");
    if (!n || !r || !p || !saltHex || !hashHex) return false;
    const expected = Buffer.from(hashHex, "hex");
    const actual = await scryptAsync(password, Buffer.from(saltHex, "hex"), expected.length, {
      N: Number(n),
      r: Number(r),
      p: Number(p),
    });
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  }

  if (isLegacySha256(stored)) {
    const actual = createHash("sha256").update(password).digest();
    return timingSafeEqual(actual, Buffer.from(stored, "hex"));
  }

  return false;
}

/** True when the stored hash uses an outdated scheme and should be replaced. */
export function needsRehash(stored: string | null): boolean {
  return !!stored && !stored.startsWith("scrypt$");
}
