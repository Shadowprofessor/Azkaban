"use client";

import { Guard } from "@/components/Guard";
import { FlowList } from "@/components/radar/FlowList";
import { Controls } from "@/components/radar/Controls";
import { ExposurePanel } from "@/components/score/ExposurePanel";
import { Filters } from "@/components/radar/Filters";
import { FlowDrawer } from "@/components/radar/FlowDrawer";

export default function RadarPage() {
  return (
    <Guard>
      <div className="flex h-[calc(100vh-57px)] flex-col gap-3 p-3 md:p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Leak Radar</h1>
          <Controls />
        </div>
        <Filters />
        <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
          <FlowList />
          <aside className="shrink-0 overflow-y-auto lg:w-[340px]">
            <ExposurePanel />
          </aside>
        </div>
      </div>
      <FlowDrawer />
    </Guard>
  );
}
