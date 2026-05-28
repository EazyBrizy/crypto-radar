export const motionPolicy = {
  allowed: [
    "hover and focus transitions",
    "selected-row highlights",
    "toast enter/exit",
    "connection-status pulse",
    "single-row realtime update flash"
  ],
  disallowed: [
    "page-level entrance choreography",
    "parallax",
    "decorative background motion",
    "animated market data on every tick",
    "Framer Motion as a default wrapper for app screens"
  ],
  preferCssTransitions: true,
  requireReducedMotionFallback: true
} as const;
