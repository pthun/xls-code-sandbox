import { forwardRef } from "react";

import { cn } from "../../lib/utils";

type LabelProps = React.LabelHTMLAttributes<HTMLLabelElement>;

export const Label = forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn("text-sm font-medium text-slate-700", className)}
      {...props}
    />
  )
);

Label.displayName = "Label";
