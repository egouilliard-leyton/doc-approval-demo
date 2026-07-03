// Copies the current deep link (live window.location.href) to the clipboard, so
// a document/tab/field view can be shared exactly as it looks.
import { Link2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function CopyLinkButton({ className }: { className?: string }) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className={className}
      onClick={() => {
        void navigator.clipboard.writeText(window.location.href);
        toast.success("Link copied");
      }}
    >
      <Link2 className="size-3.5" />
      Copy link
    </Button>
  );
}
