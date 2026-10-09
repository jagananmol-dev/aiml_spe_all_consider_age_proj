import { NextRequest, NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";

/**
 * GET /api/maintenance/orders
 * Returns all maintenance orders for the current tenant.
 * No seed data — returns empty array if none exist.
 */
export async function GET() {
  try {
    const { tenantId } = await getScopedDb();

    const orders = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT id, order_number, title, description, equipment_tag, status, tolerances, created_at
        FROM maintenance_orders
        WHERE tenant_id = ${tenantId}
        ORDER BY created_at DESC
      `
    );

    return NextResponse.json({
      success: true,
      orders: orders.map((o) => ({
        id: o.id,
        orderNumber: o.order_number,
        title: o.title,
        description: o.description,
        equipmentTag: o.equipment_tag,
        status: o.status,
        tolerances: o.tolerances ?? {},
        createdAt: o.created_at,
      })),
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to query maintenance orders:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

/**
 * POST /api/maintenance/orders
 * Create a new maintenance order for the current tenant.
 */
export async function POST(request: NextRequest) {
  try {
    const { tenantId } = await getScopedDb();
    const { orderNumber, title, description, equipmentTag, tolerances } = await request.json();

    if (!orderNumber || !title) {
      return NextResponse.json({ error: "Order number and title are required" }, { status: 400 });
    }
    if (
      typeof orderNumber !== "string" ||
      typeof title !== "string" ||
      orderNumber.length > 100 ||
      title.length > 255
    ) {
      return NextResponse.json(
        { error: "Order number (max 100) and title (max 255) must be text" },
        { status: 400 }
      );
    }
    if (tolerances !== undefined && (typeof tolerances !== "object" || Array.isArray(tolerances))) {
      return NextResponse.json(
        { error: "tolerances must be an object of name: value" },
        { status: 400 }
      );
    }

    const [order] = await withTenant(
      tenantId,
      (sql) => sql`
        INSERT INTO maintenance_orders
          (tenant_id, order_number, title, description, equipment_tag, status, tolerances)
        VALUES (
          ${tenantId}, ${orderNumber}, ${title}, ${description ?? ""}, ${equipmentTag ?? ""},
          'open', ${JSON.stringify(tolerances ?? {})}::jsonb
        )
        RETURNING id, order_number, title, status, created_at
      `
    );

    return NextResponse.json({ success: true, order }, { status: 201 });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to create maintenance order:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
