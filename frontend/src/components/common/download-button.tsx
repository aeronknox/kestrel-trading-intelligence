import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";

/** A CSV download through the same-origin API proxy (the session cookie authorizes it). */
export function DownloadButton({ href, children, label }: { href: string; children: React.ReactNode; label?: string }) {
  return (
    <Button variant="outline" size="sm" asChild>
      <a href={`/api/v1${href}`} download aria-label={label}>
        <Download /> {children}
      </a>
    </Button>
  );
}
