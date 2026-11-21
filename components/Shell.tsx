export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="border-b border-border bg-surface px-4 py-3">
        <span className="font-semibold tracking-wide">Azkaban</span>
      </header>
      <main className="p-4">{children}</main>
    </div>
  );
}
