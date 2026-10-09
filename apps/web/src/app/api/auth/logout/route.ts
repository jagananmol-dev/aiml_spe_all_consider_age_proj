import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/auth/logout
 *
 * Clears the session cookie and signs out user.
 */
export async function POST(request: NextRequest) {
  const response = NextResponse.json({
    success: true,
    message: "Logged out successfully",
  });

  // Expire the session cookie
  response.cookies.set("veda-session", "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    expires: new Date(0),
  });

  return response;
}
