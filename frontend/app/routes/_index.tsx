import { useState } from "react";

import type { Route } from "./+types/_index";

type DoubleResponse = {
  input: number;
  doubled: number;
};

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Welcome | React Router" },
    {
      name: "description",
      content: "Submit a number to get it doubled by the FastAPI backend.",
    },
  ];
}

export default function IndexRoute() {
  const [value, setValue] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState<DoubleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const parsedValue = Number(value);
    if (!Number.isFinite(parsedValue)) {
      setError("Please enter a valid number.");
      setResult(null);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch("http://localhost:3101/api/double", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ value: parsedValue }),
      });

      if (!response.ok) {
        throw new Error("Unexpected server response");
      }

      const data = (await response.json()) as DoubleResponse;
      setResult(data);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Something went wrong"
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-950/95 px-6 text-slate-100">
      <section className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-8 shadow-2xl">
        <header className="mb-6 text-center">
          <h1 className="text-2xl font-semibold">Welcome to the Double App</h1>
          <p className="mt-2 text-sm text-slate-300">
            Enter a number and we&apos;ll ask the FastAPI backend to double it for
            you.
          </p>
        </header>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium" htmlFor="value">
            Your number
          </label>
          <input
            id="value"
            name="value"
            type="number"
            className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-base text-slate-100 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="e.g. 21"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={isSubmitting}
            required
            step="any"
          />

          <button
            type="submit"
            className="w-full rounded-lg bg-indigo-500 px-3 py-2 font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Submitting..." : "Double it"}
          </button>
        </form>

        {error && (
          <p className="mt-4 rounded-lg border border-red-500 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-4 rounded-lg border border-emerald-500 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            <p>
              We sent <span className="font-semibold">{result.input}</span> and
              the backend responded with
              <span className="font-semibold"> {result.doubled}</span>.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
