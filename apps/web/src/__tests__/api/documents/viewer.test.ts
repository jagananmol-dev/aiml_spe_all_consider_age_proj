/**
 * VEDA AI — Document viewer routes
 *
 * GET /api/documents/:id/file     original file, tenant-scoped, right content type
 * GET /api/documents/:id/preview  stored Office preview, tenant-scoped
 */

import fs from "fs";
import os from "os";
import path from "path";

jest.mock("@/lib/db", () => require("../../helpers/mockDb").dbMockModule());
jest.mock("minio", () => ({ Client: jest.fn(() => ({ getObject: jest.fn() })) }));

import { GET as getFile } from "@/app/api/documents/[id]/file/route";
import { GET as getPreview } from "@/app/api/documents/[id]/preview/route";
import { mockDbState, TEST_SESSION } from "../../helpers/mockDb";

const DOC_ID = "11111111-2222-4333-8444-555555555555";
const params = (id: string) => ({ params: Promise.resolve({ id }) });
const req = () => new Request("http://localhost/x");

let dir: string;

beforeEach(() => {
  mockDbState.reset();
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "veda-viewer-"));
  process.env.LOCAL_STORAGE_DIR = dir;
  fs.mkdirSync(path.join(dir, "t1"));
  fs.writeFileSync(path.join(dir, "t1", "ledger.csv"), "name,amount\nRent,100\n");
});

afterEach(() => {
  delete process.env.LOCAL_STORAGE_DIR;
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("GET /api/documents/:id/file", () => {
  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await getFile(req(), params(DOC_ID))).status).toBe(401);
  });

  it("serves the stored file of the session tenant with its content type", async () => {
    mockDbState.result = [{ title: "ledger.csv", storage_bucket: "local", storage_path: "t1/ledger.csv" }];
    const res = await getFile(req(), params(DOC_ID));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(res.headers.get("content-disposition")).toContain("inline");
    expect(await res.text()).toBe("name,amount\nRent,100\n");
    expect(mockDbState.queries[0].values).toEqual([DOC_ID, TEST_SESSION.tenantId]);
  });

  it("returns 404 for a document of another tenant (no row)", async () => {
    mockDbState.result = [];
    expect((await getFile(req(), params(DOC_ID))).status).toBe(404);
  });

  it("returns 404 for a malformed id without querying", async () => {
    expect((await getFile(req(), params("../../etc"))).status).toBe(404);
    expect(mockDbState.queries).toHaveLength(0);
  });

  it("refuses a stored path outside the storage directory", async () => {
    mockDbState.result = [{ title: "x.txt", storage_bucket: "local", storage_path: "../outside.txt" }];
    expect((await getFile(req(), params(DOC_ID))).status).toBe(404);
  });
});

describe("GET /api/documents/:id/preview", () => {
  it("returns the stored preview", async () => {
    const preview = { kind: "slides", slides: [{ number: 1, title: "Q3", bullets: [], tables: [], notes: "" }] };
    mockDbState.result = [{ preview }];
    const res = await getPreview(req(), params(DOC_ID));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(preview);
    expect(mockDbState.tenantScopes).toEqual([TEST_SESSION.tenantId]);
  });

  it("returns 404 when there is no preview", async () => {
    mockDbState.result = [];
    expect((await getPreview(req(), params(DOC_ID))).status).toBe(404);
  });

  it("returns 401 without a session", async () => {
    mockDbState.authenticated = false;
    expect((await getPreview(req(), params(DOC_ID))).status).toBe(401);
  });
});
