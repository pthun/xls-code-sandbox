import { cn } from "../../lib/utils";

type SeparatorProps = React.HTMLAttributes<HTMLDivElement>;

export function Separator({ className, ...props }: SeparatorProps) {
  return (
    <div
      className={cn("h-px w-full bg-slate-200", className)}
      role="separator"
      {...props}
    />
  );
}
