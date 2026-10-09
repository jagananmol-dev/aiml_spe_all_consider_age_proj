import {
  buildCatalogChunk,
  isOverviewQuestion,
  isSmallTalk,
  retrievalQuery,
} from "@/lib/chatPrompt";

describe("isOverviewQuestion", () => {
  it.each([
    "What topics do our documents cover?",
    "give a summary",
    "give a summanry",
    "summarise everything",
    "Can you give me an overview?",
    "What documents do we have?",
    "Which files mention Pimpri?",
    "List all documents",
  ])("treats %p as a question about the collection", (q) => {
    expect(isOverviewQuestion(q)).toBe(true);
  });

  it.each([
    "Why did GEN-P1 start late?",
    "What is the notice period for a technician?",
    "How were the catheter infections at Pimpri treated?",
    "What was total revenue in September?",
  ])("treats %p as a specific question", (q) => {
    expect(isOverviewQuestion(q)).toBe(false);
  });
});

describe("retrievalQuery", () => {
  const history = [
    { role: "user" as const, content: "What happened to the Hadapsar water plant?" },
    { role: "assistant" as const, content: "Endotoxin was above limit [1]." },
  ];

  it("searches a short follow-up together with the previous question", () => {
    expect(retrievalQuery("and Pimpri?", history)).toBe(
      "What happened to the Hadapsar water plant?\nand Pimpri?"
    );
  });

  it("asks for summarising passages on overview questions", () => {
    const q = retrievalQuery("give a summary", history);
    expect(q.startsWith("What happened to the Hadapsar water plant?\ngive a summary\n")).toBe(true);
    expect(q).toContain("Overview and summary of the organisation");
  });

  it("searches a full question on its own", () => {
    const q = "What is the notice period for a dialysis technician who resigns?";
    expect(retrievalQuery(q, history)).toBe(q);
  });

  it("uses the question alone when there is no history", () => {
    expect(retrievalQuery("Who approves refunds?", [])).toBe("Who approves refunds?");
  });
});

describe("buildCatalogChunk", () => {
  it("lists every document with date, format and readable name", () => {
    const chunk = buildCatalogChunk("Acme", [
      { title: "HR_Leave_Policy.md", documentType: "Markdown", uploadedAt: "2026-08-01" },
      { title: "Board_Pack.docx", documentType: "Word", uploadedAt: "2026-10-09" },
    ]);
    expect(chunk.document_id).toBe("catalog");
    expect(chunk.metadata.title).toBe("Company document catalog");
    expect(chunk.text).toContain("Acme has 2 uploaded documents");
    expect(chunk.text).toContain("cite it as [1]");
    expect(chunk.text).toContain("- 2026-08-01 · Markdown · HR Leave Policy.md");
    expect(chunk.text).toContain("- 2026-10-09 · Word · Board Pack.docx");
  });

  it("keeps the newest documents when there are very many", () => {
    const docs = Array.from({ length: 200 }, (_, i) => ({
      title: `doc_${i}.txt`,
      documentType: "Plain Text",
      uploadedAt: "2026-08-01",
    }));
    const chunk = buildCatalogChunk("Acme", docs);
    expect(chunk.text).toContain("200 uploaded documents (the 150 most recent are listed)");
    expect(chunk.text).toContain("doc 199.txt");
    expect(chunk.text).not.toContain("doc 0.txt");
  });
});

describe("isSmallTalk", () => {
  it.each([
    "hi",
    "Hii",
    "hello!",
    "hey there",
    "Good morning",
    "thanks",
    "thank you!",
    "ok",
    "bye",
  ])("treats %p as small talk", (m) => {
    expect(isSmallTalk(m)).toBe(true);
  });

  it.each([
    "hi, what is the notice period?",
    "thanks — and who approves refunds?",
    "summary",
    "HD-K04",
  ])("treats %p as a real question", (m) => {
    expect(isSmallTalk(m)).toBe(false);
  });
});
