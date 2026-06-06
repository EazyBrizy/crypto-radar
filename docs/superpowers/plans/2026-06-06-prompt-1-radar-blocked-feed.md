# Prompt 1 Radar Blocked Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide low-score blocked diagnostic ideas from the normal radar working feed while keeping them visible in the diagnostic blocked mode and making the UI clearly non-executable.

**Architecture:** Backend feed policy stays in `RadarService`; execution eligibility stays in `SignalExecutionGateService`. Frontend only renders backend `execution_gate`, card views, and action state, with diagnostic copy for blocked cards and blocked filter mode.

**Tech Stack:** FastAPI/Pydantic/Python unit tests, Next.js/React/TypeScript/Vitest.

---

### Task 1: Backend Radar Feed Policy

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/schemas/signal.py`
- Modify: `backend/app/services/radar_service.py`
- Test: `backend/tests/test_radar_service.py`

- [ ] **Step 1: Write failing backend tests**

Add tests named:

```python
def test_radar_service_all_feed_hides_blocked_low_score(self) -> None:
    blocked_low = _signal(
        status="ready",
        score=23,
        execution_gate=_execution_gate(
            can_show=False,
            feed_kind="blocked",
            status="blocked",
        ),
    )
    visible_market = _signal(
        status="active",
        score=64,
        symbol="ETHUSDT",
        execution_gate=_execution_gate(
            can_show=False,
            feed_kind="market_idea",
            status="warning",
        ),
    )
    low_market = _signal(
        status="active",
        score=49,
        symbol="XRPUSDT",
        execution_gate=_execution_gate(
            can_show=False,
            feed_kind="market_idea",
            status="warning",
        ),
    )
    service = _service(
        [blocked_low, visible_market, low_market],
        risk_preview=FakeRiskPreviewEvaluator({}),
        user_mode="all_market_opportunities",
    )

    response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")

    self.assertEqual([signal.id for signal in response.signals], [visible_market.id])
    self.assertEqual(response.summary.hidden_blocked_ideas, 1)
    self.assertEqual(response.summary.hidden_low_score_ideas, 1)
    self.assertEqual(response.summary.visible_market_ideas, 1)
```

```python
def test_radar_service_blocked_mode_shows_blocked_diagnostics(self) -> None:
    blocked_low = _signal(
        status="ready",
        score=23,
        execution_gate=_execution_gate(
            can_show=False,
            feed_kind="blocked",
            status="blocked",
        ),
    )
    service = _service(
        [blocked_low],
        risk_preview=FakeRiskPreviewEvaluator({}),
        user_mode="all_market_opportunities",
    )

    response = service.list_signals(user_id="demo_user", mode="blocked")

    self.assertEqual([signal.id for signal in response.signals], [blocked_low.id])
    self.assertEqual(response.summary.diagnostic_blocked_ideas, 1)
```

```python
def test_radar_summary_counts_hidden_blocked(self) -> None:
    blocked = _signal(
        status="ready",
        score=82,
        execution_gate=_execution_gate(
            can_show=False,
            feed_kind="blocked",
            status="blocked",
        ),
    )
    service = _service(
        [blocked],
        risk_preview=FakeRiskPreviewEvaluator({}),
        user_mode="all_market_opportunities",
    )

    response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")

    self.assertEqual(response.signals, [])
    self.assertEqual(response.summary.hidden_blocked_ideas, 1)
    self.assertEqual(response.summary.diagnostic_blocked_ideas, 1)
```

- [ ] **Step 2: Run backend tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_radar_service.py -q
```

Expected: the new tests fail because `RadarSummary` lacks the new fields and all-feed still does not apply the low-score policy.

- [ ] **Step 3: Add settings and summary fields**

Add settings to `backend/app/core/config.py`:

```python
radar_all_feed_excludes_blocked: bool = True
radar_all_feed_min_visible_score: int = 50
radar_debug_blocked_feed_enabled: bool = True
```

Add fields to `RadarSummary` in `backend/app/schemas/signal.py`:

```python
visible_market_ideas: int = 0
hidden_blocked_ideas: int = 0
hidden_low_score_ideas: int = 0
diagnostic_blocked_ideas: int = 0
```

- [ ] **Step 4: Implement radar policy**

Import `settings` in `backend/app/services/radar_service.py`.

Add this helper:

```python
def _should_show_in_all_market_feed(signal: RadarSignal) -> bool:
    feed_kind = _gate_feed_kind(signal)
    if settings.radar_all_feed_excludes_blocked and feed_kind == "blocked":
        return False
    if signal.score < settings.radar_all_feed_min_visible_score:
        return False
    return feed_kind in {"market_idea", "watchlist", "execution_signal"} or feed_kind is None
```

Add a second helper that calls `build_radar_summary(visible_signals)` and then returns `summary.model_copy(update={"visible_market_ideas": visible_market_ideas, "hidden_blocked_ideas": hidden_blocked_ideas, "hidden_low_score_ideas": hidden_low_score_ideas, "diagnostic_blocked_ideas": diagnostic_blocked_ideas})` with those counters calculated from the original filtered source signals. Use this helper for the final `RadarResponse`.

