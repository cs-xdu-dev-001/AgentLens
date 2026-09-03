import { useEffect, useState } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

export function TooltipProvider({ children }) {
  return (
    <TooltipPrimitive.Provider delayDuration={450} skipDelayDuration={300}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

// asChild preserves the button's ref, event handlers and direct-child layout.
export function Tooltip({ children, content, shortcut, side = "top", disabled = false }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <TooltipPrimitive.Root open={!disabled && open} onOpenChange={(nextOpen) => setOpen(!disabled && nextOpen)}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className={"agentlens-tooltip"}
          side={side}
          sideOffset={8}
          collisionPadding={12}
          hideWhenDetached
          onEscapeKeyDown={(event) => event.stopPropagation()}
        >
          <span>{content}</span>
          {shortcut ? <kbd>{shortcut}</kbd> : null}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
