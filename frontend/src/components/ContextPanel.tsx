import React from "react";

export default function ContextPanel({ ctx }: { ctx: any }) {
  const tz = ctx?.timezone ?? "UTC";
  const city = ctx?.last_known_location?.city || "";
  const local = ctx?.local_time_str || "";

  return (
    <aside className="p-4 border-l bg-white h-full">
      <h3 className="font-semibold mb-2 text-gray-700">Context</h3>
      <div className="space-y-1 text-sm">
        <div>
          <span className="font-medium">Timezone:</span> {tz}
        </div>
        <div>
          <span className="font-medium">Local time:</span> {local}
        </div>
        <div>
          <span className="font-medium">Location:</span> {city || "—"}
        </div>
      </div>
    </aside>
  );
}