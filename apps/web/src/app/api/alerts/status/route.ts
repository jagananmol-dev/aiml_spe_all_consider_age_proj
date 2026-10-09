import { NextRequest, NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";

/**
 * GET /api/alerts/status
 * Returns all non-resolved alerts for the current tenant.
 * No seed data — returns empty array if none exist.
 */
export async function GET() {
  try {
    const { tenantId } = await getScopedDb();

    const alerts = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT id, title, description, severity, category, equipment_tag, status, created_at
        FROM alerts
        WHERE tenant_id = ${tenantId} AND status != 'resolved'
        ORDER BY created_at DESC
      `
    );

    return NextResponse.json({
      success: true,
      alerts: alerts.map((a) => ({
        id: a.id,
        title: a.title,
        description: a.description,
        severity: a.severity,
        category: a.category,
        equipmentTag: a.equipment_tag,
        status: a.status,
        createdAt: a.created_at,
      })),
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to query alerts:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

/**
 * POST /api/alerts/status
 * Create a new alert for the current tenant.
 */
export async function POST(request: NextRequest) {
  try {
    const { tenantId } = await getScopedDb();
    const { title, description, severity, category, equipmentTag } = await request.json();

    if (!title) {
      return NextResponse.json({ error: "Title is required" }, { status: 400 });
    }

    const [alert] = await withTenant(
      tenantId,
      (sql) => sql`
        INSERT INTO alerts (tenant_id, title, description, severity, category, equipment_tag, status)
        VALUES (
          ${tenantId}, ${title}, ${description ?? ""}, ${severity ?? "info"},
          ${category ?? "general"}, ${equipmentTag ?? ""}, 'open'
        )
        RETURNING id, title, severity, status, created_at
      `
    );

    return NextResponse.json({ success: true, alert }, { status: 201 });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to create alert:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
