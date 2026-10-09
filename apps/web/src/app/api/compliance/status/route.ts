import { NextRequest, NextResponse } from "next/server";
import { getScopedDb, UnauthorizedError, withTenant } from "@/lib/db";

/**
 * GET /api/compliance/status
 * Returns all compliance rules for the current tenant.
 * No seed data — returns empty array if none exist.
 */
export async function GET() {
  try {
    const { tenantId } = await getScopedDb();

    const rules = await withTenant(
      tenantId,
      (sql) => sql`
        SELECT id, regulation_name, regulation_version, section_reference,
               requirement_text, requirement_type, compliance_status, notes
        FROM compliance_rules
        WHERE tenant_id = ${tenantId}
        ORDER BY regulation_name ASC, section_reference ASC
      `
    );

    return NextResponse.json({
      success: true,
      rules: rules.map((r) => ({
        id: r.id,
        regulationName: r.regulation_name,
        regulationVersion: r.regulation_version,
        sectionReference: r.section_reference,
        requirementText: r.requirement_text,
        requirementType: r.requirement_type,
        complianceStatus: r.compliance_status,
        notes: r.notes,
      })),
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to query compliance status:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * POST /api/compliance/status
 * Update a compliance rule for the current tenant.
 */
export async function POST(request: NextRequest) {
  try {
    const { tenantId } = await getScopedDb();
    const { ruleId, complianceStatus, notes } = await request.json();

    if (!ruleId || !complianceStatus) {
      return NextResponse.json(
        { error: "ruleId and complianceStatus are required" },
        { status: 400 }
      );
    }
    if (!UUID.test(String(ruleId))) {
      return NextResponse.json({ error: "ruleId must be a valid id" }, { status: 400 });
    }
    if (typeof complianceStatus !== "string" || complianceStatus.length > 50) {
      return NextResponse.json({ error: "Invalid complianceStatus" }, { status: 400 });
    }

    const rows = await withTenant(
      tenantId,
      (sql) => sql`
        UPDATE compliance_rules
        SET compliance_status = ${complianceStatus},
            notes = ${notes ?? ""},
            updated_at = NOW()
        WHERE id = ${ruleId} AND tenant_id = ${tenantId}
        RETURNING id, compliance_status, notes
      `
    );

    if (rows.length === 0) {
      return NextResponse.json(
        { error: "Compliance rule not found or access denied" },
        { status: 404 }
      );
    }

    return NextResponse.json({ success: true, rule: rows[0] });
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      return NextResponse.json({ error: "Authentication required" }, { status: 401 });
    }
    console.error("Failed to update compliance rule:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
