// Thin dialog shell around DocTypeManager — the entry point opened from the
// upload view's "Manage types" button.
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DocTypeManager } from "./DocTypeManager";

export function DocTypeManagerDialog({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Document types</DialogTitle>
          <DialogDescription>
            Manage the document types available to the pipeline.
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[70vh]">
          <DocTypeManager onChanged={onChanged} />
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
