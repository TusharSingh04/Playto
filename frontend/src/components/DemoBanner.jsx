/**
 * DEMO MODE banner. Shown unconditionally in this build because the
 * "bank API" is `random.random()` server-side. Removing this banner before
 * integrating a real PSP is intentional — never ship without it while the
 * simulator is live.
 */
export default function DemoBanner() {
  return (
    <div className="bg-amber-100 border-b border-amber-300 text-amber-900 text-sm">
      <div className="max-w-6xl mx-auto px-4 py-2 flex items-center gap-3">
        <span className="font-bold uppercase tracking-wider text-xs px-2 py-0.5 rounded bg-amber-500 text-white">
          Demo
        </span>
        <span>
          Payout outcomes are simulated (~70% success / 20% fail / 10% stuck).
          No real money moves. Do not enter real bank details.
        </span>
      </div>
    </div>
  );
}
