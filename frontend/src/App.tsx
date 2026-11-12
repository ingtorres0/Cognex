import { Dashboard } from "./components/Dashboard";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 font-sans text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/80">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-3 px-6 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.22em] text-amber-400">
              Station 01
            </p>
            <h1 className="text-xl font-semibold tracking-tight text-white">
              Automated Visual Inspection
            </h1>
          </div>
          <p className="text-sm text-slate-400">Cognex Native Mode · TCP mock</p>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Dashboard />
      </main>
    </div>
  );
}
