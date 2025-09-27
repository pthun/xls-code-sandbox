import { useState } from "react";
import {
  NavLink,
  Outlet,
  useLoaderData,
  useNavigate,
  useRevalidator,
} from "react-router";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app";

type ToolSummary = {
  id: number;
  name: string;
  created_at: string;
};

type ToolListPayload = {
  tools: ToolSummary[];
  loadError?: string;
};

export async function loader({}: Route.LoaderArgs) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/tools`, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      const message = `Failed to load tools (${response.status})`;
      console.warn(message);
      return { tools: [], loadError: message } satisfies ToolListPayload;
    }

    const tools = (await response.json()) as ToolSummary[];
    return { tools } satisfies ToolListPayload;
  } catch (error) {
    console.warn("Unable to reach tool API", error);
    return {
      tools: [],
      loadError: "Unable to reach the tool API. Start the backend on :3101.",
    } satisfies ToolListPayload;
  }
}

export default function AppLayout() {
  const { tools, loadError } = useLoaderData<typeof loader>();
  const navigate = useNavigate();
  const revalidator = useRevalidator();

  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreateTool() {
    try {
      setIsCreating(true);
      setError(null);

      const response = await fetch(`${API_BASE_URL}/api/tools`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      if (!response.ok) {
        throw new Error("Unable to create tool");
      }

      const tool = (await response.json()) as ToolSummary;
      navigate(`/tools/${tool.id}`);
      revalidator.revalidate();
    } catch (creationError) {
      setError(
        creationError instanceof Error
          ? creationError.message
          : "Something went wrong while creating the tool"
      );
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <aside className="flex w-72 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60 px-6 py-8">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Tools</h1>
          <button
            type="button"
            className="rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={handleCreateTool}
            disabled={isCreating}
          >
            {isCreating ? "Creating..." : "New tool"}
          </button>
        </div>

        <nav className="mt-6 flex-1 space-y-1 overflow-y-auto pr-1 text-sm">
          {tools.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 px-3 py-4 text-center text-xs text-slate-400">
              No tools yet. Create your first tool to get started.
            </p>
          ) : (
            tools.map((tool) => (
              <NavLink
                key={tool.id}
                to={`/tools/${tool.id}`}
                className={({ isActive }) =>
                  `block rounded-lg border px-3 py-2 transition ${
                    isActive
                      ? "border-indigo-400 bg-indigo-500/20 text-white"
                      : "border-transparent bg-slate-900/40 text-slate-300 hover:border-slate-700 hover:bg-slate-900/60"
                  }`
                }
              >
                <div className="font-medium">{tool.name}</div>
                <div className="text-[10px] uppercase tracking-wide text-slate-500">
                  {new Date(tool.created_at).toLocaleString()}
                </div>
              </NavLink>
            ))
          )}
        </nav>

        {error && (
          <p className="mt-4 rounded-lg border border-red-500/70 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {error}
          </p>
        )}
        {loadError && (
          <p className="mt-4 rounded-lg border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {loadError}
          </p>
        )}
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="border-b border-slate-800 bg-slate-900/60 px-8 py-6">
          <h2 className="text-xl font-semibold">Tool Workspace</h2>
          <p className="text-sm text-slate-400">
            Upload spreadsheets to configure your analysis tools.
          </p>
        </header>
        <section className="flex-1 overflow-y-auto px-8 py-6">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