- [ ] **Step 5: Run backend tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_radar_service.py -q
```

Expected: all radar service tests pass.

### Task 2: Frontend Diagnostic Feed Rendering

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/i18n/dictionary.ts`
- Modify: `frontend/src/features/app-shell/RadarPage.tsx`
- Modify: `frontend/src/components/SignalCard.tsx`
- Modify: `frontend/src/components/SignalDetails.tsx`
- Test: `frontend/src/features/app-shell/RadarPage.test.tsx`
- Test: `frontend/src/components/SignalCard.test.tsx`
- Test: `frontend/src/domain/signal-status.test.ts`

- [ ] **Step 1: Write failing frontend tests**

Add assertions:

```tsx
expect(screen.getByRole("button", { name: "Working feed" })).toBeInTheDocument();
expect(screen.getByRole("button", { name: "Blocked diagnostics" })).toBeInTheDocument();
```

Add blocked mode warning test by rendering `RadarPage` with the same required props used in the existing tests and `radarDisplayMode="blocked"`:

```tsx
expect(screen.getByText("These are diagnostic ideas, they are not entry signals.")).toBeInTheDocument();
```

Add blocked card test by creating `blockedGate` in `SignalCard.test.tsx`:

```tsx
const blockedGate: RadarSignal["execution_gate"] = {
  status: "blocked",
  feed_kind: "blocked",
  can_notify: false,
  can_enter_now: false,
  can_arm_pending: false,
  can_show_in_execution_feed: false,
  reasons: [
    {
      code: "forming_candle",
      severity: "blocker",
      source: "candle",
      message: "Waiting for candle close",
      metadata: {}
    }
  ],
  warnings: [],
  metadata: {}
};

render(<SignalCard signal={baseSignal({ score: 23, execution_gate: blockedGate })} selected={false} onSelect={vi.fn()} />);
expect(screen.getByText("Not for execution")).toBeInTheDocument();
expect(screen.getByText("Blocked idea")).toBeInTheDocument();
expect(screen.queryByText(/TP1/)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
cd frontend
corepack pnpm test src/components/SignalCard.test.tsx src/features/app-shell/RadarPage.test.tsx src/domain/signal-status.test.ts
```

Expected: tests fail on missing labels/warning/diagnostic card rendering.

- [ ] **Step 3: Update TypeScript summary and dictionary labels**

Add optional summary fields to `frontend/src/types.ts`. Update dictionary labels for:

- `radar.allIdeasFilter` -> "Working feed"
- `radar.blockedFilter` -> "Blocked diagnostics"
- add `radar.blockedDiagnosticsWarning`

- [ ] **Step 4: Update RadarPage**

Render warning when `props.radarDisplayMode === "blocked"`:

```tsx
<div className="warning-banner">{tKey("radar.blockedDiagnosticsWarning")}</div>
```

Keep filter behavior controlled by `onRadarDisplayModeChange`; do not recompute backend eligibility.

- [ ] **Step 5: Update SignalCard**

Derive:

```ts
const isBlockedDiagnostic = signal.execution_gate?.feed_kind === "blocked";
const scoreLabel = "Idea score";
const scoreQualifier = signal.score < 70 ? "low score" : null;
```

For blocked diagnostic cards, show the primary blocker and "Not for execution", hide the trading setup grid, and use "Blocked idea" for low-score blocked cards.

- [ ] **Step 6: Update SignalDetails disabled pending caption**

When pending entry is disabled, show:

```text
Waiting entry unavailable: <reason>
```

Use action state disabled reason first, then first `execution_gate` blocker.

- [ ] **Step 7: Run frontend tests and verify GREEN**

Run:

```powershell
cd frontend
corepack pnpm test src/components/SignalCard.test.tsx src/features/app-shell/RadarPage.test.tsx src/domain/signal-status.test.ts
```

Expected: all targeted frontend tests pass.

### Task 3: Verification And Commit

**Files:**
- All modified files from Tasks 1-2.

- [ ] **Step 1: Run targeted backend verification**

Run:

```powershell
python -m pytest backend/tests/test_radar_service.py -q
```

- [ ] **Step 2: Run targeted frontend verification**

Run:

```powershell
cd frontend
corepack pnpm test src/components/SignalCard.test.tsx src/features/app-shell/RadarPage.test.tsx src/domain/signal-status.test.ts
```

- [ ] **Step 3: Inspect git diff**

Run:

```powershell
git diff --stat
git diff
```

- [ ] **Step 4: Commit Prompt 1**

Run:

```powershell
git add backend/app/core/config.py backend/app/schemas/signal.py backend/app/services/radar_service.py backend/tests/test_radar_service.py frontend/src/types.ts frontend/src/i18n/dictionary.ts frontend/src/features/app-shell/RadarPage.tsx frontend/src/components/SignalCard.tsx frontend/src/components/SignalDetails.tsx frontend/src/features/app-shell/RadarPage.test.tsx frontend/src/components/SignalCard.test.tsx frontend/src/domain/signal-status.test.ts docs/superpowers/plans/2026-06-06-prompt-1-radar-blocked-feed.md
git commit -m "feat: hide blocked diagnostics from radar feed"
```
