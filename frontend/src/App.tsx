import React, { useEffect, useState } from "react";
import ChatPane from "./components/ChatPane";
import ContextPanel from "./components/ContextPanel";
import { getContext } from "./lib/api";

export default function App() {
  const [ctx, setCtx] = useState<any>(null);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const res = await getContext();
        if (alive && res?.status === "ok") setCtx(res.data);
      } catch {}
    }
    tick();
    const id = setInterval(tick, 15_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] h-screen">
      <section className="flex flex-col bg-white">
        <header className="border-b p-4">
          <h1 className="text-xl font-semibold text-gray-800">
            Cortex · Chat Interface
          </h1>
        </header>
        <main className="flex-1 overflow-hidden">
          <ChatPane />
        </main>
      </section>
      <ContextPanel ctx={ctx} />
    </div>
  );
}