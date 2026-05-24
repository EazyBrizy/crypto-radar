# Signal Scoring

Score = weighted sum:

score =
0.3 * volume_signal +
0.3 * oi_signal +
0.2 * funding_signal +
0.2 * volatility

Range: 0–1

Rules:
- score > 0.7 → strong signal
- score 0.5–0.7 → medium
- <0.5 ignore