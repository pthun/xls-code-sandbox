import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useOutletContext } from "react-router";

import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

import { API_BASE_URL } from "../config";
import type { ToolLayoutContextValue } from "./_app.tools";

export default function ManageProjectView() {
  const { tool, revalidate } = useOutletContext<ToolLayoutContextValue>();
  const [nameInput, setNameInput] = useState(tool.name);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    setNameInput(tool.name);
  }, [tool.name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmed = nameInput.trim();
    if (!trimmed) {
      setError("Tool name cannot be empty.");
      return;
    }

    setIsSaving(true);
    setError(null);
    setFeedback(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });

      if (!response.ok) {
        let detail = "Unable to rename tool";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (parseError) {
          console.error(parseError);
        }
        throw new Error(detail);
      }

      setFeedback("Tool renamed successfully.");
      revalidate();
    } catch (renameError) {
      setError(
        renameError instanceof Error ? renameError.message : "Rename failed"
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Manage project</h1>
        <p className="text-sm text-muted-foreground">
          Update the name used for this tool in the workspace sidebar.
        </p>
      </header>

      <form className="space-y-3" onSubmit={handleSubmit}>
        <div className="space-y-2">
          <Label htmlFor="tool-name">Tool name</Label>
          <Input
            id="tool-name"
            value={nameInput}
            onChange={(event) => setNameInput(event.target.value)}
            disabled={isSaving}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <Button type="submit" disabled={isSaving}>
          {isSaving ? "Saving..." : "Save changes"}
        </Button>
      </form>

      {feedback && (
        <p className="text-sm text-muted-foreground">{feedback}</p>
      )}

      <p className="text-xs text-muted-foreground">
        Created {new Date(tool.created_at).toLocaleString()}
      </p>
    </section>
  );
}
