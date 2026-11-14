export default function Home() {
  return <main className="mx-auto max-w-5xl px-6 py-16">
    <p className="text-sm uppercase tracking-widest text-cyan-300">Georgia · Informational monitoring</p>
    <h1 className="mt-4 text-4xl font-semibold">Georgia WindCast</h1>
    <p className="mt-4 text-slate-300">National generation and model wind. Times display in Asia/Tbilisi when data becomes available.</p>
    <section className="mt-10 grid gap-5 md:grid-cols-2" aria-label="Data availability">
      <article className="rounded-xl border border-slate-700 p-6">
        <h2 className="text-xl">National wind generation</h2>
        <p className="mt-4 text-cyan-200">Unavailable</p>
        <p className="mt-2 text-slate-300">The national aggregate MW source has not been verified or connected. Freshness is unverified.</p>
      </article>
      <article className="rounded-xl border border-slate-700 p-6">
        <h2 className="text-xl">Site model wind</h2>
        <p className="mt-4 text-cyan-200">Unavailable</p>
        <p className="mt-2 text-slate-300">Ruisi, Zemo Wind and Kartli/Gori model weather sources are not connected. History and forecasts are unavailable.</p>
      </article>
    </section>
    <p className="mt-8 text-sm text-slate-400">Model weather is not station telemetry. Weather forecasts are not MW forecasts.</p>
  </main>;
}
