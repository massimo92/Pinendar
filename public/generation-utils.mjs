export function clampGenerationTimeLimit(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return null;
  const minutes = Number(raw);
  if (!Number.isFinite(minutes)) return null;
  return Math.min(30, Math.max(1, Math.trunc(minutes)));
}
