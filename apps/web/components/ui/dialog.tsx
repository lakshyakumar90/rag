"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export function DialogContent({
  className,
  children,
  side = "center",
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  side?: "center" | "right" | "bottom";
}) {
  const placement = {
    center: "left-1/2 top-1/2 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-[10px]",
    right: "right-0 top-0 h-full w-[min(92vw,380px)] rounded-l-[12px] data-[state=open]:animate-none",
    bottom:
      "bottom-0 left-0 max-h-[85vh] w-full rounded-t-[14px] data-[state=open]:result-in",
  }[side];
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 border border-border bg-surface-raised p-5 shadow-[var(--shadow-panel)] focus:outline-none",
          placement,
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute right-4 top-4 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Close"
        >
          <X size={16} />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
