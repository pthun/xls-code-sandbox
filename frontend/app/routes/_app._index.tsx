import { API_BASE_URL } from "../config";
import { Button } from "~/components/ui/button";
import type { Route } from "./+types/_app._index";
import { useLoaderData } from "react-router";

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
    } else {
      const tools = (await response.json()) as ToolSummary[];
      return { hasTools: tools.length > 0 };
    }
  } catch (error) {
    console.warn("Unable to reach tool API", error);
  }

  return { hasTools: false };
}

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Tools | XLS Workspace" },
    { name: "description", content: "Create tools and upload spreadsheet data." },
  ];
}

export default function ToolIndexRoute() {
  const data = useLoaderData<typeof loader>();
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Welcome to the Tool Workspace</h1>
        <p className="text-sm text-muted-foreground">
          {data?.hasTools
            ? "Select a tool from the sidebar or create another to start uploading data."
            : "Spin up your first analysis tool to start uploading CSV or Excel files for processing."}
        </p>
      </header>
      <div className="space-y-4 text-sm text-muted-foreground">
        <p>
          Use the <span className="font-medium">New tool</span> button in the sidebar to create a workspace.
          Each tool keeps its uploads separate so you can manage multiple datasets in parallel.
        </p>
        <p>
          Once created, head to the tool page to upload your spreadsheets and review the file history.
        </p>
        <Button
          onClick={() => window.dispatchEvent(new CustomEvent("tool-create-requested"))}
        >
          {data?.hasTools ? "Create another tool" : "Create your first tool"}
        </Button>
      </div>
    </div>
  );
}
