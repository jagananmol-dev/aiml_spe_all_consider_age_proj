import { parseCsv } from "@/lib/csv";
import { contentTypeFor, viewerKindFor } from "@/lib/formats";

describe("parseCsv", () => {
  it("parses plain rows", () => {
    expect(parseCsv("a,b\n1,2\n")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("handles quotes, embedded commas, doubled quotes and newlines", () => {
    expect(parseCsv('name,note\r\n"Khan, Farah","said ""ok""\nthen left"\r\n')).toEqual([
      ["name", "note"],
      ["Khan, Farah", 'said "ok"\nthen left'],
    ]);
  });

  it("drops a BOM and blank lines, keeps a last line without newline", () => {
    expect(parseCsv("﻿a\n\nb")).toEqual([["a"], ["b"]]);
  });
});

describe("viewer helpers", () => {
  it.each([
    ["report.pdf", "pdf"],
    ["policy.docx", "office"],
    ["mis.xlsx", "office"],
    ["deck.pptx", "office"],
    ["log.csv", "csv"],
    ["data.json", "json"],
    ["rows.jsonl", "jsonl"],
    ["notes.md", "markdown"],
    ["shift.txt", "text"],
    ["scan.PNG", "image"],
  ])("%s is shown as %s", (name, kind) => {
    expect(viewerKindFor(name)).toBe(kind);
  });

  it("serves text formats as UTF-8 and binaries with their type", () => {
    expect(contentTypeFor("log.csv")).toBe("text/csv; charset=utf-8");
    expect(contentTypeFor("report.pdf")).toBe("application/pdf");
    expect(contentTypeFor("mystery.bin")).toBe("application/octet-stream");
  });
});
