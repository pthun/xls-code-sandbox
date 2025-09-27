import { redirect } from "react-router";

import { API_BASE_URL } from "../config";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
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
    if (error instanceof Response) {
      throw error;
    }
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
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Welcome to the Tool Workspace</CardTitle>
          <CardDescription>
            Spin up your first analysis tool to start uploading CSV or Excel
            files for processing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-slate-600">
          <p>
            Use the <span className="font-medium text-indigo-600">New tool</span>
            button in the sidebar to create a workspace. Each tool keeps its
            uploads separate so you can manage multiple datasets in parallel.
          </p>
          <p>
            Once created, head to the tool page to upload your spreadsheets and
            review the file history.
          </p>
          <Button className="mt-6" onClick={() => window.dispatchEvent(new CustomEvent("tool-create-requested"))}>
            Create your first tool
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
