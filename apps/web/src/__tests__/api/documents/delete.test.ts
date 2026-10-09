/**
 * VEDA AI — DELETE /api/documents/:id
 */

import fs from "fs";
import os from "os";
import path from "path";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
jest.mock("minio", () => ({ Client: jest.fn(() => ({ removeObject: jest.fn() })) }));

import { DELETE } from "@/app/api/documents/[id]/route";
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

const DOC_ID = "11111111-2222-4333-8444-555555555555";
const params = (id: string) => ({ params: Promise.resolve({ id }) });
const req = () => new Request("http://localhost/x", { method: "DELETE" });

let dir: string;

beforeEach(() => {
  mockDbState.reset();
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "veda-delete-"));
  process.env.LOCAL_STORAGE_DIR = dir;
  fs.mkdirSync(path.join(dir, "t1"));
  fs.writeFileSync(path.join(dir, "t1", "wrong.csv"), "a,b\n");
});

afterEach(() => {
  delete process.env.LOCAL_STORAGE_DIR;
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("DELETE /api/documents/:id", () => {
  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await DELETE(req(), params(DOC_ID))).status).toBe(401);
  });

  it("deletes only the session tenant's row and removes the stored file", async () => {
    mockDbState.result = [
      { storage_bucket: "local", storage_path: "t1/wrong.csv", title: "wrong.csv" },
    ];
    const res = await DELETE(req(), params(DOC_ID));
    expect(res.status).toBe(200);
    const query = mockDbState.queries[0];
    expect(query.text).toContain("DELETE FROM documents");
    expect(query.values).toEqual([DOC_ID, TEST_SESSION.tenantId]);
    expect(fs.existsSync(path.join(dir, "t1", "wrong.csv"))).toBe(false);
  });

  it("returns 404 for another tenant's or a missing document", async () => {
    mockDbState.result = [];
    expect((await DELETE(req(), params(DOC_ID))).status).toBe(404);
    expect((await DELETE(req(), params("not-a-uuid"))).status).toBe(404);
  });

  it("refuses a stored path outside the storage directory", async () => {
    mockDbState.result = [
      { storage_bucket: "local", storage_path: "../../etc/passwd", title: "x" },
    ];
    // The row is deleted; the unsafe path is refused and only logged
    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    expect((await DELETE(req(), params(DOC_ID))).status).toBe(200);
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
