import { NextRequest, NextResponse } from "next/server";
import { client } from "@/lib/db";
import { hashPassword } from "@/lib/password";
import { clientIp, hit } from "@/lib/rateLimit";

/**
 * POST /api/auth/register
 *
 * Registers a new tenant and creates an admin user.
 */
export async function POST(request: NextRequest) {
  try {
    const wait = hit(`register-ip:${clientIp(request.headers)}`, 5, 60 * 60);
    if (wait > 0) {
      return NextResponse.json(
        { error: `Too many attempts. Try again in ${wait} seconds.` },
        { status: 429, headers: { "Retry-After": String(wait) } }
      );
    }

    const body = await request.json();
    const fields = ["companyName", "tenantSlug", "email", "name", "password"] as const;
    if (fields.some((f) => typeof body?.[f] !== "string" || !body[f].trim())) {
      return NextResponse.json({ error: "All fields are required" }, { status: 400 });
    }
    const { companyName, tenantSlug, email, name, password } = body as Record<
      (typeof fields)[number],
      string
    >;
    if (
      companyName.length > 200 ||
      name.length > 200 ||
      email.length > 254 ||
      password.length > 200
    ) {
      return NextResponse.json({ error: "A field is too long" }, { status: 400 });
    }

    // Validate email format (server-side, RFC 5322 simplified)
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    if (!emailRegex.test(email.trim())) {
      return NextResponse.json({ error: "Invalid email address format" }, { status: 400 });
    }

    // Validate password length
    if (password.length < 8) {
      return NextResponse.json(
        { error: "Password must be at least 8 characters" },
        { status: 400 }
      );
    }

    const cleanSlug = tenantSlug
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "");

    if (cleanSlug.length < 3) {
      return NextResponse.json(
        { error: "Slug must be at least 3 alphanumeric characters" },
        { status: 400 }
      );
    }

    // Check if tenant slug already exists
    const existingTenant = await client`
      SELECT id FROM tenants WHERE slug = ${cleanSlug} LIMIT 1
    `;

    if (existingTenant.length > 0) {
      return NextResponse.json({ error: "Tenant slug already registered" }, { status: 409 });
    }

    // Check if user email already exists
    const existingUser = await client`
      SELECT id FROM users WHERE email = ${email.trim().toLowerCase()} LIMIT 1
    `;

    if (existingUser.length > 0) {
      return NextResponse.json({ error: "User email already registered" }, { status: 409 });
    }

    const passwordHash = await hashPassword(password);

    // Insert tenant and user in a transaction
    const result = await client.begin(async (sql) => {
      // The checks above can race with a concurrent sign-up; the unique
      // constraints still hold and are reported as 409 below
      // 1. Insert tenant
      const [tenant] = await sql`
        INSERT INTO tenants (name, slug, subscription_tier)
        VALUES (${companyName.trim()}, ${cleanSlug}, 'professional')
        RETURNING id, name, slug
      `;

      // Scope the rest of the transaction to the new tenant for RLS
      await sql`SELECT set_config('app.current_tenant_id', ${tenant.id}, true)`;

      // 2. Insert admin user
      const [user] = await sql`
        INSERT INTO users (tenant_id, email, name, role, password_hash)
        VALUES (${tenant.id}, ${email.trim().toLowerCase()}, ${name.trim()}, 'admin', ${passwordHash})
        RETURNING id, email, name, role
      `;

      return { tenant, user };
    });

    return NextResponse.json(
      {
        success: true,
        message: "Tenant and user registered successfully",
        tenant: result.tenant,
        user: result.user,
      },
      { status: 201 }
    );
  } catch (error) {
    if ((error as { code?: string })?.code === "23505") {
      return NextResponse.json(
        { error: "Tenant slug or email already registered" },
        { status: 409 }
      );
    }
    console.error("Tenant registration failed:", error);
    return NextResponse.json(
      { error: "Internal server error during registration" },
      { status: 500 }
    );
  }
}
