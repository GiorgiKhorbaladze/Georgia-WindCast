import Link from "next/link";

export default function NotFound() {
  return (
    <section className="wc-panel mx-auto max-w-xl p-8 text-center">
      <h1 className="font-mono text-4xl text-cyan-glow">404</h1>
      <p className="mt-3 text-slate-300">
        <Link className="text-cyan-glow hover:underline" href="/">
          GEORGIA WINDCAST
        </Link>
      </p>
    </section>
  );
}
