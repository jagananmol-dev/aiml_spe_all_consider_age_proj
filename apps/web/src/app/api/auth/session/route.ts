import { NextResponse } from "next/server";
import { getSession } from "@/lib/db";

/**
 * GET /api/auth/session
 *
 * Returns the current session if the signed session cookie is valid.
 */
export async function GET() {
  try {
    const session = await getSession();

    if (!session) {
      return NextResponse.json({ authenticated: false, session: null }, { status: 200 });
    }

    const { exp: _exp, ...publicSession } = session;
    return NextResponse.json({ authenticated: true, session: publicSession });
  } catch (error) {
    console.error("Session fetch failed:", error);
    return NextResponse.json({ error: "Failed to read session" }, { status: 500 });
  }
}
