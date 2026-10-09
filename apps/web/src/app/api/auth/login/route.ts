import { NextRequest, NextResponse } from "next/server";
import { resolveTenantId, withTenant } from "@/lib/db";
import { hashPassword, needsRehash, verifyPassword } from "@/lib/password";
import { createSessionToken, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS } from "@/lib/session";

const INVALID_CREDENTIALS = "Invalid tenant, email, or password";

/**
 * POST /api/auth/login
 *
 * Validates credentials and issues a signed session cookie.
 */
export async function POST(request: NextRequest) {
  try {
    const { tenantSlug, email, password } = await request.json();

    if (!tenantSlug || !email || !password) {
      return NextResponse.json(
        { error: "Tenant slug, email, and password are required" },
        { status: 400 }
      );
    }

    const cleanSlug = String(tenantSlug).trim().toLowerCase();
    const cleanEmail = String(email).trim().toLowerCase();

    // 1. Resolve tenant — same error as a bad password so tenants can't be enumerated
    let tenantId: string;
    try {
      tenantId = await resolveTenantId(cleanSlug);
    } catch {
      return NextResponse.json({ error: INVALID_CREDENTIALS }, { status: 401 });
    }

    // 2. Fetch user scoped to tenant and verify password
    const user = await withTenant(tenantId, async (sql) => {
      const users = await sql`
        SELECT id, email, name, role, password_hash
        FROM users
        WHERE tenant_id = ${tenantId} AND email = ${cleanEmail} AND is_active = true
        LIMIT 1
      `;
      const found = users[0];
      if (!found || !(await verifyPassword(String(password), found.password_hash))) {
        return null;
      }

      // Upgrade legacy unsalted SHA-256 hashes to scrypt on successful login
      if (needsRehash(found.password_hash)) {
        const upgraded = await hashPassword(String(password));
        await sql`
          UPDATE users SET password_hash = ${upgraded}, updated_at = NOW()
          WHERE id = ${found.id} AND tenant_id = ${tenantId}
        `;
      }
      await sql`
        UPDATE users SET last_login_at = NOW()
        WHERE id = ${found.id} AND tenant_id = ${tenantId}
      `;
      return found;
    });

    if (!user) {
      return NextResponse.json({ error: INVALID_CREDENTIALS }, { status: 401 });
    }

    // 3. Issue signed session
    const token = await createSessionToken({
      userId: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      tenantId,
      tenantSlug: cleanSlug,
    });

    const response = NextResponse.json({
      success: true,
      message: "Login successful",
      user: {
        id: user.id,
        email: user.email,
        name: user.name,
        role: user.role,
      },
      tenant: {
        id: tenantId,
        slug: cleanSlug,
      },
    });

    response.cookies.set(SESSION_COOKIE, token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE_SECONDS,
    });

    // Non-sensitive tenant hint for the login form; never trusted for authorization
    response.cookies.set("veda-tenant", cleanSlug, {
      httpOnly: false,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30, // 30 days
    });

    return response;
  } catch (error) {
    console.error("Login failed:", error);
    return NextResponse.json(
      { error: "Internal server error during authentication" },
      { status: 500 }
    );
  }
}
