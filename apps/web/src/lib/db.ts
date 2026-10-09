import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { cookies } from "next/headers";
import { SESSION_COOKIE, verifySessionToken, type SessionPayload } from "@/lib/session";

/**
 * VEDA AI — Database Connection with Tenant Isolation
 *
 * Tenant isolation is enforced in two layers:
 * 1. Every tenant-scoped query filters explicitly on `tenant_id`, using the
 *    tenant id from the *verified* session (never from client headers).
 * 2. `withTenant` runs queries inside a transaction with
 *    `app.current_tenant_id` set, so PostgreSQL RLS policies apply when the
 *    app connects as a non-owner role.
 */

// Connection pool for the application
const connectionString = process.env.DATABASE_URL!;

export const client = postgres(connectionString, {
  max: 20,
  idle_timeout: 20,
  connect_timeout: 10,
});

export const db = drizzle(client);

export type TenantSql = postgres.TransactionSql;

export class UnauthorizedError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

/**
 * Run `fn` inside a transaction whose RLS context is set to `tenantId`.
 *
 * `set_config(..., true)` is transaction-local, so it must run on the same
 * connection and transaction as the queries it protects — which is why the
 * queries are passed the transaction handle `sql` rather than the pool.
 */
export async function withTenant<T>(
  tenantId: string,
  fn: (sql: TenantSql) => Promise<T>
): Promise<T> {
  return client.begin(async (sql) => {
    await sql`SELECT set_config('app.current_tenant_id', ${tenantId}, true)`;
    return fn(sql);
  }) as Promise<T>;
}

/**
 * Read and verify the session cookie for the current request.
 * Returns null when there is no valid session.
 */
export async function getSession(): Promise<SessionPayload | null> {
  const cookieStore = await cookies();
  return verifySessionToken(cookieStore.get(SESSION_COOKIE)?.value);
}

/**
 * Require a valid session. Throws UnauthorizedError otherwise.
 */
export async function requireSession(): Promise<SessionPayload> {
  const session = await getSession();
  if (!session) throw new UnauthorizedError();
  return session;
}

/**
 * Resolve tenant ID from slug by querying the tenants table.
 * Used only during login, before a session exists. Cached for 5 minutes.
 */
const tenantCache = new Map<string, { id: string; expiresAt: number }>();

export async function resolveTenantId(slug: string): Promise<string> {
  const cached = tenantCache.get(slug);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.id;
  }

  // The tenants table is not tenant-scoped, so no RLS context is needed
  const result =
    await client`SELECT id FROM tenants WHERE slug = ${slug} AND is_active = true LIMIT 1`;

  if (result.length === 0) {
    throw new Error(`Tenant not found: ${slug}`);
  }

  const tenantId = result[0].id;
  tenantCache.set(slug, { id: tenantId, expiresAt: Date.now() + 5 * 60 * 1000 });
  return tenantId;
}

/**
 * Get the tenant context for the current request from the verified session.
 * Throws UnauthorizedError when there is no valid session.
 */
export async function getScopedDb() {
  const session = await requireSession();
  return { db, tenantId: session.tenantId, session };
}
