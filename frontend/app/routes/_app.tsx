import { useCallback, useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  useLoaderData,
  useNavigate,
  useRevalidator,
} from "react-router";

import { API_BASE_URL } from "../config";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";
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

  const handleCreateTool = useCallback(async () => {
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
  }, [navigate, revalidator]);

  useEffect(() => {
    const handler = () => {
      if (!isCreating) {
        void handleCreateTool();
      }
    };
    window.addEventListener("tool-create-requested", handler);
    return () => window.removeEventListener("tool-create-requested", handler);
  }, [handleCreateTool, isCreating]);

  useEffect(() => {
    const handler = () => revalidator.revalidate();
    window.addEventListener("tool-data-updated", handler);
    return () => window.removeEventListener("tool-data-updated", handler);
  }, [revalidator]);

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white px-6 py-8">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold text-slate-900">Tools</h1>
          <Button onClick={handleCreateTool} disabled={isCreating}>
            {isCreating ? "Creating..." : "New tool"}
          </Button>
        </div>

        <nav className="mt-6 flex-1 space-y-1 overflow-y-auto pr-1 text-sm">
          {tools.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-center text-xs text-slate-500">
              No tools yet. Create your first tool to get started.
            </p>
          ) : (
            tools.map((tool) => (
              <NavLink
                key={tool.id}
                to={`/tools/${tool.id}`}
                className={({ isActive }) =>
                  `group flex items-center justify-between rounded-lg border px-3 py-2 transition ${
                    isActive
                      ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                      : "border-transparent bg-white text-slate-600 hover:border-slate-200 hover:bg-slate-50"
                  }`
                }
              >
                <div className="flex flex-col">
                  <span className="font-medium">{tool.name}</span>
                  <span className="text-[10px] uppercase tracking-wide text-slate-400">
                    {new Date(tool.created_at).toLocaleString()}
                  </span>
                </div>
              </NavLink>
            ))
          )}
        </nav>

        {error && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        )}
        {loadError && (
          <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-600">
            {loadError}
          </p>
        )}
        <Separator className="mt-6" />
        <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
          Rename or delete tools from their workspace pages. All uploads are
          stored per tool and will be removed on deletion.
        </p>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="border-b border-slate-200 bg-white px-8 py-6">
          <h2 className="text-xl font-semibold text-slate-900">Tool Workspace</h2>
          <p className="text-sm text-slate-500">
            Upload spreadsheets to configure your analysis tools.
          </p>
        </header>
        <section className="flex-1 overflow-y-auto bg-slate-50 px-8 py-6">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
