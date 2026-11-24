import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "border-input bg-card placeholder:text-muted-foreground/80 flex h-11 w-full min-w-0 rounded-lg border px-3.5 text-sm shadow-xs transition-[border-color,box-shadow] duration-150 outline-none",
        "focus-visible:border-ring focus-visible:ring-ring/25 focus-visible:ring-[3px]",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
