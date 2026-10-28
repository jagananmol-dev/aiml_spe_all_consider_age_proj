import { NextResponse } from "next/server";
import { getSession } from "@/lib/db";
import { getComputeNodeUrl, isTunnelMode, markActivity } from "@/lib/computeNode";

/**
 * GET /api/node/status
 *
 * Called every so often by open pages of signed-in users. In hosted mode
 * (COMPUTE_NODE=tunnel) each call counts as activity, which is what makes
 * the agent on the owner's PC open the tunnel, and keeps it open. Returns
 * whether the tunnel is up, so the page can say the assistant is starting.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }
  if (!isTunnelMode()) {
    return NextResponse.json({ mode: "direct", online: true });
  }

  try {
    await markActivity();
    const online = (await getComputeNodeUrl()) !== null;
    return NextResponse.json({ mode: "tunnel", online }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("[node/status] Could not read the compute node state:", error);
    return NextResponse.json({ mode: "tunnel", online: false }, { status: 503 });
  }
}
