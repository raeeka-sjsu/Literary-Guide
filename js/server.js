const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = 3000;
const AGENT_URL = process.env.AGENT_URL || "http://localhost:5050";

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const BOOKS_DIR = path.join(__dirname, "..", "python", "data", "books");
const CATALOG_PATH = path.join(__dirname, "..", "python", "data", "catalog.json");

// Library catalog — augmented with chapter counts from the fetched book files
app.get("/api/books", (_req, res) => {
  try {
    const catalog = JSON.parse(fs.readFileSync(CATALOG_PATH, "utf-8"));
    const enriched = catalog.map((entry) => {
      const bookPath = path.join(BOOKS_DIR, `${entry.id}.json`);
      let chapterCount = 0;
      let available = false;
      if (fs.existsSync(bookPath)) {
        try {
          const book = JSON.parse(fs.readFileSync(bookPath, "utf-8"));
          chapterCount = book.chapters?.length || 0;
          available = true;
        } catch (_) {}
      }
      return { ...entry, chapter_count: chapterCount, available };
    });
    res.json(enriched);
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

// Single book — full chapters
app.get("/api/books/:id", (req, res) => {
  const bookPath = path.join(BOOKS_DIR, `${req.params.id}.json`);
  if (!fs.existsSync(bookPath)) {
    return res.status(404).json({ error: "Book not found" });
  }
  res.json(JSON.parse(fs.readFileSync(bookPath, "utf-8")));
});

// Serve BookSum sample data as JSON API
app.get("/api/samples", (_req, res) => {
  const samplesPath = path.join(
    __dirname,
    "..",
    "python",
    "outputs",
    "booksum_samples.json"
  );

  if (!fs.existsSync(samplesPath)) {
    return res.status(404).json({
      error: "booksum_samples.json not found. Run the Python loader first.",
    });
  }

  const data = JSON.parse(fs.readFileSync(samplesPath, "utf-8"));
  res.json(data);
});

// Proxy helper
async function proxyTo(path, req, res) {
  try {
    const upstream = await fetch(`${AGENT_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body || {}),
    });
    const data = await upstream.json();
    res.status(upstream.status).json(data);
  } catch (err) {
    res.status(502).json({
      error: `Could not reach Literary Guide agent at ${AGENT_URL}. Start it with: python scripts/api_server.py`,
      detail: String(err),
    });
  }
}

// Build per-book index on demand
app.post("/api/index_book", (req, res) => proxyTo("/index_book", req, res));

// Chapter-aware Q&A
app.post("/api/ask", (req, res) => proxyTo("/ask", req, res));

// ----- Memory + reading position (D3) -----
async function proxyGet(path, req, res) {
  try {
    const url = new URL(`${AGENT_URL}${path}`);
    Object.entries(req.query || {}).forEach(([k, v]) => url.searchParams.set(k, v));
    const upstream = await fetch(url.toString());
    const data = await upstream.json();
    res.status(upstream.status).json(data);
  } catch (err) {
    res.status(502).json({ error: `Could not reach agent at ${AGENT_URL}`, detail: String(err) });
  }
}
app.get("/api/memory/:book_id", (req, res) => proxyGet(`/memory/${req.params.book_id}`, req, res));
app.post("/api/memory/:book_id/summarize", (req, res) =>
  proxyTo(`/memory/${req.params.book_id}/summarize`, req, res));
app.post("/api/reading_position", (req, res) => proxyTo("/reading_position", req, res));
app.get("/api/recent_books", (req, res) => proxyGet("/recent_books", req, res));

app.listen(PORT, () => {
  console.log(`Literary Guide viewer running at http://localhost:${PORT}`);
  console.log(`Proxying agent calls to ${AGENT_URL}`);
});
