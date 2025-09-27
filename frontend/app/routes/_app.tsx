import { useCallback, useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  useLoaderData,
  useNavigate,
  useRevalidator,
} from "react-router";

import { Button } from "~/components/ui/button";
import { Separator } from "~/components/ui/separator";
import { cn } from "~/lib/utils";

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
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-card px-6 py-8">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Tools</h1>
          <Button onClick={handleCreateTool} disabled={isCreating}>
            {isCreating ? "Creating..." : "New tool"}
          </Button>
        </div>

        <nav className="mt-6 flex-1 space-y-1 overflow-y-auto pr-1 text-sm">
          <NavLink
            to="/e2b-test"
            className={({ isActive }) =>
              cn(
                "flex items-center justify-between rounded-md border border-transparent px-3 py-2 transition",
                isActive ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
              )
            }
          >
            <span className="font-medium">E2B Sandbox</span>
          </NavLink>

          <Separator className="my-2" />

          {tools.length === 0 ? (
            <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
              No tools yet. Create your first tool to get started.
            </p>
          ) : (
            tools.map((tool) => (
              <NavLink
                key={tool.id}
                to={`/tools/${tool.id}`}
                className={({ isActive }) =>
                  cn(
                    "flex items-center justify-between rounded-md border border-transparent px-3 py-2 transition",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/50"
                  )
                }
              >
                <div className="flex flex-col">
                  <span className="font-medium">{tool.name}</span>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {new Date(tool.created_at).toLocaleString()}
                  </span>
                </div>
              </NavLink>
            ))
          )}
        </nav>

        {error && (
          <p className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}
        {loadError && (
          <p className="mt-4 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {loadError}
          </p>
        )}
        <Separator className="mt-6" />
        <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">
          Rename or delete tools from their workspace pages. All uploads are
          stored per tool and will be removed on deletion.
        </p>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="border-b border-border bg-background px-8 py-6">
          <h2 className="text-xl font-semibold">Tool Workspace</h2>
          <p className="text-sm text-muted-foreground">
            Upload spreadsheets to configure your analysis tools.
          </p>
        </header>
        <section className="flex-1 overflow-y-auto bg-muted/30 px-8 py-6">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
