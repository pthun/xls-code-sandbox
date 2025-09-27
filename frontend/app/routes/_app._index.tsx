import { redirect } from "react-router";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app._index";

type ToolSummary = {
  id: number;
};

export async function loader({}: Route.LoaderArgs) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/tools`, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      console.warn("Failed to inspect tools", response.status, response.statusText);
      return null;
    }

    const tools = (await response.json()) as ToolSummary[];
    if (tools.length > 0) {
      throw redirect(`/tools/${tools[0].id}`);
    }
  } catch (error) {
    console.warn("Unable to reach tool API", error);
  }

  return null;
}

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Tools | XLS Workspace" },
    { name: "description", content: "Create tools and upload spreadsheet data." },
  ];
}

export default function ToolIndexRoute() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 rounded-2xl border border-slate-800 bg-slate-900/50 p-10 text-slate-200 shadow-xl">
      <h3 className="text-2xl font-semibold">Welcome to the Tool Workspace</h3>
      <p className="text-sm text-slate-400">
        There are no tools yet. Use the <span className="font-semibold text-indigo-200">New tool</span> button in the sidebar to create one.
      </p>
      <p className="text-sm text-slate-400">
        After your tool exists you can upload CSV or Excel files on its project page to begin processing data.
      </p>
    </div>
  );
}
