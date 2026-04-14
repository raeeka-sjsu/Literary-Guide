const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = 3000;

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

app.listen(PORT, () => {
  console.log(`Literary Guide viewer running at http://localhost:${PORT}`);
});
