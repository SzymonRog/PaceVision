import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Minimal header — no logo, no brand mark (this is a portfolio piece).
 * A quiet wordless home link on the left, actions + theme toggle on the right.
 */
export function SiteHeader({ right }: { right?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center justify-between px-6 md:px-10">
        <Link
          href="/"
          className="text-sm font-medium tracking-tight text-muted-foreground transition-colors hover:text-foreground"
        >
          Running form analysis
        </Link>
        <div className="flex items-center gap-2">
          {right}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
