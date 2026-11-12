import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * A CSV download through the same-origin API proxy (the session cookie authorizes it).
 * The accessible name is "Download <visible text>", so it contains what's on screen (WCAG
 * 2.5.3) and speech users can say what they see; `label` is the fuller hover description.
 */
export function DownloadButton({ href, children, label }: { href: string; children: React.ReactNode; label?: string }) {
  return (
    <Button variant="outline" size="sm" asChild>
      <a href={`/api/v1${href}`} download title={label}>
        <Download aria-hidden /> <span className="sr-only">Download </span>
        {children}
      </a>
    </Button>
  );
}
