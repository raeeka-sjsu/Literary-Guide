const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = 3000;
const AGENT_URL = process.env.AGENT_URL || "http://localhost:5050";

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

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

// Proxy chapter-aware Q&A to the Python Flask agent
app.post("/api/ask", async (req, res) => {
  try {
    const upstream = await fetch(`${AGENT_URL}/ask`, {
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
});

app.listen(PORT, () => {
  console.log(`Literary Guide viewer running at http://localhost:${PORT}`);
  console.log(`Proxying agent calls to ${AGENT_URL}`);
});
